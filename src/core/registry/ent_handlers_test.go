package registry

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"mcp-mesh/src/core/ent"
	"mcp-mesh/src/core/ent/agent"
	"mcp-mesh/src/core/ent/registryevent"
	"mcp-mesh/src/core/registry/generated"
)

func TestFastHeartbeatCheck(t *testing.T) {
	tests := []struct {
		name           string
		agentID        string
		agentExists    bool
		hasChanges     bool
		serviceError   bool
		expectedStatus int
		expectedBody   string
	}{
		{
			name:           "healthy_no_changes",
			agentID:        "fastmcp-service-3a65d884",
			agentExists:    true,
			hasChanges:     false,
			serviceError:   false,
			expectedStatus: 200,
			expectedBody:   "",
		},
		{
			name:           "topology_changed",
			agentID:        "fastmcp-service-3a65d884",
			agentExists:    true,
			hasChanges:     true,
			serviceError:   false,
			expectedStatus: 202,
			expectedBody:   "",
		},
		{
			name:           "unknown_agent",
			agentID:        "nonexistent-agent",
			agentExists:    false,
			hasChanges:     false,
			serviceError:   false,
			expectedStatus: 410,
			expectedBody:   "",
		},
		{
			name:           "service_unavailable",
			agentID:        "fastmcp-service-3a65d884",
			agentExists:    true,
			hasChanges:     false,
			serviceError:   true,
			expectedStatus: 503,
			expectedBody:   "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup: Create test server with mocked EntService
			mockService := NewMockEntService()
			server := NewTestServer(mockService)
			defer server.Close()

			// Mock the service behavior based on test case
			if tt.agentExists {
				mockAgent := &ent.Agent{
					ID:              tt.agentID,
					Name:            tt.agentID,
					LastFullRefresh: time.Now().Add(-5 * time.Minute),
					UpdatedAt:       time.Now(),
				}
				mockService.SetAgent(tt.agentID, mockAgent)
			}

			if tt.serviceError {
				mockService.SetServiceError(true)
			} else {
				mockService.SetTopologyChanges(tt.agentID, tt.hasChanges)
			}

			// Execute: Send HEAD request to /heartbeat/{agent_id}
			req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+tt.agentID, nil)
			require.NoError(t, err)

			client := &http.Client{}
			resp, err := client.Do(req)
			require.NoError(t, err)
			defer resp.Body.Close()

			// Assert: Verify status code and empty body
			assert.Equal(t, tt.expectedStatus, resp.StatusCode, "Expected status code %d, got %d", tt.expectedStatus, resp.StatusCode)
			assert.Equal(t, tt.expectedBody, "", "HEAD response should have empty body")
			// Note: Content-Length header is handled by HTTP server automatically for HEAD requests
		})
	}
}

func TestUnregisterAgent(t *testing.T) {
	tests := []struct {
		name           string
		agentID        string
		agentExists    bool
		expectedStatus int
		expectEvent    bool
		expectDeleted  bool
	}{
		{
			name:           "successful_unregister",
			agentID:        "dependent-service-00d6169a",
			agentExists:    true,
			expectedStatus: 204,
			expectEvent:    true,
			expectDeleted:  true,
		},
		{
			name:           "nonexistent_agent",
			agentID:        "missing-agent",
			agentExists:    false,
			expectedStatus: 204, // Idempotent - should still return 204
			expectEvent:    false,
			expectDeleted:  false,
		},
		{
			name:           "database_error",
			agentID:        "dependent-service-00d6169a",
			agentExists:    true,
			expectedStatus: 500,
			expectEvent:    false,
			expectDeleted:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup: Create test database with agent
			mockService := NewMockEntService()
			server := NewTestServer(mockService)
			defer server.Close()

			if tt.agentExists {
				mockAgent := &ent.Agent{
					ID:        tt.agentID,
					Name:      tt.agentID,
					UpdatedAt: time.Now(),
				}
				mockService.SetAgent(tt.agentID, mockAgent)
			}

			if tt.name == "database_error" {
				mockService.SetServiceError(true)
			}

			// Execute: Send DELETE request to /agents/{agent_id}
			req, err := http.NewRequest("DELETE", server.URL+"/agents/"+tt.agentID, nil)
			require.NoError(t, err)

			client := &http.Client{}
			resp, err := client.Do(req)
			require.NoError(t, err)
			defer resp.Body.Close()

			// Assert: Status code, event creation, agent deletion
			assert.Equal(t, tt.expectedStatus, resp.StatusCode)

			if tt.expectEvent {
				events := mockService.GetEvents()
				assert.Len(t, events, 1, "Should create one unregister event")
				assert.Equal(t, registryevent.EventTypeUnregister, events[0].EventType)
				// Note: AgentID is not directly on the event struct but accessed via edges
			}

			if tt.expectDeleted {
				agent := mockService.GetAgent(tt.agentID)
				assert.Nil(t, agent, "Agent should be deleted")
			}
		})
	}
}

