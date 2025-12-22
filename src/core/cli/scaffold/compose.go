package scaffold

import (
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"text/template"

	"gopkg.in/yaml.v3"
)

// DetectedAgent represents an agent discovered from main.py
type DetectedAgent struct {
	Name     string // From @mesh.agent(name="...")
	Port     int    // From http_port=...
	Dir      string // Directory containing main.py (relative to scan root)
	MainFile string // Full path to main.py
}

// ComposeConfig holds configuration for docker-compose generation
type ComposeConfig struct {
	Agents        []DetectedAgent
	Observability bool   // Include tempo/grafana/redis
	NetworkName   string // Docker network name
	ProjectName   string // Docker compose project name
	Force         bool   // Force regenerate agent configurations
}

// GenerateResult contains information about what happened during generation
type GenerateResult struct {
	WasMerged     bool     // True if we merged with existing file
	AddedAgents   []string // Names of newly added agents
	SkippedAgents []string // Names of agents that already existed (preserved)
}

// ScanForAgents walks the directory tree looking for main.py files with @mesh.agent decorator
func ScanForAgents(dir string) ([]DetectedAgent, error) {
	var agents []DetectedAgent

	// Get absolute path for consistent handling
	absDir, err := filepath.Abs(dir)
	if err != nil {
		return nil, fmt.Errorf("failed to get absolute path: %w", err)
	}

	err = filepath.WalkDir(absDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		// Skip hidden directories
		if d.IsDir() && strings.HasPrefix(d.Name(), ".") {
			return filepath.SkipDir
		}

		// Skip common non-agent directories
		if d.IsDir() {
			switch d.Name() {
			case "node_modules", "__pycache__", "venv", ".venv", "env", ".env", "dist", "build":
				return filepath.SkipDir
			}
		}

		// Look for main.py files
		if d.Name() == "main.py" {
			content, err := os.ReadFile(path)
			if err != nil {
				return nil // Skip unreadable files
			}

			agent, err := parseAgentDecorator(string(content))
			if err != nil || agent == nil {
				return nil // Skip files without @mesh.agent
			}

			// Set directory relative to scan root
			relDir, err := filepath.Rel(absDir, filepath.Dir(path))
			if err != nil {
				relDir = filepath.Dir(path)
			}
			agent.Dir = relDir
			agent.MainFile = path

			agents = append(agents, *agent)
		}
		return nil
	})

	if err != nil {
		return nil, fmt.Errorf("failed to scan directory: %w", err)
	}

	return agents, nil
}

// parseAgentDecorator extracts name and port from @mesh.agent decorator
func parseAgentDecorator(content string) (*DetectedAgent, error) {
	// Pattern to match @mesh.agent decorator (handles multiline)
	// We need to match the decorator and its contents, handling newlines
	agentPattern := regexp.MustCompile(`@mesh\.agent\s*\([\s\S]*?\)`)
	match := agentPattern.FindString(content)
	if match == "" {
		return nil, nil // Not an agent file
	}

	// Extract name - handles both single and double quotes
	namePattern := regexp.MustCompile(`name\s*=\s*["']([^"']+)["']`)
	nameMatch := namePattern.FindStringSubmatch(match)
	if len(nameMatch) < 2 {
		return nil, fmt.Errorf("could not extract agent name from decorator")
	}

	// Extract port (optional, default 9000)
	portPattern := regexp.MustCompile(`http_port\s*=\s*(\d+)`)
	portMatch := portPattern.FindStringSubmatch(match)
	port := 9000 // Default
	if len(portMatch) >= 2 {
		port, _ = strconv.Atoi(portMatch[1])
	}

	return &DetectedAgent{
		Name: nameMatch[1],
		Port: port,
	}, nil
}

// validateAgentPorts checks for port conflicts among agents
func validateAgentPorts(agents []DetectedAgent) error {
	ports := make(map[int]string)
	for _, agent := range agents {
		if existing, ok := ports[agent.Port]; ok {
			return fmt.Errorf("port conflict: %s and %s both use port %d",
				existing, agent.Name, agent.Port)
		}
		ports[agent.Port] = agent.Name
	}
	return nil
}

