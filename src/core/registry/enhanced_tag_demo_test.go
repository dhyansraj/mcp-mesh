package registry

import (
	"testing"
	"github.com/stretchr/testify/require"
)

// TestEnhancedTagMatchingDemo demonstrates the new +/- tag matching capabilities
func TestEnhancedTagMatchingDemo(t *testing.T) {
	t.Run("SmartLLMSelection_PreferredTags", func(t *testing.T) {
		service := setupTestService(t)

		// Register three LLM providers with different capabilities
		providers := []struct {
			agentID     string
			tags        []string
			description string
		}{
			{
				agentID:     "claude-haiku-provider",
				tags:        []string{"claude", "haiku", "fast"},
				description: "Fast Claude Haiku - good for simple tasks",
			},
			{
				agentID:     "claude-sonnet-provider",
				tags:        []string{"claude", "sonnet", "balanced"},
				description: "Balanced Claude Sonnet - good performance/cost ratio",
			},
			{
				agentID:     "claude-opus-provider",
				tags:        []string{"claude", "opus", "premium"},
				description: "Premium Claude Opus - best quality",
			},
		}

		// Register all providers
		for _, p := range providers {
			req := &AgentRegistrationRequest{
				AgentID: p.agentID,
				Metadata: map[string]interface{}{
					"agent_type": "mcp_agent",
					"name":       p.agentID,
					"version":    "1.0.0",
					"http_host":  p.agentID,
					"http_port":  float64(8080),
					"tools": []interface{}{
						map[string]interface{}{
							"function_name": "generate_text",
							"capability":    "llm_service",
							"version":       "1.0.0",
							"tags":          p.tags,
							"description":   p.description,
						},
					},
				},
			}
			_, err := service.RegisterAgent(req)
			require.NoError(t, err)
		}

		// Test Case 1: Consumer prefers premium (opus)
		consumerReq1 := &AgentRegistrationRequest{
			AgentID: "premium-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "premium-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "premium_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "+opus"}, // Required: claude, Preferred: opus
							},
						},
						"description": "Premium chat preferring best quality",
					},
				},
			},
		}

		response1, err := service.RegisterAgent(consumerReq1)
		require.NoError(t, err)

		// Should select opus provider (highest score due to +opus preference)
		deps1 := response1.DependenciesResolved["premium_chat"]
		require.Len(t, deps1, 1)
		require.Equal(t, "claude-opus-provider", deps1[0].AgentID)

		t.Logf("✅ Premium consumer got preferred provider: %s", deps1[0].AgentID)

		// Test Case 2: Consumer wants balanced performance
		consumerReq2 := &AgentRegistrationRequest{
			AgentID: "balanced-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "balanced-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "balanced_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "+balanced", "-premium"}, // Required: claude, Preferred: balanced, Excluded: premium
							},
						},
						"description": "Balanced chat avoiding premium costs",
					},
				},
			},
		}

		response2, err := service.RegisterAgent(consumerReq2)
		require.NoError(t, err)

		// Should select sonnet provider (has +balanced, opus is excluded by -premium)
		deps2 := response2.DependenciesResolved["balanced_chat"]
		require.Len(t, deps2, 1)
		require.Equal(t, "claude-sonnet-provider", deps2[0].AgentID)

		t.Logf("✅ Balanced consumer got correct provider: %s", deps2[0].AgentID)

		// Test Case 3: Consumer wants fast responses
		consumerReq3 := &AgentRegistrationRequest{
			AgentID: "speed-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "speed-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "fast_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "+fast", "+haiku"}, // Required: claude, Preferred: fast+haiku
							},
						},
						"description": "Fast chat prioritizing speed",
					},
				},
			},
		}

		response3, err := service.RegisterAgent(consumerReq3)
		require.NoError(t, err)

		// Should select haiku provider (has both +fast and +haiku preferences)
		deps3 := response3.DependenciesResolved["fast_chat"]
		require.Len(t, deps3, 1)
		require.Equal(t, "claude-haiku-provider", deps3[0].AgentID)

		t.Logf("✅ Speed consumer got optimal provider: %s", deps3[0].AgentID)

		t.Logf("\n🎉 Enhanced Tag Matching Demo Complete!")
		t.Logf("   Premium consumer → %s (preferred opus)", deps1[0].AgentID)
		t.Logf("   Balanced consumer → %s (preferred balanced, excluded premium)", deps2[0].AgentID)
		t.Logf("   Speed consumer → %s (preferred fast+haiku)", deps3[0].AgentID)
	})
}
