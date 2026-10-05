package registry

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

// TestCleanupStaleAgentsOnStartupPreservesUpdatedAt verifies that the startup
// stale-agent sweep flips status to unhealthy WITHOUT bumping updated_at.
//
// updated_at is the agent's last-heartbeat timestamp from the periodic sweep
// job's perspective (it filters on UpdatedAtLT(now-retention)). If startup
// cleanup bumped updated_at, just-marked-stale agents would survive the
// immediate sweep tick even when they had been silent for hours/days.
func TestCleanupStaleAgentsOnStartupPreservesUpdatedAt(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:startup_cleanup_preserve?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	testLogger := logger.New(&config.Config{LogLevel: "ERROR"})
	entDB := &database.EntDatabase{Client: client}
	cfg := &RegistryConfig{
		StartupCleanupThreshold: 30, // 30s
	}
	// Status change hooks stay ENABLED, as in production: the transition must
	// still produce exactly one event (markAgentStaleAttempt's own).
	service := NewEntService(entDB, cfg, testLogger)

	ctx := context.Background()

	// Seed a healthy agent whose updated_at is 2h in the past — well beyond
	// the 30s threshold, so it qualifies as stale on startup.
	oldUpdatedAt := time.Now().UTC().Add(-2 * time.Hour).Truncate(time.Microsecond)
	agentID := "stale-on-startup"
	if _, err := client.Agent.Create().
		SetID(agentID).
		SetName(agentID).
		SetAgentType(agent.AgentTypeMcpAgent).
		SetStatus(agent.StatusHealthy).
		SetUpdatedAt(oldUpdatedAt).
		Save(ctx); err != nil {
		t.Fatalf("seed agent: %v", err)
	}
	// Defensive re-write of updated_at in case any default fired.
	if _, err := client.Agent.UpdateOneID(agentID).SetUpdatedAt(oldUpdatedAt).Save(ctx); err != nil {
		t.Fatalf("force updated_at: %v", err)
	}

	// Run the startup cleanup.
	cleaned, err := service.CleanupStaleAgentsOnStartup(ctx)
	if err != nil {
		t.Fatalf("CleanupStaleAgentsOnStartup: %v", err)
	}
	if cleaned != 1 {
		t.Fatalf("cleaned = %d, want 1", cleaned)
	}

	// Verify status flipped to unhealthy AND updated_at was preserved.
	got, err := client.Agent.Get(ctx, agentID)
	if err != nil {
		t.Fatalf("re-fetch agent: %v", err)
	}
	if got.Status != agent.StatusUnhealthy {
		t.Errorf("Status = %s, want %s", got.Status, agent.StatusUnhealthy)
	}
	if !got.UpdatedAt.Equal(oldUpdatedAt) {
		t.Errorf("UpdatedAt = %s, want preserved %s (last-heartbeat semantic must survive startup cleanup)",
			got.UpdatedAt.UTC().Format(time.RFC3339Nano),
			oldUpdatedAt.Format(time.RFC3339Nano))
	}

	// Verify exactly one event was recorded for the transition: the explicit
	// stale_on_startup unhealthy event, with timestamp = now (not the
	// preserved updated_at). It records when the cleanup happened.
	events, err := client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("registry events = %d, want exactly 1", len(events))
	}
	if events[0].EventType != registryevent.EventTypeUnhealthy {
		t.Errorf("event type = %s, want unhealthy", events[0].EventType)
	}
	if events[0].Data["reason"] != "stale_on_startup" {
		t.Errorf("event reason = %v, want stale_on_startup", events[0].Data["reason"])
	}
	if !events[0].Timestamp.After(oldUpdatedAt) {
		t.Errorf("event timestamp %s should be after preserved updated_at %s",
			events[0].Timestamp, oldUpdatedAt)
	}
}

// TestMarkAgentStaleAttemptRaceLostWritesNoEvent: a heartbeat lands between
// the startup staleness query and the conditional update, so the update
// affects 0 rows. No event may be recorded and the agent stays healthy.
func TestMarkAgentStaleAttemptRaceLostWritesNoEvent(t *testing.T) {
	client, service, _ := newHealthMonitorHookedEnv(t)
	ctx := context.Background()

	staleTime := time.Now().UTC().Add(-2 * time.Hour).Truncate(time.Millisecond)
	seedAgent(t, client, "startup-racer", agent.StatusHealthy, staleTime)

	snapshot, err := client.Agent.Get(ctx, "startup-racer")
	if err != nil {
		t.Fatalf("load snapshot: %v", err)
	}

	// The heartbeat lands after the snapshot was taken. It is applied before
	// the call rather than injected mid-transaction: under SQLite's shared
	// cache, a second connection writing to agents inside that window hits a
	// table lock, which is a test artifact, not the race under test.
	heartbeatTime := time.Now().UTC().Truncate(time.Millisecond)
	if _, err := client.Agent.UpdateOneID("startup-racer").
		SetUpdatedAt(heartbeatTime).
		Save(ctx); err != nil {
		t.Fatalf("simulate heartbeat: %v", err)
	}

	if err := service.markAgentStaleAttempt(ctx, snapshot, 30); err != nil {
		t.Fatalf("markAgentStaleAttempt: %v", err)
	}

	got, err := client.Agent.Get(ctx, "startup-racer")
	if err != nil {
		t.Fatalf("reload agent: %v", err)
	}
	if got.Status != agent.StatusHealthy {
		t.Errorf("agent status = %s, want healthy", got.Status)
	}
	if !got.UpdatedAt.Equal(heartbeatTime) {
		t.Errorf("agent updated_at = %v, want heartbeat time %v", got.UpdatedAt, heartbeatTime)
	}

	count, err := client.RegistryEvent.Query().Count(ctx)
	if err != nil {
		t.Fatalf("count events: %v", err)
	}
	if count != 0 {
		t.Errorf("race-lost startup cleanup recorded %d registry event(s), want 0", count)
	}
}
