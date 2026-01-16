package scaffold

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gopkg.in/yaml.v3"
)

func TestGenerateDockerCompose_NewFile(t *testing.T) {
	tmpDir := t.TempDir()

	config := &ComposeConfig{
		Agents: []DetectedAgent{
			{Name: "agent1", Port: 9001, Dir: "agent1", Language: "python"},
			{Name: "agent2", Port: 9002, Dir: "agent2", Language: "python"},
		},
		Observability: false,
		ProjectName:   "test-project",
	}

	result, err := GenerateDockerCompose(config, tmpDir)
	require.NoError(t, err)

	// Should not be a merge
	assert.False(t, result.WasMerged)
	assert.ElementsMatch(t, []string{"agent1", "agent2"}, result.AddedAgents)
	assert.Empty(t, result.SkippedAgents)

	// Verify file was created
	content, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)

	// Check content contains expected services
	assert.Contains(t, string(content), "agent1:")
	assert.Contains(t, string(content), "agent2:")
	assert.Contains(t, string(content), "postgres:")
	assert.Contains(t, string(content), "registry:")
}

func TestGenerateDockerCompose_MergePreservesExisting(t *testing.T) {
	tmpDir := t.TempDir()

	// Create existing docker-compose.yml with one agent and custom config
	existingContent := `# User's custom docker-compose
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: customuser
  registry:
    image: mcpmesh/registry:0.8
  agent1:
    image: mcpmesh/python-runtime:0.8
    container_name: test-agent1
    environment:
      CUSTOM_VAR: "user-added-value"
    ports:
      - "9001:9001"
networks:
  test-network:
    driver: bridge
`
	err := os.WriteFile(filepath.Join(tmpDir, "docker-compose.yml"), []byte(existingContent), 0644)
	require.NoError(t, err)

	// Now run compose with agent1 (existing) and agent2 (new)
	config := &ComposeConfig{
		Agents: []DetectedAgent{
			{Name: "agent1", Port: 9001, Dir: "agent1", Language: "python"},
			{Name: "agent2", Port: 9002, Dir: "agent2", Language: "python"},
		},
		Observability: false,
		ProjectName:   "test",
		NetworkName:   "test-network",
	}

	result, err := GenerateDockerCompose(config, tmpDir)
	require.NoError(t, err)

	// Should be a merge
	assert.True(t, result.WasMerged)
	assert.ElementsMatch(t, []string{"agent2"}, result.AddedAgents)
	assert.ElementsMatch(t, []string{"agent1"}, result.SkippedAgents)

	// Read the merged file
	content, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)
	contentStr := string(content)

	// Verify user's custom POSTGRES_USER was preserved
	assert.Contains(t, contentStr, "customuser")

	// Verify user's CUSTOM_VAR on agent1 was preserved
	assert.Contains(t, contentStr, "CUSTOM_VAR")
	assert.Contains(t, contentStr, "user-added-value")

	// Verify agent2 was added
	assert.Contains(t, contentStr, "agent2:")
}

func TestGenerateDockerCompose_ForceRegenerate(t *testing.T) {
	tmpDir := t.TempDir()

	// Create existing docker-compose.yml with custom agent config
	existingContent := `services:
  postgres:
    image: postgres:15-alpine
  registry:
    image: mcpmesh/registry:0.8
  agent1:
    image: mcpmesh/python-runtime:0.8
    environment:
      CUSTOM_VAR: "should-be-gone"
networks:
  test-network:
    driver: bridge
`
	err := os.WriteFile(filepath.Join(tmpDir, "docker-compose.yml"), []byte(existingContent), 0644)
	require.NoError(t, err)

	// Run with force flag
	config := &ComposeConfig{
		Agents: []DetectedAgent{
			{Name: "agent1", Port: 9001, Dir: "agent1", Language: "python"},
		},
		Observability: false,
		ProjectName:   "test",
		Force:         true,
	}

	result, err := GenerateDockerCompose(config, tmpDir)
	require.NoError(t, err)

	// Should not be a merge (force regenerates)
	assert.False(t, result.WasMerged)
	assert.ElementsMatch(t, []string{"agent1"}, result.AddedAgents)

	// Read the regenerated file
	content, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)
	contentStr := string(content)

	// Custom var should be gone
	assert.NotContains(t, contentStr, "CUSTOM_VAR")
	assert.NotContains(t, contentStr, "should-be-gone")
}

func TestGenerateDockerCompose_NoNewAgents(t *testing.T) {
	tmpDir := t.TempDir()

	// Create existing docker-compose.yml with agent1
	existingContent := `services:
  postgres:
    image: postgres:15-alpine
  registry:
    image: mcpmesh/registry:0.8
  agent1:
    image: mcpmesh/python-runtime:0.8
    environment:
      CUSTOM_VAR: "preserved"
networks:
  test-network:
    driver: bridge
`
	err := os.WriteFile(filepath.Join(tmpDir, "docker-compose.yml"), []byte(existingContent), 0644)
	require.NoError(t, err)

	// Run with same agent
	config := &ComposeConfig{
		Agents: []DetectedAgent{
			{Name: "agent1", Port: 9001, Dir: "agent1"},
		},
		Observability: false,
		ProjectName:   "test",
	}

	result, err := GenerateDockerCompose(config, tmpDir)
	require.NoError(t, err)

	// Should be a merge with no additions
	assert.True(t, result.WasMerged)
	assert.Empty(t, result.AddedAgents)
	assert.ElementsMatch(t, []string{"agent1"}, result.SkippedAgents)

	// File should be unchanged (user's CUSTOM_VAR preserved)
	content, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)
	assert.Contains(t, string(content), "CUSTOM_VAR")
	assert.Contains(t, string(content), "preserved")
}

