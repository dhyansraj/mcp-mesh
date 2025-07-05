package registry

import (
	"context"
	"testing"
	"time"

	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/enttest"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/logger"

	_ "github.com/mattn/go-sqlite3"
)

func TestAgentStatusChangeHook(t *testing.T) {
	// Create an in-memory SQLite database for testing
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	// Create logger for testing
	testConfig := &config.Config{LogLevel: "DEBUG"}
	testLogger := logger.New(testConfig)

	// Create hook manager
	hookManager := NewAgentStatusChangeHookManager(testLogger, true)

	// Register hooks with the client
	for _, hook := range hookManager.GetHooks() {
		client.Use(hook)
	}

	ctx := context.Background()

	// Test case 1: Create agent (should not trigger status change hook)
	_, err := client.Agent.Create().
		SetID("test-agent-1").
		SetName("Test Agent 1").
		SetStatus(agent.StatusHealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to create agent: %v", err)
	}

	// Verify no events were created during agent creation
	events, err := client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}
	if len(events) != 0 {
		t.Errorf("Expected 0 events after agent creation, got %d", len(events))
	}

	// Test case 2: Update agent status from healthy to unhealthy (should trigger hook)
	_, err = client.Agent.UpdateOneID("test-agent-1").
		SetStatus(agent.StatusUnhealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Verify event was created
	events, err = client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}
	if len(events) != 1 {
		t.Errorf("Expected 1 event after status change, got %d", len(events))
	}

	// Verify event details
	if len(events) > 0 {
		event := events[0]
		if event.EventType != registryevent.EventTypeUnhealthy {
			t.Errorf("Expected event type %s, got %s", registryevent.EventTypeUnhealthy, event.EventType)
		}
		// Get the agent through the edge relationship
		agentEdge, err := event.QueryAgent().Only(ctx)
		if err != nil {
			t.Errorf("Failed to query agent edge: %v", err)
		} else if agentEdge.ID != "test-agent-1" {
			t.Errorf("Expected agent ID 'test-agent-1', got %s", agentEdge.ID)
		}

		// Check event data
		data := event.Data
		if data["old_status"] != "healthy" {
			t.Errorf("Expected old_status 'healthy', got %v", data["old_status"])
		}
		if data["new_status"] != "unhealthy" {
			t.Errorf("Expected new_status 'unhealthy', got %v", data["new_status"])
		}
		if data["reason"] != "health_degradation" {
			t.Errorf("Expected reason 'health_degradation', got %v", data["reason"])
		}
	}

	// Test case 3: Update agent status from unhealthy to healthy (should trigger recovery)
	_, err = client.Agent.UpdateOneID("test-agent-1").
		SetStatus(agent.StatusHealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Verify second event was created
	events, err = client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("Expected 2 events after recovery, got %d", len(events))
	}

	// Verify recovery event details
	if len(events) >= 2 {
		// Get the latest event
		recoveryEvent := events[1]
		if recoveryEvent.EventType != registryevent.EventTypeRegister {
			t.Errorf("Expected recovery event type %s, got %s", registryevent.EventTypeRegister, recoveryEvent.EventType)
		}

		data := recoveryEvent.Data
		if data["old_status"] != "unhealthy" {
			t.Errorf("Expected old_status 'unhealthy', got %v", data["old_status"])
		}
		if data["new_status"] != "healthy" {
			t.Errorf("Expected new_status 'healthy', got %v", data["new_status"])
		}
		if data["reason"] != "recovery" {
			t.Errorf("Expected reason 'recovery', got %v", data["reason"])
		}
	}

	// Test case 4: Update agent with same status (should not trigger hook)
	_, err = client.Agent.UpdateOneID("test-agent-1").
		SetStatus(agent.StatusHealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Verify no new events were created
	events, err = client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("Expected 2 events after same-status update, got %d", len(events))
	}

	// Test case 5: Update agent field other than status (should not trigger hook)
	_, err = client.Agent.UpdateOneID("test-agent-1").
		SetName("Updated Test Agent 1").
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent name: %v", err)
	}

	// Verify no new events were created
	events, err = client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}
	if len(events) != 2 {
		t.Errorf("Expected 2 events after name update, got %d", len(events))
	}
}

