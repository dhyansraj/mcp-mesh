package scaffold

import (
	"bytes"
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
    image: mcpmesh/registry:3.7.1
  agent1:
    image: mcpmesh/python-runtime:3.7.1
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
    image: mcpmesh/registry:3.7.1
  agent1:
    image: mcpmesh/python-runtime:3.7.1
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
    image: mcpmesh/registry:3.7.1
  agent1:
    image: mcpmesh/python-runtime:3.7.1
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

// scaffoldAPIGateway renders a real `meshctl scaffold api` agent from the
// in-repo templates into outputDir, so detection is tested against what the
// scaffold actually emits rather than a hand-written fixture.
func scaffoldAPIGateway(t *testing.T, outputDir, lang, name string, port int) {
	t.Helper()
	t.Setenv("MESHCTL_TEMPLATE_DIR", getProjectRoot()+"/cmd/meshctl/templates")
	cmd := newScaffoldAPICommand()
	out := bytes.NewBufferString("")
	cmd.SetOut(out)
	cmd.SetErr(out)
	cmd.SetArgs([]string{
		"--name", name, "--lang", lang, "--port", itoa(port),
		"--output", outputDir, "--no-interactive",
	})
	require.NoError(t, cmd.Execute(), "scaffold api --lang %s failed:\n%s", lang, out.String())
}

// TestScanForAgents_DetectsAPIGateways covers #1575: `meshctl scaffold
// --compose` only recognised @mesh.agent / mesh(server, ...) / @MeshAgent,
// so every `meshctl scaffold api` gateway was silently left out of the
// generated docker-compose.yml.
func TestScanForAgents_DetectsAPIGateways(t *testing.T) {
	tmpDir := t.TempDir()
	scaffoldAPIGateway(t, tmpDir, "python", "gw-py", 9301)
	scaffoldAPIGateway(t, tmpDir, "typescript", "gw-ts", 9302)
	scaffoldAPIGateway(t, tmpDir, "java", "gw-java", 9303)
	writePyAgent(t, tmpDir, "tool-agent", 9304)

	agents, err := ScanForAgents(tmpDir)
	require.NoError(t, err)

	got := map[string]DetectedAgent{}
	for _, a := range agents {
		got[a.Name] = a
	}
	require.Len(t, got, 4, "expected 3 gateways + 1 tool agent, got %+v", agents)

	for _, want := range []DetectedAgent{
		{Name: "gw-py", Port: 9301, Language: "python", Dir: "gw-py"},
		{Name: "gw-ts", Port: 9302, Language: "typescript", Dir: "gw-ts"},
		{Name: "gw-java", Port: 9303, Language: "java", Dir: "gw-java"},
		{Name: "tool-agent", Port: 9304, Language: "python", Dir: "tool-agent"},
	} {
		a, ok := got[want.Name]
		require.True(t, ok, "agent %s not detected", want.Name)
		assert.Equal(t, want.Port, a.Port, want.Name)
		assert.Equal(t, want.Language, a.Language, want.Name)
		assert.Equal(t, want.Dir, a.Dir, want.Name)
	}

	// And the generated compose file carries a service for each of them.
	_, err = GenerateDockerCompose(&ComposeConfig{Agents: agents, ProjectName: "t"}, tmpDir)
	require.NoError(t, err)
	content, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)
	var parsed map[string]interface{}
	require.NoError(t, yaml.Unmarshal(content, &parsed))
	services, ok := parsed["services"].(map[string]interface{})
	require.True(t, ok, "compose file has no services map")
	for _, name := range []string{"gw-py", "gw-ts", "gw-java", "tool-agent"} {
		assert.Contains(t, services, name)
	}
}

// TestNextAvailablePort_CountsAPIGateways: auto-port assignment shares the
// scanner, so an undetected gateway used to let the next scaffold reuse its port.
func TestNextAvailablePort_CountsAPIGateways(t *testing.T) {
	tmpDir := t.TempDir()
	scaffoldAPIGateway(t, tmpDir, "typescript", "gw-ts", 9400)
	assert.Equal(t, 9401, NextAvailablePort(tmpDir))
}