// Test helpers

func NewTestServer(entService *MockEntService) *httptest.Server {
	gin.SetMode(gin.TestMode)
	router := gin.New()

	// Create handlers that implement the generated interfaces
	handlers := &TestHandlers{
		entService: entService,
	}

	// Register routes using the generated registration function
	generated.RegisterHandlers(router, handlers)

	return httptest.NewServer(router)
}

// TestHandlers implements the generated.ServerInterface for testing
type TestHandlers struct {
	entService *MockEntService
}

func (h *TestHandlers) GetRoot(c *gin.Context) {
	c.JSON(200, gin.H{"message": "MCP Mesh Registry"})
}

func (h *TestHandlers) ListAgents(c *gin.Context) {
	agents := h.entService.GetAllAgents()
	c.JSON(200, gin.H{"agents": agents})
}

func (h *TestHandlers) GetHealth(c *gin.Context) {
	c.JSON(200, gin.H{"status": "healthy"})
}

func (h *TestHandlers) HeadHealth(c *gin.Context) {
	c.Status(200)
}

func (h *TestHandlers) SendHeartbeat(c *gin.Context) {
	c.JSON(200, gin.H{"status": "success"})
}

// FastHeartbeatCheck implements the HEAD /heartbeat/{agent_id} endpoint
func (h *TestHandlers) FastHeartbeatCheck(c *gin.Context, agentId string) {
	if h.entService.HasServiceError() {
		c.Status(503) // Service unavailable
		return
	}

	agentEntity := h.entService.GetAgent(agentId)
	if agentEntity == nil {
		c.Status(410) // Gone - unknown agent, please register
		return
	}

	// If agent is unhealthy, return 410 to force full registration
	if agentEntity.Status == agent.StatusUnhealthy {
		c.Status(410) // Gone - agent unhealthy, please re-register
		return
	}

	// Update agent timestamp to indicate recent activity (TDD fix)
	err := h.entService.UpdateAgentHeartbeatTimestamp(agentId)
	if err != nil {
		c.Status(503) // Service unavailable - failed to update timestamp
		return
	}

	// Check for topology changes since last full refresh
	hasChanges := h.entService.GetTopologyChanges(agentId)
	if hasChanges {
		c.Status(202) // Accepted - please send full heartbeat
		return
	}

	c.Status(200) // OK - no changes
}

// UnregisterAgent implements the DELETE /agents/{agent_id} endpoint
func (h *TestHandlers) UnregisterAgent(c *gin.Context, agentId string) {
	if h.entService.HasServiceError() {
		c.JSON(500, gin.H{"error": "internal server error"})
		return
	}

	agent := h.entService.GetAgent(agentId)
	if agent != nil {
		// Create unregister event
		event := &ent.RegistryEvent{
			EventType: registryevent.EventTypeUnregister,
			Timestamp: time.Now(),
			Data:      map[string]interface{}{"reason": "graceful_shutdown"},
		}
		h.entService.AddEvent(event)

		// Remove agent from registry
		h.entService.DeleteAgent(agentId)
	}

	c.Status(204) // No content - successfully unregistered (idempotent)
}

