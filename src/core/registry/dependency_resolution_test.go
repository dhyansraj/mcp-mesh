package registry

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestDependencyResolutionNewFormat tests the new dependency resolution format
func TestDependencyResolutionNewFormat(t *testing.T) {
	t.Run("RegisterMultipleAgentsAndResolveDependencies", func(t *testing.T) {
		service := setupTestService(t)

		// Register a provider agent first (provides date_service capability)
		providerReq := &AgentRegistrationRequest{
			AgentID: "date-service-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "date-service-provider",
				"version":    "1.2.0",
				"http_host":  "date-service",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_current_date",
						"capability":    "date_service",
						"version":       "1.2.0",
						"tags":          []string{"system", "production"},
						"description":   "Get current date and time",
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err, "Provider registration should succeed")

		// Register consumer agent that depends on date_service
		consumerReq := &AgentRegistrationRequest{
			AgentID: "greeting-service-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "greeting-service-consumer",
				"version":    "1.0.0",
				"http_host":  "greeting-service",
				"http_port":  float64(9090),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "smart_greet",
						"capability":    "personalized_greeting",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "date_service",
								"version":    ">=1.0.0",
								"tags":       []string{"system"},
							},
						},
						"description": "Smart greeting with date",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Consumer registration should succeed")

		// Validate response structure
		assert.Equal(t, "success", response.Status)
		assert.Equal(t, "greeting-service-consumer", response.AgentID)
		assert.NotNil(t, response.DependenciesResolved)

		// Check dependency resolution format
		depsResolved := response.DependenciesResolved
		t.Logf("DEBUG: Dependencies resolved: %+v", depsResolved)

		assert.Contains(t, depsResolved, "smart_greet", "Should have dependencies for smart_greet function")

		smartGreetDeps := depsResolved["smart_greet"]
		t.Logf("DEBUG: smart_greet dependencies: %+v", smartGreetDeps)
		assert.Equal(t, 1, len(smartGreetDeps), "Should have 1 resolved dependency")

		// Validate dependency resolution structure
		dep := smartGreetDeps[0]
		assert.Equal(t, "date-service-provider", dep.AgentID)
		assert.Equal(t, "get_current_date", dep.FunctionName)
		assert.Equal(t, "date_service", dep.Capability)
		assert.Equal(t, "available", dep.Status)
		assert.Equal(t, "http://date-service:8080", dep.Endpoint)

		t.Logf("✅ Dependency resolved successfully:")
		t.Logf("   Function: %s", "smart_greet")
		t.Logf("   Requires: %s", dep.Capability)
		t.Logf("   Provided by: %s.%s", dep.AgentID, dep.FunctionName)
		t.Logf("   Endpoint: %s", dep.Endpoint)
	})

	t.Run("MultipleDependenciesPerFunction", func(t *testing.T) {
		service := setupTestService(t)

		// Register multiple provider agents
		weatherProviderReq := &AgentRegistrationRequest{
			AgentID: "weather-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "weather-service",
				"version":    "2.0.0",
				"http_host":  "weather-api",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_weather",
						"capability":    "weather_service",
						"version":       "2.0.0",
						"tags":          []string{"external", "api"},
						"description":   "Get weather data",
					},
				},
			},
		}

		locationProviderReq := &AgentRegistrationRequest{
			AgentID: "location-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "location-service",
				"version":    "1.5.0",
				"http_host":  "location-api",
				"http_port":  float64(8080),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_coordinates",
						"capability":    "location_service",
						"version":       "1.5.0",
						"tags":          []string{"geo", "location"},
						"description":   "Get coordinates",
					},
				},
			},
		}

		_, err := service.RegisterAgent(weatherProviderReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(locationProviderReq)
		require.NoError(t, err)

		// Register consumer with multiple dependencies
		consumerReq := &AgentRegistrationRequest{
			AgentID: "weather-report-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "weather-report-service",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_weather_report",
						"capability":    "weather_report",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "weather_service",
								"version":    ">=2.0.0",
								"tags":       []string{"external", "api"},
							},
							map[string]interface{}{
								"capability": "location_service",
								"version":    ">=1.5.0",
								"tags":       []string{"geo", "location"},
							},
						},
						"description": "Weather report with location",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		// Check multiple dependencies resolved
		depsResolved := response.DependenciesResolved
		assert.Contains(t, depsResolved, "get_weather_report")

		weatherReportDeps := depsResolved["get_weather_report"]
		assert.Equal(t, 2, len(weatherReportDeps), "Should have 2 resolved dependencies")

		// Verify both dependencies are resolved
		capabilityFound := make(map[string]bool)
		for _, dep := range weatherReportDeps {
			capabilityFound[dep.Capability] = true
		}

		assert.True(t, capabilityFound["weather_service"], "Should resolve weather_service")
		assert.True(t, capabilityFound["location_service"], "Should resolve location_service")

		t.Logf("✅ Multiple dependencies resolved:")
		for _, dep := range weatherReportDeps {
			t.Logf("   %s -> %s.%s (%s)", dep.Capability, dep.AgentID, dep.FunctionName, dep.Endpoint)
		}
	})

	t.Run("NoDependenciesToResolve", func(t *testing.T) {
		service := setupTestService(t)

		// Register agent with no dependencies
		req := &AgentRegistrationRequest{
			AgentID: "standalone-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "standalone-service",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "standalone_function",
						"capability":    "standalone_capability",
						"version":       "1.0.0",
						"description":   "Standalone function",
						// No dependencies
					},
				},
			},
		}

		response, err := service.RegisterAgent(req)
		require.NoError(t, err)

		// Should have empty dependencies array
		depsResolved := response.DependenciesResolved
		assert.Contains(t, depsResolved, "standalone_function")
		assert.Equal(t, 0, len(depsResolved["standalone_function"]), "Should have no dependencies")

		t.Logf("✅ No dependencies case handled correctly")
	})

	t.Run("UnresolvableDependencies", func(t *testing.T) {
		service := setupTestService(t)

		// Register consumer that requires non-existent service
		consumerReq := &AgentRegistrationRequest{
			AgentID: "orphaned-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "orphaned-service",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "orphaned_function",
						"capability":    "orphaned_capability",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "non_existent_service",
								"version":    ">=1.0.0",
							},
						},
						"description": "Function with unresolvable dependency",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Registration should succeed even with unresolvable dependencies")

		// With partial resolution, functions with unresolvable dependencies are included but with empty deps
		depsResolved := response.DependenciesResolved
		assert.Contains(t, depsResolved, "orphaned_function", "Function should be included even with unresolvable dependencies")
		assert.Empty(t, depsResolved["orphaned_function"], "Function with unresolvable dependencies should have empty dependency list")

		t.Logf("✅ Unresolvable dependencies handled gracefully")
	})

	t.Run("PartialResolutionWithTagMismatch", func(t *testing.T) {
		service := setupTestService(t)

		// Register provider with specific tags
		providerReq := &AgentRegistrationRequest{
			AgentID: "time-service-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "time-service-provider",
				"version":    "1.5.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_time",
						"capability":    "time_service",
						"version":       "1.5.0",
						"tags":          []string{"system", "time"},
						"description":   "Get current time",
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err, "Provider registration should succeed")

		// Register consumer with mixed tag requirements
		consumerReq := &AgentRegistrationRequest{
			AgentID: "mixed-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "mixed-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "function_with_matching_tags",
						"capability":    "report_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "time_service",
								"version":    ">=1.0.0",
								"tags":       []string{"system"}, // Will match ["system", "time"]
							},
						},
						"description": "Function with matching tags",
					},
					map[string]interface{}{
						"function_name": "function_with_mismatched_tags",
						"capability":    "analysis_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "time_service",
								"version":    ">=1.0.0",
								"tags":       []string{"system", "general"}, // Won't match ["system", "time"]
							},
						},
						"description": "Function with mismatched tags",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Consumer registration should succeed")

		// Validate partial resolution
		depsResolved := response.DependenciesResolved
		t.Logf("DEBUG: Dependencies resolved: %+v", depsResolved)

		// Function with matching tags should resolve
		assert.Contains(t, depsResolved, "function_with_matching_tags", "Function with matching tags should be included")
		assert.Len(t, depsResolved["function_with_matching_tags"], 1, "Function with matching tags should have 1 resolved dependency")

		resolvedDep := depsResolved["function_with_matching_tags"][0]
		assert.Equal(t, "time-service-provider", resolvedDep.AgentID)
		assert.Equal(t, "get_time", resolvedDep.FunctionName)
		assert.Equal(t, "time_service", resolvedDep.Capability)

		// Function with mismatched tags should not resolve
		assert.Contains(t, depsResolved, "function_with_mismatched_tags", "Function with mismatched tags should be included")
		assert.Empty(t, depsResolved["function_with_mismatched_tags"], "Function with mismatched tags should have empty dependency list")

		t.Logf("✅ Partial resolution with tag mismatch handled correctly")
	})

	t.Run("PartialResolutionWithVersionMismatch", func(t *testing.T) {
		service := setupTestService(t)

		// Register provider with specific version
		providerReq := &AgentRegistrationRequest{
			AgentID: "database-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "database-provider",
				"version":    "1.2.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "query_db",
						"capability":    "database_service",
						"version":       "1.2.0",
						"tags":          []string{"data"},
						"description":   "Query database",
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err, "Provider registration should succeed")

		// Register consumer with mixed version requirements
		consumerReq := &AgentRegistrationRequest{
			AgentID: "version-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "version-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "compatible_function",
						"capability":    "app_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "database_service",
								"version":    ">=1.0.0", // Will match 1.2.0
								"tags":       []string{"data"},
							},
						},
						"description": "Function with compatible version requirement",
					},
					map[string]interface{}{
						"function_name": "incompatible_function",
						"capability":    "legacy_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "database_service",
								"version":    ">=2.0.0", // Won't match 1.2.0
								"tags":       []string{"data"},
							},
						},
						"description": "Function with incompatible version requirement",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Consumer registration should succeed")

		// Validate partial resolution
		depsResolved := response.DependenciesResolved
		t.Logf("DEBUG: Dependencies resolved: %+v", depsResolved)

		// Function with compatible version should resolve
		assert.Contains(t, depsResolved, "compatible_function", "Function with compatible version should be included")
		assert.Len(t, depsResolved["compatible_function"], 1, "Function with compatible version should have 1 resolved dependency")

		resolvedDep := depsResolved["compatible_function"][0]
		assert.Equal(t, "database-provider", resolvedDep.AgentID)
		assert.Equal(t, "query_db", resolvedDep.FunctionName)
		assert.Equal(t, "database_service", resolvedDep.Capability)

		// Function with incompatible version should not resolve
		assert.Contains(t, depsResolved, "incompatible_function", "Function with incompatible version should be included")
		assert.Empty(t, depsResolved["incompatible_function"], "Function with incompatible version should have empty dependency list")

		t.Logf("✅ Partial resolution with version mismatch handled correctly")
	})

	t.Run("PartialResolutionWithComplexConstraints", func(t *testing.T) {
		service := setupTestService(t)

		// Register multiple providers with different versions and tags
		authProviderReq := &AgentRegistrationRequest{
			AgentID: "auth-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "auth-provider",
				"version":    "2.1.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "authenticate",
						"capability":    "auth_service",
						"version":       "2.1.0",
						"tags":          []string{"security", "production"},
						"description":   "Authentication service",
					},
				},
			},
		}

		storageProviderReq := &AgentRegistrationRequest{
			AgentID: "storage-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "storage-provider",
				"version":    "1.8.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "store_data",
						"capability":    "storage_service",
						"version":       "1.8.0",
						"tags":          []string{"data", "persistence"},
						"description":   "Data storage service",
					},
				},
			},
		}

		_, err := service.RegisterAgent(authProviderReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(storageProviderReq)
		require.NoError(t, err)

		// Register consumer with complex mixed requirements
		consumerReq := &AgentRegistrationRequest{
			AgentID: "complex-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "complex-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "secure_operation", // Should resolve both deps
						"capability":    "secure_app_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "auth_service",
								"version":    "^2.0.0", // Matches 2.1.0
								"tags":       []string{"security"},
							},
							map[string]interface{}{
								"capability": "storage_service",
								"version":    "~1.8.0", // Matches 1.8.0
								"tags":       []string{"data"},
							},
						},
						"description": "Secure operation with both auth and storage",
					},
					map[string]interface{}{
						"function_name": "legacy_operation", // Should resolve storage but not auth
						"capability":    "legacy_app_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "auth_service",
								"version":    "<2.0.0", // Won't match 2.1.0
								"tags":       []string{"security"},
							},
							map[string]interface{}{
								"capability": "storage_service",
								"version":    ">=1.5.0", // Matches 1.8.0
								"tags":       []string{"data"},
							},
						},
						"description": "Legacy operation with mixed compatibility",
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Consumer registration should succeed")

		// Validate complex partial resolution
		depsResolved := response.DependenciesResolved
		t.Logf("DEBUG: Dependencies resolved: %+v", depsResolved)

		// secure_operation should have both dependencies resolved
		assert.Contains(t, depsResolved, "secure_operation")
		assert.Len(t, depsResolved["secure_operation"], 2, "secure_operation should have 2 resolved dependencies")

		// legacy_operation should have only storage resolved (auth fails version constraint)
		assert.Contains(t, depsResolved, "legacy_operation")
		assert.Len(t, depsResolved["legacy_operation"], 1, "legacy_operation should have 1 resolved dependency")

		// Verify which service was resolved for legacy_operation
		legacyDep := depsResolved["legacy_operation"][0]
		assert.Equal(t, "storage_service", legacyDep.Capability, "Only storage_service should resolve for legacy_operation")

		t.Logf("✅ Complex partial resolution with mixed constraints handled correctly")
	})
}
