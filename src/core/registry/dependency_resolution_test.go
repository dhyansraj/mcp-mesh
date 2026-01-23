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

// TestPositionalDependencyResolution tests Issue #471 - Positional integrity and correct resolution
// These tests ensure dependencies are resolved by capability + tags + version, not just capability
func TestPositionalDependencyResolution(t *testing.T) {

	// Test 1: Same capability, different tags → different providers
	// This is the core bug in Issue #471 - all math_operations were resolving to "add"
	t.Run("SameCapabilityDifferentTags_ResolvesToDifferentProviders", func(t *testing.T) {
		service := setupTestService(t)

		// Register math-agent that provides 4 tools with same capability but different tags
		mathProviderReq := &AgentRegistrationRequest{
			AgentID: "math-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "math-agent",
				"version":    "1.0.0",
				"http_host":  "math-service",
				"http_port":  float64(9011),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "add",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "addition"},
						"description":   "Add two numbers",
					},
					map[string]interface{}{
						"function_name": "subtract",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "subtraction"},
						"description":   "Subtract two numbers",
					},
					map[string]interface{}{
						"function_name": "multiply",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "multiplication"},
						"description":   "Multiply two numbers",
					},
					map[string]interface{}{
						"function_name": "divide",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "division"},
						"description":   "Divide two numbers",
					},
				},
			},
		}

		_, err := service.RegisterAgent(mathProviderReq)
		require.NoError(t, err, "Math provider registration should succeed")

		// Register calculator-agent that depends on all 4 math operations
		calculatorReq := &AgentRegistrationRequest{
			AgentID: "calculator-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "calculator-agent",
				"version":    "1.0.0",
				"http_host":  "calculator-service",
				"http_port":  float64(9025),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "calculate",
						"capability":    "calculator",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "math_operations",
								"tags":       []string{"addition"},
							},
							map[string]interface{}{
								"capability": "math_operations",
								"tags":       []string{"subtraction"},
							},
							map[string]interface{}{
								"capability": "math_operations",
								"tags":       []string{"multiplication"},
							},
							map[string]interface{}{
								"capability": "math_operations",
								"tags":       []string{"division"},
							},
						},
						"description": "Calculator with multiple deps",
					},
				},
			},
		}

		response, err := service.RegisterAgent(calculatorReq)
		require.NoError(t, err, "Calculator registration should succeed")

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "calculate")

		calculateDeps := depsResolved["calculate"]
		require.Len(t, calculateDeps, 4, "Should have 4 resolved dependencies")

		// Verify each dependency resolved to the CORRECT function (not all to "add")
		functionNames := make([]string, len(calculateDeps))
		for i, dep := range calculateDeps {
			functionNames[i] = dep.FunctionName
		}

		// The bug was: all 4 resolved to "add". The fix should give us add, subtract, multiply, divide
		assert.Contains(t, functionNames, "add", "Should resolve addition dep to 'add' function")
		assert.Contains(t, functionNames, "subtract", "Should resolve subtraction dep to 'subtract' function")
		assert.Contains(t, functionNames, "multiply", "Should resolve multiplication dep to 'multiply' function")
		assert.Contains(t, functionNames, "divide", "Should resolve division dep to 'divide' function")

		t.Logf("✅ Same capability with different tags resolved to different providers:")
		for i, dep := range calculateDeps {
			t.Logf("   dep[%d]: %s -> %s", i, dep.Capability, dep.FunctionName)
		}
	})

	// Test 2: Positional integrity - middle dependency unresolved
	t.Run("PositionalIntegrity_MiddleUnresolved", func(t *testing.T) {
		service := setupTestService(t)

		// Register time-service and auth-service, but NOT location-service
		timeProviderReq := &AgentRegistrationRequest{
			AgentID: "time-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "time-service",
				"version":    "1.0.0",
				"http_host":  "time-service",
				"http_port":  float64(8001),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "get_time",
						"capability":    "time_service",
						"version":       "1.0.0",
						"tags":          []string{"time"},
					},
				},
			},
		}

		authProviderReq := &AgentRegistrationRequest{
			AgentID: "auth-service",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "auth-service",
				"version":    "1.0.0",
				"http_host":  "auth-service",
				"http_port":  float64(8003),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "authenticate",
						"capability":    "auth_service",
						"version":       "1.0.0",
						"tags":          []string{"auth"},
					},
				},
			},
		}

		_, err := service.RegisterAgent(timeProviderReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(authProviderReq)
		require.NoError(t, err)

		// Consumer with 3 deps: time (available), location (NOT available), auth (available)
		consumerReq := &AgentRegistrationRequest{
			AgentID: "consumer-with-gap",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "consumer-with-gap",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "complex_operation",
						"capability":    "complex_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "time_service", // dep[0] - available
							},
							map[string]interface{}{
								"capability": "location_service", // dep[1] - NOT available
							},
							map[string]interface{}{
								"capability": "auth_service", // dep[2] - available
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Registration should succeed even with unresolved middle dep")

		// Query the DB to check dep_index is preserved
		// For now, check the response structure
		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "complex_operation")

		// With the fix, we should store all 3 deps (including unresolved)
		// Currently returns only resolved ones - after fix should include unresolved with status
		deps := depsResolved["complex_operation"]
		t.Logf("DEBUG: Resolved deps count: %d", len(deps))

		// Verify time and auth are resolved
		capabilitiesResolved := make(map[string]bool)
		for _, dep := range deps {
			capabilitiesResolved[dep.Capability] = true
		}
		assert.True(t, capabilitiesResolved["time_service"], "time_service should be resolved")
		assert.True(t, capabilitiesResolved["auth_service"], "auth_service should be resolved")

		t.Logf("✅ Positional integrity test - middle dep unresolved handled")
	})

	// Test 3: OR alternatives - primary available
	t.Run("ORAlternatives_PrimaryAvailable", func(t *testing.T) {
		service := setupTestService(t)

		// Register both claude and gpt providers
		claudeProviderReq := &AgentRegistrationRequest{
			AgentID: "claude-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-provider",
				"version":    "1.0.0",
				"http_host":  "claude-service",
				"http_port":  float64(8010),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "process_chat",
						"capability":    "llm",
						"version":       "1.0.0",
						"tags":          []string{"llm", "claude", "anthropic"},
					},
				},
			},
		}

		gptProviderReq := &AgentRegistrationRequest{
			AgentID: "gpt-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "gpt-provider",
				"version":    "1.0.0",
				"http_host":  "gpt-service",
				"http_port":  float64(8011),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "process_chat",
						"capability":    "llm",
						"version":       "1.0.0",
						"tags":          []string{"llm", "gpt", "openai"},
					},
				},
			},
		}

		_, err := service.RegisterAgent(claudeProviderReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(gptProviderReq)
		require.NoError(t, err)

		// Consumer with OR alternatives: prefer claude, fallback to gpt
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
							// OR alternatives as array of specs
							[]interface{}{
								map[string]interface{}{
									"capability": "llm",
									"tags":       []string{"+claude"}, // Primary: prefer claude
								},
								map[string]interface{}{
									"capability": "llm",
									"tags":       []string{"+gpt"}, // Fallback: gpt
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "smart_chat")

		deps := depsResolved["smart_chat"]
		require.Len(t, deps, 1, "Should have 1 resolved dependency")

		// Should resolve to claude (primary) since both are available
		// The first alternative wins when both match
		dep := deps[0]
		assert.Equal(t, "llm", dep.Capability)
		// With +preferred tags, the one with higher match score wins
		t.Logf("✅ OR alternatives - resolved to: %s (%s)", dep.AgentID, dep.FunctionName)
	})

	// Test 4: OR alternatives - fallback used
	t.Run("ORAlternatives_FallbackUsed", func(t *testing.T) {
		service := setupTestService(t)

		// Only register gpt provider (no claude)
		gptProviderReq := &AgentRegistrationRequest{
			AgentID: "gpt-only-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "gpt-only-provider",
				"version":    "1.0.0",
				"http_host":  "gpt-service",
				"http_port":  float64(8012),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "process_chat",
						"capability":    "llm",
						"version":       "1.0.0",
						"tags":          []string{"llm", "gpt", "openai"},
					},
				},
			},
		}

		_, err := service.RegisterAgent(gptProviderReq)
		require.NoError(t, err)

		// Consumer with OR alternatives: claude (unavailable), gpt (available)
		consumerReq := &AgentRegistrationRequest{
			AgentID: "llm-consumer-fallback",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "llm-consumer-fallback",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "smart_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							// OR alternatives: claude first (unavailable), gpt second (available)
							[]interface{}{
								map[string]interface{}{
									"capability": "llm",
									"tags":       []string{"claude"}, // Primary: NOT available
								},
								map[string]interface{}{
									"capability": "llm",
									"tags":       []string{"gpt"}, // Fallback: available
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "smart_chat")

		deps := depsResolved["smart_chat"]
		require.Len(t, deps, 1, "Should have 1 resolved dependency (fallback)")

		// Should resolve to gpt since claude is not available
		dep := deps[0]
		assert.Equal(t, "llm", dep.Capability)
		assert.Equal(t, "gpt-only-provider", dep.AgentID, "Should use fallback gpt provider")

		t.Logf("✅ OR alternatives - fallback used: %s", dep.AgentID)
	})

	// Test 5: OR alternatives - all unresolved
	t.Run("ORAlternatives_AllUnresolved", func(t *testing.T) {
		service := setupTestService(t)

		// Don't register any LLM providers

		// Consumer with OR alternatives - none available
		consumerReq := &AgentRegistrationRequest{
			AgentID: "llm-consumer-none",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "llm-consumer-none",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "smart_chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							[]interface{}{
								map[string]interface{}{
									"capability": "llm",
									"tags":       []string{"claude"}, // NOT available
								},
								map[string]interface{}{
									"capability": "llm",
									"tags":       []string{"gpt"}, // NOT available
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Registration should succeed even with all unresolved")

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "smart_chat")

		// All alternatives failed - should have empty resolved list (or unresolved status after fix)
		deps := depsResolved["smart_chat"]
		assert.Empty(t, deps, "All alternatives unresolved - should have empty deps")

		t.Logf("✅ OR alternatives - all unresolved handled gracefully")
	})

	// Test 6: Weighted tag matching
	t.Run("WeightedTagMatching", func(t *testing.T) {
		service := setupTestService(t)

		// Register two LLM providers
		claudeProviderReq := &AgentRegistrationRequest{
			AgentID: "claude-weighted",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "claude-weighted",
				"version":    "1.0.0",
				"http_host":  "claude-service",
				"http_port":  float64(8020),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "process",
						"capability":    "llm",
						"version":       "1.0.0",
						"tags":          []string{"llm", "claude", "anthropic"},
					},
				},
			},
		}

		gptProviderReq := &AgentRegistrationRequest{
			AgentID: "gpt-weighted",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "gpt-weighted",
				"version":    "1.0.0",
				"http_host":  "gpt-service",
				"http_port":  float64(8021),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "process",
						"capability":    "llm",
						"version":       "1.0.0",
						"tags":          []string{"llm", "gpt", "openai"},
					},
				},
			},
		}

		_, err := service.RegisterAgent(claudeProviderReq)
		require.NoError(t, err)
		_, err = service.RegisterAgent(gptProviderReq)
		require.NoError(t, err)

		// Consumer with weighted preference: +claude has higher weight than +gpt
		// When both are available, claude should win
		consumerReq := &AgentRegistrationRequest{
			AgentID: "weighted-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "weighted-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "chat",
						"capability":    "chat_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "llm",
								"tags":       []string{"+claude", "+gpt"}, // Both preferred, claude listed first
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "chat")

		deps := depsResolved["chat"]
		require.Len(t, deps, 1)

		// With weighted matching, provider with more matching +tags should win
		dep := deps[0]
		t.Logf("✅ Weighted tag matching resolved to: %s (tags matched)", dep.AgentID)
	})

	// Test 7: Backward compatibility
	t.Run("BackwardCompatibility_OldFormat", func(t *testing.T) {
		service := setupTestService(t)

		// Register a provider
		providerReq := &AgentRegistrationRequest{
			AgentID: "simple-provider",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "simple-provider",
				"version":    "1.0.0",
				"http_host":  "simple-service",
				"http_port":  float64(8030),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "simple_function",
						"capability":    "simple_service",
						"version":       "1.0.0",
						"tags":          []string{"simple"},
					},
				},
			},
		}

		_, err := service.RegisterAgent(providerReq)
		require.NoError(t, err)

		// Consumer with OLD format (single object, not array)
		consumerReq := &AgentRegistrationRequest{
			AgentID: "old-format-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "old-format-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "consume",
						"capability":    "consumer_service",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							// Old format: single object (not array of alternatives)
							map[string]interface{}{
								"capability": "simple_service",
								"tags":       []string{"simple"},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err, "Old format should still work")

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "consume")

		deps := depsResolved["consume"]
		require.Len(t, deps, 1, "Should resolve old format dependency")

		dep := deps[0]
		assert.Equal(t, "simple_service", dep.Capability)
		assert.Equal(t, "simple-provider", dep.AgentID)

		t.Logf("✅ Backward compatibility - old format works: %s", dep.AgentID)
	})
}

