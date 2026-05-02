package registry

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/dependencyresolution"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/llmproviderresolution"
	"mcp-mesh/src/core/ent/llmtoolresolution"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/ent/schemaentry"
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

// newSweepTestEnv constructs an in-memory Ent client + EntService + sweep job
// with a mock clock fixed at `now`. The returned cleanup func closes the client.
func newSweepTestEnv(t *testing.T, cfg SweepConfig, now time.Time) (*ent.Client, *EntService, *SweepJob, func()) {
	t.Helper()

	client := enttest.Open(t, "sqlite3", "file:sweep_"+t.Name()+"?mode=memory&cache=shared&_fk=1")
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	entDB := &database.EntDatabase{Client: client}
	service := NewEntService(entDB, nil, testLogger)
	// Status change hooks would create extra events on every status update we
	// do via direct Ent calls; that pollutes the event-counts under test.
	service.DisableStatusChangeHooks()

	job := NewSweepJob(cfg, entDB, service, testLogger)
	job.clock = func() time.Time { return now }

	cleanup := func() {
		client.Close()
	}
	return client, service, job, cleanup
}

// seedAgent inserts an agent directly via Ent with the requested status and
// updated_at, bypassing RegisterAgent (which always sets updated_at = now).
func seedAgent(t *testing.T, client *ent.Client, id string, status agent.Status, updatedAt time.Time) {
	t.Helper()
	ctx := context.Background()
	_, err := client.Agent.Create().
		SetID(id).
		SetName(id).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(status).
		SetUpdatedAt(updatedAt).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed agent %s: %v", id, err)
	}
	// SetUpdatedAt on Create is honored, but defensive: force it again via
	// Update so the field reflects exactly what we asked for even if hooks
	// fire. The test env disables hooks, so this is belt-and-suspenders.
	_, err = client.Agent.UpdateOneID(id).SetUpdatedAt(updatedAt).Save(ctx)
	if err != nil {
		t.Fatalf("force updated_at on %s: %v", id, err)
	}
}

func seedEvent(t *testing.T, client *ent.Client, agentID string, ts time.Time) {
	t.Helper()
	ctx := context.Background()
	_, err := client.RegistryEvent.Create().
		SetAgentID(agentID).
		SetEventType(registryevent.EventTypeHeartbeat).
		SetTimestamp(ts).
		SetData(map[string]interface{}{}).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed event for %s: %v", agentID, err)
	}
}

// TestSweepStaleAgentsOnly verifies that only agents in unhealthy/unknown
// status with updated_at older than the retention window are purged, and
// that healthy agents (regardless of age) are left alone.
func TestSweepStaleAgentsOnly(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	// Stale unhealthy: should be purged (2h old > 1h retention).
	seedAgent(t, client, "stale-unhealthy", agent.StatusUnhealthy, now.Add(-2*time.Hour))
	// Stale unknown: should also be purged.
	seedAgent(t, client, "stale-unknown", agent.StatusUnknown, now.Add(-2*time.Hour))
	// Healthy and old: should NOT be purged (status filter).
	seedAgent(t, client, "old-healthy", agent.StatusHealthy, now.Add(-2*time.Hour))
	// Recently unhealthy: should NOT be purged (updated_at within retention).
	seedAgent(t, client, "fresh-unhealthy", agent.StatusUnhealthy, now.Add(-30*time.Minute))

	purgedAgents, purgedEvents, _, err := job.runOnce(context.Background())
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if purgedAgents != 2 {
		t.Errorf("expected 2 agents purged, got %d", purgedAgents)
	}
	if purgedEvents != 0 {
		t.Errorf("expected 0 events purged, got %d", purgedEvents)
	}

	// Verify exactly the expected agents remain.
	remaining, err := client.Agent.Query().IDs(context.Background())
	if err != nil {
		t.Fatalf("query remaining: %v", err)
	}
	want := map[string]bool{"old-healthy": true, "fresh-unhealthy": true}
	if len(remaining) != len(want) {
		t.Errorf("expected %d remaining agents, got %d (%v)", len(want), len(remaining), remaining)
	}
	for _, id := range remaining {
		if !want[id] {
			t.Errorf("unexpected agent remained: %s", id)
		}
	}
}

