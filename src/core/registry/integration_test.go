package registry

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

func TestEntServiceStatusChangeIntegration(t *testing.T) {
	// Create an in-memory SQLite database for testing
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	// Create logger and config
	testConfig := &config.Config{LogLevel: "INFO"}
	testLogger := logger.New(testConfig)

	// Create EntDatabase wrapper
	entDB := &database.EntDatabase{Client: client}

	// Create EntService (this should register the hooks automatically)
	service := NewEntService(entDB, nil, testLogger)

	// Verify hooks are enabled
	if !service.IsStatusChangeHooksEnabled() {
		t.Error("Status change hooks should be enabled by default")
	}

	ctx := context.Background()

	// Test 1: Register an agent (should not trigger status change hook since it's create, not update)
	registerReq := &AgentRegistrationRequest{
		AgentID:   "integration-test-agent",
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "integration-test-agent",
			"version":    "1.0.0",
		},
	}

	resp, err := service.RegisterAgent(registerReq)
	if err != nil {
		t.Fatalf("Failed to register agent: %v", err)
	}
	if resp.Status != "success" {
		t.Errorf("Expected successful registration, got status: %s", resp.Status)
	}

	// Check events - should have no status change events yet (only from hooks)
	events, err := entDB.Client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}

	// There should be no events from status changes since registration doesn't trigger status hooks
	hookEvents := 0
	for _, event := range events {
		if data, ok := event.Data["source"]; ok && data == "status_change_hook" {
			hookEvents++
		}
	}
	if hookEvents != 0 {
		t.Errorf("Expected 0 hook events after registration, got %d", hookEvents)
	}

	// Test 2: Directly update agent status (should trigger status change hook)
	_, err = entDB.Client.Agent.UpdateOneID("integration-test-agent").
		SetStatus(agent.StatusUnhealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Check that status change hook created an event
	events, err = entDB.Client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}

	hookEvents = 0
	var statusChangeEvent *ent.RegistryEvent
	for _, event := range events {
		if data, ok := event.Data["source"]; ok && data == "status_change_hook" {
			hookEvents++
			statusChangeEvent = event
		}
	}
	if hookEvents != 1 {
		t.Errorf("Expected 1 hook event after status update, got %d", hookEvents)
	}

	if statusChangeEvent != nil {
		if statusChangeEvent.EventType != registryevent.EventTypeUnhealthy {
			t.Errorf("Expected unhealthy event type, got %s", statusChangeEvent.EventType)
		}

		if statusChangeEvent.Data["old_status"] != "healthy" {
			t.Errorf("Expected old_status 'healthy', got %v", statusChangeEvent.Data["old_status"])
		}
		if statusChangeEvent.Data["new_status"] != "unhealthy" {
			t.Errorf("Expected new_status 'unhealthy', got %v", statusChangeEvent.Data["new_status"])
		}
	}

	// Test 3: Update via heartbeat (should also trigger status change hook on recovery)
	heartbeatReq := &HeartbeatRequest{
		AgentID: "integration-test-agent",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "integration-test-agent",
			"version":    "1.0.0",
			"tools":      []interface{}{}, // Empty tools to trigger metadata update
		},
	}

	heartbeatResp, err := service.UpdateHeartbeat(heartbeatReq)
	if err != nil {
		t.Fatalf("Failed to update heartbeat: %v", err)
	}
	if heartbeatResp.Status != "success" {
		t.Errorf("Expected successful heartbeat, got status: %s", heartbeatResp.Status)
	}

	// Check that recovery triggered another status change hook
	events, err = entDB.Client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}

	hookEvents = 0
	for _, event := range events {
		if data, ok := event.Data["source"]; ok && data == "status_change_hook" {
			hookEvents++
		}
	}
	if hookEvents != 2 {
		t.Errorf("Expected 2 hook events after heartbeat recovery, got %d", hookEvents)
	}

	// Test 4: Disable hooks and verify they don't trigger
	service.DisableStatusChangeHooks()

	if service.IsStatusChangeHooksEnabled() {
		t.Error("Status change hooks should be disabled after calling DisableStatusChangeHooks")
	}

	// Update status again
	_, err = entDB.Client.Agent.UpdateOneID("integration-test-agent").
		SetStatus(agent.StatusUnknown).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Should still have only 2 hook events (hooks disabled)
	events, err = entDB.Client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}

	hookEvents = 0
	for _, event := range events {
		if data, ok := event.Data["source"]; ok && data == "status_change_hook" {
			hookEvents++
		}
	}
	if hookEvents != 2 {
		t.Errorf("Expected still 2 hook events after disabling hooks, got %d", hookEvents)
	}

	// Test 5: Re-enable hooks
	service.EnableStatusChangeHooks()

	if !service.IsStatusChangeHooksEnabled() {
		t.Error("Status change hooks should be enabled after calling EnableStatusChangeHooks")
	}

	// Update status again
	_, err = entDB.Client.Agent.UpdateOneID("integration-test-agent").
		SetStatus(agent.StatusHealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Should now have 3 hook events (hooks re-enabled)
	events, err = entDB.Client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}

	hookEvents = 0
	for _, event := range events {
		if data, ok := event.Data["source"]; ok && data == "status_change_hook" {
			hookEvents++
		}
	}
	if hookEvents != 3 {
		t.Errorf("Expected 3 hook events after re-enabling hooks, got %d", hookEvents)
	}

	t.Logf("Integration test completed successfully with %d status change events", hookEvents)
}