// GenerateDockerCompose generates a docker-compose.yml file for the given configuration
// If the file already exists, it merges new agents without overwriting existing services
func GenerateDockerCompose(config *ComposeConfig, outputDir string) (*GenerateResult, error) {
	// Validate ports
	if err := validateAgentPorts(config.Agents); err != nil {
		return nil, err
	}

	// Set defaults
	if config.ProjectName == "" {
		// Get absolute path to handle "." properly
		absPath, err := filepath.Abs(outputDir)
		if err == nil {
			config.ProjectName = filepath.Base(absPath)
		} else {
			config.ProjectName = "mcp-mesh"
		}
	}
	if config.NetworkName == "" {
		config.NetworkName = config.ProjectName + "-network"
	}

	outputPath := filepath.Join(outputDir, "docker-compose.yml")

	// Check if file exists
	existingContent, err := os.ReadFile(outputPath)
	fileExists := err == nil

	// If file doesn't exist or force is set, generate fresh
	if !fileExists || config.Force {
		result := &GenerateResult{
			WasMerged:     false,
			AddedAgents:   make([]string, 0, len(config.Agents)),
			SkippedAgents: []string{},
		}
		for _, agent := range config.Agents {
			result.AddedAgents = append(result.AddedAgents, agent.Name)
		}

		if err := generateFreshCompose(config, outputPath); err != nil {
			return nil, err
		}
		return result, nil
	}

	// File exists and force is false - merge new agents
	return mergeAgentsIntoCompose(config, outputPath, existingContent)
}

// generateFreshCompose generates a new docker-compose.yml from template
func generateFreshCompose(config *ComposeConfig, outputPath string) error {
	tmpl, err := template.New("docker-compose").Parse(dockerComposeTemplate)
	if err != nil {
		return fmt.Errorf("failed to parse template: %w", err)
	}

	file, err := os.Create(outputPath)
	if err != nil {
		return fmt.Errorf("failed to create docker-compose.yml: %w", err)
	}
	defer file.Close()

	if err := tmpl.Execute(file, config); err != nil {
		return fmt.Errorf("failed to render template: %w", err)
	}

	return nil
}

// mergeAgentsIntoCompose adds new agents to an existing docker-compose.yml
func mergeAgentsIntoCompose(config *ComposeConfig, outputPath string, existingContent []byte) (*GenerateResult, error) {
	result := &GenerateResult{
		WasMerged:     true,
		AddedAgents:   []string{},
		SkippedAgents: []string{},
	}

	// Parse existing YAML using Node API to preserve structure
	var doc yaml.Node
	if err := yaml.Unmarshal(existingContent, &doc); err != nil {
		return nil, fmt.Errorf("failed to parse existing docker-compose.yml: %w", err)
	}

	// Find the services node
	servicesNode := findServicesNode(&doc)
	if servicesNode == nil {
		return nil, fmt.Errorf("could not find 'services' section in existing docker-compose.yml")
	}

	// Get existing service names
	existingServices := getExistingServiceNames(servicesNode)

	// Determine which agents to add
	var agentsToAdd []DetectedAgent
	for _, agent := range config.Agents {
		if _, exists := existingServices[agent.Name]; exists {
			result.SkippedAgents = append(result.SkippedAgents, agent.Name)
		} else {
			agentsToAdd = append(agentsToAdd, agent)
			result.AddedAgents = append(result.AddedAgents, agent.Name)
		}
	}

	// If no agents to add, just return
	if len(agentsToAdd) == 0 {
		return result, nil
	}

	// Generate YAML for new agent services
	newServicesYAML, err := generateAgentServicesYAML(agentsToAdd, config)
	if err != nil {
		return nil, fmt.Errorf("failed to generate agent services: %w", err)
	}

	// Parse the new services YAML
	var newServicesDoc yaml.Node
	if err := yaml.Unmarshal([]byte(newServicesYAML), &newServicesDoc); err != nil {
		return nil, fmt.Errorf("failed to parse generated services: %w", err)
	}

	// Add new service nodes to existing services
	if newServicesDoc.Kind == yaml.DocumentNode && len(newServicesDoc.Content) > 0 {
		newServicesMap := newServicesDoc.Content[0]
		if newServicesMap.Kind == yaml.MappingNode {
			servicesNode.Content = append(servicesNode.Content, newServicesMap.Content...)
		}
	}

	// Add volumes for new agents
	addVolumesForAgents(&doc, agentsToAdd)

	// Write back the merged document
	var buf bytes.Buffer
	encoder := yaml.NewEncoder(&buf)
	encoder.SetIndent(2)
	if err := encoder.Encode(&doc); err != nil {
		return nil, fmt.Errorf("failed to encode merged docker-compose.yml: %w", err)
	}
	encoder.Close()

	if err := os.WriteFile(outputPath, buf.Bytes(), 0644); err != nil {
		return nil, fmt.Errorf("failed to write docker-compose.yml: %w", err)
	}

	return result, nil
}

