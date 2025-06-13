package registry

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"mcp-mesh/src/core/database"
)

// TestMultiToolRegistration tests the new multi-tool registration format
func TestMultiToolRegistration(t *testing.T) {
	t.Run("SingleAgentMultipleTools", func(t *testing.T) {
		service, cleanup := setupTestService(t)
		defer cleanup()

		// Create registration with multiple tools
		req := &AgentRegistrationRequest{
			AgentID:   "myservice-abc12345",
			Timestamp: time.Now().Format(time.RFC3339),
			Metadata: map[string]interface{}{
				"name":     "myservice-abc12345",
				"endpoint": "http://localhost:8889",
				"tools": []map[string]interface{}{
					{
						"function_name": "greet",
						"capability":    "greeting",
						"version":       "1.0.0",
						"tags":          []string{"demo", "v1"},
						"dependencies": []map[string]interface{}{
							{
								"capability": "date_service",
								"version":    ">=1.0.0",
								"tags":       []string{"production"},
							},
						},
					},
					{
						"function_name": "farewell",
						"capability":    "goodbye",
						"version":       "1.0.0",
						"tags":          []string{"demo"},
						"dependencies":  []map[string]interface{}{},
					},
				},
			},
		}

		resp, err := service.RegisterAgent(req)
		require.NoError(t, err)
		assert.Equal(t, "success", resp.Status)

		// Verify both tools are registered
		var count int
		err = service.db.Raw("SELECT COUNT(*) FROM capabilities WHERE agent_id = ?", req.AgentID).Scan(&count).Error
		require.NoError(t, err)
		assert.Equal(t, 2, count)

		// Verify dependencies are resolved per tool
		assert.Contains(t, resp.Metadata, "dependencies_resolved")
		depsResolved := resp.Metadata["dependencies_resolved"].(map[string]interface{})
		assert.Contains(t, depsResolved, "greet")
		assert.Contains(t, depsResolved, "farewell")
	})

	t.Run("UpdateExistingAgentTools", func(t *testing.T) {
		service, cleanup := setupTestService(t)
		defer cleanup()

		agentID := "myservice-def456"

		// First registration with 2 tools
		req1 := &AgentRegistrationRequest{
			AgentID:   agentID,
			Timestamp: time.Now().Format(time.RFC3339),
			Metadata: map[string]interface{}{
				"name":     agentID,
				"endpoint": "http://localhost:9000",
				"tools": []map[string]interface{}{
					{
						"function_name": "func1",
						"capability":    "cap1",
						"version":       "1.0.0",
					},
					{
						"function_name": "func2",
						"capability":    "cap2",
						"version":       "1.0.0",
					},
				},
			},
		}

		_, err := service.RegisterAgent(req1)
		require.NoError(t, err)

		// Second registration with 3 tools (added func3, kept func1, removed func2)
		req2 := &AgentRegistrationRequest{
			AgentID:   agentID,
			Timestamp: time.Now().Format(time.RFC3339),
			Metadata: map[string]interface{}{
				"name":     agentID,
				"endpoint": "http://localhost:9000",
				"tools": []map[string]interface{}{
					{
						"function_name": "func1",
						"capability":    "cap1",
						"version":       "1.1.0", // Updated version
					},
					{
						"function_name": "func3",
						"capability":    "cap3",
						"version":       "1.0.0",
					},
				},
			},
		}

		_, err = service.RegisterAgent(req2)
		require.NoError(t, err)

		// Verify tools are updated correctly
		var capabilities []database.Capability
		err = service.db.Where("agent_id = ?", agentID).Find(&capabilities).Error
		require.NoError(t, err)

		assert.Len(t, capabilities, 2)

		// Check that func2 was removed and func3 was added
		capNames := make(map[string]string)
		for _, cap := range capabilities {
			capNames[cap.Name] = cap.Version
		}

		assert.Equal(t, "1.1.0", capNames["cap1"]) // Updated version
		assert.Contains(t, capNames, "cap3")       // New tool
		assert.NotContains(t, capNames, "cap2")    // Removed tool
	})
}