func TestParsePythonAPIAgent(t *testing.T) {
	t.Run("route_with_uvicorn_port", func(t *testing.T) {
		src := "import mesh\n@app.get('/x')\n@mesh.route(dependencies=['a'])\nasync def x(): ...\n" +
			"if __name__ == '__main__':\n    uvicorn.run(app, host='0.0.0.0', port=9010)\n"
		a := parsePythonAPIAgent(src, "/tmp/some/gw")
		require.NotNil(t, a)
		assert.Equal(t, "gw", a.Name)
		assert.Equal(t, 9010, a.Port)
		assert.Equal(t, "python", a.Language)
	})
	t.Run("no_uvicorn_leaves_port_unknown", func(t *testing.T) {
		a := parsePythonAPIAgent("@mesh.route(dependencies=['a'])\ndef x(): ...\n", "/tmp/gw")
		require.NotNil(t, a)
		assert.Equal(t, 0, a.Port, "an unreadable port must not be guessed")
	})
	t.Run("env_var_with_default", func(t *testing.T) {
		for _, call := range []string{
			`uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "9000")))`,
			`uvicorn.run(app, port=int(os.environ.get('PORT', 9001)))`,
		} {
			a := parsePythonAPIAgent("@mesh.route(dependencies=['a'])\ndef x(): ...\n"+call+"\n", "/tmp/gw")
			require.NotNil(t, a)
			assert.Contains(t, []int{9000, 9001}, a.Port, call)
		}
	})
	t.Run("env_var_without_default_is_unknown", func(t *testing.T) {
		a := parsePythonAPIAgent("@mesh.route(dependencies=['a'])\ndef x(): ...\nuvicorn.run(app, port=int(os.environ['PORT']))\n", "/tmp/gw")
		require.NotNil(t, a)
		assert.Equal(t, 0, a.Port)
	})
	t.Run("commented_and_docstring_uvicorn_calls_are_ignored", func(t *testing.T) {
		src := "\"\"\"Run with:\n    uvicorn.run(app, port=7000)\n@mesh.route is used below\n\"\"\"\n" +
			"@mesh.route(dependencies=['a'])\ndef x(): ...\n" +
			"# uvicorn.run(app, port=7001)\n" +
			"uvicorn.run(app, port=9002)\n"
		a := parsePythonAPIAgent(src, "/tmp/gw")
		require.NotNil(t, a)
		assert.Equal(t, 9002, a.Port)
	})
	t.Run("route_only_in_docstring_is_not_a_gateway", func(t *testing.T) {
		src := "\"\"\"\nThis module could use @mesh.route(dependencies=['a']).\n\"\"\"\nprint('hi')\n"
		assert.Nil(t, parsePythonAPIAgent(src, "/tmp/x"))
	})
	t.Run("commented_route_is_not_a_gateway", func(t *testing.T) {
		assert.Nil(t, parsePythonAPIAgent("# @mesh.route(dependencies=['a'])\nprint('hi')\n", "/tmp/x"))
	})
	t.Run("plain_script_is_not_a_gateway", func(t *testing.T) {
		assert.Nil(t, parsePythonAPIAgent("print('hello')\n", "/tmp/x"))
	})
}

func TestParseTypeScriptAPIAgent(t *testing.T) {
	t.Run("env_port_default", func(t *testing.T) {
		src := "const PORT = process.env.PORT || 9020;\napp.get('/x', mesh.route([{ capability: 'a' }], async () => {}));\n"
		a := parseTypeScriptAPIAgent(src, "/tmp/gw-ts")
		require.NotNil(t, a)
		assert.Equal(t, "gw-ts", a.Name)
		assert.Equal(t, 9020, a.Port)
		assert.Equal(t, "typescript", a.Language)
	})
	t.Run("listen_literal_port", func(t *testing.T) {
		src := "app.get('/x', mesh.route([{ capability: 'a' }], h));\napp.listen(9021);\n"
		a := parseTypeScriptAPIAgent(src, "/tmp/gw-ts")
		require.NotNil(t, a)
		assert.Equal(t, 9021, a.Port)
	})
	t.Run("comment_only_mentions_are_ignored", func(t *testing.T) {
		src := "/**\n * consumes capabilities via mesh.route().\n */\n// app.get('/x', mesh.route([], h));\n"
		assert.Nil(t, parseTypeScriptAPIAgent(src, "/tmp/x"))
	})
	t.Run("port_expression_variants", func(t *testing.T) {
		route := "app.get('/x', mesh.route([{ capability: 'a' }], h));\n"
		for expr, want := range map[string]int{
			`const PORT = process.env.PORT || "3000";`:           3000,
			`const PORT = process.env.PORT ?? 3001;`:             3001,
			`const PORT = Number(process.env.PORT) || 3002;`:     3002,
			`const PORT = parseInt(process.env.PORT || '3003');`: 3003,
		} {
			a := parseTypeScriptAPIAgent(expr+"\n"+route, "/tmp/gw-ts")
			require.NotNil(t, a, expr)
			assert.Equal(t, want, a.Port, expr)
		}
	})
	t.Run("no_literal_port_is_unknown", func(t *testing.T) {
		src := "const PORT = process.env.PORT;\napp.get('/x', mesh.route([{ capability: 'a' }], h));\napp.listen(PORT);\n"
		a := parseTypeScriptAPIAgent(src, "/tmp/gw-ts")
		require.NotNil(t, a)
		assert.Equal(t, 0, a.Port)
	})
	t.Run("commented_port_is_ignored", func(t *testing.T) {
		src := "// const PORT = process.env.PORT || 4000;\napp.get('/x', mesh.route([{ capability: 'a' }], h));\n"
		a := parseTypeScriptAPIAgent(src, "/tmp/gw-ts")
		require.NotNil(t, a)
		assert.Equal(t, 0, a.Port)
	})
}