// addVolumesForAgents adds named volumes for new agents to the document
func addVolumesForAgents(doc *yaml.Node, agents []DetectedAgent) {
	if doc.Kind != yaml.DocumentNode || len(doc.Content) == 0 {
		return
	}

	root := doc.Content[0]
	if root.Kind != yaml.MappingNode {
		return
	}

	// Find or create volumes section
	var volumesNode *yaml.Node
	var volumesKeyIndex int = -1

	for i := 0; i < len(root.Content)-1; i += 2 {
		if root.Content[i].Value == "volumes" {
			volumesNode = root.Content[i+1]
			volumesKeyIndex = i
			break
		}
	}

	// If volumes section doesn't exist, create it before networks
	if volumesNode == nil {
		volumesNode = &yaml.Node{
			Kind:    yaml.MappingNode,
			Content: []*yaml.Node{},
		}
		volumesKeyNode := &yaml.Node{
			Kind:  yaml.ScalarNode,
			Value: "volumes",
		}

		// Find networks section to insert before it
		networksIndex := -1
		for i := 0; i < len(root.Content)-1; i += 2 {
			if root.Content[i].Value == "networks" {
				networksIndex = i
				break
			}
		}

		if networksIndex >= 0 {
			// Insert before networks
			newContent := make([]*yaml.Node, 0, len(root.Content)+2)
			newContent = append(newContent, root.Content[:networksIndex]...)
			newContent = append(newContent, volumesKeyNode, volumesNode)
			newContent = append(newContent, root.Content[networksIndex:]...)
			root.Content = newContent
		} else {
			// Append at the end
			root.Content = append(root.Content, volumesKeyNode, volumesNode)
		}
		volumesKeyIndex = len(root.Content) - 2
	}

	// Get existing volume names
	existingVolumes := make(map[string]bool)
	if volumesNode.Kind == yaml.MappingNode {
		for i := 0; i < len(volumesNode.Content)-1; i += 2 {
			existingVolumes[volumesNode.Content[i].Value] = true
		}
	}

	// Add new agent volumes
	for _, agent := range agents {
		volumeName := agent.Name + "-packages"
		if !existingVolumes[volumeName] {
			keyNode := &yaml.Node{
				Kind:  yaml.ScalarNode,
				Value: volumeName,
			}
			valueNode := &yaml.Node{
				Kind:  yaml.MappingNode,
				Tag:   "!!map",
				Content: []*yaml.Node{},
			}
			volumesNode.Content = append(volumesNode.Content, keyNode, valueNode)
		}
	}

	// Update the volumes node in root if we modified it
	if volumesKeyIndex >= 0 && volumesKeyIndex+1 < len(root.Content) {
		root.Content[volumesKeyIndex+1] = volumesNode
	}
}

// findServicesNode finds the services mapping node in the document
func findServicesNode(doc *yaml.Node) *yaml.Node {
	if doc.Kind == yaml.DocumentNode && len(doc.Content) > 0 {
		root := doc.Content[0]
		if root.Kind == yaml.MappingNode {
			for i := 0; i < len(root.Content)-1; i += 2 {
				if root.Content[i].Value == "services" {
					return root.Content[i+1]
				}
			}
		}
	}
	return nil
}

