package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"mcp-mesh/src/core/registry/generated"
)

// TestTagResolutionConsistency verifies that database counts match response resolution
// This test specifically addresses the bug where tags weren't handled consistently
func TestTagResolutionConsistency(t *testing.T) {
	service := setupTestService(t)

	// Register provider with specific tags
	providerReq := &AgentRegistrationRequest{
		AgentID: "time-provider",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "time-provider",
			"version":    "1.0.0",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "get_time",
					"capability":    "time_service",
					"version":       "1.0.0",
					"tags":          []string{"system"}, // Only has "system" tag
				},
			},
		},
	}

	_, err := service.RegisterAgent(providerReq)
	require.NoError(t, err)

	// Register consumer with dependencies requiring different tags
	consumerReq := &AgentRegistrationRequest{
		AgentID: "consumer-with-tags",
		Metadata: map[string]interface{}{
			"agent_type": "mcp_agent",
			"name":       "consumer-with-tags",
			"version":    "1.0.0",
			"tools": []interface{}{
				map[string]interface{}{
					"function_name": "function_matching_tags",
					"capability":    "app_service",
					"version":       "1.0.0",
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability": "time_service",
							"tags":       []string{"system"}, // Will match
						},
					},
				},
				map[string]interface{}{
					"function_name": "function_mismatched_tags",
					"capability":    "other_service",
					"version":       "1.0.0",
					"dependencies": []interface{}{
						map[string]interface{}{
							"capability": "time_service",
							"tags":       []string{"system", "general"}, // Won't match (needs both)
						},
					},
				},
			},
		},
	}

	response, err := service.RegisterAgent(consumerReq)
	require.NoError(t, err)

	// Verify response shows only 1 dependency resolved (matching tags)
	assert.Contains(t, response.DependenciesResolved, "function_matching_tags")
	assert.Len(t, response.DependenciesResolved["function_matching_tags"], 1, "Function with matching tags should resolve")

	assert.Contains(t, response.DependenciesResolved, "function_mismatched_tags")
	assert.Len(t, response.DependenciesResolved["function_mismatched_tags"], 0, "Function with mismatched tags should not resolve")

	// Now check that database shows the SAME counts as response
	params := &AgentQueryParams{}
	listResponse, err := service.ListAgents(params)
	require.NoError(t, err)

	// Find the consumer agent
	var consumerAgent *generated.AgentInfo
	for _, agent := range listResponse.Agents {
		if agent.Id == "consumer-with-tags" {
			consumerAgent = &agent
			break
		}
	}
	require.NotNil(t, consumerAgent)

	// Database should show 2 total dependencies, 1 resolved (matching the response)
	assert.Equal(t, 2, consumerAgent.TotalDependencies, "Should have 2 total dependencies")
	assert.Equal(t, 1, consumerAgent.DependenciesResolved, "Should have 1 resolved dependency (matching response)")

	t.Logf("✅ Tag resolution consistency verified:")
	t.Logf("   Response: function_matching_tags=%d resolved, function_mismatched_tags=%d resolved",
		len(response.DependenciesResolved["function_matching_tags"]),
		len(response.DependenciesResolved["function_mismatched_tags"]))
	t.Logf("   Database: %d/%d dependencies resolved", consumerAgent.DependenciesResolved, consumerAgent.TotalDependencies)
}