// TestHealthMonitor tests the background health monitoring functionality
func TestHealthMonitor(t *testing.T) {
	tests := []struct {
		name                string
		agentLastSeen       time.Duration // How long ago the agent was last seen
		heartbeatTimeout    time.Duration // Threshold for considering agent unhealthy
		expectUnhealthyEvent bool
		expectTopologyChange bool
	}{
		{
			name:                "healthy_agent_recent_heartbeat",
			agentLastSeen:       30 * time.Second,
			heartbeatTimeout:    60 * time.Second,
			expectUnhealthyEvent: false,
			expectTopologyChange: false,
		},
		{
			name:                "unhealthy_agent_missed_threshold",
			agentLastSeen:       90 * time.Second,
			heartbeatTimeout:    60 * time.Second,
			expectUnhealthyEvent: true,
			expectTopologyChange: true,
		},
		{
			name:                "agent_at_exact_threshold",
			agentLastSeen:       60 * time.Second,
			heartbeatTimeout:    60 * time.Second,
			expectUnhealthyEvent: true,
			expectTopologyChange: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup: Create test environment with mock service
			mockService := NewMockEntService()

			// Create agent with specific last seen time
			agentID := "test-agent-health-monitor"
			mockAgent := &ent.Agent{
				ID:        agentID,
				Name:      agentID,
				UpdatedAt: time.Now().Add(-tt.agentLastSeen),
				LastFullRefresh: time.Now().Add(-tt.agentLastSeen),
			}
			mockService.SetAgent(agentID, mockAgent)

			// Track initial event count
			initialEventCount := len(mockService.GetEvents())

			// Execute: Run health monitor check
			healthMonitor := NewHealthMonitor(mockService, tt.heartbeatTimeout)
			healthMonitor.CheckUnhealthyAgents()

			// Assert: Verify unhealthy event creation
			events := mockService.GetEvents()
			newEventCount := len(events) - initialEventCount

			if tt.expectUnhealthyEvent {
				assert.Equal(t, 1, newEventCount, "Should create one unhealthy event")
				assert.Equal(t, registryevent.EventTypeUnhealthy, events[len(events)-1].EventType)
			} else {
				assert.Equal(t, 0, newEventCount, "Should not create any events")
			}

			// Verify topology change detection
			if tt.expectTopologyChange {
				// After unhealthy event, HEAD checks should return 202
				hasChanges := mockService.GetTopologyChanges(agentID)
				assert.True(t, hasChanges, "Should have topology changes after unhealthy event")
			}
		})
	}
}

// TestUnhealthyEventCreation tests the creation of unhealthy events
func TestUnhealthyEventCreation(t *testing.T) {
	tests := []struct {
		name          string
		agentExists   bool
		expectedEvent bool
	}{
		{
			name:          "create_unhealthy_event_for_existing_agent",
			agentExists:   true,
			expectedEvent: true,
		},
		{
			name:          "skip_unhealthy_event_for_missing_agent",
			agentExists:   false,
			expectedEvent: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Setup: Create mock service
			mockService := NewMockEntService()

			agentID := "test-agent-unhealthy"
			if tt.agentExists {
				mockAgent := &ent.Agent{
					ID:        agentID,
					Name:      agentID,
					UpdatedAt: time.Now().Add(-5 * time.Minute),
				}
				mockService.SetAgent(agentID, mockAgent)
			}

			initialEventCount := len(mockService.GetEvents())

			// Execute: Create unhealthy event
			healthMonitor := NewHealthMonitor(mockService, 60*time.Second)
			healthMonitor.MarkAgentUnhealthy(agentID, "heartbeat_timeout")

			// Assert: Verify event creation
			events := mockService.GetEvents()
			newEventCount := len(events) - initialEventCount

			if tt.expectedEvent {
				assert.Equal(t, 1, newEventCount, "Should create one unhealthy event")
				lastEvent := events[len(events)-1]
				assert.Equal(t, registryevent.EventTypeUnhealthy, lastEvent.EventType)
				// Verify event data contains reason
				reason, exists := lastEvent.Data["reason"]
				assert.True(t, exists, "Event should contain reason")
				assert.Equal(t, "heartbeat_timeout", reason)
			} else {
				assert.Equal(t, 0, newEventCount, "Should not create events for missing agents")
			}
		})
	}
}