func TestGenerateDockerCompose_InfrastructureNeverOverwritten(t *testing.T) {
	tmpDir := t.TempDir()

	// Create existing docker-compose.yml with custom postgres config
	existingContent := `services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: myspecialuser
      POSTGRES_PASSWORD: mysecretpassword
  registry:
    image: mcpmesh/registry:custom-tag
    environment:
      CUSTOM_REGISTRY_CONFIG: "true"
networks:
  my-network:
    driver: bridge
`
	err := os.WriteFile(filepath.Join(tmpDir, "docker-compose.yml"), []byte(existingContent), 0644)
	require.NoError(t, err)

	// Add a new agent
	config := &ComposeConfig{
		Agents: []DetectedAgent{
			{Name: "new-agent", Port: 9001, Dir: "new-agent", Language: "python"},
		},
		Observability: false,
		ProjectName:   "test",
		NetworkName:   "my-network",
	}

	result, err := GenerateDockerCompose(config, tmpDir)
	require.NoError(t, err)

	assert.True(t, result.WasMerged)
	assert.ElementsMatch(t, []string{"new-agent"}, result.AddedAgents)

	// Read the merged file
	content, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)
	contentStr := string(content)

	// User's custom postgres config should be preserved
	assert.Contains(t, contentStr, "myspecialuser")
	assert.Contains(t, contentStr, "mysecretpassword")

	// User's custom registry config should be preserved
	assert.Contains(t, contentStr, "custom-tag")
	assert.Contains(t, contentStr, "CUSTOM_REGISTRY_CONFIG")

	// New agent should be added
	assert.Contains(t, contentStr, "new-agent:")
}

func TestFindServicesNode(t *testing.T) {
	tests := []struct {
		name      string
		yamlInput string
		hasNode   bool
	}{
		{
			name:      "valid docker-compose",
			yamlInput: "services:\n  postgres:\n    image: postgres\n",
			hasNode:   true,
		},
		{
			name:      "empty services",
			yamlInput: "services:\n",
			hasNode:   true,
		},
		{
			name:      "no services key",
			yamlInput: "version: '3'\n",
			hasNode:   false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var doc yaml.Node
			err := yaml.Unmarshal([]byte(tt.yamlInput), &doc)
			require.NoError(t, err)

			node := findServicesNode(&doc)
			if tt.hasNode {
				assert.NotNil(t, node)
			} else {
				assert.Nil(t, node)
			}
		})
	}
}

func TestGetExistingServiceNames(t *testing.T) {
	yamlContent := `services:
  postgres:
    image: postgres
  redis:
    image: redis
  my-agent:
    image: agent
`
	var doc yaml.Node
	err := yaml.Unmarshal([]byte(yamlContent), &doc)
	require.NoError(t, err)

	servicesNode := findServicesNode(&doc)
	require.NotNil(t, servicesNode)

	names := getExistingServiceNames(servicesNode)
	assert.True(t, names["postgres"])
	assert.True(t, names["redis"])
	assert.True(t, names["my-agent"])
	assert.False(t, names["nonexistent"])
}

func TestGenerateAgentServicesYAML(t *testing.T) {
	agents := []DetectedAgent{
		{Name: "test-agent", Port: 9001, Dir: "test-agent", Language: "python"},
	}

	config := &ComposeConfig{
		ProjectName:   "myproject",
		NetworkName:   "mynetwork",
		Observability: false,
	}

	yamlStr, err := generateAgentServicesYAML(agents, config)
	require.NoError(t, err)

	assert.Contains(t, yamlStr, "test-agent:")
	assert.Contains(t, yamlStr, "container_name: myproject-test-agent")
	assert.Contains(t, yamlStr, "mynetwork")
	assert.Contains(t, yamlStr, "9001:9001")
}

func TestGenerateAgentServicesYAML_WithObservability(t *testing.T) {
	agents := []DetectedAgent{
		{Name: "test-agent", Port: 9001, Dir: "test-agent", Language: "python"},
	}

	config := &ComposeConfig{
		ProjectName:   "myproject",
		NetworkName:   "mynetwork",
		Observability: true,
	}

	yamlStr, err := generateAgentServicesYAML(agents, config)
	require.NoError(t, err)

	assert.Contains(t, yamlStr, "REDIS_URL: redis://redis:6379")
	assert.Contains(t, yamlStr, "MCP_MESH_DISTRIBUTED_TRACING_ENABLED")
}

func TestValidateAgentPorts_Conflict(t *testing.T) {
	agents := []DetectedAgent{
		{Name: "agent1", Port: 9001},
		{Name: "agent2", Port: 9001}, // Same port
	}

	err := validateAgentPorts(agents)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "port conflict")
}

func TestValidateAgentPorts_NoConflict(t *testing.T) {
	agents := []DetectedAgent{
		{Name: "agent1", Port: 9001},
		{Name: "agent2", Port: 9002},
	}

	err := validateAgentPorts(agents)
	require.NoError(t, err)
}