// TestDependencyResolutionPerTool tests dependency resolution for each tool
func TestDependencyResolutionPerTool(t *testing.T) {
	t.Run("DifferentVersionConstraints", func(t *testing.T) {
		service, cleanup := setupTestService(t)
		defer cleanup()

		// Register date service providers with different versions
		providers := []struct {
			agentID string
			version string
		}{
			{"dateservice-v1", "1.0.0"},
			{"dateservice-v2", "2.0.0"},
			{"dateservice-v3", "3.0.0"},
		}

		for _, p := range providers {
			req := &AgentRegistrationRequest{
				AgentID:   p.agentID,
				Timestamp: time.Now().Format(time.RFC3339),
				Metadata: map[string]interface{}{
					"name":     p.agentID,
					"endpoint": "http://" + p.agentID + ":8080",
					"tools": []map[string]interface{}{
						{
							"function_name": "get_date",
							"capability":    "date_service",
							"version":       p.version,
						},
					},
				},
			}
			_, err := service.RegisterAgent(req)
			require.NoError(t, err)
		}

		// Register agent with tools having different version constraints
		req := &AgentRegistrationRequest{
			AgentID:   "myapp-123",
			Timestamp: time.Now().Format(time.RFC3339),
			Metadata: map[string]interface{}{
				"name":     "myapp-123",
				"endpoint": "http://localhost:8889",
				"tools": []map[string]interface{}{
					{
						"function_name": "old_function",
						"capability":    "old_feature",
						"dependencies": []map[string]interface{}{
							{
								"capability": "date_service",
								"version":    ">=1.0.0,<2.0.0", // Should get v1
							},
						},
					},
					{
						"function_name": "new_function",
						"capability":    "new_feature",
						"dependencies": []map[string]interface{}{
							{
								"capability": "date_service",
								"version":    ">=2.0.0", // Should get v2 or v3
							},
						},
					},
				},
			},
		}

		resp, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// Check dependency resolution
		depsResolved := resp.Metadata["dependencies_resolved"].(map[string]interface{})

		// old_function should get v1
		oldDeps := depsResolved["old_function"].(map[string]interface{})
		dateSvc := oldDeps["date_service"].(map[string]interface{})
		assert.Equal(t, "dateservice-v1", dateSvc["agent_id"])

		// new_function should get v2 or v3
		newDeps := depsResolved["new_function"].(map[string]interface{})
		dateSvc2 := newDeps["date_service"].(map[string]interface{})
		assert.Contains(t, []string{"dateservice-v2", "dateservice-v3"}, dateSvc2["agent_id"])
	})

	t.Run("TagBasedFiltering", func(t *testing.T) {
		service, cleanup := setupTestService(t)
		defer cleanup()

		// Register services with different tags
		services := []struct {
			agentID string
			tags    []string
		}{
			{"auth-prod-east", []string{"production", "US_EAST", "oauth2"}},
			{"auth-prod-west", []string{"production", "US_WEST", "oauth2"}},
			{"auth-dev", []string{"development", "US_EAST", "oauth2"}},
		}

		for _, s := range services {
			req := &AgentRegistrationRequest{
				AgentID:   s.agentID,
				Timestamp: time.Now().Format(time.RFC3339),
				Metadata: map[string]interface{}{
					"name":     s.agentID,
					"endpoint": "http://" + s.agentID + ":8080",
					"tools": []map[string]interface{}{
						{
							"function_name": "authenticate",
							"capability":    "auth_service",
							"version":       "1.0.0",
							"tags":          s.tags,
						},
					},
				},
			}
			_, err := service.RegisterAgent(req)
			require.NoError(t, err)
		}

		// Request with specific tag requirements
		req := &AgentRegistrationRequest{
			AgentID:   "myapp-456",
			Timestamp: time.Now().Format(time.RFC3339),
			Metadata: map[string]interface{}{
				"name":     "myapp-456",
				"endpoint": "http://localhost:8890",
				"tools": []map[string]interface{}{
					{
						"function_name": "secure_function",
						"capability":    "secure_feature",
						"dependencies": []map[string]interface{}{
							{
								"capability": "auth_service",
								"tags":       []string{"production", "US_EAST"}, // Should match only auth-prod-east
							},
						},
					},
				},
			},
		}

		resp, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// Verify correct service is selected based on tags
		depsResolved := resp.Metadata["dependencies_resolved"].(map[string]interface{})
		secureDeps := depsResolved["secure_function"].(map[string]interface{})
		authSvc := secureDeps["auth_service"].(map[string]interface{})
		assert.Equal(t, "auth-prod-east", authSvc["agent_id"])
	})
}

