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
	service := NewEntService(entDB, cfg, testLogger)
	// Status change hooks would create extra events; we assert the
	// markAgentStaleAttempt-emitted event explicitly below.
	service.DisableStatusChangeHooks()

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

	// Verify the unhealthy event was created with timestamp = now (not the
	// preserved updated_at). It records when the cleanup happened.
	events, err := client.RegistryEvent.Query().
		Where(registryevent.EventTypeEQ(registryevent.EventTypeUnhealthy)).
		All(ctx)
	if err != nil {
		t.Fatalf("query events: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("unhealthy events = %d, want 1", len(events))
	}
	if !events[0].Timestamp.After(oldUpdatedAt) {
		t.Errorf("event timestamp %s should be after preserved updated_at %s",
			events[0].Timestamp, oldUpdatedAt)
	}
}
