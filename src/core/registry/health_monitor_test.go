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
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

// newHealthMonitorTestEnv constructs an in-memory Ent client + EntService +
// health monitor with the given heartbeat timeout. Status change hooks are
// disabled (like the sweep tests) so direct Ent status updates don't create
// extra registry events.
func newHealthMonitorTestEnv(t *testing.T, heartbeatTimeout time.Duration) (*ent.Client, *EntService, *AgentHealthMonitor, func()) {
	t.Helper()

	client := enttest.Open(t, "sqlite3", "file:healthmon_"+t.Name()+"?mode=memory&cache=shared&_fk=1")
	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	entDB := &database.EntDatabase{Client: client}
	service := NewEntService(entDB, nil, testLogger)
	service.DisableStatusChangeHooks()

	monitor := NewAgentHealthMonitor(service, testLogger, heartbeatTimeout, time.Minute)

	cleanup := func() {
		client.Close()
	}
	return client, service, monitor, cleanup
}

// seedProviderResolutions inserts one row per resolution table, all pointing
// consumer -> provider with status=available.
func seedProviderResolutions(t *testing.T, client *ent.Client, consumerID, providerID string) {
	t.Helper()
	ctx := context.Background()

	_, err := client.DependencyResolution.Create().
		SetConsumerAgentID(consumerID).
		SetConsumerFunctionName("do_thing").
		SetCapabilityRequired("widget").
		SetProviderAgentID(providerID).
		SetProviderFunctionName("widget_impl").
		SetEndpoint("http://provider:8080").
		SetStatus(dependencyresolution.StatusAvailable).
		SetResolvedAt(time.Now().UTC()).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed dep resolution: %v", err)
	}

	_, err = client.LLMToolResolution.Create().
		SetConsumerAgentID(consumerID).
		SetConsumerFunctionName("ask_llm").
		SetProviderAgentID(providerID).
		SetProviderFunctionName("time_tool").
		SetProviderCapability("time_service").
		SetEndpoint("http://provider:8080").
		SetStatus(llmtoolresolution.StatusAvailable).
		SetResolvedAt(time.Now().UTC()).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed llm tool resolution: %v", err)
	}

	_, err = client.LLMProviderResolution.Create().
		SetConsumerAgentID(consumerID).
		SetConsumerFunctionName("ask_llm").
		SetRequiredCapability("llm").
		SetProviderAgentID(providerID).
		SetProviderFunctionName("llm").
		SetEndpoint("http://provider:8080").
		SetStatus(llmproviderresolution.StatusAvailable).
		SetResolvedAt(time.Now().UTC()).
		Save(ctx)
	if err != nil {
		t.Fatalf("seed llm provider resolution: %v", err)
	}
}

// assertProviderResolutionStatuses asserts the status of the seeded rows in
// all three resolution tables for the given consumer.
func assertProviderResolutionStatuses(t *testing.T, client *ent.Client, consumerID string, wantAvailable bool) {
	t.Helper()
	ctx := context.Background()

	depRows, err := client.DependencyResolution.Query().
		Where(dependencyresolution.ConsumerAgentIDEQ(consumerID)).
		All(ctx)
	if err != nil || len(depRows) != 1 {
		t.Fatalf("query dep resolutions: err=%v len=%d", err, len(depRows))
	}
	toolRows, err := client.LLMToolResolution.Query().
		Where(llmtoolresolution.ConsumerAgentIDEQ(consumerID)).
		All(ctx)
	if err != nil || len(toolRows) != 1 {
		t.Fatalf("query llm tool resolutions: err=%v len=%d", err, len(toolRows))
	}
	provRows, err := client.LLMProviderResolution.Query().
		Where(llmproviderresolution.ConsumerAgentIDEQ(consumerID)).
		All(ctx)
	if err != nil || len(provRows) != 1 {
		t.Fatalf("query llm provider resolutions: err=%v len=%d", err, len(provRows))
	}

	if wantAvailable {
		if depRows[0].Status != dependencyresolution.StatusAvailable {
			t.Errorf("dep resolution status = %s, want available", depRows[0].Status)
		}
		if toolRows[0].Status != llmtoolresolution.StatusAvailable {
			t.Errorf("llm tool resolution status = %s, want available", toolRows[0].Status)
		}
		if provRows[0].Status != llmproviderresolution.StatusAvailable {
			t.Errorf("llm provider resolution status = %s, want available", provRows[0].Status)
		}
	} else {
		if depRows[0].Status != dependencyresolution.StatusUnavailable {
			t.Errorf("dep resolution status = %s, want unavailable", depRows[0].Status)
		}
		if toolRows[0].Status != llmtoolresolution.StatusUnavailable {
			t.Errorf("llm tool resolution status = %s, want unavailable", toolRows[0].Status)
		}
		if provRows[0].Status != llmproviderresolution.StatusUnavailable {
			t.Errorf("llm provider resolution status = %s, want unavailable", provRows[0].Status)
		}
	}
}

