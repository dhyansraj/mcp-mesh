package registry

import (
	"testing"

	"mcp-mesh/src/core/registry/generated"
)

// makeDepTagsEmpty creates an empty MeshToolDependencyRegistration_Tags_Item slice
func makeDepTagsEmpty() *[]generated.MeshToolDependencyRegistration_Tags_Item {
	return &[]generated.MeshToolDependencyRegistration_Tags_Item{}
}

// TestDependencyCalculation tests the dependency counting logic in isolation
func TestDependencyCalculation(t *testing.T) {
	// Create test request (same structure as real request)
	agentType := generated.MeshAgentRegistrationAgentTypeMcpAgent
	realRequest := generated.MeshAgentRegistration{
		AgentId:   "fastmcp-service-6fe236a0",
		AgentType: &agentType,
		Name:      stringPtr("fastmcp-service-6fe236a0"),
		Version:   stringPtr("1.0.0"),
		HttpHost:  stringPtr("10.211.55.3"),
		HttpPort:  intPtr(9092),
		Namespace: stringPtr("default"),
		Tools: []generated.MeshToolRegistration{
			{
				FunctionName: "analysis_prompt",
				Capability:   "prompt_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{},
				Dependencies: &[]generated.MeshToolDependencyRegistration{
					{
						Capability: "time_service",
						Tags:       makeDepTagsEmpty(),
						Version:    stringPtr(""),
						Namespace:  stringPtr("default"),
					},
				},
				Description: stringPtr("Generate analysis prompt with current time."),
			},
			{
				FunctionName: "get_current_time",
				Capability:   "time_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{"system", "time"},
				Dependencies: &[]generated.MeshToolDependencyRegistration{},
				Description:  stringPtr("Get the current system time."),
			},
			{
				FunctionName: "calculate_with_timestamp",
				Capability:   "math_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{},
				Dependencies: &[]generated.MeshToolDependencyRegistration{
					{
						Capability: "time_service",
						Tags:       makeDepTagsEmpty(),
						Version:    stringPtr(""),
						Namespace:  stringPtr("default"),
					},
				},
				Description: stringPtr("Perform math operation with timestamp from time service."),
			},
			{
				FunctionName: "process_data",
				Capability:   "data_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{"data", "json"},
				Dependencies: &[]generated.MeshToolDependencyRegistration{},
				Description:  stringPtr("Process and format data."),
			},
			{
				FunctionName: "report_template",
				Capability:   "template_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{},
				Dependencies: &[]generated.MeshToolDependencyRegistration{},
				Description:  stringPtr("Generate report template."),
			},
			{
				FunctionName: "service_config",
				Capability:   "config_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{},
				Dependencies: &[]generated.MeshToolDependencyRegistration{},
				Description:  stringPtr("Service configuration data."),
			},
			{
				FunctionName: "health_status",
				Capability:   "status_service",
				Version:      stringPtr("1.0.0"),
				Tags:         &[]string{},
				Dependencies: &[]generated.MeshToolDependencyRegistration{
					{
						Capability: "time_service",
						Tags:       makeDepTagsEmpty(),
						Version:    stringPtr(""),
						Namespace:  stringPtr("default"),
					},
				},
				Description: stringPtr("Health status information."),
			},
		},
	}

	// Convert to metadata (same as handlers do)
	metadata := ConvertMeshAgentRegistrationToMap(realRequest)

	// DEBUG: Print the converted metadata to see structure
	t.Logf("=== CONVERTED METADATA ===")
	if tools, exists := metadata["tools"]; exists {
		toolsArray := tools.([]interface{})
		t.Logf("Found %d tools in metadata", len(toolsArray))

		for i, tool := range toolsArray {
			toolMap := tool.(map[string]interface{})
			functionName := toolMap["function_name"].(string)
			deps := toolMap["dependencies"]

			if deps != nil {
				depsArray := deps.([]map[string]interface{})
				t.Logf("Tool %d (%s): %d dependencies", i, functionName, len(depsArray))
				for j, dep := range depsArray {
					t.Logf("  Dep %d: capability=%s", j, dep["capability"])
				}
			} else {
				t.Logf("Tool %d (%s): no dependencies", i, functionName)
			}
		}
	} else {
		t.Errorf("CRITICAL: No tools found in converted metadata")
		return
	}

	// Test dependency counting logic by parsing tools directly
	totalDeps := 0

	if toolsData, exists := metadata["tools"]; exists {
		if toolsList, ok := toolsData.([]interface{}); ok {
			for _, toolData := range toolsList {
				if toolMap, ok := toolData.(map[string]interface{}); ok {
					functionName := toolMap["function_name"].(string)

					// Count dependencies for this function
					if deps, exists := toolMap["dependencies"]; exists {
						if depsSlice, ok := deps.([]map[string]interface{}); ok {
							depCount := len(depsSlice)
							totalDeps += depCount
							t.Logf("Function %s has %d dependencies", functionName, depCount)
						}
					}
				}
			}
		}
	}

	// VERIFY: Should count 3 dependencies total
	if totalDeps != 3 {
		t.Errorf("FAIL: Expected 3 total dependencies, got %d", totalDeps)
	} else {
		t.Logf("SUCCESS: Correctly counted %d dependencies", totalDeps)
	}

	// Test if dependencies are in expected format
	if toolsData, exists := metadata["tools"]; exists {
		if toolsList, ok := toolsData.([]interface{}); ok {
			for _, toolData := range toolsList {
				if toolMap, ok := toolData.(map[string]interface{}); ok {
					functionName := toolMap["function_name"].(string)

					if deps, exists := toolMap["dependencies"]; exists {
						if depsSlice, ok := deps.([]map[string]interface{}); ok {
							for _, depMap := range depsSlice {
								capability, _ := depMap["capability"].(string)
								if capability == "" {
									t.Errorf("Function %s has dependency with empty capability", functionName)
								}
								if capability == "time_service" {
									t.Logf("✓ Function %s correctly depends on time_service", functionName)
								}
							}
						}
					}
				}
			}
		}
	}
}

// Helper functions are defined in ent_dependency_test.go