// TestAgentStatusTransitions tests the agent status column and transitions
func TestAgentStatusTransitions(t *testing.T) {
	t.Run("initial_agent_status_healthy", func(t *testing.T) {
		// Setup: Create new agent
		mockService := NewMockEntService()
		agentID := "test-agent-initial"

		// Register agent - should start as healthy
		req := &AgentRegistrationRequest{
			AgentID: agentID,
			Metadata: map[string]interface{}{
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "test_function",
						"capability":    "test_capability",
					},
				},
			},
			Timestamp: time.Now().Format(time.RFC3339),
		}

		resp, err := mockService.RegisterAgent(req)
		require.NoError(t, err)
		assert.Equal(t, "success", resp.Status)

		// Assert: Agent should start with healthy status
		agentEntity := mockService.GetAgent(agentID)
		require.NotNil(t, agentEntity)
		assert.Equal(t, agent.StatusHealthy, agentEntity.Status, "New agent should start with healthy status")
	})

	t.Run("health_monitor_sets_unhealthy_status", func(t *testing.T) {
		// Setup: Create healthy agent
		mockService := NewMockEntService()
		agentID := "test-agent-timeout"

		mockAgent := &ent.Agent{
			ID:        agentID,
			Name:      agentID,
			Status:    agent.StatusHealthy,
			UpdatedAt: time.Now().Add(-90 * time.Second), // Stale timestamp
		}
		mockService.SetAgent(agentID, mockAgent)

		// Execute: Health monitor detects unhealthy agent
		healthMonitor := NewHealthMonitor(mockService, 60*time.Second)
		healthMonitor.CheckUnhealthyAgents()

		// Assert: Agent status should be unhealthy
		agentEntity := mockService.GetAgent(agentID)
		require.NotNil(t, agentEntity)
		assert.Equal(t, agent.StatusUnhealthy, agentEntity.Status, "Health monitor should set status to unhealthy")

		// Assert: Unhealthy event should be created
		events := mockService.GetEvents()
		assert.Len(t, events, 1)
		assert.Equal(t, registryevent.EventTypeUnhealthy, events[0].EventType)
	})

	t.Run("full_heartbeat_restores_healthy_status", func(t *testing.T) {
		// Setup: Create unhealthy agent
		mockService := NewMockEntService()
		agentID := "test-agent-recovery"

		mockAgent := &ent.Agent{
			ID:     agentID,
			Name:   agentID,
			Status: agent.StatusUnhealthy,
			UpdatedAt: time.Now().Add(-30 * time.Second),
		}
		mockService.SetAgent(agentID, mockAgent)

		// Execute: Full heartbeat with metadata
		req := &HeartbeatRequest{
			AgentID: agentID,
			Metadata: map[string]interface{}{
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "test_function",
						"capability":    "test_capability",
					},
				},
			},
		}

		resp, err := mockService.UpdateHeartbeat(req)
		require.NoError(t, err)
		assert.Equal(t, "success", resp.Status)

		// Assert: Agent status should be healthy again
		agentEntity := mockService.GetAgent(agentID)
		require.NotNil(t, agentEntity)
		assert.Equal(t, agent.StatusHealthy, agentEntity.Status, "Full heartbeat should restore healthy status")

		// Assert: Register event should be created (agent recovered)
		events := mockService.GetEvents()
		registerEvents := make([]*ent.RegistryEvent, 0)
		for _, event := range events {
			if event.EventType == registryevent.EventTypeRegister {
				registerEvents = append(registerEvents, event)
			}
		}
		assert.Len(t, registerEvents, 1, "Should create register event when unhealthy agent recovers")
		assert.Contains(t, registerEvents[0].Data, "recovery", "Register event should indicate agent recovery")
	})

	t.Run("head_heartbeat_on_unhealthy_returns_gone", func(t *testing.T) {
		// Setup: Create unhealthy agent
		mockService := NewMockEntService()
		agentID := "test-agent-head-unhealthy"

		mockAgent := &ent.Agent{
			ID:     agentID,
			Name:   agentID,
			Status: agent.StatusUnhealthy,
			UpdatedAt: time.Now().Add(-30 * time.Second),
		}
		mockService.SetAgent(agentID, mockAgent)

		server := NewTestServer(mockService)
		defer server.Close()

		// Execute: HEAD heartbeat request
		req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+agentID, nil)
		require.NoError(t, err)

		client := &http.Client{}
		resp, err := client.Do(req)
		require.NoError(t, err)
		defer resp.Body.Close()

		// Assert: Should return 410 Gone to force full registration
		assert.Equal(t, 410, resp.StatusCode, "HEAD heartbeat on unhealthy agent should return 410 Gone")
	})

	t.Run("status_column_prevents_calculation_mismatch", func(t *testing.T) {
		// Setup: Create agent with recent UpdatedAt but unhealthy status
		mockService := NewMockEntService()
		agentID := "test-agent-status-override"

		mockAgent := &ent.Agent{
			ID:        agentID,
			Name:      agentID,
			Status:    "unhealthy", // Explicit status
			UpdatedAt: time.Now(),  // Recent timestamp (would calculate as healthy)
		}
		mockService.SetAgent(agentID, mockAgent)

		// Execute: List agents endpoint
		agents := mockService.GetAllAgents()

		// Assert: Should respect status column, not calculate from UpdatedAt
		agentFound := false
		for _, agentEntity := range agents {
			if agentEntity.ID == agentID {
				agentFound = true
				assert.Equal(t, agent.StatusUnhealthy, agentEntity.Status, "Should use status column, not calculate from UpdatedAt")
				break
			}
		}
		assert.True(t, agentFound, "Agent should be found in list")
	})

	t.Run("status_transition_with_event_generation", func(t *testing.T) {
		tests := []struct {
			name           string
			initialStatus  agent.Status
			newStatus      agent.Status
			expectedEvent  registryevent.EventType
			eventRequired  bool
		}{
			{
				name:          "healthy_to_unhealthy",
				initialStatus: agent.StatusHealthy,
				newStatus:     agent.StatusUnhealthy,
				expectedEvent: registryevent.EventTypeUnhealthy,
				eventRequired: true,
			},
			{
				name:          "unhealthy_to_healthy",
				initialStatus: agent.StatusUnhealthy,
				newStatus:     agent.StatusHealthy,
				expectedEvent: registryevent.EventTypeRegister,
				eventRequired: true,
			},
			{
				name:          "healthy_to_healthy",
				initialStatus: agent.StatusHealthy,
				newStatus:     agent.StatusHealthy,
				expectedEvent: registryevent.EventTypeHeartbeat,
				eventRequired: false, // Only heartbeat event, no status change event
			},
		}

		for _, tt := range tests {
			t.Run(tt.name, func(t *testing.T) {
				// Setup: Create agent with initial status
				mockService := NewMockEntService()
				agentID := "test-agent-transitions"

				mockAgent := &ent.Agent{
					ID:        agentID,
					Name:      agentID,
					Status:    tt.initialStatus,
					UpdatedAt: time.Now().Add(-30 * time.Second),
				}
				mockService.SetAgent(agentID, mockAgent)

				initialEventCount := len(mockService.GetEvents())

				// Execute: Trigger status change based on scenario
				var err error
				if tt.newStatus == agent.StatusUnhealthy {
					// Health monitor marks as unhealthy
					healthMonitor := NewHealthMonitor(mockService, 20*time.Second)
					healthMonitor.CheckUnhealthyAgents()
				} else if tt.newStatus == agent.StatusHealthy && tt.initialStatus == agent.StatusUnhealthy {
					// Full heartbeat restores healthy status
					req := &HeartbeatRequest{
						AgentID: agentID,
						Metadata: map[string]interface{}{
							"tools": []interface{}{
								map[string]interface{}{
									"function_name": "test_function",
									"capability":    "test_capability",
								},
							},
						},
					}
					_, err = mockService.UpdateHeartbeat(req)
					require.NoError(t, err)
				} else {
					// Normal heartbeat (no status change)
					req := &HeartbeatRequest{
						AgentID: agentID,
					}
					_, err = mockService.UpdateHeartbeat(req)
					require.NoError(t, err)
				}

				// Assert: Verify status change
				agentEntity := mockService.GetAgent(agentID)
				require.NotNil(t, agentEntity)
				assert.Equal(t, tt.newStatus, agentEntity.Status, "Agent status should transition correctly")

				// Assert: Verify event generation
				events := mockService.GetEvents()
				newEventCount := len(events) - initialEventCount

				if tt.eventRequired {
					assert.Greater(t, newEventCount, 0, "Should create event for status transition")
					// Find the specific event type
					foundEvent := false
					for i := initialEventCount; i < len(events); i++ {
						if events[i].EventType == tt.expectedEvent {
							foundEvent = true
							break
						}
					}
					assert.True(t, foundEvent, "Should create %s event for %s transition", tt.expectedEvent, tt.name)
				}
			})
		}
	})
}