// TestHealthMonitorMarksStaleAgentUnhealthy verifies the happy path: a stale
// agent is flipped to unhealthy with its updated_at PRESERVED (not bumped),
// and all three resolution tables pointing at it are flipped to unavailable
// (MED-5 wiring).
func TestHealthMonitorMarksStaleAgentUnhealthy(t *testing.T) {
	client, _, monitor, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "provider", agent.StatusHealthy, staleTime)
	seedAgent(t, client, "consumer", agent.StatusHealthy, time.Now().UTC())
	seedProviderResolutions(t, client, "consumer", "provider")

	monitor.checkUnhealthyAgents()

	got, err := client.Agent.Get(ctx, "provider")
	if err != nil {
		t.Fatalf("reload provider: %v", err)
	}
	if got.Status != agent.StatusUnhealthy {
		t.Errorf("provider status = %s, want unhealthy", got.Status)
	}
	if !got.UpdatedAt.Equal(staleTime) {
		t.Errorf("provider updated_at = %v, want preserved %v", got.UpdatedAt, staleTime)
	}

	// Consumer (fresh heartbeat) must be untouched.
	gotConsumer, err := client.Agent.Get(ctx, "consumer")
	if err != nil {
		t.Fatalf("reload consumer: %v", err)
	}
	if gotConsumer.Status != agent.StatusHealthy {
		t.Errorf("consumer status = %s, want healthy", gotConsumer.Status)
	}

	// All three resolution tables flipped to unavailable.
	assertProviderResolutionStatuses(t, client, "consumer", false)
}

// TestHealthMonitorSkipsConcurrentHeartbeat simulates the MED-1 interleave:
// the monitor queries a stale snapshot, a heartbeat lands on the row, and the
// monitor's guarded update must affect 0 rows — leaving the agent healthy
// with its CURRENT (heartbeat) timestamp instead of overwriting it unhealthy
// with a rolled-back timestamp.
func TestHealthMonitorSkipsConcurrentHeartbeat(t *testing.T) {
	client, _, monitor, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "racer", agent.StatusHealthy, staleTime)
	seedAgent(t, client, "consumer", agent.StatusHealthy, time.Now().UTC())
	seedProviderResolutions(t, client, "consumer", "racer")

	// Step 1: the monitor's staleness query loads a snapshot.
	snapshot, err := client.Agent.Get(ctx, "racer")
	if err != nil {
		t.Fatalf("load snapshot: %v", err)
	}

	// Step 2: a heartbeat lands between query and update.
	heartbeatTime := time.Now().UTC().Truncate(time.Millisecond)
	if _, err := client.Agent.UpdateOneID("racer").
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(heartbeatTime).
		Save(ctx); err != nil {
		t.Fatalf("simulate heartbeat: %v", err)
	}

	// Step 3: the monitor's guarded update runs with the stale snapshot and
	// must lose the race (0 rows affected, no error).
	won, err := monitor.markAgentUnhealthyIfUnchanged(ctx, snapshot)
	if err != nil {
		t.Fatalf("markAgentUnhealthyIfUnchanged: %v", err)
	}
	if won {
		t.Error("guarded update must lose the race against a concurrent heartbeat")
	}

	got, err := client.Agent.Get(ctx, "racer")
	if err != nil {
		t.Fatalf("reload agent: %v", err)
	}
	if got.Status != agent.StatusHealthy {
		t.Errorf("agent status = %s, want healthy (heartbeat must win)", got.Status)
	}
	if !got.UpdatedAt.Equal(heartbeatTime) {
		t.Errorf("agent updated_at = %v, want heartbeat time %v (must NOT be rolled back to %v)",
			got.UpdatedAt, heartbeatTime, staleTime)
	}

	// Race-lost path must NOT flip resolution rows either.
	assertProviderResolutionStatuses(t, client, "consumer", true)
}