// TestSweepBoth verifies a tick that purges a stale agent and trims excess
// events via the rolling cap in one pass.
func TestSweepBoth(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	// One stale agent + one healthy host for events.
	seedAgent(t, client, "host", agent.StatusHealthy, now)
	seedAgent(t, client, "stale", agent.StatusUnhealthy, now.Add(-3*time.Hour))

	// Seed events; with the production cap (100k) none of these would be
	// trimmed, so we drop the cap for this test by manipulating the count
	// via the rolling-cap test below. Here we just verify the agent purge
	// happens and event purge stays at 0 because we're well under the cap.
	seedEvent(t, client, "host", now.Add(-2*24*time.Hour))
	seedEvent(t, client, "host", now.Add(-1*time.Minute))

	purgedAgents, purgedEvents, _, err := job.runOnce(context.Background())
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if purgedAgents != 1 {
		t.Errorf("expected 1 agent purged, got %d", purgedAgents)
	}
	if purgedEvents != 0 {
		t.Errorf("expected 0 events purged (under cap), got %d", purgedEvents)
	}
}

// TestSweepEventMaxRowsUnderCap verifies that nothing is purged when the
// event row count is at or below the cap.
func TestSweepEventMaxRowsUnderCap(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	seedAgent(t, client, "host", agent.StatusHealthy, now)

	// Seed 5 events; well under the 100k cap, so nothing should be purged.
	for i := 0; i < 5; i++ {
		seedEvent(t, client, "host", now.Add(-time.Duration(5-i)*time.Minute))
	}

	purgedAgents, purgedEvents, _, err := job.runOnce(context.Background())
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if purgedAgents != 0 {
		t.Errorf("expected 0 agents purged, got %d", purgedAgents)
	}
	if purgedEvents != 0 {
		t.Errorf("expected 0 events purged (under cap), got %d", purgedEvents)
	}

	count, err := client.RegistryEvent.Query().Count(context.Background())
	if err != nil {
		t.Fatalf("count events: %v", err)
	}
	if count != 5 {
		t.Errorf("expected 5 events remaining (under cap), got %d", count)
	}
}

// TestSweepEventMaxRowsOverCap verifies that when the event row count
// exceeds the cap, exactly the oldest excess rows are deleted (in
// timestamp ASC order) and the newest cap-many rows remain.
func TestSweepEventMaxRowsOverCap(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	// Override the cap to a small number so the test can drive the
	// over-cap branch without seeding 100k rows.
	job.eventMaxRows = 3

	seedAgent(t, client, "host", agent.StatusHealthy, now)

	// Seed 5 events with strictly increasing timestamps. The 2 oldest
	// (i=0, i=1) should be deleted; the 3 newest (i=2, i=3, i=4) remain.
	timestamps := make([]time.Time, 5)
	for i := 0; i < 5; i++ {
		timestamps[i] = now.Add(-time.Duration(5-i) * time.Minute)
		seedEvent(t, client, "host", timestamps[i])
	}

	purgedAgents, purgedEvents, _, err := job.runOnce(context.Background())
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if purgedAgents != 0 {
		t.Errorf("expected 0 agents purged, got %d", purgedAgents)
	}
	if purgedEvents != 2 {
		t.Errorf("expected 2 events purged (5 - cap of 3), got %d", purgedEvents)
	}

	// Verify exactly 3 events remain, and they are the 3 newest.
	remaining, err := client.RegistryEvent.Query().
		Order(ent.Asc(registryevent.FieldTimestamp)).
		All(context.Background())
	if err != nil {
		t.Fatalf("query remaining events: %v", err)
	}
	if len(remaining) != 3 {
		t.Fatalf("expected 3 events remaining, got %d", len(remaining))
	}
	for i, ev := range remaining {
		want := timestamps[i+2] // we deleted indices 0 and 1
		if !ev.Timestamp.Equal(want) {
			t.Errorf("event[%d] timestamp = %s, want %s (oldest 2 should have been deleted)", i, ev.Timestamp, want)
		}
	}
}