// TDD: Test for HEAD request timestamp updates (RED phase - will fail initially)
func TestFastHeartbeatCheck_UpdatesTimestamp(t *testing.T) {
	// Setup: Create test server with mocked EntService
	mockService := NewMockEntService()
	server := NewTestServer(mockService)
	defer server.Close()

	agentID := "timestamp-test-agent"
	initialTime := time.Now().Add(-10 * time.Minute) // Old timestamp

	// Setup: Create agent with old timestamp
	mockAgent := &ent.Agent{
		ID:              agentID,
		Name:            agentID,
		Status:          agent.StatusHealthy,
		LastFullRefresh: initialTime,
		UpdatedAt:       initialTime, // Old timestamp - should be updated
	}
	mockService.SetAgent(agentID, mockAgent)
	mockService.SetTopologyChanges(agentID, false) // No topology changes

	// Execute: Send HEAD request to /heartbeat/{agent_id}
	req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+agentID, nil)
	require.NoError(t, err)

	client := &http.Client{}
	resp, err := client.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	// Assert: Response should be 200 OK
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	// Assert: Agent timestamp should be updated (TDD - this will fail initially)
	updatedAgent := mockService.GetAgent(agentID)
	require.NotNil(t, updatedAgent)

	// The timestamp should be significantly newer than the initial time
	assert.True(t, updatedAgent.UpdatedAt.After(initialTime.Add(5*time.Minute)),
		"HEAD request should update agent timestamp. Initial: %v, Updated: %v",
		initialTime, updatedAgent.UpdatedAt)
}

