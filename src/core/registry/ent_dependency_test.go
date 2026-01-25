package registry

import (
	"encoding/json"
	"testing"

	"mcp-mesh/src/core/registry/generated"
)

// makeDepTags creates a slice of MeshToolDependencyRegistration_Tags_Item from strings
func makeDepTags(tags ...string) *[]generated.MeshToolDependencyRegistration_Tags_Item {
	items := make([]generated.MeshToolDependencyRegistration_Tags_Item, len(tags))
	for i, tag := range tags {
		_ = items[i].FromMeshToolDependencyRegistrationTags0(tag)
	}
	return &items
}

// TestEntDependencyResolution tests the complete dependency resolution flow with in-memory SQLite
func TestEntDependencyResolution(t *testing.T) {
	// Use the common test setup
	entService := setupTestService(t)

	// Test real request format from test_request.json
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
						Tags:       makeDepTags(),
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
						Tags:       makeDepTags(),
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
						Tags:       makeDepTags(),
						Version:    stringPtr(""),
						Namespace:  stringPtr("default"),
					},
				},
				Description: stringPtr("Health status information."),
			},
		},
	}

	// Convert to registration request (direct registration)
	regReq := &AgentRegistrationRequest{
		AgentID:   realRequest.AgentId,
		Metadata:  ConvertMeshAgentRegistrationToMap(realRequest),
		Timestamp: "2025-06-29T19:41:26.677130Z",
	}

	// Register agent directly
	response, err := entService.RegisterAgent(regReq)
	if err != nil {
		t.Fatalf("Failed to register agent: %v", err)
	}

	// Verify response shows success
	if response.Status != "success" {
		t.Errorf("Expected success status, got: %s", response.Status)
	}

	// Check that dependency resolution worked in response
	if response.DependenciesResolved == nil {
		t.Errorf("Expected dependencies resolved in response, got nil")
	} else {
		// Should have 3 functions with resolved dependencies
		expectedFunctions := []string{"analysis_prompt", "calculate_with_timestamp", "health_status"}
		for _, fn := range expectedFunctions {
			if deps, found := response.DependenciesResolved[fn]; !found {
				t.Errorf("Expected function %s to have resolved dependencies", fn)
			} else if len(deps) != 1 {
				t.Errorf("Expected function %s to have 1 resolved dependency, got %d", fn, len(deps))
			} else if deps[0].Capability != "time_service" {
				t.Errorf("Expected dependency to be time_service, got %s", deps[0].Capability)
			}
		}
	}

	// Now check /agents endpoint - this is where the real test is
	agentsResp, err := entService.ListAgents(&AgentQueryParams{})
	if err != nil {
		t.Fatalf("Failed to list agents: %v", err)
	}

	if len(agentsResp.Agents) != 1 {
		t.Fatalf("Expected 1 agent, got %d", len(agentsResp.Agents))
	}

	agent := agentsResp.Agents[0]

	// Verify agent details
	if agent.Id != "fastmcp-service-6fe236a0" {
		t.Errorf("Expected agent ID fastmcp-service-6fe236a0, got %s", agent.Id)
	}

	// Verify capabilities count
	if len(agent.Capabilities) != 7 {
		t.Errorf("Expected 7 capabilities, got %d", len(agent.Capabilities))
	}

	// THE CRITICAL TEST: Verify dependency counts
	if agent.TotalDependencies != 3 {
		t.Errorf("FAIL: Expected 3 total dependencies, got %d", agent.TotalDependencies)
	}

	if agent.DependenciesResolved != 3 {
		t.Errorf("FAIL: Expected 3 resolved dependencies, got %d", agent.DependenciesResolved)
	}

	// Debug: Print the conversion result to see what's happening
	metadata := ConvertMeshAgentRegistrationToMap(realRequest)
	metadataJSON, _ := json.MarshalIndent(metadata, "", "  ")
	t.Logf("Converted metadata: %s", metadataJSON)

	// Debug: Check if tools are in metadata
	if tools, exists := metadata["tools"]; exists {
		t.Logf("Tools found in metadata: %d tools", len(tools.([]interface{})))
	} else {
		t.Errorf("CRITICAL: No tools found in converted metadata")
	}
}

// Helper functions
func stringPtr(s string) *string {
	return &s
}

func intPtr(i int) *int {
	return &i
}
