package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestEnhancedTagMatching tests the new +/- tag matching logic
func TestEnhancedTagMatching(t *testing.T) {
	t.Run("RequiredTags_ExactMatch_ShouldPass", func(t *testing.T) {
		// Provider has: ["claude", "sonnet"]
		// Consumer needs: ["claude"] (required)
		// Expected: MATCH (all required tags present)

		providerTags := []string{"claude", "sonnet"}
		requiredTags := []string{"claude"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match when all required tags are present")
		assert.Greater(t, score, 0, "Should have positive score for matches")
	})

	t.Run("RequiredTags_Missing_ShouldFail", func(t *testing.T) {
		// Provider has: ["claude", "sonnet"]
		// Consumer needs: ["gpt"] (required)
		// Expected: NO MATCH (required tag missing)

		providerTags := []string{"claude", "sonnet"}
		requiredTags := []string{"gpt"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.False(t, matches, "Should not match when required tag is missing")
		assert.Equal(t, 0, score, "Should have zero score for non-matches")
	})

	t.Run("PreferredTags_Present_ShouldGetBonus", func(t *testing.T) {
		// Provider has: ["claude", "opus"]
		// Consumer needs: ["claude", "+opus"] (required: claude, preferred: opus)
		// Expected: MATCH with bonus score

		providerTags := []string{"claude", "opus"}
		requiredTags := []string{"claude", "+opus"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match with preferred tags present")

		// Also test against provider without preferred tag
		providerTagsNoPreferred := []string{"claude", "sonnet"}
		matchesNoPreferred, scoreNoPreferred := matchesEnhancedTags(providerTagsNoPreferred, requiredTags)
		assert.True(t, matchesNoPreferred, "Should still match without preferred tags")
		assert.Greater(t, score, scoreNoPreferred, "Should have higher score with preferred tags")
	})

	t.Run("PreferredTags_Missing_ShouldStillMatch", func(t *testing.T) {
		// Provider has: ["claude", "sonnet"]
		// Consumer needs: ["claude", "+opus"] (required: claude, preferred: opus)
		// Expected: MATCH (preferred missing is OK)

		providerTags := []string{"claude", "sonnet"}
		requiredTags := []string{"claude", "+opus"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match even when preferred tags are missing")
		assert.Greater(t, score, 0, "Should still have positive score for required matches")
	})

	t.Run("ExcludedTags_Present_ShouldFail", func(t *testing.T) {
		// Provider has: ["claude", "experimental"]
		// Consumer needs: ["claude", "-experimental"] (required: claude, excluded: experimental)
		// Expected: NO MATCH (excluded tag is present)

		providerTags := []string{"claude", "experimental"}
		requiredTags := []string{"claude", "-experimental"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.False(t, matches, "Should not match when excluded tags are present")
		assert.Equal(t, 0, score, "Should have zero score when excluded tags are present")
	})

	t.Run("ExcludedTags_Missing_ShouldMatch", func(t *testing.T) {
		// Provider has: ["claude", "production"]
		// Consumer needs: ["claude", "-experimental"] (required: claude, excluded: experimental)
		// Expected: MATCH (excluded tag is not present)

		providerTags := []string{"claude", "production"}
		requiredTags := []string{"claude", "-experimental"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match when excluded tags are not present")
		assert.Greater(t, score, 0, "Should have positive score")
	})

	t.Run("ComplexScenario_RequiredPreferredExcluded", func(t *testing.T) {
		// Provider has: ["claude", "opus", "production", "us-east"]
		// Consumer needs: ["claude", "+opus", "+us-east", "-experimental", "-beta"]
		// Expected: MATCH with high score (required + 2 preferred, no excluded)

		providerTags := []string{"claude", "opus", "production", "us-east"}
		requiredTags := []string{"claude", "+opus", "+us-east", "-experimental", "-beta"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match complex scenario")

		// Compare with a provider that has fewer preferred tags
		providerTagsFewerPreferred := []string{"claude", "production"} // Missing both preferred
		matchesFewerPreferred, scoreFewerPreferred := matchesEnhancedTags(providerTagsFewerPreferred, requiredTags)
		assert.True(t, matchesFewerPreferred, "Should still match with fewer preferred tags")
		assert.Greater(t, score, scoreFewerPreferred, "Should have higher score with more preferred tags")
	})

	t.Run("EdgeCase_OnlyPreferredTags_ShouldMatch", func(t *testing.T) {
		// Provider has: ["claude", "opus"]
		// Consumer needs: ["+claude", "+opus"] (all preferred, no required)
		// Expected: MATCH with bonus score

		providerTags := []string{"claude", "opus"}
		requiredTags := []string{"+claude", "+opus"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match when all tags are preferred")
		assert.Greater(t, score, 0, "Should have positive score for preferred matches")
	})

	t.Run("EdgeCase_OnlyExcludedTags_ShouldMatchIfNonePresent", func(t *testing.T) {
		// Provider has: ["claude", "production"]
		// Consumer needs: ["-experimental", "-beta"] (only exclusions)
		// Expected: MATCH (no excluded tags present)

		providerTags := []string{"claude", "production"}
		requiredTags := []string{"-experimental", "-beta"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match when no excluded tags are present")
		assert.Equal(t, 0, score, "Should have zero score since no positive points earned")
	})

	t.Run("EdgeCase_ExactTagMatches_ShouldIgnoreSpecialChars", func(t *testing.T) {
		// Provider has: ["+opus", "-experimental", "opus-4.1"]
		// Consumer needs: ["+opus", "-experimental", "opus-4.1"] (exact matches)
		// Expected: MATCH (these are literal tag names, not operators)

		providerTags := []string{"+opus", "-experimental", "opus-4.1"}
		requiredTags := []string{"+opus", "-experimental", "opus-4.1"}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match exact tag names with special characters")
		assert.Greater(t, score, 0, "Should have positive score for exact matches")
	})

	t.Run("EmptyTags_ShouldMatch", func(t *testing.T) {
		// Provider has: ["claude", "opus"]
		// Consumer needs: [] (no requirements)
		// Expected: MATCH (no constraints = always match)

		providerTags := []string{"claude", "opus"}
		requiredTags := []string{}

		matches, score := matchesEnhancedTags(providerTags, requiredTags)
		assert.True(t, matches, "Should match when no tag requirements")
		assert.Equal(t, 0, score, "Should have zero score when no requirements")
	})
}

// TestEnhancedTagMatchingIntegration tests the integration with dependency resolution
func TestEnhancedTagMatchingIntegration(t *testing.T) {
	t.Run("DependencyResolution_PreferredTagSelection", func(t *testing.T) {
		service := setupTestService(t)

		// Register Provider 1: claude + sonnet
		provider1Req := &AgentRegistrationRequest{
			AgentID: "claude-sonnet-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-sonnet-provider",
				"version":    "1.0.0",
				"http_host":  "claude-sonnet",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "generate_text",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "sonnet"},
						"description":   "Claude Sonnet text generation",
					},
				},
			},
		}

		// Register Provider 2: claude + opus (preferred)
		provider2Req := &AgentRegistrationRequest{
			AgentID: "claude-opus-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-opus-provider",
				"version":    "1.0.0",
				"http_host":  "claude-opus",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "generate_text",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "opus"},
						"description":   "Claude Opus text generation",
					},
				},
			},
		}

		_, err := service.RegisterAgent(provider1Req)
		require.NoError(t, err)
		_, err = service.RegisterAgent(provider2Req)
		require.NoError(t, err)

		// Register consumer that prefers opus
		consumerReq := &AgentRegistrationRequest{
			AgentID: "llm-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "llm-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "smart_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "+opus"}, // Required: claude, Preferred: opus
							},
						},
						"description": "Smart chat with LLM",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// Verify dependency resolution chose the preferred provider (opus)
		assert.Contains(t, response.DependenciesResolved, "smart_chat")
		deps := response.DependenciesResolved["smart_chat"]
		require.Len(t, deps, 1, "Should resolve to one provider")

		resolvedDep := deps[0]
		assert.Equal(t, "claude-opus-provider", resolvedDep.AgentID, "Should prefer opus provider over sonnet")
		assert.Equal(t, "http://claude-opus:8080", resolvedDep.Endpoint)

		t.Logf("✅ Enhanced tag matching correctly selected preferred provider: %s", resolvedDep.AgentID)
	})

	t.Run("DependencyResolution_ExclusionTagFiltering", func(t *testing.T) {
		service := setupTestService(t)

		// Register Provider 1: claude + experimental (should be excluded)
		provider1Req := &AgentRegistrationRequest{
			AgentID: "claude-experimental",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-experimental",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "experimental_feature",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "experimental"},
						"description":   "Experimental Claude features",
					},
				},
			},
		}

		// Register Provider 2: claude + production (should be selected)
		provider2Req := &AgentRegistrationRequest{
			AgentID: "claude-production",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-production",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "stable_feature",
						"capability":    "llm_service",
						"version":       "1.0.0",
						"tags":          []string{"claude", "production"},
						"description":   "Stable Claude features",
					},
				},
			},
		}

		_, err := service.RegisterAgent(provider1Req)
		require.NoError(t, err)
		_, err = service.RegisterAgent(provider2Req)
		require.NoError(t, err)

		// Register consumer that excludes experimental
		consumerReq := &AgentRegistrationRequest{
			AgentID: "production-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "production-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "production_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm_service",
								"tags":       []string{"claude", "-experimental"}, // Required: claude, Excluded: experimental
							},
						},
						"description": "Production chat without experimental features",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// Verify dependency resolution excluded experimental provider
		assert.Contains(t, response.DependenciesResolved, "production_chat")
		deps := response.DependenciesResolved["production_chat"]
		require.Len(t, deps, 1, "Should resolve to one provider")

		resolvedDep := deps[0]
		assert.Equal(t, "claude-production", resolvedDep.AgentID, "Should exclude experimental provider")
		assert.NotEqual(t, "claude-experimental", resolvedDep.AgentID, "Should not select experimental provider")

		t.Logf("✅ Enhanced tag matching correctly excluded experimental provider")
	})
}