func TestParseJavaAgent_APIGatewayPortSources(t *testing.T) {
	writeJava := func(t *testing.T, dir, body string) {
		t.Helper()
		pkg := filepath.Join(dir, "src", "main", "java", "com", "example")
		require.NoError(t, os.MkdirAll(pkg, 0755))
		require.NoError(t, os.WriteFile(filepath.Join(pkg, "App.java"), []byte(body), 0644))
	}
	writeResource := func(t *testing.T, dir, file, body string) {
		t.Helper()
		res := filepath.Join(dir, "src", "main", "resources")
		require.NoError(t, os.MkdirAll(res, 0755))
		require.NoError(t, os.WriteFile(filepath.Join(res, file), []byte(body), 0644))
	}
	route := "class C {\n    @GetMapping(\"/x\")\n    @MeshRoute(dependencies = @MeshDependency(capability = \"a\"))\n    public void x() {}\n}\n"

	t.Run("properties_port", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-props")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.properties", "server.port=9031\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, "gw-props", a.Name)
		assert.Equal(t, 9031, a.Port)
		assert.Equal(t, "java", a.Language)
	})
	t.Run("properties_placeholder_port", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-ph")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.properties", "spring.application.name=x\nserver.port=${PORT:9034}\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, 9034, a.Port)
	})
	t.Run("yaml_other_port_keys_before_server_are_ignored", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-other")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.yml",
			"spring:\n  data:\n    redis:\n      port: 6379\nmanagement:\n  server:\n    port: 9999\nserver:\n  port: ${MCP_MESH_HTTP_PORT:9035}\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, 9035, a.Port)
	})
	t.Run("yaml_flat_server_port_key", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-flat")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.yml", "management.server.port: 9998\nserver.port: 9036\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, 9036, a.Port)
	})
	t.Run("yaml_without_server_port_falls_through_to_properties", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-fall")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.yml", "spring:\n  data:\n    redis:\n      port: 6379\n")
		writeResource(t, dir, "application.properties", "server.port=9037\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, 9037, a.Port)
	})
	t.Run("no_server_port_anywhere_is_unknown", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-none")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.yml", "redis:\n  port: 6379\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, 0, a.Port)
	})
	t.Run("plain_yaml_port", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "gw-yaml")
		writeJava(t, dir, route)
		writeResource(t, dir, "application.yaml", "server:\n  port: 9032\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, 9032, a.Port)
	})
	t.Run("javadoc_mention_is_not_a_gateway", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "plain")
		writeJava(t, dir, "/**\n * Uses @MeshRoute elsewhere.\n */\nclass C {}\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		assert.Nil(t, a)
	})
	t.Run("mesh_agent_still_wins", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "dir-name")
		writeJava(t, dir, "@MeshAgent(name = \"real-name\", port = 9033)\nclass C {}\n")
		a, err := parseJavaAgent(dir)
		require.NoError(t, err)
		require.NotNil(t, a)
		assert.Equal(t, "real-name", a.Name)
		assert.Equal(t, 9033, a.Port)
	})
}

// TestScanForAgents_UnparseableGatewayIsSkippedNotGuessed: a gateway whose
// port can't be read used to fall back to 8080, which collides with a real
// 8080 agent and fails the whole compose run. It must be reported and left out.
func TestScanForAgents_UnparseableGatewayIsSkippedNotGuessed(t *testing.T) {
	tmpDir := t.TempDir()
	writePyAgent(t, tmpDir, "tool-agent", 8080)
	gw := filepath.Join(tmpDir, "gw-env")
	require.NoError(t, os.MkdirAll(gw, 0755))
	require.NoError(t, os.WriteFile(filepath.Join(gw, "main.py"), []byte(
		"import os\nimport mesh\n@app.get('/x')\n@mesh.route(dependencies=['a'])\nasync def x(): ...\n"+
			"uvicorn.run(app, port=int(os.environ['PORT']))\n"), 0644))

	agents, skipped, err := ScanForAgentsWithSkipped(tmpDir)
	require.NoError(t, err)
	require.Len(t, agents, 1)
	assert.Equal(t, "tool-agent", agents[0].Name)
	require.Len(t, skipped, 1)
	assert.Equal(t, "gw-env", skipped[0].Dir)
	assert.Equal(t, "python", skipped[0].Language)
	assert.Contains(t, skipped[0].PortHint, "uvicorn.run")

	_, err = GenerateDockerCompose(&ComposeConfig{Agents: agents, ProjectName: "t"}, tmpDir)
	require.NoError(t, err, "compose must still succeed with the gateway skipped")

	// Auto-port ignores it too rather than counting a guessed 8080.
	assert.Equal(t, 8081, NextAvailablePort(tmpDir))
}