func TestAgentStatusChangeHookDisabled(t *testing.T) {
	// Create an in-memory SQLite database for testing
	client := enttest.Open(t, "sqlite3", "file:ent?mode=memory&cache=shared&_fk=1")
	defer client.Close()

	// Create logger for testing
	testConfig := &config.Config{LogLevel: "DEBUG"}
	testLogger := logger.New(testConfig)

	// Create hook manager with hooks disabled
	hookManager := NewAgentStatusChangeHookManager(testLogger, false)

	// Register hooks with the client
	for _, hook := range hookManager.GetHooks() {
		client.Use(hook)
	}

	ctx := context.Background()

	// Create agent
	_, err := client.Agent.Create().
		SetID("test-agent-disabled").
		SetName("Test Agent Disabled").
		SetStatus(agent.StatusHealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to create agent: %v", err)
	}

	// Update agent status (should not trigger hook because it's disabled)
	_, err = client.Agent.UpdateOneID("test-agent-disabled").
		SetStatus(agent.StatusUnhealthy).
		Save(ctx)
	if err != nil {
		t.Fatalf("Failed to update agent status: %v", err)
	}

	// Verify no events were created
	events, err := client.RegistryEvent.Query().All(ctx)
	if err != nil {
		t.Fatalf("Failed to query events: %v", err)
	}
	if len(events) != 0 {
		t.Errorf("Expected 0 events when hooks are disabled, got %d", len(events))
	}
}

func TestGetEventTypeForStatusChange(t *testing.T) {
	testCases := []struct {
		name        string
		oldStatus   agent.Status
		newStatus   agent.Status
		expectedType registryevent.EventType
	}{
		{
			name:        "healthy to unhealthy",
			oldStatus:   agent.StatusHealthy,
			newStatus:   agent.StatusUnhealthy,
			expectedType: registryevent.EventTypeUnhealthy,
		},
		{
			name:        "unhealthy to healthy",
			oldStatus:   agent.StatusUnhealthy,
			newStatus:   agent.StatusHealthy,
			expectedType: registryevent.EventTypeRegister,
		},
		{
			name:        "healthy to unknown",
			oldStatus:   agent.StatusHealthy,
			newStatus:   agent.StatusUnknown,
			expectedType: registryevent.EventTypeUnhealthy,
		},
		{
			name:        "unknown to healthy",
			oldStatus:   agent.StatusUnknown,
			newStatus:   agent.StatusHealthy,
			expectedType: registryevent.EventTypeRegister,
		},
		{
			name:        "unknown to unhealthy",
			oldStatus:   agent.StatusUnknown,
			newStatus:   agent.StatusUnhealthy,
			expectedType: registryevent.EventTypeUnhealthy,
		},
		{
			name:        "unhealthy to unknown",
			oldStatus:   agent.StatusUnhealthy,
			newStatus:   agent.StatusUnknown,
			expectedType: registryevent.EventTypeUpdate,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			eventType := getEventTypeForStatusChange(tc.oldStatus, tc.newStatus)
			if eventType != tc.expectedType {
				t.Errorf("Expected event type %s, got %s", tc.expectedType, eventType)
			}
		})
	}
}

func TestCreateEventDataForStatusChange(t *testing.T) {
	oldStatus := agent.StatusHealthy
	newStatus := agent.StatusUnhealthy

	eventData := createEventDataForStatusChange(oldStatus, newStatus)

	// Check required fields
	if eventData["old_status"] != "healthy" {
		t.Errorf("Expected old_status 'healthy', got %v", eventData["old_status"])
	}
	if eventData["new_status"] != "unhealthy" {
		t.Errorf("Expected new_status 'unhealthy', got %v", eventData["new_status"])
	}
	if eventData["reason"] != "health_degradation" {
		t.Errorf("Expected reason 'health_degradation', got %v", eventData["reason"])
	}
	if eventData["source"] != "status_change_hook" {
		t.Errorf("Expected source 'status_change_hook', got %v", eventData["source"])
	}
	if eventData["transition_type"] != "healthy_to_unhealthy" {
		t.Errorf("Expected transition_type 'healthy_to_unhealthy', got %v", eventData["transition_type"])
	}

	// Check that detected_at is a valid timestamp
	if detectedAt, ok := eventData["detected_at"].(string); ok {
		if _, err := time.Parse(time.RFC3339, detectedAt); err != nil {
			t.Errorf("Invalid detected_at timestamp: %v", err)
		}
	} else {
		t.Errorf("Expected detected_at to be a string, got %T", eventData["detected_at"])
	}
}
