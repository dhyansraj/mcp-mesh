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
				"name":       "Date Service Provider",
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
				"name":       "Greeting Service Consumer",
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
				"name":       "Weather Service",
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
				"name":       "Location Service",
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
				"name":       "Weather Report Service",
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
				"name":       "Standalone Service",
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
				"name":       "Orphaned Service",
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

		// With strict resolution, functions with unresolvable dependencies should be excluded
		depsResolved := response.DependenciesResolved
		assert.NotContains(t, depsResolved, "orphaned_function", "Function with unresolvable dependencies should be excluded")

		t.Logf("✅ Unresolvable dependencies handled gracefully")
	})
}