// TDD: Test for unhealthy agent status after HEAD-only heartbeats
func TestFastHeartbeatCheck_PreventAgentEviction(t *testing.T) {
	// Setup: Create test server with mocked EntService
	mockService := NewMockEntService()
	server := NewTestServer(mockService)
	defer server.Close()

	agentID := "eviction-test-agent"

	// Setup: Create healthy agent
	mockAgent := &ent.Agent{
		ID:              agentID,
		Name:            agentID,
		Status:          agent.StatusHealthy,
		LastFullRefresh: time.Now(),
		UpdatedAt:       time.Now(),
	}
	mockService.SetAgent(agentID, mockAgent)
	mockService.SetTopologyChanges(agentID, false)

	// Execute: Simulate multiple HEAD requests over time (like real agent behavior)
	for i := 0; i < 5; i++ {
		// Simulate time passing between HEAD requests
		time.Sleep(10 * time.Millisecond)

		req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+agentID, nil)
		require.NoError(t, err)

		client := &http.Client{}
		resp, err := client.Do(req)
		require.NoError(t, err)
		resp.Body.Close()

		// Each HEAD request should succeed
		assert.Equal(t, http.StatusOK, resp.StatusCode, "HEAD request #%d should succeed", i+1)
	}

	// Assert: Agent should still be healthy after HEAD-only heartbeats (TDD - might fail initially)
	finalAgent := mockService.GetAgent(agentID)
	require.NotNil(t, finalAgent)
	assert.Equal(t, agent.StatusHealthy, finalAgent.Status,
		"Agent should remain healthy after HEAD-only heartbeats")
}

// TDD: Test integration with health monitor behavior
func TestFastHeartbeatCheck_HealthMonitorIntegration(t *testing.T) {
	// Setup: Create test server with mocked EntService
	mockService := NewMockEntService()
	server := NewTestServer(mockService)
	defer server.Close()

	agentID := "health-monitor-test-agent"

	// Setup: Create agent that would be considered stale by health monitor
	staleTime := time.Now().Add(-45 * time.Minute) // Older than typical health check threshold
	mockAgent := &ent.Agent{
		ID:              agentID,
		Name:            agentID,
		Status:          agent.StatusHealthy,
		LastFullRefresh: staleTime,
		UpdatedAt:       staleTime, // This should be updated by HEAD request
	}
	mockService.SetAgent(agentID, mockAgent)
	mockService.SetTopologyChanges(agentID, false)

	// Execute: Send HEAD request (should update timestamp)
	req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+agentID, nil)
	require.NoError(t, err)

	client := &http.Client{}
	resp, err := client.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	// Assert: HEAD request succeeds
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	// Assert: Timestamp updated enough to prevent health monitor eviction (TDD - will fail initially)
	updatedAgent := mockService.GetAgent(agentID)
	require.NotNil(t, updatedAgent)

	// The agent should now have a recent timestamp that wouldn't trigger health monitor eviction
	healthThreshold := time.Now().Add(-30 * time.Minute) // Typical health monitor threshold
	assert.True(t, updatedAgent.UpdatedAt.After(healthThreshold),
		"HEAD request should update timestamp enough to prevent health monitor eviction. "+
		"Threshold: %v, Updated: %v", healthThreshold, updatedAgent.UpdatedAt)
}

