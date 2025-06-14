package registry

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// Test structs matching the new OpenAPI schema
type DecoratorAgentRequest struct {
	AgentID   string                    `json:"agent_id"`
	Timestamp string                    `json:"timestamp"`
	Metadata  DecoratorAgentMetadata    `json:"metadata"`
}

type DecoratorAgentMetadata struct {
	Name        string          `json:"name"`
	AgentType   string          `json:"agent_type"`
	Namespace   string          `json:"namespace"`
	Endpoint    string          `json:"endpoint"`
	Version     string          `json:"version"`
	Decorators  []DecoratorInfo `json:"decorators"`
}

type DecoratorInfo struct {
	FunctionName string                   `json:"function_name"`
	Capability   string                   `json:"capability"`
	Dependencies []StandardizedDependency `json:"dependencies"`
	Description  string                   `json:"description,omitempty"`
	Version      string                   `json:"version,omitempty"`
	Tags         []string                 `json:"tags,omitempty"`
}

type StandardizedDependency struct {
	Capability string   `json:"capability"`
	Tags       []string `json:"tags,omitempty"`
	Version    string   `json:"version,omitempty"`
	Namespace  string   `json:"namespace,omitempty"`
}

type DecoratorAgentResponse struct {
	AgentID              string              `json:"agent_id"`
	Status               string              `json:"status"`
	Message              string              `json:"message"`
	Timestamp            string              `json:"timestamp"`
	DependenciesResolved []ResolvedDecorator `json:"dependencies_resolved,omitempty"`
}

type ResolvedDecorator struct {
	FunctionName string               `json:"function_name"`
	Capability   string               `json:"capability"`
	Dependencies []ResolvedDependency `json:"dependencies"`
}

type ResolvedDependency struct {
	Capability  string                 `json:"capability"`
	MCPToolInfo map[string]interface{} `json:"mcp_tool_info,omitempty"`
	Status      string                 `json:"status"`
}

func TestDecoratorAgentRequestSerialization(t *testing.T) {
	// Test data matching hello_world.py structure
	request := DecoratorAgentRequest{
		AgentID:   "agent-hello-world-123",
		Timestamp: time.Now().Format(time.RFC3339),
		Metadata: DecoratorAgentMetadata{
			Name:      "hello-world",
			AgentType: "mcp_agent",
			Namespace: "default",
			Endpoint:  "stdio://agent-hello-world-123",
			Version:   "1.0.0",
			Decorators: []DecoratorInfo{
				{
					FunctionName: "hello_mesh_simple",
					Capability:   "greeting",
					Dependencies: []StandardizedDependency{
						{
							Capability: "date_service",
						},
					},
					Description: "Simple greeting with date dependency",
				},
				{
					FunctionName: "hello_mesh_typed",
					Capability:   "advanced_greeting",
					Dependencies: []StandardizedDependency{
						{
							Capability: "info",
							Tags:       []string{"system", "general"},
						},
					},
					Description: "Advanced greeting with system info",
				},
				{
					FunctionName: "test_dependencies",
					Capability:   "dependency_test",
					Dependencies: []StandardizedDependency{
						{
							Capability: "date_service",
						},
						{
							Capability: "info",
							Tags:       []string{"system", "disk"},
						},
					},
					Description: "Test multiple dependencies",
				},
			},
		},
	}

	// Serialize to JSON
	jsonData, err := json.MarshalIndent(request, "", "  ")
	require.NoError(t, err)

	// Verify JSON structure
	assert.Contains(t, string(jsonData), `"agent_id": "agent-hello-world-123"`)
	assert.Contains(t, string(jsonData), `"agent_type": "mcp_agent"`)
	assert.Contains(t, string(jsonData), `"decorators":`)
	assert.Contains(t, string(jsonData), `"hello_mesh_simple"`)
	assert.Contains(t, string(jsonData), `"greeting"`)
	assert.Contains(t, string(jsonData), `"date_service"`)
	assert.Contains(t, string(jsonData), `"system"`)

	// Deserialize back
	var parsed DecoratorAgentRequest
	err = json.Unmarshal(jsonData, &parsed)
	require.NoError(t, err)

	// Verify deserialization
	assert.Equal(t, request.AgentID, parsed.AgentID)
	assert.Equal(t, request.Metadata.Name, parsed.Metadata.Name)
	assert.Len(t, parsed.Metadata.Decorators, 3)
	assert.Equal(t, "hello_mesh_simple", parsed.Metadata.Decorators[0].FunctionName)
	assert.Equal(t, "greeting", parsed.Metadata.Decorators[0].Capability)
	assert.Len(t, parsed.Metadata.Decorators[0].Dependencies, 1)
	assert.Equal(t, "date_service", parsed.Metadata.Decorators[0].Dependencies[0].Capability)
}