// TestSweepJobIntegration exercises the sweep job end-to-end against a real
// EntService: register an agent via the public API, force its updated_at and
// status to look stale, run one sweep tick, and verify ListAgents no longer
// returns it.
func TestSweepJobIntegration(t *testing.T) {
	client := enttest.Open(t, "sqlite3", "file:sweep_integration?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	testConfig := &config.Config{LogLevel: "INFO"}
	testLogger := logger.New(testConfig)
	entDB := &database.EntDatabase{Client: client}
	service := NewEntService(entDB, nil, testLogger)

	ctx := context.Background()

	registerReq := &AgentRegistrationRequest{
		AgentID:   "sweep-target",
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "sweep-target",
			"version":    "1.0.0",
		},
	}
	if _, err := service.RegisterAgent(registerReq); err != nil {
		t.Fatalf("Failed to register agent: %v", err)
	}

	// Force the agent into a stale unhealthy state: timestamp > AgentRetention
	// in the past, status=unhealthy. This mimics a real-world agent whose
	// heartbeat stopped over an hour ago and was already flagged by the
	// health monitor.
	twoHoursAgo := time.Now().UTC().Add(-2 * time.Hour)
	if _, err := entDB.Client.Agent.UpdateOneID("sweep-target").
		SetStatus(agent.StatusUnhealthy).
		SetUpdatedAt(twoHoursAgo).
		Save(ctx); err != nil {
		t.Fatalf("Failed to force stale state: %v", err)
	}

	cfg := SweepConfig{Retention: 1 * time.Hour}
	job := NewSweepJob(cfg, entDB, service, testLogger)

	purgedAgents, _, _, err := job.runOnce(ctx)
	if err != nil {
		t.Fatalf("runOnce: %v", err)
	}
	if purgedAgents != 1 {
		t.Errorf("expected 1 agent purged, got %d", purgedAgents)
	}

	// Sanity-check via the public ListAgents API: the agent must be gone
	// from both the default (healthy-only) and unfiltered views.
	resp, err := service.ListAgents(&AgentQueryParams{})
	if err != nil {
		t.Fatalf("ListAgents: %v", err)
	}
	for _, a := range resp.Agents {
		if a.Id == "sweep-target" {
			t.Errorf("sweep-target still present in ListAgents after purge")
		}
	}
}