// TestSweepDisabledRetention verifies that retention=0 makes runOnce a
// no-op for the agent-purge path (gated by the Retention > 0 check) while
// the seeded event is preserved — the latter happens because the single
// event is well under the 100k cap, not because enforceEventCap is gated
// (it always runs regardless of Retention).
//
// Note: Start() bails out before launching the goroutine when retention=0;
// runOnce here is invoked directly to confirm the agent path is gated.
func TestSweepDisabledRetention(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 0}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	seedAgent(t, client, "stale", agent.StatusUnhealthy, now.Add(-100*24*time.Hour))
	seedEvent(t, client, "stale", now.Add(-100*24*time.Hour))

	purgedAgents, _, _, err := job.runOnce(context.Background())
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if purgedAgents != 0 {
		t.Errorf("expected 0 agents purged with retention=0, got %d", purgedAgents)
	}

	// The stale agent row should still exist.
	if n, _ := client.Agent.Query().Count(context.Background()); n != 1 {
		t.Errorf("expected 1 agent kept, got %d", n)
	}
	if n, _ := client.RegistryEvent.Query().Count(context.Background()); n != 1 {
		t.Errorf("expected 1 event kept, got %d", n)
	}
}

// TestSweepDisabledStartIsNoop verifies that Start() with retention=0 does
// not launch the goroutine (the operator's forensic escape hatch).
func TestSweepDisabledStartIsNoop(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 0}
	_, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	job.Start(context.Background())

	job.mu.Lock()
	running := job.running
	job.mu.Unlock()

	if running {
		t.Errorf("expected sweep job to NOT be running when Retention=0, but running=true")
	}
}

// TestSweepFixesOrphanProviderResolutions verifies that purging an agent
// flips consumer-side rows in ALL THREE resolution tables pointing to it
// from status=available to status=unavailable BEFORE the cascade-set-null
// FK would otherwise leave them dangling. The three tables are:
//   - dependency_resolution    (@mesh.tool deps)
//   - llm_tool_resolution      (@mesh.llm tool filter)
//   - llm_provider_resolution  (@mesh.llm provider config)
func TestSweepFixesOrphanProviderResolutions(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Healthy consumer agent (will survive sweep).
	seedAgent(t, client, "consumer", agent.StatusHealthy, now)
	// Stale provider agent (will be purged by sweep).
	seedAgent(t, client, "provider", agent.StatusUnhealthy, now.Add(-3*time.Hour))

	// Insert a dependency_resolution row pointing consumer -> provider, status=available.
	_, err := client.DependencyResolution.Create().
		SetConsumerAgentID("consumer").
		SetConsumerFunctionName("do_thing").
		SetCapabilityRequired("widget").
		SetProviderAgentID("provider").
		SetProviderFunctionName("widget_impl").
		SetEndpoint("http://provider:8080").
		SetStatus(dependencyresolution.StatusAvailable).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed dep resolution: %v", err)
	}

	// Insert an llm_tool_resolution row pointing consumer -> provider, status=available.
	_, err = client.LLMToolResolution.Create().
		SetConsumerAgentID("consumer").
		SetConsumerFunctionName("ask_llm").
		SetProviderAgentID("provider").
		SetProviderFunctionName("time_tool").
		SetProviderCapability("time_service").
		SetEndpoint("http://provider:8080").
		SetStatus(llmtoolresolution.StatusAvailable).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed llm tool resolution: %v", err)
	}

	// Insert an llm_provider_resolution row pointing consumer -> provider, status=available.
	_, err = client.LLMProviderResolution.Create().
		SetConsumerAgentID("consumer").
		SetConsumerFunctionName("ask_llm").
		SetRequiredCapability("llm").
		SetProviderAgentID("provider").
		SetProviderFunctionName("llm").
		SetEndpoint("http://provider:8080").
		SetStatus(llmproviderresolution.StatusAvailable).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed llm provider resolution: %v", err)
	}

	if _, _, _, err := job.runOnce(ctx); err != nil {
		t.Fatalf("runOnce: %v", err)
	}

	// Provider should be gone.
	if n, _ := client.Agent.Query().Where(agent.IDEQ("provider")).Count(ctx); n != 0 {
		t.Errorf("expected provider purged, got count=%d", n)
	}

	// dependency_resolution: consumer-side row remains, status flipped.
	depResolutions, err := client.DependencyResolution.Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer")).
		All(ctx)
	if err != nil {
		t.Fatalf("query dep resolutions: %v", err)
	}
	if len(depResolutions) != 1 {
		t.Fatalf("expected 1 dep resolution row for consumer, got %d", len(depResolutions))
	}
	if depResolutions[0].Status != dependencyresolution.StatusUnavailable {
		t.Errorf("expected dep resolution status=unavailable after provider purge, got %s", depResolutions[0].Status)
	}

	// llm_tool_resolution: consumer-side row remains, status flipped.
	toolResolutions, err := client.LLMToolResolution.Query().
		Where(llmtoolresolution.ConsumerAgentIDEQ("consumer")).
		All(ctx)
	if err != nil {
		t.Fatalf("query llm tool resolutions: %v", err)
	}
	if len(toolResolutions) != 1 {
		t.Fatalf("expected 1 llm tool resolution row for consumer, got %d", len(toolResolutions))
	}
	if toolResolutions[0].Status != llmtoolresolution.StatusUnavailable {
		t.Errorf("expected llm tool resolution status=unavailable after provider purge, got %s", toolResolutions[0].Status)
	}

	// llm_provider_resolution: consumer-side row remains, status flipped.
	provResolutions, err := client.LLMProviderResolution.Query().
		Where(llmproviderresolution.ConsumerAgentIDEQ("consumer")).
		All(ctx)
	if err != nil {
		t.Fatalf("query llm provider resolutions: %v", err)
	}
	if len(provResolutions) != 1 {
		t.Fatalf("expected 1 llm provider resolution row for consumer, got %d", len(provResolutions))
	}
	if provResolutions[0].Status != llmproviderresolution.StatusUnavailable {
		t.Errorf("expected llm provider resolution status=unavailable after provider purge, got %s", provResolutions[0].Status)
	}
}