func TestValidateAgentNames(t *testing.T) {
	t.Run("duplicate_service_name", func(t *testing.T) {
		err := validateAgentNames([]DetectedAgent{
			{Name: "gateway", Dir: "a/gateway", Port: 8080},
			{Name: "gateway", Dir: "b/gateway", Port: 8081},
		})
		require.Error(t, err)
		assert.Contains(t, err.Error(), `a/gateway/ and b/gateway/ both resolve to service "gateway"`)
	})
	t.Run("infrastructure_name", func(t *testing.T) {
		err := validateAgentNames([]DetectedAgent{{Name: "registry", Dir: "registry", Port: 8080}})
		require.Error(t, err)
		assert.Contains(t, err.Error(), `resolves to service "registry"`)
	})
	t.Run("distinct_names_pass", func(t *testing.T) {
		require.NoError(t, validateAgentNames([]DetectedAgent{
			{Name: "a", Dir: "a", Port: 8080}, {Name: "b", Dir: "b", Port: 8081},
		}))
	})
}

// TestGenerateDockerCompose_DuplicateGatewayDirsFail: two gateways in
// same-named directories under different parents used to emit one service.
func TestGenerateDockerCompose_DuplicateGatewayDirsFail(t *testing.T) {
	tmpDir := t.TempDir()
	scaffoldAPIGateway(t, filepath.Join(tmpDir, "team-a"), "python", "gateway", 9601)
	scaffoldAPIGateway(t, filepath.Join(tmpDir, "team-b"), "typescript", "gateway", 9602)

	agents, err := ScanForAgents(tmpDir)
	require.NoError(t, err)
	_, err = GenerateDockerCompose(&ComposeConfig{Agents: agents, ProjectName: "t"}, tmpDir)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "service name conflict")
	assert.NoFileExists(t, filepath.Join(tmpDir, "docker-compose.yml"))
}

func TestPublishedHostPorts(t *testing.T) {
	src := "services:\n" +
		"  a:\n    ports:\n      - \"8080:8080\"\n      - \"127.0.0.1:9090:90/tcp\"\n      - \"7000\"\n" +
		"  b:\n    ports:\n      - target: 80\n        published: 8443\n" +
		"  c:\n    image: x\n"
	var doc yaml.Node
	require.NoError(t, yaml.Unmarshal([]byte(src), &doc))
	got := publishedHostPorts(findServicesNode(&doc))
	assert.Equal(t, map[int]string{8080: "a", 9090: "a", 8443: "b"}, got)
}

// TestGenerateDockerCompose_MergeRejectsHostPortClash: on merge, a new agent
// whose port an existing service already publishes fails with a clear error
// instead of producing a file that only fails at `docker compose up`.
func TestGenerateDockerCompose_MergeRejectsHostPortClash(t *testing.T) {
	tmpDir := t.TempDir()
	existing := "services:\n  mesh-ui:\n    image: mcpmesh/mesh-ui\n    ports:\n      - \"3080:3080\"\n"
	require.NoError(t, os.WriteFile(filepath.Join(tmpDir, "docker-compose.yml"), []byte(existing), 0644))

	_, err := GenerateDockerCompose(&ComposeConfig{
		Agents:      []DetectedAgent{{Name: "new-agent", Dir: "new-agent", Port: 3080, Language: "python"}},
		ProjectName: "t",
	}, tmpDir)
	require.Error(t, err)
	assert.Contains(t, err.Error(), `new agent new-agent (in new-agent/) uses host port 3080, which service "mesh-ui"`)

	after, err := os.ReadFile(filepath.Join(tmpDir, "docker-compose.yml"))
	require.NoError(t, err)
	assert.Equal(t, existing, string(after), "a rejected merge must not touch the file")
}

// TestGenerateDockerCompose_DryRun: no files are written; the YAML goes to DryRunOut.
func TestGenerateDockerCompose_DryRun(t *testing.T) {
	tmpDir := t.TempDir()
	var out bytes.Buffer
	_, err := GenerateDockerCompose(&ComposeConfig{
		Agents:        []DetectedAgent{{Name: "a1", Dir: "a1", Port: 9701, Language: "python"}},
		ProjectName:   "t",
		Observability: true,
		DryRun:        true,
		DryRunOut:     &out,
	}, tmpDir)
	require.NoError(t, err)
	assert.Contains(t, out.String(), "a1:")
	assert.NoFileExists(t, filepath.Join(tmpDir, "docker-compose.yml"))
	assert.NoFileExists(t, filepath.Join(tmpDir, "tempo.yaml"))
}