// TestHealthMonitorFullPassSkipsConcurrentHeartbeat exercises the same race
// through checkUnhealthyAgents itself: the agent heartbeats after seeding but
// the monitor query then no longer sees it as stale — and a stale OTHER agent
// in the same pass is still flipped. Guards against the per-agent failure
// affecting the whole batch.
func TestHealthMonitorFullPassSkipsConcurrentHeartbeat(t *testing.T) {
	client, _, monitor, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	staleTime := time.Now().UTC().Add(-2 * time.Minute).Truncate(time.Millisecond)
	seedAgent(t, client, "stale-a", agent.StatusHealthy, staleTime)
	seedAgent(t, client, "fresh-b", agent.StatusHealthy, time.Now().UTC())

	monitor.checkUnhealthyAgents()

	gotA, _ := client.Agent.Get(ctx, "stale-a")
	if gotA.Status != agent.StatusUnhealthy {
		t.Errorf("stale-a status = %s, want unhealthy", gotA.Status)
	}
	gotB, _ := client.Agent.Get(ctx, "fresh-b")
	if gotB.Status != agent.StatusHealthy {
		t.Errorf("fresh-b status = %s, want healthy", gotB.Status)
	}
}

// TestUnregisterAgentFlipsResolutions verifies the MED-5 wiring on the
// graceful-shutdown path: UnregisterAgent marks the agent unhealthy AND flips
// all three resolution tables pointing at it to unavailable.
func TestUnregisterAgentFlipsResolutions(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	seedAgent(t, client, "provider", agent.StatusHealthy, time.Now().UTC())
	seedAgent(t, client, "consumer", agent.StatusHealthy, time.Now().UTC())
	seedProviderResolutions(t, client, "consumer", "provider")

	if err := service.UnregisterAgent(ctx, "provider"); err != nil {
		t.Fatalf("UnregisterAgent: %v", err)
	}

	got, err := client.Agent.Get(ctx, "provider")
	if err != nil {
		t.Fatalf("reload provider: %v", err)
	}
	if got.Status != agent.StatusUnhealthy {
		t.Errorf("provider status = %s, want unhealthy", got.Status)
	}

	assertProviderResolutionStatuses(t, client, "consumer", false)
}

// TestReturningProviderRestoresResolutions documents the reverse transition:
// when the provider comes back, the consumer's next FULL heartbeat re-resolves
// and StoreDependencyResolutions recreates the row with status=available.
// (HEAD heartbeats detect the provider's "register" event as a topology
// change, which is what triggers that full refresh in production.)
func TestReturningProviderRestoresResolutions(t *testing.T) {
	client, service, _, cleanup := newHealthMonitorTestEnv(t, time.Minute)
	defer cleanup()
	ctx := context.Background()

	seedAgent(t, client, "provider", agent.StatusHealthy, time.Now().UTC())
	seedAgent(t, client, "consumer", agent.StatusHealthy, time.Now().UTC())
	seedProviderResolutions(t, client, "consumer", "provider")

	// Provider goes away gracefully — rows flip to unavailable.
	if err := service.UnregisterAgent(ctx, "provider"); err != nil {
		t.Fatalf("UnregisterAgent: %v", err)
	}
	assertProviderResolutionStatuses(t, client, "consumer", false)

	// Provider returns; consumer's full-heartbeat persistence path runs.
	resolutions := []IndexedResolution{
		{
			FunctionName: "do_thing",
			DepIndex:     0,
			Spec:         DependencySpec{Capability: "widget"},
			Resolution: &DependencyResolution{
				AgentID:      "provider",
				FunctionName: "widget_impl",
				Endpoint:     "http://provider:8080",
				Capability:   "widget",
				Status:       "available",
			},
			Status: "available",
		},
	}
	if err := service.StoreDependencyResolutions(ctx, "consumer", resolutions); err != nil {
		t.Fatalf("StoreDependencyResolutions: %v", err)
	}

	depRows, err := client.DependencyResolution.Query().
		Where(dependencyresolution.ConsumerAgentIDEQ("consumer")).
		All(ctx)
	if err != nil || len(depRows) != 1 {
		t.Fatalf("query dep resolutions: err=%v len=%d", err, len(depRows))
	}
	if depRows[0].Status != dependencyresolution.StatusAvailable {
		t.Errorf("dep resolution status = %s, want available after provider returns", depRows[0].Status)
	}
}