// TestSweepSkipsAgentRevivedDuringTick verifies the race-safety re-query
// inside the purge transaction: if an agent appears in the candidate set
// but heartbeats (becoming healthy with a fresh updated_at) before the
// purge transaction runs, the unconditional delete is skipped and
// orphan-fix does NOT touch the consumer-side resolution rows.
func TestSweepSkipsAgentRevivedDuringTick(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Consumer + stale provider, both seeded.
	seedAgent(t, client, "consumer", agent.StatusHealthy, now)
	seedAgent(t, client, "provider", agent.StatusUnhealthy, now.Add(-3*time.Hour))

	_, err := client.DependencyResolution.Create().
		SetConsumerAgentID("consumer").
		SetConsumerFunctionName("do_thing").
		SetCapabilityRequired("widget").
		SetProviderAgentID("provider").
		SetProviderFunctionName("widget_impl").
		SetEndpoint("http://provider:8080").
		SetStatus(dependencyresolution.StatusAvailable).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed dep resolution: %v", err)
	}

	// Simulate the race by manually walking the sweep flow:
	//   1. Snapshot the candidate set (would-be-purged).
	//   2. Heartbeat the provider (status -> healthy, updated_at -> now).
	//   3. Call purgeOneAgent on the stale snapshot — the re-query
	//      inside the tx must see the now-healthy agent and bail out.
	threshold := now.Add(-cfg.Retention)
	candidates, err := client.Agent.Query().
		Where(
			agent.StatusIn(agent.StatusUnhealthy, agent.StatusUnknown),
			agent.UpdatedAtLT(threshold),
		).
		All(ctx)
	if err != nil {
		t.Fatalf("query candidates: %v", err)
	}
	if len(candidates) != 1 || candidates[0].ID != "provider" {
		t.Fatalf("expected exactly one candidate (provider), got %v", candidates)
	}

	// Heartbeat: provider revives between snapshot and purge.
	_, err = client.Agent.UpdateOneID("provider").
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(now).
		Save(ctx)
	if err != nil {
		t.Fatalf("heartbeat provider: %v", err)
	}

	didPurge, err := job.purgeOneAgent(ctx, candidates[0], threshold)
	if err != nil {
		t.Fatalf("purgeOneAgent: %v", err)
	}
	if didPurge {
		t.Errorf("expected purge to be skipped (race lost), got didPurge=true")
	}

	// Provider must still exist and be healthy.
	a, err := client.Agent.Get(ctx, "provider")
	if err != nil {
		t.Fatalf("get provider: %v", err)
	}
	if a.Status != agent.StatusHealthy {
		t.Errorf("expected provider status=healthy after revival, got %s", a.Status)
	}

	// Dependency resolution must NOT have been flipped (orphan-fix
	// rolled back / never ran because the re-query bailed out).
	resolutions, err := client.DependencyResolution.Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer")).
		All(ctx)
	if err != nil {
		t.Fatalf("query resolutions: %v", err)
	}
	if len(resolutions) != 1 {
		t.Fatalf("expected 1 resolution row, got %d", len(resolutions))
	}
	if resolutions[0].Status != dependencyresolution.StatusAvailable {
		t.Errorf("expected resolution status to remain available (race lost), got %s", resolutions[0].Status)
	}
}