// TestHeartbeatDeducesHealth tests that health is deduced from heartbeat receipt
func TestHeartbeatDeducesHealth(t *testing.T) {
	service, cleanup := setupTestService(t)
	defer cleanup()

	// Register an agent
	agentID := "test-health-123"
	req := &AgentRegistrationRequest{
		AgentID:   agentID,
		Timestamp: time.Now().Format(time.RFC3339),
		Metadata: map[string]interface{}{
			"name":               agentID,
			"endpoint":           "http://localhost:9999",
			"health_interval":    1, // 1 second for testing
			"timeout_threshold":  2,
			"eviction_threshold": 4,
		},
	}

	_, err := service.RegisterAgent(req)
	require.NoError(t, err)

	// Send heartbeat - no status in payload
	heartbeatReq := map[string]interface{}{
		"agent_id": agentID,
		"metadata": map[string]interface{}{
			// No status field - registry should deduce healthy
		},
	}

	err = service.UpdateHeartbeat(heartbeatReq)
	require.NoError(t, err)

	// Check agent is healthy
	var agent database.Agent
	err = service.db.First(&agent, "id = ?", agentID).Error
	require.NoError(t, err)
	assert.Equal(t, "healthy", agent.Status)

	// Wait beyond timeout threshold
	time.Sleep(3 * time.Second)

	// Run health monitor check
	service.healthMonitor.checkAgentHealth(&agent)

	// Status should be degraded (no heartbeat within timeout)
	err = service.db.First(&agent, "id = ?", agentID).Error
	require.NoError(t, err)
	assert.Equal(t, "degraded", agent.Status)

	// Send another heartbeat
	err = service.UpdateHeartbeat(heartbeatReq)
	require.NoError(t, err)

	// Should be healthy again
	err = service.db.First(&agent, "id = ?", agentID).Error
	require.NoError(t, err)
	assert.Equal(t, "healthy", agent.Status)
}

// TestBackwardCompatibility tests that old single-capability format still works
func TestBackwardCompatibility(t *testing.T) {
	service, cleanup := setupTestService(t)
	defer cleanup()

	// Old format: capabilities array at top level
	req := &AgentRegistrationRequest{
		AgentID:   "old-agent-789",
		Timestamp: time.Now().Format(time.RFC3339),
		Metadata: map[string]interface{}{
			"name":     "old-agent-789",
			"endpoint": "http://localhost:7777",
			"capabilities": []map[string]interface{}{
				{
					"name":        "greeting",
					"version":     "1.0.0",
					"description": "Old style capability",
				},
			},
		},
	}

	resp, err := service.RegisterAgent(req)
	require.NoError(t, err)
	assert.Equal(t, "success", resp.Status)

	// Verify capability is registered
	var count int
	err = service.db.Raw("SELECT COUNT(*) FROM capabilities WHERE agent_id = ?", req.AgentID).Scan(&count).Error
	require.NoError(t, err)
	assert.Equal(t, 1, count)
}

// TestCapabilityEndpointWithTools tests the /capabilities endpoint with new format
func TestCapabilityEndpointWithTools(t *testing.T) {
	service, cleanup := setupTestService(t)
	defer cleanup()

	// Register multiple agents with same capability
	agents := []struct {
		agentID  string
		toolName string
		version  string
	}{
		{"service1-abc", "greet_v1", "1.0.0"},
		{"service2-def", "greet_v2", "2.0.0"},
		{"service3-ghi", "say_hello", "1.5.0"},
	}

	for _, a := range agents {
		req := &AgentRegistrationRequest{
			AgentID:   a.agentID,
			Timestamp: time.Now().Format(time.RFC3339),
			Metadata: map[string]interface{}{
				"name":     a.agentID,
				"endpoint": "http://" + a.agentID + ":8080",
				"tools": []map[string]interface{}{
					{
						"function_name": a.toolName,
						"capability":    "greeting",
						"version":       a.version,
					},
				},
			},
		}
		_, err := service.RegisterAgent(req)
		require.NoError(t, err)
	}

	// Search for greeting capability
	params := &CapabilityQueryParams{
		Name:        "greeting",
		AgentStatus: "healthy",
	}

	resp, err := service.SearchCapabilities(params)
	require.NoError(t, err)
	assert.Equal(t, 3, resp.Count)

	// Verify all tools are returned
	toolNames := make(map[string]bool)
	for _, cap := range resp.Capabilities {
		capMap := cap.(map[string]interface{})
		// New format should include tool_name
		if toolName, ok := capMap["tool_name"]; ok {
			toolNames[toolName.(string)] = true
		}
	}

	assert.True(t, toolNames["greet_v1"])
	assert.True(t, toolNames["greet_v2"])
	assert.True(t, toolNames["say_hello"])
}

// Helper function to setup test service
func setupTestService(t *testing.T) (*Service, func()) {
	// Create in-memory database
	db, err := database.NewDatabase(&database.Config{
		DatabaseURL: ":memory:",
	})
	require.NoError(t, err)

	// Create service
	service := &Service{
		db:     db,
		config: DefaultConfig(),
		cache:  newCache(30 * time.Second),
	}

	// Initialize health monitor
	service.healthMonitor = &HealthMonitor{
		service:  service,
		interval: 1 * time.Second,
	}

	cleanup := func() {
		// Clean up database
		sqlDB, _ := db.DB.DB()
		sqlDB.Close()
	}

	return service, cleanup
}