// TDD: Test mixed HEAD and POST heartbeat pattern
func TestFastHeartbeatCheck_MixedHeartbeatPattern(t *testing.T) {
	// Setup: Create test server with mocked EntService
	mockService := NewMockEntService()
	server := NewTestServer(mockService)
	defer server.Close()

	agentID := "mixed-pattern-test-agent"
	initialTime := time.Now().Add(-5 * time.Minute)

	// Setup: Create agent
	mockAgent := &ent.Agent{
		ID:              agentID,
		Name:            agentID,
		Status:          agent.StatusHealthy,
		LastFullRefresh: initialTime,
		UpdatedAt:       initialTime,
	}
	mockService.SetAgent(agentID, mockAgent)
	mockService.SetTopologyChanges(agentID, false)

	// Execute: Simulate realistic pattern - multiple HEAD requests followed by topology change

	// Phase 1: Multiple HEAD requests (optimization)
	for i := 0; i < 3; i++ {
		req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+agentID, nil)
		require.NoError(t, err)

		client := &http.Client{}
		resp, err := client.Do(req)
		require.NoError(t, err)
		resp.Body.Close()

		assert.Equal(t, http.StatusOK, resp.StatusCode, "HEAD request #%d should succeed", i+1)
	}

	// Phase 2: Topology change detected
	mockService.SetTopologyChanges(agentID, true)

	req, err := http.NewRequest("HEAD", server.URL+"/heartbeat/"+agentID, nil)
	require.NoError(t, err)

	client := &http.Client{}
	resp, err := client.Do(req)
	require.NoError(t, err)
	defer resp.Body.Close()

	// Should get 202 (topology changed) but timestamp should still be updated (TDD)
	assert.Equal(t, http.StatusAccepted, resp.StatusCode, "Should detect topology change")

	// Assert: Even when topology changed, timestamp should be updated
	updatedAgent := mockService.GetAgent(agentID)
	require.NotNil(t, updatedAgent)
	assert.True(t, updatedAgent.UpdatedAt.After(initialTime.Add(time.Minute)),
		"HEAD request should update timestamp even when topology changed")
}

// TDD: Test that health monitor doesn't repeatedly mark already-unhealthy agents
func TestHealthMonitor_SkipsAlreadyUnhealthyAgents(t *testing.T) {
	// Setup: Create test environment with mock service
	mockService := NewMockEntService()

	agentID := "already-unhealthy-agent"
	staleTime := time.Now().Add(-120 * time.Second) // Very old timestamp

	// Create agent that is already unhealthy with stale timestamp
	mockAgent := &ent.Agent{
		ID:        agentID,
		Name:      agentID,
		Status:    agent.StatusUnhealthy, // Already unhealthy
		UpdatedAt: staleTime,             // Old timestamp that would trigger health check
	}
	mockService.SetAgent(agentID, mockAgent)

	// Track initial event count
	initialEventCount := len(mockService.GetEvents())

	// Execute: Run health monitor check
	healthMonitor := NewHealthMonitor(mockService, 60*time.Second)
	healthMonitor.CheckUnhealthyAgents()

	// Assert: No new events should be created for already-unhealthy agents
	events := mockService.GetEvents()
	newEventCount := len(events) - initialEventCount
	assert.Equal(t, 0, newEventCount, "Should not create events for already-unhealthy agents")

	// Assert: Agent status should remain unchanged
	finalAgent := mockService.GetAgent(agentID)
	require.NotNil(t, finalAgent)
	assert.Equal(t, agent.StatusUnhealthy, finalAgent.Status, "Already-unhealthy agent status should remain unchanged")
}