// getExistingServiceNames returns a set of existing service names
func getExistingServiceNames(servicesNode *yaml.Node) map[string]bool {
	existing := make(map[string]bool)
	if servicesNode.Kind == yaml.MappingNode {
		for i := 0; i < len(servicesNode.Content)-1; i += 2 {
			existing[servicesNode.Content[i].Value] = true
		}
	}
	return existing
}

// generateAgentServicesYAML generates YAML for agent services only
func generateAgentServicesYAML(agents []DetectedAgent, config *ComposeConfig) (string, error) {
	tmpl, err := template.New("agent-services").Parse(agentServicesTemplate)
	if err != nil {
		return "", err
	}

	data := struct {
		Agents        []DetectedAgent
		ProjectName   string
		NetworkName   string
		Observability bool
	}{
		Agents:        agents,
		ProjectName:   config.ProjectName,
		NetworkName:   config.NetworkName,
		Observability: config.Observability,
	}

	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return "", err
	}

	return buf.String(), nil
}

// agentServicesTemplate generates only the agent service definitions
const agentServicesTemplate = `{{- range .Agents }}
# Agent: {{ .Name }}
# NOTE: In dev mode, entrypoint is overridden to install requirements on startup.
#       In production (Dockerfile), base image ENTRYPOINT ["python"] is used with CMD ["main.py"]
{{ .Name }}:
  image: mcpmesh/python-runtime:0.7
  container_name: {{ $.ProjectName }}-{{ .Name }}
  hostname: {{ .Name }}
  user: root
  ports:
    - "{{ .Port }}:{{ .Port }}"
  volumes:
    - ./{{ .Dir }}:/app:ro
    - {{ .Name }}-packages:/packages
  working_dir: /app
  entrypoint: ["sh", "-c"]
  command: ["chown -R mcp-mesh:mcp-mesh /packages && su mcp-mesh -c 'if [ -f /app/requirements.txt ]; then pip install --target /packages -q -r /app/requirements.txt 2>/dev/null; fi && python main.py'"]
  environment:
    PYTHONPATH: /packages
    MCP_MESH_REGISTRY_URL: http://registry:8000
    AGENT_NAME: {{ .Name }}
    AGENT_PORT: "{{ .Port }}"
    HOST: "0.0.0.0"
    MCP_MESH_HTTP_HOST: {{ .Name }}
    MCP_MESH_HTTP_PORT: "{{ .Port }}"
    POD_IP: {{ .Name }}
    MCP_MESH_HTTP_ENABLED: "true"
    MCP_MESH_AGENT_NAME: {{ .Name }}
    MCP_MESH_ENABLED: "true"
    MCP_MESH_AUTO_RUN: "true"
    MCP_MESH_LOG_LEVEL: DEBUG
    MCP_MESH_DEBUG_MODE: "true"
    PYTHONUNBUFFERED: "1"
{{- if $.Observability }}
    REDIS_URL: redis://redis:6379
    MCP_MESH_DISTRIBUTED_TRACING_ENABLED: "true"
{{- end }}
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{{ .Port }}/health').read()"]
    interval: 5s
    timeout: 3s
    retries: 10
    start_period: 30s
  networks:
    - {{ $.NetworkName }}
{{- end }}`