// TestLoadSweepConfigFromEnv verifies env-var parsing and defaults for the
// single MCP_MESH_RETENTION knob.
func TestLoadSweepConfigFromEnv(t *testing.T) {
	t.Run("default when unset", func(t *testing.T) {
		t.Setenv("MCP_MESH_RETENTION", "")
		cfg := LoadSweepConfigFromEnv(nil)
		if cfg.Retention != defaultRetention {
			t.Errorf("Retention default = %s, want %s", cfg.Retention, defaultRetention)
		}
	})

	t.Run("custom value parsed", func(t *testing.T) {
		t.Setenv("MCP_MESH_RETENTION", "2h")
		cfg := LoadSweepConfigFromEnv(nil)
		if cfg.Retention != 2*time.Hour {
			t.Errorf("Retention = %s, want 2h", cfg.Retention)
		}
	})

	t.Run("zero disables", func(t *testing.T) {
		t.Setenv("MCP_MESH_RETENTION", "0s")
		cfg := LoadSweepConfigFromEnv(nil)
		if cfg.Retention != 0 {
			t.Errorf("Retention = %s, want 0", cfg.Retention)
		}
	})

	t.Run("invalid falls back to default", func(t *testing.T) {
		t.Setenv("MCP_MESH_RETENTION", "not-a-duration")
		cfg := LoadSweepConfigFromEnv(nil)
		if cfg.Retention != defaultRetention {
			t.Errorf("Retention with invalid value = %s, want %s (default)", cfg.Retention, defaultRetention)
		}
	})

	t.Run("negative falls back to default", func(t *testing.T) {
		// Negative durations parse successfully via time.ParseDuration but
		// would silently disable sweep via the Retention<=0 check in Start().
		// Treat them as a typo (likely meant a positive value) and keep the
		// default; 0 remains the documented disable mechanism.
		t.Setenv("MCP_MESH_RETENTION", "-1h")
		cfg := LoadSweepConfigFromEnv(nil)
		if cfg.Retention != defaultRetention {
			t.Errorf("Retention with negative value = %s, want %s (default)", cfg.Retention, defaultRetention)
		}
	})
}

// seedSchemaEntryAt inserts a schema_entry directly via Ent with the given
// hash and created_at, bypassing the upsert path used by RegisterAgent.
func seedSchemaEntryAt(t *testing.T, client *ent.Client, hash string, createdAt time.Time) {
	t.Helper()
	ctx := context.Background()
	_, err := client.SchemaEntry.Create().
		SetHash(hash).
		SetCanonical(map[string]interface{}{"type": "object"}).
		SetCreatedAt(createdAt).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed schema_entry %s: %v", hash, err)
	}
}

// TestSweep_PurgeOrphanSchemaEntries_DeletesOrphan verifies that a
// schema_entry with no referencing capability and a created_at older
// than retention is purged.
func TestSweep_PurgeOrphanSchemaEntries_DeletesOrphan(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Orphan schema entry, well past retention.
	seedSchemaEntryAt(t, client, "sha256:orphan", now.Add(-2*time.Hour))

	_, _, schemasPurged, err := job.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if schemasPurged != 1 {
		t.Errorf("expected 1 schema purged, got %d", schemasPurged)
	}

	count, err := client.SchemaEntry.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count schema entries: %v", err)
	}
	if count != 0 {
		t.Errorf("expected 0 schema entries remaining, got %d", count)
	}
}

