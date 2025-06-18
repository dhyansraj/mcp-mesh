package registry

import (
	"testing"

	"mcp-mesh/src/core/registry/generated"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestAgentsEndpoint tests the /agents endpoint service layer with new schema
func TestAgentsEndpoint(t *testing.T) {
	t.Run("ListAgentsBasic", func(t *testing.T) {
		service := setupTestService(t)

		// Register a test agent with multiple capabilities
		req := &AgentRegistrationRequest{
			AgentID: "test-agent-1",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Test Agent One",
				"version":    "2.1.0",
				"http_host":  "localhost",
				"http_port":  float64(8080),
				"namespace":  "production",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "greet_user",
						"capability":    "greeting_service",
						"version":       "2.1.0",
						"tags":          []string{"social", "interaction"},
					},
					map[string]interface{}{
						"function_name": "send_notification",
						"capability":    "notification_service",
						"version":       "2.1.0",
						"tags":          []string{"alerts", "messaging"},
					},
				},
			},
		}

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// List agents
		params := &AgentQueryParams{}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		// Verify response structure
		assert.Equal(t, 1, response.Count)
		assert.Len(t, response.Agents, 1)

		agent := response.Agents[0]
		assert.Equal(t, "test-agent-1", agent.Id)
		assert.Equal(t, "Test Agent One", agent.Name)
		assert.Equal(t, "healthy", string(agent.Status)) // Should be healthy since just registered
		assert.Equal(t, "2.1.0", *agent.Version)
		// Note: namespace is not part of AgentInfo response per OpenAPI spec
		assert.Equal(t, "http://localhost:8080", agent.Endpoint)

		// Check capabilities - now []CapabilityInfo, not []string
		assert.Len(t, agent.Capabilities, 2)
		capabilityNames := make([]string, len(agent.Capabilities))
		for i, cap := range agent.Capabilities {
			capabilityNames[i] = cap.Name
		}
		assert.ElementsMatch(t, []string{"greeting_service", "notification_service"}, capabilityNames)

		// Note: Dependencies field removed from API - we use real-time resolution instead

		t.Logf("✅ Agent listed successfully:")
		t.Logf("   ID: %s", agent.Id)
		t.Logf("   Name: %s", agent.Name)
		t.Logf("   Status: %s", string(agent.Status))
		t.Logf("   Capabilities: %v", capabilityNames)
		t.Logf("   Endpoint: %s", agent.Endpoint)
	})

	t.Run("ListAgentsWithFiltering", func(t *testing.T) {
		service := setupTestService(t)

		// Register multiple agents with different capabilities
		req1 := &AgentRegistrationRequest{
			AgentID: "weather-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Weather Service",
				"version":    "1.0.0",
				"namespace":  "external",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_weather",
						"capability":    "weather_service",
						"version":       "1.0.0",
					},
				},
			},
		}

		req2 := &AgentRegistrationRequest{
			AgentID: "database-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Database Service",
				"version":    "2.0.0",
				"namespace":  "internal",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "query_db",
						"capability":    "database_service",
						"version":       "2.0.0",
					},
					map[string]interface{}{
						"function_name": "backup_db",
						"capability":    "backup_service",
						"version":       "2.0.0",
					},
				},
			},
		}

		_, err := service.RegisterAgent(req1)
		require.NoError(t, err)
		_, err = service.RegisterAgent(req2)
		require.NoError(t, err)

		// Test capability filtering
		params := &AgentQueryParams{
			Capabilities: []string{"weather_service"},
		}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		assert.Equal(t, "weather-agent", response.Agents[0].Id)

		// Test namespace filtering
		params = &AgentQueryParams{
			Namespace: "internal",
		}
		response, err = service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		assert.Equal(t, "database-agent", response.Agents[0].Id)

		// Test fuzzy capability matching
		params = &AgentQueryParams{
			Capabilities: []string{"weather"},
			FuzzyMatch:   true,
		}
		response, err = service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		assert.Equal(t, "weather-agent", response.Agents[0].Id)

		t.Logf("✅ Filtering tests passed")
	})

	t.Run("ListAgentsHealthStatus", func(t *testing.T) {
		service := setupTestService(t)

		// Register an agent
		req := &AgentRegistrationRequest{
			AgentID: "health-test-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Health Test Agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "test_function",
						"capability":    "test_capability",
					},
				},
			},
		}

		_, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// List agents immediately - should be healthy
		params := &AgentQueryParams{}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 1, response.Count)
		agent := response.Agents[0]
		assert.Equal(t, "healthy", string(agent.Status))

		t.Logf("✅ Health status correctly shows: %s", string(agent.Status))
	})

	t.Run("ListAgentsWithDependencies", func(t *testing.T) {
		service := setupTestService(t)

		// Register provider
		providerReq := &AgentRegistrationRequest{
			AgentID: "provider-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Provider Agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "provide_service",
						"capability":    "provider_capability",
					},
				},
			},
		}

		// Register consumer with dependencies
		consumerReq := &AgentRegistrationRequest{
			AgentID: "consumer-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Consumer Agent",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "consume_service",
						"capability":    "consumer_capability",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "provider_capability",
								"version":    ">=1.0.0",
							},
						},
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// List agents and verify dependency counts are included
		params := &AgentQueryParams{}
		response, err := service.ListAgents(params)
		require.NoError(t, err)

		assert.Equal(t, 2, response.Count)

		// Find consumer agent and check dependency tracking
		var consumerAgent *generated.AgentInfo
		for _, agent := range response.Agents {
			if agent.Id == "consumer-agent" {
				consumerAgent = &agent
				break
			}
		}
		require.NotNil(t, consumerAgent)

		// Check that dependency counts are included (for CLI display)
		assert.Equal(t, 1, consumerAgent.TotalDependencies)

		t.Logf("✅ Dependency tracking in agents list verified")
	})
}
