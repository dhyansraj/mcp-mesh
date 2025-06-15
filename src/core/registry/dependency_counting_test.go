package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestDependencyCountingInDatabase tests that dependency counts are properly stored in DB
func TestDependencyCountingInDatabase(t *testing.T) {
	t.Run("VerifyDependencyCountsInDatabase", func(t *testing.T) {
		// Setup database and service with same database instance
		db := setupTestDatabase(t)
		defer db.Close()

		config := &RegistryConfig{
			CacheTTL:                 30,
			DefaultTimeoutThreshold:  60,
			DefaultEvictionThreshold: 120,
			EnableResponseCache:      false,
		}
		service := NewService(db, config)

		// Register provider first
		providerReq := &AgentRegistrationRequest{
			AgentID: "test-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Test Provider",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "provide_service",
						"capability":    "test_capability",
						"version":       "1.0.0",
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err)

		// Register consumer with 3 dependencies (2 resolvable, 1 not)
		consumerReq := &AgentRegistrationRequest{
			AgentID: "test-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Test Consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "function_with_deps",
						"capability":    "consumer_capability",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "test_capability", // This will resolve
								"version":    ">=1.0.0",
							},
							map[string]interface{}{
								"capability": "missing_capability", // This won't resolve
								"version":    ">=1.0.0",
							},
						},
					},
					map[string]interface{}{
						"function_name": "another_function",
						"capability":    "another_capability",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "test_capability", // This will resolve
								"version":    ">=1.0.0",
							},
						},
					},
				},
			},
		}

		_, err = service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// Query database directly to verify counts
		var totalDeps, resolvedDeps int
		err = db.DB.QueryRow(
			"SELECT total_dependencies, dependencies_resolved FROM agents WHERE agent_id = ?",
			"test-consumer").Scan(&totalDeps, &resolvedDeps)
		require.NoError(t, err)

		// Verify counts: 3 total deps (2 + 1), 2 resolved with partial resolution logic
		// Function 1: 1 resolved (test_capability), 1 unresolved (missing_capability)
		// Function 2: 1 resolved (test_capability)
		// Total: 2 resolved dependencies with partial resolution counting
		assert.Equal(t, 3, totalDeps, "Should count all dependencies across all tools")
		assert.Equal(t, 2, resolvedDeps, "Should count individual resolved dependencies (partial resolution enabled)")

		t.Logf("✅ Database dependency counts verified:")
		t.Logf("   Total dependencies: %d", totalDeps)
		t.Logf("   Resolved dependencies: %d", resolvedDeps)
	})

	t.Run("VerifyProviderHasZeroDependencies", func(t *testing.T) {
		db := setupTestDatabase(t)
		defer db.Close()

		config := &RegistryConfig{
			DefaultTimeoutThreshold: 60,
			EnableResponseCache:     false,
		}
		service := NewService(db, config)

		// Register pure provider (no dependencies)
		providerReq := &AgentRegistrationRequest{
			AgentID: "pure-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Pure Provider",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "service1",
						"capability":    "capability1",
						"version":       "1.0.0",
					},
					map[string]interface{}{
						"function_name": "service2",
						"capability":    "capability2",
						"version":       "1.0.0",
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err)

		// Query database
		var totalDeps, resolvedDeps int
		err = db.DB.QueryRow(
			"SELECT total_dependencies, dependencies_resolved FROM agents WHERE agent_id = ?",
			"pure-provider").Scan(&totalDeps, &resolvedDeps)
		require.NoError(t, err)

		assert.Equal(t, 0, totalDeps, "Provider with no dependencies should have 0 total")
		assert.Equal(t, 0, resolvedDeps, "Provider with no dependencies should have 0 resolved")

		t.Logf("✅ Pure provider dependency counts: %d total, %d resolved", totalDeps, resolvedDeps)
	})

	t.Run("VerifyDependencyCountsAfterUpdate", func(t *testing.T) {
		db := setupTestDatabase(t)
		defer db.Close()

		config := &RegistryConfig{
			DefaultTimeoutThreshold: 60,
			EnableResponseCache:     false,
		}
		service := NewService(db, config)

		// Initial registration with 1 dependency
		initialReq := &AgentRegistrationRequest{
			AgentID: "updating-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Updating Agent",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "initial_function",
						"capability":    "initial_capability",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "missing_service",
								"version":    ">=1.0.0",
							},
						},
					},
				},
			},
		}

		_, err := service.RegisterAgent(initialReq)
		require.NoError(t, err)

		// Update with different dependencies
		updateReq := &AgentRegistrationRequest{
			AgentID: "updating-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "Updated Agent",
				"version":    "2.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "new_function1",
						"capability":    "new_capability1",
						"version":       "2.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "service_a",
								"version":    ">=1.0.0",
							},
							map[string]interface{}{
								"capability": "service_b",
								"version":    ">=1.0.0",
							},
						},
					},
					map[string]interface{}{
						"function_name": "new_function2",
						"capability":    "new_capability2",
						"version":       "2.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "service_c",
								"version":    ">=1.0.0",
							},
						},
					},
				},
			},
		}

		_, err = service.RegisterAgent(updateReq)
		require.NoError(t, err)

		// Verify updated counts
		var totalDeps, resolvedDeps int
		err = db.DB.QueryRow(
			"SELECT total_dependencies, dependencies_resolved FROM agents WHERE agent_id = ?",
			"updating-agent").Scan(&totalDeps, &resolvedDeps)
		require.NoError(t, err)

		assert.Equal(t, 3, totalDeps, "Should have 3 total dependencies after update")
		assert.Equal(t, 0, resolvedDeps, "Should have 0 resolved dependencies (no providers registered)")

		t.Logf("✅ Dependency counts updated correctly: %d total, %d resolved", totalDeps, resolvedDeps)
	})
}
