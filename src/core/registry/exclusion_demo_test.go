package registry

import (
	"testing"
	"github.com/stretchr/testify/require"
	"github.com/stretchr/testify/assert"
)

// TestExclusionHardBlock demonstrates that exclusion tags (-) are absolute
// Even if it's the only available provider, exclusion prevents matching
func TestExclusionHardBlock(t *testing.T) {
	t.Run("ExclusionBlocks_EvenWhenOnlyProvider", func(t *testing.T) {
		service := setupTestService(t)

		// Register ONLY an opus provider (no alternatives)
		opusOnlyReq := &AgentRegistrationRequest{
			AgentID: "claude-opus-only",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-opus-only",
				"version":    "1.0.0",
				"http_host":  "claude-opus",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "generate_text",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "opus"},
						"description":   "Only available LLM provider",
					},
				},
			},
		}

		_, err := service.RegisterAgent(opusOnlyReq)
		require.NoError(t, err)

		// Consumer explicitly excludes opus (even though it's the only option)
		consumerReq := &AgentRegistrationRequest{
			AgentID: "opus-hater-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "opus-hater-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "anti_opus_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "-opus"}, // Required: claude, EXCLUDED: opus
							},
						},
						"description": "Chat that refuses to use opus",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// Verify dependency is unresolved placeholder (exclusion blocked the only provider)
		deps := response.DependenciesResolved["anti_opus_chat"]
		assert.Len(t, deps, 1, "Should have unresolved placeholder to preserve positional index")
		assert.Equal(t, "unresolved", deps[0].Status, "Placeholder should have unresolved status - exclusion blocked the only provider")

		t.Logf("✅ Exclusion working correctly:")
		t.Logf("   Available providers: claude-opus-only (claude, opus)")
		t.Logf("   Consumer requirement: claude, -opus")
		t.Logf("   Result: %d dependencies resolved (exclusion blocked it)", len(deps))
		t.Logf("   🚫 Even though opus was the ONLY available provider, exclusion prevented matching!")
	})

	t.Run("ExclusionWithMultipleProviders_SelectsNonExcluded", func(t *testing.T) {
		service := setupTestService(t)

		// Register two providers: one with opus (excluded), one without
		opusReq := &AgentRegistrationRequest{
			AgentID: "claude-opus-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-opus-provider",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "generate_opus",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "opus", "premium"},
						"description":   "Premium opus provider",
					},
				},
			},
		}

		sonnetReq := &AgentRegistrationRequest{
			AgentID: "claude-sonnet-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-sonnet-provider",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "generate_sonnet",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "sonnet", "balanced"},
						"description":   "Balanced sonnet provider",
					},
				},
			},
		}

		_, err := service.RegisterAgent(opusReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(sonnetReq)
		require.NoError(t, err)

		// Consumer excludes opus
		consumerReq := &AgentRegistrationRequest{
			AgentID: "cost-conscious-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "cost-conscious-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "budget_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "-opus"}, // Required: claude, EXCLUDED: opus
							},
						},
						"description": "Budget-conscious chat avoiding opus",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// Should select sonnet (opus excluded)
		deps := response.DependenciesResolved["budget_chat"]
		require.Len(t, deps, 1, "Should resolve to one provider (sonnet, not opus)")
		assert.Equal(t, "claude-sonnet-provider", deps[0].AgentID, "Should select sonnet provider (opus excluded)")

		t.Logf("✅ Exclusion filtering working correctly:")
		t.Logf("   Available providers: opus, sonnet")
		t.Logf("   Consumer requirement: claude, -opus")
		t.Logf("   Selected: %s (opus was filtered out)", deps[0].AgentID)
	})
}