func TestDecoratorAgentResponseSerialization(t *testing.T) {
	// Test response with per-function dependency resolution
	response := DecoratorAgentResponse{
		AgentID:   "agent-hello-world-123",
		Status:    "success",
		Message:   "Agent registered successfully",
		Timestamp: time.Now().Format(time.RFC3339),
		DependenciesResolved: []ResolvedDecorator{
			{
				FunctionName: "hello_mesh_simple",
				Capability:   "greeting",
				Dependencies: []ResolvedDependency{
					{
						Capability: "date_service",
						MCPToolInfo: map[string]interface{}{
							"name":     "get_current_date",
							"endpoint": "http://date-agent:8000",
							"agent_id": "date-agent-456",
						},
						Status: "resolved",
					},
				},
			},
			{
				FunctionName: "hello_mesh_typed",
				Capability:   "advanced_greeting",
				Dependencies: []ResolvedDependency{
					{
						Capability: "info",
						MCPToolInfo: map[string]interface{}{
							"name":     "get_system_info",
							"endpoint": "http://system-agent:8000",
							"agent_id": "system-agent-789",
						},
						Status: "resolved",
					},
				},
			},
			{
				FunctionName: "test_dependencies",
				Capability:   "dependency_test",
				Dependencies: []ResolvedDependency{
					{
						Capability: "date_service",
						MCPToolInfo: map[string]interface{}{
							"name":     "get_current_date",
							"endpoint": "http://date-agent:8000",
							"agent_id": "date-agent-456",
						},
						Status: "resolved",
					},
					{
						Capability: "info",
						MCPToolInfo: map[string]interface{}{
							"name":     "get_disk_info",
							"endpoint": "http://system-agent:8000",
							"agent_id": "system-agent-789",
						},
						Status: "resolved",
					},
				},
			},
		},
	}

	// Serialize to JSON
	jsonData, err := json.MarshalIndent(response, "", "  ")
	require.NoError(t, err)

	// Verify JSON structure
	assert.Contains(t, string(jsonData), `"agent_id": "agent-hello-world-123"`)
	assert.Contains(t, string(jsonData), `"status": "success"`)
	assert.Contains(t, string(jsonData), `"dependencies_resolved":`)
	assert.Contains(t, string(jsonData), `"hello_mesh_simple"`)
	assert.Contains(t, string(jsonData), `"mcp_tool_info"`)
	assert.Contains(t, string(jsonData), `"get_current_date"`)
	assert.Contains(t, string(jsonData), `"http://date-agent:8000"`)

	// Deserialize back
	var parsed DecoratorAgentResponse
	err = json.Unmarshal(jsonData, &parsed)
	require.NoError(t, err)

	// Verify deserialization
	assert.Equal(t, response.AgentID, parsed.AgentID)
	assert.Equal(t, response.Status, parsed.Status)
	assert.Len(t, parsed.DependenciesResolved, 3)
	assert.Equal(t, "hello_mesh_simple", parsed.DependenciesResolved[0].FunctionName)
	assert.Equal(t, "greeting", parsed.DependenciesResolved[0].Capability)
	assert.Len(t, parsed.DependenciesResolved[0].Dependencies, 1)
	assert.Equal(t, "date_service", parsed.DependenciesResolved[0].Dependencies[0].Capability)
	assert.Equal(t, "resolved", parsed.DependenciesResolved[0].Dependencies[0].Status)
}

