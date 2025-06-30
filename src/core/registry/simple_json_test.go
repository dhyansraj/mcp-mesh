package registry

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"mcp-mesh/src/core/registry/generated"
)

// TestSimpleJSONParsing is a minimal test to verify JSON parsing works
func TestSimpleJSONParsing(t *testing.T) {
	// Test parsing the multiple functions request JSON
	jsonData, err := os.ReadFile("testdata/agent_registration/multiple_functions_request.json")
	require.NoError(t, err, "Should be able to read test JSON file")

	var registration generated.MeshAgentRegistration
	err = json.Unmarshal(jsonData, &registration)
	require.NoError(t, err, "Should be able to parse JSON into MeshAgentRegistration")

	// Basic validation
	assert.Equal(t, "agent-b065c499", registration.AgentId)
	assert.Equal(t, 3, len(registration.Tools))

	t.Logf("✅ Successfully parsed JSON: AgentId=%s, Tools=%d",
		registration.AgentId, len(registration.Tools))
}

// TestConvertMeshAgentRegistrationToMap tests our conversion function
func TestConvertMeshAgentRegistrationToMap(t *testing.T) {
	// Create a simple test registration
	registration := generated.MeshAgentRegistration{
		AgentId: "test-agent",
		Tools: []generated.MeshToolRegistration{
			{
				FunctionName: "test_func",
				Capability:   "test_cap",
			},
		},
	}

	// Test conversion
	metadata := ConvertMeshAgentRegistrationToMap(registration)

	// Validate basic fields
	assert.Equal(t, "test-agent", metadata["name"])
	assert.Equal(t, "mcp_agent", metadata["agent_type"])

	// Validate tools are preserved
	tools, ok := metadata["tools"].([]interface{})
	require.True(t, ok)
	assert.Len(t, tools, 1)

	tool := tools[0].(map[string]interface{})
	assert.Equal(t, "test_cap", tool["capability"])

	t.Logf("✅ Successfully converted MeshAgentRegistration to service layer format")
}