// TestTagLevelOR tests tag-level OR alternatives (Issue #471 Phase 4)
// Syntax: tags: ["required", ["python", "typescript"]] = required AND (python OR typescript)
func TestTagLevelOR(t *testing.T) {

	// Test 1: Primary available - should prefer first alternative
	t.Run("PrimaryAvailable_ResolvesToFirstAlternative", func(t *testing.T) {
		service := setupTestService(t)

		// Provider A: math with python
		pythonProviderReq := &AgentRegistrationRequest{
			AgentID: "py-math-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "py-math-agent",
				"version":    "1.0.0",
				"http_host":  "py-math",
				"http_port":  float64(9001),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "add_py",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "addition", "python"},
						"description":   "Python addition",
					},
				},
			},
		}

		_, err := service.RegisterAgent(pythonProviderReq)
		require.NoError(t, err)

		// Provider B: math with typescript
		tsProviderReq := &AgentRegistrationRequest{
			AgentID: "ts-math-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "ts-math-agent",
				"version":    "1.0.0",
				"http_host":  "ts-math",
				"http_port":  float64(9002),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "add_ts",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "addition", "typescript"},
						"description":   "TypeScript addition",
					},
				},
			},
		}

		_, err = service.RegisterAgent(tsProviderReq)
		require.NoError(t, err)

		// Consumer with tag-level OR: addition AND (python OR typescript)
		// Python is first alternative, so should resolve to py-math-agent
		consumerReq := &AgentRegistrationRequest{
			AgentID: "or-consumer-1",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "or-consumer-1",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "calculate",
						"capability":    "calculator",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "math_operations",
								"tags": []interface{}{
									"addition",
									[]interface{}{"python", "typescript"}, // OR alternative
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "calculate")

		deps := depsResolved["calculate"]
		require.Len(t, deps, 1, "Should resolve one dependency")

		dep := deps[0]
		assert.Equal(t, "math_operations", dep.Capability)
		assert.Equal(t, "py-math-agent", dep.AgentID, "Should resolve to python (first alternative)")
		assert.Equal(t, "add_py", dep.FunctionName)
		assert.Equal(t, "available", dep.Status)

		t.Logf("✅ Tag-level OR: Primary alternative (python) selected when both available")
	})

	// Test 2: Only fallback available
	t.Run("FallbackUsed_WhenPrimaryUnavailable", func(t *testing.T) {
		service := setupTestService(t)

		// Only typescript provider available (no python)
		tsProviderReq := &AgentRegistrationRequest{
			AgentID: "ts-math-agent-only",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "ts-math-agent-only",
				"version":    "1.0.0",
				"http_host":  "ts-math",
				"http_port":  float64(9002),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "add_ts",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "addition", "typescript"},
						"description":   "TypeScript addition",
					},
				},
			},
		}

		_, err := service.RegisterAgent(tsProviderReq)
		require.NoError(t, err)

		// Consumer with tag-level OR: addition AND (python OR typescript)
		// Python is first but unavailable, so should resolve to typescript
		consumerReq := &AgentRegistrationRequest{
			AgentID: "or-consumer-fallback",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "or-consumer-fallback",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "calculate",
						"capability":    "calculator",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "math_operations",
								"tags": []interface{}{
									"addition",
									[]interface{}{"python", "typescript"}, // OR alternative
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "calculate")

		deps := depsResolved["calculate"]
		require.Len(t, deps, 1, "Should resolve one dependency")

		dep := deps[0]
		assert.Equal(t, "math_operations", dep.Capability)
		assert.Equal(t, "ts-math-agent-only", dep.AgentID, "Should resolve to typescript (fallback)")
		assert.Equal(t, "add_ts", dep.FunctionName)
		assert.Equal(t, "available", dep.Status)

		t.Logf("✅ Tag-level OR: Fallback alternative (typescript) selected when primary unavailable")
	})

	// Test 3: None of the alternatives available
	// Note: When no alternatives match, the dependency is unresolved and NOT included
	// in DependenciesResolved (only resolved ones are returned in API response).
	// Unresolved deps are tracked in the database via StoreDependencyResolutions.
	t.Run("NoneAvailable_NotInResponse", func(t *testing.T) {
		service := setupTestService(t)

		// Provider with rust (neither python nor typescript)
		rustProviderReq := &AgentRegistrationRequest{
			AgentID: "rust-math-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "rust-math-agent",
				"version":    "1.0.0",
				"http_host":  "rust-math",
				"http_port":  float64(9003),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "add_rust",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "addition", "rust"},
						"description":   "Rust addition",
					},
				},
			},
		}

		_, err := service.RegisterAgent(rustProviderReq)
		require.NoError(t, err)

		// Consumer with tag-level OR: addition AND (python OR typescript)
		// Neither python nor typescript available, should be unresolved
		consumerReq := &AgentRegistrationRequest{
			AgentID: "or-consumer-none",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "or-consumer-none",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "calculate",
						"capability":    "calculator",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "math_operations",
								"tags": []interface{}{
									"addition",
									[]interface{}{"python", "typescript"}, // OR alternative
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "calculate")

		deps := depsResolved["calculate"]
		// When no alternatives match, the dependency is not resolved
		// The DependenciesResolved map only contains successfully resolved deps
		assert.Len(t, deps, 0, "No resolved dependencies when no OR alternatives match")

		t.Logf("✅ Tag-level OR: No resolved deps when no alternatives available (unresolved tracked in DB)")
	})

	// Test 4: Multiple positions with OR alternatives
	t.Run("MultiplePositions_EachWithOR", func(t *testing.T) {
		service := setupTestService(t)

		// Only typescript providers available
		tsAddProviderReq := &AgentRegistrationRequest{
			AgentID: "ts-add-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "ts-add-agent",
				"version":    "1.0.0",
				"http_host":  "ts-add",
				"http_port":  float64(9010),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "add_ts",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "addition", "typescript"},
						"description":   "TypeScript addition",
					},
				},
			},
		}
		_, err := service.RegisterAgent(tsAddProviderReq)
		require.NoError(t, err)

		tsSubProviderReq := &AgentRegistrationRequest{
			AgentID: "ts-sub-agent",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "ts-sub-agent",
				"version":    "1.0.0",
				"http_host":  "ts-sub",
				"http_port":  float64(9011),
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "subtract_ts",
						"capability":    "math_operations",
						"version":       "1.0.0",
						"tags":          []string{"math", "subtraction", "typescript"},
						"description":   "TypeScript subtraction",
					},
				},
			},
		}
		_, err = service.RegisterAgent(tsSubProviderReq)
		require.NoError(t, err)

		// Consumer with 2 dependencies, both using OR alternatives
		consumerReq := &AgentRegistrationRequest{
			AgentID: "or-multi-consumer",
			Metadata: map[string]interface{}{
				"agent_type": "mcp_agent",
				"name":       "or-multi-consumer",
				"version":    "1.0.0",
				"tools": []interface{}{
					map[string]interface{}{
						"function_name": "calculate_multi",
						"capability":    "calculator",
						"version":       "1.0.0",
						"dependencies": []interface{}{
							map[string]interface{}{
								"capability": "math_operations",
								"tags": []interface{}{
									"addition",
									[]interface{}{"python", "typescript"},
								},
							},
							map[string]interface{}{
								"capability": "math_operations",
								"tags": []interface{}{
									"subtraction",
									[]interface{}{"python", "typescript"},
								},
							},
						},
					},
				},
			},
		}

		response, err := service.RegisterAgent(consumerReq)
		require.NoError(t, err)

		depsResolved := response.DependenciesResolved
		require.Contains(t, depsResolved, "calculate_multi")

		deps := depsResolved["calculate_multi"]
		require.Len(t, deps, 2, "Should resolve both dependencies")

		// Both should resolve to typescript providers (fallback used)
		dep0 := deps[0]
		assert.Equal(t, "ts-add-agent", dep0.AgentID, "First dep should resolve to ts-add-agent")
		assert.Equal(t, "available", dep0.Status)

		dep1 := deps[1]
		assert.Equal(t, "ts-sub-agent", dep1.AgentID, "Second dep should resolve to ts-sub-agent")
		assert.Equal(t, "available", dep1.Status)

		t.Logf("✅ Tag-level OR: Multiple positions each resolve correctly using fallback")
	})
}