func TestStandardizedDependencyFormat(t *testing.T) {
	tests := []struct {
		name       string
		dependency StandardizedDependency
		wantJSON   string
	}{
		{
			name: "simple dependency",
			dependency: StandardizedDependency{
				Capability: "date_service",
			},
			wantJSON: `{"capability":"date_service"}`,
		},
		{
			name: "dependency with tags",
			dependency: StandardizedDependency{
				Capability: "info",
				Tags:       []string{"system", "general"},
			},
			wantJSON: `{"capability":"info","tags":["system","general"]}`,
		},
		{
			name: "dependency with version constraint",
			dependency: StandardizedDependency{
				Capability: "storage",
				Tags:       []string{"system", "disk"},
				Version:    ">=1.0.0",
			},
			wantJSON: `{"capability":"storage","tags":["system","disk"],"version":"\u003e=1.0.0"}`,
		},
		{
			name: "dependency with namespace",
			dependency: StandardizedDependency{
				Capability: "auth",
				Namespace:  "security",
			},
			wantJSON: `{"capability":"auth","namespace":"security"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Serialize
			jsonData, err := json.Marshal(tt.dependency)
			require.NoError(t, err)

			// Remove whitespace for comparison
			gotJSON := strings.ReplaceAll(string(jsonData), " ", "")
			assert.Equal(t, tt.wantJSON, gotJSON)

			// Deserialize back
			var parsed StandardizedDependency
			err = json.Unmarshal(jsonData, &parsed)
			require.NoError(t, err)

			assert.Equal(t, tt.dependency.Capability, parsed.Capability)
			assert.Equal(t, tt.dependency.Tags, parsed.Tags)
			assert.Equal(t, tt.dependency.Version, parsed.Version)
			assert.Equal(t, tt.dependency.Namespace, parsed.Namespace)
		})
	}
}

func TestComplexDependencyResolution(t *testing.T) {
	// Mock database with agents providing various capabilities
	mockAgents := []struct {
		AgentID      string
		Capabilities []string
		Tags         []string
		Version      string
		Endpoint     string
	}{
		{
			AgentID:      "date-agent-456",
			Capabilities: []string{"date_service"},
			Tags:         []string{"time", "utility"},
			Version:      "1.2.0",
			Endpoint:     "http://date-agent:8000",
		},
		{
			AgentID:      "system-agent-789",
			Capabilities: []string{"info"},
			Tags:         []string{"system", "general", "disk"},
			Version:      "2.1.0",
			Endpoint:     "http://system-agent:8000",
		},
		{
			AgentID:      "storage-agent-123",
			Capabilities: []string{"storage", "info"},
			Tags:         []string{"system", "disk", "storage"},
			Version:      "1.5.0",
			Endpoint:     "http://storage-agent:8000",
		},
	}

	// Test dependency resolution logic
	dependencies := []StandardizedDependency{
		{
			Capability: "date_service",
		},
		{
			Capability: "info",
			Tags:       []string{"system", "general"},
		},
		{
			Capability: "info",
			Tags:       []string{"system", "disk"},
		},
	}

	// Mock resolution function
	resolveCapability := func(dep StandardizedDependency) *ResolvedDependency {
		for _, agent := range mockAgents {
			// Check if agent provides the capability
			hasCapability := false
			for _, cap := range agent.Capabilities {
				if cap == dep.Capability {
					hasCapability = true
					break
				}
			}
			if !hasCapability {
				continue
			}

			// Check tag matching
			if len(dep.Tags) > 0 {
				tagMatch := false
				for _, reqTag := range dep.Tags {
					for _, agentTag := range agent.Tags {
						if reqTag == agentTag {
							tagMatch = true
							break
						}
					}
					if tagMatch {
						break
					}
				}
				if !tagMatch {
					continue
				}
			}

			// Found a match
			return &ResolvedDependency{
				Capability: dep.Capability,
				MCPToolInfo: map[string]interface{}{
					"name":     "get_" + strings.ReplaceAll(dep.Capability, "_", "_"),
					"endpoint": agent.Endpoint,
					"agent_id": agent.AgentID,
				},
				Status: "resolved",
			}
		}

		// No match found
		return &ResolvedDependency{
			Capability: dep.Capability,
			Status:     "failed",
		}
	}

	// Test resolution
	var resolved []ResolvedDependency
	for _, dep := range dependencies {
		if res := resolveCapability(dep); res != nil {
			resolved = append(resolved, *res)
		}
	}

	// Verify results
	assert.Len(t, resolved, 3)

	// First dependency: date_service
	assert.Equal(t, "date_service", resolved[0].Capability)
	assert.Equal(t, "resolved", resolved[0].Status)
	assert.Equal(t, "date-agent-456", resolved[0].MCPToolInfo["agent_id"])

	// Second dependency: info with system+general tags (should match system-agent)
	assert.Equal(t, "info", resolved[1].Capability)
	assert.Equal(t, "resolved", resolved[1].Status)
	assert.Equal(t, "system-agent-789", resolved[1].MCPToolInfo["agent_id"])

	// Third dependency: info with system+disk tags (should match system-agent or storage-agent)
	assert.Equal(t, "info", resolved[2].Capability)
	assert.Equal(t, "resolved", resolved[2].Status)
	// Could match either system-agent-789 or storage-agent-123
	agentID := resolved[2].MCPToolInfo["agent_id"]
	assert.True(t, agentID == "system-agent-789" || agentID == "storage-agent-123")
}

func TestUnifiedEndpointBehavior(t *testing.T) {
	// Both /agents/register and /heartbeat should accept same request format
	request := DecoratorAgentRequest{
		AgentID:   "test-agent",
		Timestamp: time.Now().Format(time.RFC3339),
		Metadata: DecoratorAgentMetadata{
			Name:      "test-agent",
			AgentType: "mcp_agent",
			Namespace: "default",
			Endpoint:  "stdio://test-agent",
			Version:   "1.0.0",
			Decorators: []DecoratorInfo{
				{
					FunctionName: "test_function",
					Capability:   "test_capability",
					Dependencies: []StandardizedDependency{
						{
							Capability: "date_service",
						},
					},
				},
			},
		},
	}

	// Both endpoints should return same response format
	expectedResponse := DecoratorAgentResponse{
		AgentID:   "test-agent",
		Status:    "success",
		Message:   "Agent registered successfully", // or "Heartbeat received"
		Timestamp: time.Now().Format(time.RFC3339),
		DependenciesResolved: []ResolvedDecorator{
			{
				FunctionName: "test_function",
				Capability:   "test_capability",
				Dependencies: []ResolvedDependency{
					{
						Capability: "date_service",
						MCPToolInfo: map[string]interface{}{
							"name":     "get_current_date",
							"endpoint": "http://date-agent:8000",
							"agent_id": "date-agent-456",
						},
						Status: "resolved",
					},
				},
			},
		},
	}

	// Verify both request and response serialize properly
	requestJSON, err := json.Marshal(request)
	require.NoError(t, err)
	assert.Contains(t, string(requestJSON), "test_function")

	responseJSON, err := json.Marshal(expectedResponse)
	require.NoError(t, err)
	assert.Contains(t, string(responseJSON), "dependencies_resolved")
}