// dockerComposeTemplate is the embedded template for docker-compose.yml
const dockerComposeTemplate = `# MCP Mesh Development Docker Compose
# Generated by: meshctl scaffold --compose
#
# Usage:
#   docker compose up -d
#
# Services:
#   - postgres: PostgreSQL database for registry
#   - registry: MCP Mesh registry service
{{- if .Observability }}
#   - redis: Redis for state/tracing
#   - tempo: Distributed tracing backend
#   - grafana: Observability dashboard
{{- end }}
{{- range .Agents }}
#   - {{ .Name }}: Agent on port {{ .Port }}
{{- end }}

services:
  # ===== INFRASTRUCTURE =====

  postgres:
    image: postgres:15-alpine
    container_name: {{ .ProjectName }}-postgres
    hostname: postgres
    environment:
      POSTGRES_USER: mcpmesh
      POSTGRES_PASSWORD: mcpmesh
      POSTGRES_DB: mcpmesh
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mcpmesh"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - {{ .NetworkName }}

  registry:
    image: mcpmesh/registry:0.7
    container_name: {{ .ProjectName }}-registry
    hostname: registry
    ports:
      - "8000:8000"
    environment:
      HOST: "0.0.0.0"
      PORT: "8000"
      DATABASE_URL: postgresql://mcpmesh:mcpmesh@postgres:5432/mcpmesh?sslmode=disable
{{- if .Observability }}
      REDIS_URL: redis://redis:6379
{{- end }}
    depends_on:
      postgres:
        condition: service_healthy
{{- if .Observability }}
      redis:
        condition: service_healthy
{{- end }}
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8000/health"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      - {{ .NetworkName }}
{{- if .Observability }}

  # ===== OBSERVABILITY =====

  redis:
    image: redis:7-alpine
    container_name: {{ .ProjectName }}-redis
    hostname: redis
    command: redis-server --appendonly yes
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - {{ .NetworkName }}

  tempo:
    image: grafana/tempo:2.3.1
    container_name: {{ .ProjectName }}-tempo
    hostname: tempo
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml:ro
    ports:
      - "3200:3200"
      - "4317:4317"
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3200/ready"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - {{ .NetworkName }}

  grafana:
    image: grafana/grafana:10.2.0
    container_name: {{ .ProjectName }}-grafana
    hostname: grafana
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
    ports:
      - "3000:3000"
    depends_on:
      tempo:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - {{ .NetworkName }}
{{- end }}
{{- if .Agents }}

  # ===== AGENTS =====
  # NOTE: In dev mode, entrypoint is overridden to install requirements on startup.
  #       In production (Dockerfile), base image ENTRYPOINT ["python"] is used with CMD ["main.py"]
{{- range .Agents }}

  {{ .Name }}:
    image: mcpmesh/python-runtime:0.7
    container_name: {{ $.ProjectName }}-{{ .Name }}
    hostname: {{ .Name }}
    user: root
    ports:
      - "{{ .Port }}:{{ .Port }}"
    volumes:
      - ./{{ .Dir }}:/app:ro
      - {{ .Name }}-packages:/packages
    working_dir: /app
    entrypoint: ["sh", "-c"]
    command: ["chown -R mcp-mesh:mcp-mesh /packages && su mcp-mesh -c 'if [ -f /app/requirements.txt ]; then pip install --target /packages -q -r /app/requirements.txt 2>/dev/null; fi && python main.py'"]
    environment:
      PYTHONPATH: /packages
      MCP_MESH_REGISTRY_URL: http://registry:8000
      AGENT_NAME: {{ .Name }}
      AGENT_PORT: "{{ .Port }}"
      HOST: "0.0.0.0"
      MCP_MESH_HTTP_HOST: {{ .Name }}
      MCP_MESH_HTTP_PORT: "{{ .Port }}"
      POD_IP: {{ .Name }}
      MCP_MESH_HTTP_ENABLED: "true"
      MCP_MESH_AGENT_NAME: {{ .Name }}
      MCP_MESH_ENABLED: "true"
      MCP_MESH_AUTO_RUN: "true"
      MCP_MESH_LOG_LEVEL: DEBUG
      MCP_MESH_DEBUG_MODE: "true"
      PYTHONUNBUFFERED: "1"
{{- if $.Observability }}
      REDIS_URL: redis://redis:6379
      MCP_MESH_DISTRIBUTED_TRACING_ENABLED: "true"
{{- end }}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:{{ .Port }}/health').read()"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 30s
    networks:
      - {{ $.NetworkName }}
{{- end }}
{{- end }}
{{- if .Agents }}

volumes:
{{- range .Agents }}
  {{ .Name }}-packages:
{{- end }}
{{- end }}

networks:
  {{ .NetworkName }}:
    name: {{ .NetworkName }}
    driver: bridge
`