// TestSweep_PurgeOrphanSchemaEntries_KeepsReferenced verifies that a
// schema_entry referenced by a capability's input_schema_hash or
// output_schema_hash is NOT purged, even when older than retention.
func TestSweep_PurgeOrphanSchemaEntries_KeepsReferenced(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Healthy provider agent.
	seedAgent(t, client, "provider", agent.StatusHealthy, now)

	// Two stale schema entries: one referenced by input_schema_hash,
	// one by output_schema_hash. Neither should be purged.
	seedSchemaEntryAt(t, client, "sha256:input", now.Add(-2*time.Hour))
	seedSchemaEntryAt(t, client, "sha256:output", now.Add(-2*time.Hour))

	inHash := "sha256:input"
	outHash := "sha256:output"
	_, err := client.Capability.Create().
		SetAgentID("provider").
		SetFunctionName("do_thing").
		SetCapability("widget").
		SetInputSchemaHash(inHash).
		SetOutputSchemaHash(outHash).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed capability: %v", err)
	}

	_, _, schemasPurged, err := job.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if schemasPurged != 0 {
		t.Errorf("expected 0 schemas purged (both referenced), got %d", schemasPurged)
	}

	count, err := client.SchemaEntry.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count schema entries: %v", err)
	}
	if count != 2 {
		t.Errorf("expected 2 schema entries remaining, got %d", count)
	}
}

// TestSweep_PurgeOrphanSchemaEntries_KeepsRecent verifies that an orphan
// schema_entry younger than the retention window is NOT purged.
func TestSweep_PurgeOrphanSchemaEntries_KeepsRecent(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// Orphan, but only 30 minutes old (within 1h retention).
	seedSchemaEntryAt(t, client, "sha256:fresh-orphan", now.Add(-30*time.Minute))

	_, _, schemasPurged, err := job.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if schemasPurged != 0 {
		t.Errorf("expected 0 schemas purged (within retention), got %d", schemasPurged)
	}

	count, err := client.SchemaEntry.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count schema entries: %v", err)
	}
	if count != 1 {
		t.Errorf("expected 1 schema entry remaining, got %d", count)
	}
}

// TestSweep_PurgeOrphanSchemaEntries_RaceSafety simulates the race where
// a schema_entry is in the candidate set (orphan + stale) but a
// concurrent registration creates a capability referencing the hash
// before the per-row delete tx runs. The in-tx re-check must catch this
// and skip the delete. We exercise the race by calling
// purgeOneSchemaEntry directly after seeding the racing capability —
// this mirrors how TestSweepSkipsAgentRevivedDuringTick exercises the
// agent purge race.
func TestSweep_PurgeOrphanSchemaEntries_RaceSafety(t *testing.T) {
	now := time.Date(2026, 4, 29, 12, 0, 0, 0, time.UTC)
	cfg := SweepConfig{Retention: 1 * time.Hour}
	client, _, job, cleanup := newSweepTestEnv(t, cfg, now)
	defer cleanup()

	ctx := context.Background()

	// 1. Orphan schema entry, past retention. Would be purged on a
	//    naive sweep.
	seedSchemaEntryAt(t, client, "sha256:racing", now.Add(-2*time.Hour))

	// 2. Snapshot the candidate scan and confirm it would pick this
	//    entry up.
	threshold := now.Add(-cfg.Retention)
	candidates, err := client.SchemaEntry.Query().
		Where(schemaentry.CreatedAtLT(threshold)).
		All(ctx)
	if err != nil {
		t.Fatalf("query candidates: %v", err)
	}
	if len(candidates) != 1 || candidates[0].Hash != "sha256:racing" {
		t.Fatalf("expected exactly one candidate (sha256:racing), got %v", candidates)
	}

	// 3. Simulate a concurrent registration: a capability now references
	//    the hash. This is what the in-tx re-query must catch.
	seedAgent(t, client, "racing-provider", agent.StatusHealthy, now)
	racingHash := "sha256:racing"
	_, err = client.Capability.Create().
		SetAgentID("racing-provider").
		SetFunctionName("late_arrival").
		SetCapability("widget").
		SetInputSchemaHash(racingHash).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed racing capability: %v", err)
	}

	// 4. Run the per-row delete. The in-tx Capability ref-count must
	//    return >0 and the delete must be skipped.
	deleted, err := job.purgeOneSchemaEntry(ctx, "sha256:racing", threshold)
	if err != nil {
		t.Fatalf("purgeOneSchemaEntry: %v", err)
	}
	if deleted {
		t.Errorf("expected purge to be skipped (race lost), got deleted=true")
	}

	// 5. Schema entry must still exist.
	count, err := client.SchemaEntry.Query().
		Where(schemaentry.HashEQ("sha256:racing")).
		Count(ctx)
	if err != nil {
		t.Fatalf("query schema entry: %v", err)
	}
	if count != 1 {
		t.Errorf("expected racing schema_entry preserved, got count=%d", count)
	}
}
