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

// DetectedAgent represents an agent discovered from main.py or src/index.ts
type DetectedAgent struct {
	Name     string // From @mesh.agent(name="...") or mesh(server, {name: "..."})
	Port     int    // From http_port=... or httpPort: ...
	Dir      string // Directory containing main.py or src/index.ts (relative to scan root)
	MainFile string // Full path to main.py or src/index.ts
	Language string // "python" or "typescript"
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

// ScanForAgents walks the directory tree looking for Python and TypeScript agent files
// Python: main.py with @mesh.agent decorator
// TypeScript: src/index.ts with mesh(server, {...}) call
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

		// Look for Python agents (main.py with @mesh.agent)
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

		// Look for TypeScript agents (src/index.ts with mesh(...))
		if d.Name() == "index.ts" && strings.HasSuffix(filepath.Dir(path), "src") {
			content, err := os.ReadFile(path)
			if err != nil {
				return nil // Skip unreadable files
			}

			agent, err := parseTypeScriptAgent(string(content))
			if err != nil || agent == nil {
				return nil // Skip files without mesh() call
			}

			// For TypeScript, the agent dir is parent of 'src' (where package.json lives)
			srcDir := filepath.Dir(path)
			agentDir := filepath.Dir(srcDir)
			relDir, err := filepath.Rel(absDir, agentDir)
			if err != nil {
				relDir = agentDir
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
		Name:     nameMatch[1],
		Port:     port,
		Language: "python",
	}, nil
}

// parseTypeScriptAgent extracts name and port from TypeScript mesh() call
func parseTypeScriptAgent(content string) (*DetectedAgent, error) {
	// Pattern to match mesh(server, { ... }) call (handles multiline)
	// TypeScript SDK uses: mesh(server, { name: "...", httpPort: ... })
	meshPattern := regexp.MustCompile(`mesh\s*\(\s*\w+\s*,\s*\{[\s\S]*?\}\s*\)`)
	match := meshPattern.FindString(content)
	if match == "" {
		return nil, nil // Not an agent file
	}

	// Extract name - handles both single and double quotes
	namePattern := regexp.MustCompile(`name\s*:\s*["']([^"']+)["']`)
	nameMatch := namePattern.FindStringSubmatch(match)
	if len(nameMatch) < 2 {
		return nil, fmt.Errorf("could not extract agent name from mesh() call")
	}

	// Extract httpPort (optional, default 9000)
	portPattern := regexp.MustCompile(`httpPort\s*:\s*(\d+)`)
	portMatch := portPattern.FindStringSubmatch(match)
	port := 9000 // Default
	if len(portMatch) >= 2 {
		port, _ = strconv.Atoi(portMatch[1])
	}

	return &DetectedAgent{
		Name:     nameMatch[1],
		Port:     port,
		Language: "typescript",
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

	// Generate observability configs if observability is enabled
	if config.Observability {
		outputDir := filepath.Dir(outputPath)
		if err := generateTempoConfig(outputDir); err != nil {
			return fmt.Errorf("failed to generate tempo.yaml: %w", err)
		}
		if err := generateGrafanaConfig(outputDir); err != nil {
			return fmt.Errorf("failed to generate grafana configs: %w", err)
		}
	}

	return nil
}

// mergeAgentsIntoCompose adds new agents to an existing docker-compose.yml
// Also adds observability stack if --observability flag is set
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

	// Add observability stack if requested and not already present
	if config.Observability {
		if err := addObservabilityToExisting(&doc, servicesNode, existingServices, config); err != nil {
			return nil, fmt.Errorf("failed to add observability: %w", err)
		}

		// Generate observability configs if observability is enabled
		outputDir := filepath.Dir(outputPath)
		if err := generateTempoConfig(outputDir); err != nil {
			return nil, fmt.Errorf("failed to generate tempo.yaml: %w", err)
		}
		if err := generateGrafanaConfig(outputDir); err != nil {
			return nil, fmt.Errorf("failed to generate grafana configs: %w", err)
		}
	}

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

	// Generate YAML for new agent services (if any)
	if len(agentsToAdd) > 0 {
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
	}

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

// addObservabilityToExisting adds observability services and updates existing services with tracing env vars
func addObservabilityToExisting(doc *yaml.Node, servicesNode *yaml.Node, existingServices map[string]bool, config *ComposeConfig) error {
	// Check which observability services need to be added
	needsRedis := !existingServices["redis"]
	needsTempo := !existingServices["tempo"]
	needsGrafana := !existingServices["grafana"]

	// Add missing observability services
	if needsRedis || needsTempo || needsGrafana {
		obsServicesYAML := generateObservabilityServicesYAML(config, needsRedis, needsTempo, needsGrafana)
		if obsServicesYAML != "" {
			var obsDoc yaml.Node
			if err := yaml.Unmarshal([]byte(obsServicesYAML), &obsDoc); err != nil {
				return fmt.Errorf("failed to parse observability services: %w", err)
			}
			if obsDoc.Kind == yaml.DocumentNode && len(obsDoc.Content) > 0 {
				obsMap := obsDoc.Content[0]
				if obsMap.Kind == yaml.MappingNode {
					servicesNode.Content = append(servicesNode.Content, obsMap.Content...)
				}
			}
		}
	}

	// Add observability volumes if tempo is being added or exists
	if needsTempo || existingServices["tempo"] {
		addObservabilityVolumes(doc)
	}

	// Update existing registry with tracing env vars
	if existingServices["registry"] {
		addTracingEnvVarsToService(servicesNode, "registry", registryTracingEnvVars)
		addDependencyToService(servicesNode, "registry", "tempo")
	}

	// Update existing agents with tracing env vars (look for services that aren't infrastructure)
	infrastructureServices := map[string]bool{
		"postgres": true, "registry": true, "redis": true,
		"tempo": true, "grafana": true, "prometheus": true,
	}
	for serviceName := range existingServices {
		if !infrastructureServices[serviceName] {
			addTracingEnvVarsToService(servicesNode, serviceName, agentTracingEnvVars)
		}
	}

	return nil
}

// Registry tracing environment variables
var registryTracingEnvVars = map[string]string{
	"REDIS_URL":                           "redis://redis:6379",
	"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "true",
	"TRACE_EXPORTER_TYPE":                 "otlp",
	"TELEMETRY_ENDPOINT":                  "tempo:4317",
	"TELEMETRY_PROTOCOL":                  "grpc",
	"TEMPO_URL":                           "http://tempo:3200",
}

// Agent tracing environment variables
var agentTracingEnvVars = map[string]string{
	"REDIS_URL":                           "redis://redis:6379",
	"MCP_MESH_DISTRIBUTED_TRACING_ENABLED": "true",
}

// addTracingEnvVarsToService adds tracing environment variables to an existing service
// It preserves any existing environment variables the user has added
// Handles both mapping-style (KEY: value) and list-style (- KEY=value) environment formats
func addTracingEnvVarsToService(servicesNode *yaml.Node, serviceName string, envVars map[string]string) {
	if servicesNode.Kind != yaml.MappingNode {
		return
	}

	// Find the service
	for i := 0; i < len(servicesNode.Content)-1; i += 2 {
		if servicesNode.Content[i].Value == serviceName {
			serviceNode := servicesNode.Content[i+1]
			if serviceNode.Kind != yaml.MappingNode {
				continue
			}

			// Find or create environment section
			var envNode *yaml.Node
			for j := 0; j < len(serviceNode.Content)-1; j += 2 {
				if serviceNode.Content[j].Value == "environment" {
					envNode = serviceNode.Content[j+1]
					break
				}
			}

			// If no environment section, create one (default to mapping style)
			if envNode == nil {
				envKeyNode := &yaml.Node{Kind: yaml.ScalarNode, Value: "environment"}
				envNode = &yaml.Node{Kind: yaml.MappingNode, Content: []*yaml.Node{}}
				serviceNode.Content = append(serviceNode.Content, envKeyNode, envNode)
			}

			// Get existing env var names (handle both mapping and sequence styles)
			existingEnvVars := make(map[string]bool)

			if envNode.Kind == yaml.MappingNode {
				// Mapping style: KEY: value
				for k := 0; k < len(envNode.Content)-1; k += 2 {
					existingEnvVars[envNode.Content[k].Value] = true
				}
			} else if envNode.Kind == yaml.SequenceNode {
				// List style: - KEY=value
				for _, item := range envNode.Content {
					if item.Kind == yaml.ScalarNode {
						// Parse KEY=value format
						if eqIdx := strings.Index(item.Value, "="); eqIdx > 0 {
							key := item.Value[:eqIdx]
							existingEnvVars[key] = true
						}
					}
				}
			}

			// Add new env vars (only if they don't already exist)
			for key, value := range envVars {
				if !existingEnvVars[key] {
					if envNode.Kind == yaml.MappingNode {
						// Mapping style: add key and value as separate nodes
						keyNode := &yaml.Node{Kind: yaml.ScalarNode, Value: key}
						valueNode := &yaml.Node{Kind: yaml.ScalarNode, Value: value}
						envNode.Content = append(envNode.Content, keyNode, valueNode)
					} else if envNode.Kind == yaml.SequenceNode {
						// List style: add as "KEY=value" scalar
						entryNode := &yaml.Node{Kind: yaml.ScalarNode, Value: key + "=" + value}
						envNode.Content = append(envNode.Content, entryNode)
					}
				}
			}
			break
		}
	}
}

// addDependencyToService adds a depends_on entry for the specified dependency
// Handles both mapping-style (service: condition) and list-style (- service) formats
func addDependencyToService(servicesNode *yaml.Node, serviceName string, dependency string) {
	if servicesNode.Kind != yaml.MappingNode {
		return
	}

	// Find the service
	for i := 0; i < len(servicesNode.Content)-1; i += 2 {
		if servicesNode.Content[i].Value == serviceName {
			serviceNode := servicesNode.Content[i+1]
			if serviceNode.Kind != yaml.MappingNode {
				continue
			}

			// Find depends_on section
			var dependsOnNode *yaml.Node
			for j := 0; j < len(serviceNode.Content)-1; j += 2 {
				if serviceNode.Content[j].Value == "depends_on" {
					dependsOnNode = serviceNode.Content[j+1]
					break
				}
			}

			if dependsOnNode == nil {
				// No depends_on section, create one (default to mapping style for health checks)
				dependsOnKeyNode := &yaml.Node{Kind: yaml.ScalarNode, Value: "depends_on"}
				dependsOnNode = &yaml.Node{Kind: yaml.MappingNode, Content: []*yaml.Node{}}
				serviceNode.Content = append(serviceNode.Content, dependsOnKeyNode, dependsOnNode)
			}

			// Handle based on node type
			if dependsOnNode.Kind == yaml.MappingNode {
				// Mapping style: check if dependency already exists
				for k := 0; k < len(dependsOnNode.Content)-1; k += 2 {
					if dependsOnNode.Content[k].Value == dependency {
						return // Already exists
					}
				}
				// Add the dependency with condition: service_healthy
				depKeyNode := &yaml.Node{Kind: yaml.ScalarNode, Value: dependency}
				depValueNode := &yaml.Node{
					Kind: yaml.MappingNode,
					Content: []*yaml.Node{
						{Kind: yaml.ScalarNode, Value: "condition"},
						{Kind: yaml.ScalarNode, Value: "service_healthy"},
					},
				}
				dependsOnNode.Content = append(dependsOnNode.Content, depKeyNode, depValueNode)
			} else if dependsOnNode.Kind == yaml.SequenceNode {
				// List style: check if dependency already exists
				for _, item := range dependsOnNode.Content {
					if item.Kind == yaml.ScalarNode && item.Value == dependency {
						return // Already exists
					}
				}
				// Add the dependency as a simple scalar
				depNode := &yaml.Node{Kind: yaml.ScalarNode, Value: dependency}
				dependsOnNode.Content = append(dependsOnNode.Content, depNode)
			}
			break
		}
	}
}

// addObservabilityVolumes adds the tempo-data and grafana-data volumes to the document
func addObservabilityVolumes(doc *yaml.Node) {
	if doc.Kind != yaml.DocumentNode || len(doc.Content) == 0 {
		return
	}

	root := doc.Content[0]
	if root.Kind != yaml.MappingNode {
		return
	}

	// Find or create volumes section
	var volumesNode *yaml.Node
	for i := 0; i < len(root.Content)-1; i += 2 {
		if root.Content[i].Value == "volumes" {
			volumesNode = root.Content[i+1]
			break
		}
	}

	if volumesNode == nil {
		// Create volumes section before networks
		volumesKeyNode := &yaml.Node{Kind: yaml.ScalarNode, Value: "volumes"}
		volumesNode = &yaml.Node{Kind: yaml.MappingNode, Content: []*yaml.Node{}}

		// Find networks section to insert before it
		networksIndex := -1
		for i := 0; i < len(root.Content)-1; i += 2 {
			if root.Content[i].Value == "networks" {
				networksIndex = i
				break
			}
		}

		if networksIndex >= 0 {
			newContent := make([]*yaml.Node, 0, len(root.Content)+2)
			newContent = append(newContent, root.Content[:networksIndex]...)
			newContent = append(newContent, volumesKeyNode, volumesNode)
			newContent = append(newContent, root.Content[networksIndex:]...)
			root.Content = newContent
		} else {
			root.Content = append(root.Content, volumesKeyNode, volumesNode)
		}
	}

	// Add observability volumes if they don't exist
	if volumesNode.Kind == yaml.MappingNode {
		volumesToAdd := []string{"tempo-data", "grafana-data"}
		for _, volName := range volumesToAdd {
			exists := false
			for i := 0; i < len(volumesNode.Content)-1; i += 2 {
				if volumesNode.Content[i].Value == volName {
					exists = true
					break
				}
			}
			if !exists {
				keyNode := &yaml.Node{Kind: yaml.ScalarNode, Value: volName}
				valueNode := &yaml.Node{Kind: yaml.MappingNode, Tag: "!!map", Content: []*yaml.Node{}}
				volumesNode.Content = append(volumesNode.Content, keyNode, valueNode)
			}
		}
	}
}

// generateObservabilityServicesYAML generates YAML for observability services
func generateObservabilityServicesYAML(config *ComposeConfig, needsRedis, needsTempo, needsGrafana bool) string {
	var sb strings.Builder

	if needsRedis {
		sb.WriteString(fmt.Sprintf(`redis:
  image: redis:7-alpine
  container_name: %s-redis
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
    - %s
`, config.ProjectName, config.NetworkName))
	}

	if needsTempo {
		sb.WriteString(fmt.Sprintf(`tempo:
  image: grafana/tempo:2.9.0
  container_name: %s-tempo
  hostname: tempo
  command: ["-config.file=/etc/tempo.yaml"]
  volumes:
    - ./tempo.yaml:/etc/tempo.yaml:ro
    - tempo-data:/var/tempo
  ports:
    - "3200:3200"
    - "4317:4317"
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:3200/ready"]
    interval: 30s
    timeout: 10s
    retries: 3
  networks:
    - %s
`, config.ProjectName, config.NetworkName))
	}

	if needsGrafana {
		sb.WriteString(fmt.Sprintf(`grafana:
  image: grafana/grafana:12.3.1
  container_name: %s-grafana
  hostname: grafana
  environment:
    GF_SECURITY_ADMIN_USER: admin
    GF_SECURITY_ADMIN_PASSWORD: admin
    GF_AUTH_ANONYMOUS_ENABLED: "true"
    GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
    GF_FEATURE_TOGGLES_ENABLE: traceqlEditor
  volumes:
    - ./grafana/grafana.ini:/etc/grafana/grafana.ini:ro
    - ./grafana/provisioning:/etc/grafana/provisioning:ro
    - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    - grafana-data:/var/lib/grafana
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
    - %s
`, config.ProjectName, config.NetworkName))
	}

	return sb.String()
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

	// Add new agent volumes (language-specific)
	for _, agent := range agents {
		var volumeName string
		if agent.Language == "typescript" {
			volumeName = agent.Name + "-node_modules"
		} else {
			volumeName = agent.Name + "-packages"
		}
		if !existingVolumes[volumeName] {
			keyNode := &yaml.Node{
				Kind:  yaml.ScalarNode,
				Value: volumeName,
			}
			valueNode := &yaml.Node{
				Kind:    yaml.MappingNode,
				Tag:     "!!map",
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
{{- if eq .Language "python" }}
# Agent: {{ .Name }} (Python)
# NOTE: In dev mode, entrypoint is overridden to install requirements on startup.
#       In production (Dockerfile), base image ENTRYPOINT ["python"] is used with CMD ["main.py"]
{{ .Name }}:
  image: mcpmesh/python-runtime:0.8
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
{{- else if eq .Language "typescript" }}
# Agent: {{ .Name }} (TypeScript)
# NOTE: In dev mode, npm install runs on startup and source is mounted.
#       In production (Dockerfile), dependencies are pre-installed in the image.
{{ .Name }}:
  image: mcpmesh/typescript-runtime:0.8
  container_name: {{ $.ProjectName }}-{{ .Name }}
  hostname: {{ .Name }}
  user: root
  ports:
    - "{{ .Port }}:{{ .Port }}"
  volumes:
    - ./{{ .Dir }}:/app:ro
    - {{ .Name }}-node_modules:/app/node_modules
  working_dir: /app
  entrypoint: ["sh", "-c"]
  command: ["chown -R mcp-mesh:mcp-mesh /app/node_modules && su mcp-mesh -c 'npm install --silent 2>/dev/null && npx tsx src/index.ts'"]
  environment:
    NODE_ENV: development
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
{{- if $.Observability }}
    REDIS_URL: redis://redis:6379
    MCP_MESH_DISTRIBUTED_TRACING_ENABLED: "true"
{{- end }}
  healthcheck:
    test: ["CMD", "wget", "--spider", "-q", "http://localhost:{{ .Port }}/health"]
    interval: 5s
    timeout: 3s
    retries: 10
    start_period: 45s
  networks:
    - {{ $.NetworkName }}
{{- end }}
{{- end }}`

// generateTempoConfig creates the tempo.yaml configuration file
func generateTempoConfig(outputDir string) error {
	tempoPath := filepath.Join(outputDir, "tempo.yaml")

	// Don't overwrite if it already exists
	if _, err := os.Stat(tempoPath); err == nil {
		return nil
	}

	return os.WriteFile(tempoPath, []byte(tempoConfigTemplate), 0644)
}

// tempoConfigTemplate is the Tempo configuration for distributed tracing
const tempoConfigTemplate = `# Tempo configuration for MCP Mesh distributed tracing
# Generated by: meshctl scaffold --compose --observability

server:
  http_listen_port: 3200
  grpc_listen_port: 9095

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

ingester:
  max_block_duration: 5m

compactor:
  compaction:
    block_retention: 1h

storage:
  trace:
    backend: local
    wal:
      path: /var/tempo/wal
    local:
      path: /var/tempo/blocks

query_frontend:
  search:
    duration_slo: 5s
    throughput_bytes_slo: 1.073741824e+09
  trace_by_id:
    duration_slo: 5s
`

// grafanaIniTemplate is the Grafana configuration
const grafanaIniTemplate = `# Grafana configuration for MCP Mesh observability
# Generated by: meshctl scaffold --compose --observability

[analytics]
reporting_enabled = false
check_for_updates = false

[security]
admin_user = admin
admin_password = admin
disable_gravatar = true

[users]
allow_sign_up = false
allow_org_create = false
default_theme = dark

[auth.anonymous]
enabled = false

[log]
mode = console
level = info

[paths]
data = /var/lib/grafana
logs = /var/log/grafana
plugins = /var/lib/grafana/plugins
provisioning = /etc/grafana/provisioning

[server]
http_port = 3000
domain = localhost

[database]
type = sqlite3
path = /var/lib/grafana/grafana.db

[dashboards]
default_home_dashboard_path = /var/lib/grafana/dashboards/mcp-mesh-overview.json

[alerting]
enabled = false

[unified_alerting]
enabled = true

[feature_toggles]
enable = traceqlEditor
`

// grafanaDatasourcesTemplate is the Grafana datasources provisioning config
const grafanaDatasourcesTemplate = `# Grafana datasources for MCP Mesh
# Generated by: meshctl scaffold --compose --observability
apiVersion: 1

datasources:
  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    uid: tempo
    isDefault: true
    jsonData:
      nodeGraph:
        enabled: true
`

// grafanaDashboardsProviderTemplate is the Grafana dashboards provisioning config
const grafanaDashboardsProviderTemplate = `# Grafana dashboards provider for MCP Mesh
# Generated by: meshctl scaffold --compose --observability
apiVersion: 1

providers:
  - name: "default"
    orgId: 1
    folder: ""
    type: file
    disableDeletion: false
    editable: true
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /var/lib/grafana/dashboards
`

// grafanaDashboardTemplate is the MCP Mesh overview dashboard JSON
const grafanaDashboardTemplate = `{
  "annotations": {
    "list": [
      {
        "builtIn": 1,
        "datasource": {
          "type": "grafana",
          "uid": "-- Grafana --"
        },
        "enable": true,
        "hide": true,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts",
        "type": "dashboard"
      }
    ]
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "id": 1,
      "type": "piechart",
      "title": "MCP Mesh Distributed Tracing Overview",
      "gridPos": {
        "x": 0,
        "y": 0,
        "h": 8,
        "w": 24
      },
      "fieldConfig": {
        "defaults": {
          "custom": {
            "hideFrom": {
              "tooltip": false,
              "viz": false,
              "legend": false
            }
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "unit": "µs"
        },
        "overrides": []
      },
      "transformations": [
        {
          "id": "groupBy",
          "options": {
            "fields": {
              "Duration": {
                "aggregations": ["sum"],
                "operation": "aggregate"
              },
              "Service": {
                "aggregations": [],
                "operation": "groupby"
              },
              "traceDuration": {
                "aggregations": ["max"],
                "operation": "aggregate"
              },
              "traceService": {
                "aggregations": ["count"],
                "operation": "groupby"
              }
            }
          }
        }
      ],
      "pluginVersion": "12.3.1",
      "targets": [
        {
          "datasource": {
            "type": "tempo",
            "uid": "tempo"
          },
          "limit": 20,
          "query": "{}",
          "queryType": "traceql",
          "refId": "A",
          "tableType": "traces"
        }
      ],
      "datasource": {
        "type": "tempo",
        "uid": "tempo"
      },
      "options": {
        "reduceOptions": {
          "values": true,
          "calcs": ["lastNotNull"],
          "fields": "/.*/"
        },
        "pieType": "pie",
        "tooltip": {
          "mode": "single",
          "sort": "none"
        },
        "legend": {
          "showLegend": true,
          "displayMode": "list",
          "placement": "bottom"
        },
        "displayLabels": ["name"]
      }
    },
    {
      "id": 2,
      "type": "barchart",
      "title": "Service Activity Summary",
      "gridPos": {
        "x": 0,
        "y": 8,
        "h": 8,
        "w": 24
      },
      "fieldConfig": {
        "defaults": {
          "custom": {
            "lineWidth": 1,
            "fillOpacity": 80,
            "gradientMode": "none",
            "axisPlacement": "auto",
            "axisLabel": "",
            "axisColorMode": "text",
            "axisBorderShow": false,
            "scaleDistribution": {
              "type": "linear"
            },
            "axisCenteredZero": false,
            "hideFrom": {
              "tooltip": false,
              "viz": false,
              "legend": false
            },
            "thresholdsStyle": {
              "mode": "off"
            },
            "axisGridShow": true
          },
          "color": {
            "mode": "palette-classic"
          },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "red",
                "value": 80
              }
            ]
          }
        },
        "overrides": []
      },
      "transformations": [
        {
          "id": "groupBy",
          "options": {
            "fields": {
              "Service": {
                "aggregations": [],
                "operation": "groupby"
              },
              "traceName": {
                "aggregations": [],
                "operation": "groupby"
              },
              "traceDuration": {
                "aggregations": ["lastNotNull"],
                "operation": "aggregate"
              }
            }
          }
        }
      ],
      "pluginVersion": "12.3.1",
      "targets": [
        {
          "datasource": {
            "type": "tempo",
            "uid": "tempo"
          },
          "query": "{}",
          "refId": "A",
          "queryType": "traceql",
          "limit": 20,
          "tableType": "traces"
        }
      ],
      "datasource": {
        "type": "tempo",
        "uid": "tempo"
      },
      "options": {
        "orientation": "vertical",
        "xTickLabelRotation": 0,
        "xTickLabelSpacing": 0,
        "showValue": "always",
        "stacking": "normal",
        "groupWidth": 0.7,
        "barWidth": 0.97,
        "barRadius": 0,
        "fullHighlight": false,
        "tooltip": {
          "mode": "single",
          "sort": "none"
        },
        "legend": {
          "showLegend": true,
          "displayMode": "list",
          "placement": "bottom",
          "calcs": []
        }
      }
    },
    {
      "datasource": {
        "type": "tempo",
        "uid": "tempo"
      },
      "fieldConfig": {
        "defaults": {
          "color": {
            "mode": "palette-classic"
          },
          "custom": {
            "cellOptions": {
              "type": "auto"
            },
            "inspect": false
          },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {
                "color": "green",
                "value": null
              },
              {
                "color": "red",
                "value": 80
              }
            ]
          }
        },
        "overrides": []
      },
      "gridPos": {
        "h": 8,
        "w": 24,
        "x": 0,
        "y": 16
      },
      "id": 3,
      "options": {
        "showHeader": true,
        "cellHeight": "sm",
        "footer": {
          "show": false,
          "reducer": ["sum"],
          "countRows": false,
          "fields": ""
        }
      },
      "pluginVersion": "12.3.1",
      "targets": [
        {
          "datasource": {
            "type": "tempo",
            "uid": "tempo"
          },
          "query": "{}",
          "refId": "A"
        }
      ],
      "title": "Recent Trace Activity",
      "type": "table"
    }
  ],
  "refresh": "5s",
  "schemaVersion": 39,
  "tags": ["mcp-mesh", "distributed-tracing", "observability"],
  "templating": {
    "list": []
  },
  "time": {
    "from": "now-5m",
    "to": "now"
  },
  "timepicker": {},
  "timezone": "",
  "title": "MCP Mesh Distributed Tracing",
  "uid": "mcp-mesh-overview",
  "version": 1,
  "weekStart": ""
}
`

// generateGrafanaConfig generates the Grafana configuration files
func generateGrafanaConfig(outputDir string) error {
	// Create directory structure
	dirs := []string{
		filepath.Join(outputDir, "grafana"),
		filepath.Join(outputDir, "grafana", "provisioning"),
		filepath.Join(outputDir, "grafana", "provisioning", "datasources"),
		filepath.Join(outputDir, "grafana", "provisioning", "dashboards"),
		filepath.Join(outputDir, "grafana", "dashboards"),
	}

	for _, dir := range dirs {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return fmt.Errorf("failed to create directory %s: %w", dir, err)
		}
	}

	// Write grafana.ini
	grafanaIniPath := filepath.Join(outputDir, "grafana", "grafana.ini")
	if _, err := os.Stat(grafanaIniPath); os.IsNotExist(err) {
		if err := os.WriteFile(grafanaIniPath, []byte(grafanaIniTemplate), 0644); err != nil {
			return fmt.Errorf("failed to write grafana.ini: %w", err)
		}
	}

	// Write datasources.yaml
	datasourcesPath := filepath.Join(outputDir, "grafana", "provisioning", "datasources", "datasources.yaml")
	if _, err := os.Stat(datasourcesPath); os.IsNotExist(err) {
		if err := os.WriteFile(datasourcesPath, []byte(grafanaDatasourcesTemplate), 0644); err != nil {
			return fmt.Errorf("failed to write datasources.yaml: %w", err)
		}
	}

	// Write dashboards.yaml (provider config)
	dashboardsProviderPath := filepath.Join(outputDir, "grafana", "provisioning", "dashboards", "dashboards.yaml")
	if _, err := os.Stat(dashboardsProviderPath); os.IsNotExist(err) {
		if err := os.WriteFile(dashboardsProviderPath, []byte(grafanaDashboardsProviderTemplate), 0644); err != nil {
			return fmt.Errorf("failed to write dashboards.yaml: %w", err)
		}
	}

	// Write mcp-mesh-overview.json dashboard
	dashboardPath := filepath.Join(outputDir, "grafana", "dashboards", "mcp-mesh-overview.json")
	if _, err := os.Stat(dashboardPath); os.IsNotExist(err) {
		if err := os.WriteFile(dashboardPath, []byte(grafanaDashboardTemplate), 0644); err != nil {
			return fmt.Errorf("failed to write mcp-mesh-overview.json: %w", err)
		}
	}

	return nil
}

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
    image: mcpmesh/registry:0.8
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
      MCP_MESH_DISTRIBUTED_TRACING_ENABLED: "true"
      TRACE_EXPORTER_TYPE: otlp
      TELEMETRY_ENDPOINT: tempo:4317
      TELEMETRY_PROTOCOL: grpc
      TEMPO_URL: http://tempo:3200
{{- end }}
    depends_on:
      postgres:
        condition: service_healthy
{{- if .Observability }}
      redis:
        condition: service_healthy
      tempo:
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
    image: grafana/tempo:2.9.0
    container_name: {{ .ProjectName }}-tempo
    hostname: tempo
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml:ro
      - tempo-data:/var/tempo
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
    image: grafana/grafana:12.3.1
    container_name: {{ .ProjectName }}-grafana
    hostname: grafana
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Admin
      GF_FEATURE_TOGGLES_ENABLE: traceqlEditor
    volumes:
      - ./grafana/grafana.ini:/etc/grafana/grafana.ini:ro
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
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
{{- range .Agents }}
{{- if eq .Language "python" }}

  # Python Agent: {{ .Name }}
  # NOTE: In dev mode, entrypoint is overridden to install requirements on startup.
  #       In production (Dockerfile), base image ENTRYPOINT ["python"] is used with CMD ["main.py"]
  {{ .Name }}:
    image: mcpmesh/python-runtime:0.8
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
{{- else if eq .Language "typescript" }}

  # TypeScript Agent: {{ .Name }}
  # NOTE: In dev mode, npm install runs on startup and source is mounted.
  #       In production (Dockerfile), dependencies are pre-installed in the image.
  {{ .Name }}:
    image: mcpmesh/typescript-runtime:0.8
    container_name: {{ $.ProjectName }}-{{ .Name }}
    hostname: {{ .Name }}
    user: root
    ports:
      - "{{ .Port }}:{{ .Port }}"
    volumes:
      - ./{{ .Dir }}:/app:ro
      - {{ .Name }}-node_modules:/app/node_modules
    working_dir: /app
    entrypoint: ["sh", "-c"]
    command: ["chown -R mcp-mesh:mcp-mesh /app/node_modules && su mcp-mesh -c 'npm install --silent 2>/dev/null && npx tsx src/index.ts'"]
    environment:
      NODE_ENV: development
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
{{- if $.Observability }}
      REDIS_URL: redis://redis:6379
      MCP_MESH_DISTRIBUTED_TRACING_ENABLED: "true"
{{- end }}
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:{{ .Port }}/health"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 45s
    networks:
      - {{ $.NetworkName }}
{{- end }}
{{- end }}
{{- end }}
{{- if or .Agents .Observability }}

volumes:
{{- if .Observability }}
  tempo-data:
  grafana-data:
{{- end }}
{{- range .Agents }}
{{- if eq .Language "python" }}
  {{ .Name }}-packages:
{{- else if eq .Language "typescript" }}
  {{ .Name }}-node_modules:
{{- end }}
{{- end }}
{{- end }}

networks:
  {{ .NetworkName }}:
    name: {{ .NetworkName }}
    driver: bridge
`
