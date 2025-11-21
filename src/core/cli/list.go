package cli

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// Color constants for beautiful output
const (
	colorReset  = "\033[0m"
	colorRed    = "\033[31m"
	colorGreen  = "\033[32m"
	colorYellow = "\033[33m"
	colorBlue   = "\033[34m"
	colorGray   = "\033[37m"
)

// Display constants
const (
	maxCapabilityDisplayWidth = 80 // Maximum width for capability display
)

// NewListCommand creates the list command
func NewListCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List running agents with docker-compose style display",
		Long: `List all running MCP Mesh agents with a beautiful table display.

Shows agent status, dependency resolution, uptime, and endpoint information
in a docker-compose-style format for easy monitoring.

Examples:
  meshctl list                                    # Show beautiful table with all agents
  meshctl list --json                             # Output in JSON format
  meshctl list --filter hello                     # Filter agents by name pattern
  meshctl list --no-deps                          # Hide dependency status
  meshctl list --wide                             # Show endpoints and tool counts
  meshctl list --registry-url http://remote:8000  # Connect to remote registry
  meshctl list --registry-host prod.example.com   # Connect to remote host
  meshctl list --registry-port 9000               # Use custom port`,
		RunE: runListCommand,
	}

	// Enhanced flags for better UX
	cmd.Flags().String("filter", "", "Filter by name pattern")
	cmd.Flags().Bool("json", false, "Output in JSON format")
	cmd.Flags().Bool("verbose", false, "Show detailed information")
	cmd.Flags().Bool("no-deps", false, "Hide dependency status")
	cmd.Flags().Bool("wide", false, "Show additional columns")

	// New enhanced filtering and display options
	cmd.Flags().String("since", "", "Show agents active since duration (e.g., 1h, 30m, 24h)")
	cmd.Flags().Bool("healthy-only", false, "Show only healthy agents")
	cmd.Flags().String("id", "", "Show detailed information for specific agent ID")

	// Remote registry connection flags
	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Int("timeout", 10, "Connection timeout in seconds")

	return cmd
}

// ListOutput represents the complete output structure
type ListOutput struct {
	Registry  RegistryStatus  `json:"registry"`
	Agents    []EnhancedAgent `json:"agents"`
	Processes []ProcessInfo   `json:"processes"`
	Timestamp time.Time       `json:"timestamp"`
}

// RegistryStatus represents registry status information
type RegistryStatus struct {
	Status     string    `json:"status"`
	URL        string    `json:"url,omitempty"`
	AgentCount int       `json:"agent_count,omitempty"`
	Error      string    `json:"error,omitempty"`
	Uptime     string    `json:"uptime,omitempty"`
	StartTime  time.Time `json:"start_time,omitempty"`
}

// EnhancedAgent contains comprehensive agent information for display
type EnhancedAgent struct {
	ID                    string                 `json:"id"`
	Name                  string                 `json:"name"`
	AgentType             string                 `json:"agent_type"`
	Status                string                 `json:"status"`
	Endpoint              string                 `json:"endpoint"`
	Tools                 []ToolInfo             `json:"tools"`
	Dependencies          []Dependency           `json:"dependencies"`
	DependencyResolutions []DependencyResolution `json:"dependency_resolutions,omitempty"`
	DependenciesResolved  int                    `json:"dependencies_resolved"`
	DependenciesTotal     int                    `json:"dependencies_total"`
	LastHeartbeat         *time.Time             `json:"last_heartbeat,omitempty"`
	CreatedAt             time.Time              `json:"created_at"`
	UpdatedAt             time.Time              `json:"updated_at"`
	Version               string                 `json:"version,omitempty"`
	PID                   int                    `json:"pid,omitempty"`
	FilePath              string                 `json:"file_path,omitempty"`
	StartTime             time.Time              `json:"start_time,omitempty"`
	Config                map[string]interface{} `json:"config,omitempty"`
	Labels                map[string]interface{} `json:"labels,omitempty"`
}

// ToolInfo represents tool/capability information
type ToolInfo struct {
	ID           int      `json:"id"`
	Name         string   `json:"name"`
	Capability   string   `json:"capability"`
	FunctionName string   `json:"function_name"`
	Version      string   `json:"version"`
	Tags         []string `json:"tags,omitempty"`
	Dependencies []string `json:"dependencies,omitempty"`
}

// Dependency represents a resolved dependency
type Dependency struct {
	Name     string `json:"name"`
	Status   string `json:"status"` // "resolved", "missing", "unhealthy"
	AgentID  string `json:"agent_id,omitempty"`
	Endpoint string `json:"endpoint,omitempty"`
}

// DependencyResolution represents detailed dependency resolution information from the registry
type DependencyResolution struct {
	FunctionName    string   `json:"function_name"`
	Capability      string   `json:"capability"`
	Tags            []string `json:"tags,omitempty"`
	MCPTool         string   `json:"mcp_tool,omitempty"`
	ProviderAgentID string   `json:"provider_agent_id,omitempty"`
	Endpoint        string   `json:"endpoint,omitempty"`
	Status          string   `json:"status"` // "available", "unavailable", "unresolved"
}

func runListCommand(cmd *cobra.Command, args []string) error {
	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get flags
	filterPattern, _ := cmd.Flags().GetString("filter")
	jsonOutput, _ := cmd.Flags().GetBool("json")
	verbose, _ := cmd.Flags().GetBool("verbose")
	noDeps, _ := cmd.Flags().GetBool("no-deps")
	wide, _ := cmd.Flags().GetBool("wide")

	// New enhanced flags
	sinceFlag, _ := cmd.Flags().GetString("since")
	healthyOnly, _ := cmd.Flags().GetBool("healthy-only")
	agentID, _ := cmd.Flags().GetString("id")

	// Registry connection flags
	registryURL, _ := cmd.Flags().GetString("registry-url")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")
	registryScheme, _ := cmd.Flags().GetString("registry-scheme")
	timeout, _ := cmd.Flags().GetInt("timeout")

	// Determine final registry URL
	finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)

	// Set connection timeout if provided
	if timeout > 0 {
		// Configure HTTP client with timeout (will be used by HTTP functions)
		configureHTTPClient(timeout)
	}

	// Collect all information
	output := ListOutput{
		Timestamp: time.Now(),
	}

	// Check registry status and get detailed agent information
	output.Registry = getRegistryStatus(finalRegistryURL)

	if output.Registry.Status == "running" {
		// Get enhanced agent information with dependencies
		enhancedAgents, err := getEnhancedAgents(finalRegistryURL)
		if err != nil {
			if !jsonOutput {
				fmt.Printf("Warning: failed to get detailed agent information: %v\n", err)
			}
		} else {
			output.Agents = enhancedAgents
		}
	}

	// Get local process information
	processes, err := GetRunningProcesses()
	if err != nil {
		if !jsonOutput && verbose {
			fmt.Printf("Warning: failed to get process information: %v\n", err)
		}
	} else {
		output.Processes = processes
		// Enrich agents with process information
		output.Agents = enrichWithProcessInfo(output.Agents, processes)
	}

	// Handle single agent details view
	if agentID != "" {
		return outputAgentDetails(output.Agents, agentID, jsonOutput)
	}

	// Apply filters
	if filterPattern != "" {
		output.Agents = filterEnhancedAgents(output.Agents, filterPattern)
	}

	// Apply time-based filtering
	if sinceFlag != "" {
		filtered, err := filterAgentsSince(output.Agents, sinceFlag)
		if err != nil {
			return fmt.Errorf("invalid --since duration: %w", err)
		}
		output.Agents = filtered
	}

	// Apply healthy-only filter
	if healthyOnly {
		output.Agents = filterHealthyAgents(output.Agents)
	}

	// Output results
	if jsonOutput {
		return outputEnhancedJSON(output)
	}

	return outputDockerComposeStyle(output, verbose, noDeps, wide)
}

// getRegistryStatus checks registry status and gathers uptime information
func getRegistryStatus(registryURL string) RegistryStatus {
	status := RegistryStatus{
		Status: "not running",
	}

	if IsRegistryRunning(registryURL) {
		status.Status = "running"
		status.URL = registryURL

		// Try to get registry process info for uptime
		processes, err := GetRunningProcesses()
		if err == nil {
			for _, proc := range processes {
				if proc.Type == "registry" && proc.Status == "running" {
					status.StartTime = proc.StartTime
					status.Uptime = formatDuration(time.Since(proc.StartTime))
					break
				}
			}
		}

		// Get agent count
		if agents, err := getDetailedAgents(registryURL); err == nil {
			status.AgentCount = len(agents)
		}
	}

	return status
}

// AgentInfoAPI represents the agent structure returned by the registry API
type AgentInfoAPI struct {
	ID                   string      `json:"id"`
	Name                 string      `json:"name"`
	AgentType            string      `json:"agent_type"`
	Status               string      `json:"status"`
	Endpoint             string      `json:"endpoint"`
	Version              *string     `json:"version,omitempty"`
	LastSeen             *time.Time  `json:"last_seen,omitempty"`
	TotalDependencies    int         `json:"total_dependencies"`
	DependenciesResolved int         `json:"dependencies_resolved"`
	Capabilities         []struct {
		Name         string   `json:"name"`
		Version      string   `json:"version"`
		FunctionName string   `json:"function_name"`
		Description  *string  `json:"description,omitempty"`
		Tags         []string `json:"tags,omitempty"`
	} `json:"capabilities"`
	DependencyResolutions []struct {
		FunctionName    string   `json:"function_name"`
		Capability      string   `json:"capability"`
		Tags            []string `json:"tags,omitempty"`
		MCPTool         string   `json:"mcp_tool,omitempty"`
		ProviderAgentID string   `json:"provider_agent_id,omitempty"`
		Endpoint        string   `json:"endpoint,omitempty"`
		Status          string   `json:"status"`
	} `json:"dependency_resolutions,omitempty"`
}

// AgentsListResponseAPI represents the API response structure
type AgentsListResponseAPI struct {
	Agents    []AgentInfoAPI `json:"agents"`
	Count     int            `json:"count"`
	Timestamp time.Time      `json:"timestamp"`
}

// getDetailedAgents fetches detailed agent information from registry
func getDetailedAgents(registryURL string) ([]map[string]interface{}, error) {
	agentsURL := registryURL + "/agents"
	resp, err := registryHTTPClient.Get(agentsURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		switch resp.StatusCode {
		case http.StatusNotFound:
			// Registry or endpoint not found - return empty list
			return []map[string]interface{}{}, nil
		case http.StatusServiceUnavailable:
			return nil, fmt.Errorf("registry service unavailable (status %d)", resp.StatusCode)
		case http.StatusInternalServerError:
			return nil, fmt.Errorf("registry internal error (status %d)", resp.StatusCode)
		default:
			return nil, fmt.Errorf("registry returned status %d", resp.StatusCode)
		}
	}

	var response AgentsListResponseAPI

	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode registry response: %w", err)
	}

	// Convert structured response to map format for compatibility with existing code
	agents := make([]map[string]interface{}, len(response.Agents))
	for i, agent := range response.Agents {
		agentMap := map[string]interface{}{
			"id":                    agent.ID,
			"name":                  agent.Name,
			"agent_type":            agent.AgentType,
			"status":                agent.Status,
			"endpoint":              agent.Endpoint,
			"total_dependencies":    agent.TotalDependencies,
			"dependencies_resolved": agent.DependenciesResolved,
		}

		if agent.Version != nil {
			agentMap["version"] = *agent.Version
		}

		if agent.LastSeen != nil {
			agentMap["last_seen"] = agent.LastSeen.Format(time.RFC3339)
		}

		// Convert capabilities to the expected format ([]interface{} containing maps)
		capabilities := make([]interface{}, len(agent.Capabilities))
		for j, cap := range agent.Capabilities {
			capMap := map[string]interface{}{
				"name":          cap.Name,
				"capability":    cap.Name, // Use name as capability for compatibility
				"version":       cap.Version,
				"function_name": cap.FunctionName,
			}
			if cap.Description != nil {
				capMap["description"] = *cap.Description
			}
			if len(cap.Tags) > 0 {
				capMap["tags"] = cap.Tags
			}
			capabilities[j] = capMap
		}
		agentMap["capabilities"] = capabilities

		// Convert dependency resolutions to the expected format
		if len(agent.DependencyResolutions) > 0 {
			depResolutions := make([]interface{}, len(agent.DependencyResolutions))
			for j, depRes := range agent.DependencyResolutions {
				depResMap := map[string]interface{}{
					"function_name":     depRes.FunctionName,
					"capability":        depRes.Capability,
					"mcp_tool":          depRes.MCPTool,
					"provider_agent_id": depRes.ProviderAgentID,
					"endpoint":          depRes.Endpoint,
					"status":            depRes.Status,
				}
				if len(depRes.Tags) > 0 {
					depResMap["tags"] = depRes.Tags
				}
				depResolutions[j] = depResMap
			}
			agentMap["dependency_resolutions"] = depResolutions
		}

		agents[i] = agentMap
	}

	return agents, nil
}

// getEnhancedAgents processes detailed agent data and creates enhanced agent objects
func getEnhancedAgents(registryURL string) ([]EnhancedAgent, error) {
	detailedAgents, err := getDetailedAgents(registryURL)
	if err != nil {
		return nil, err
	}

	var enhanced []EnhancedAgent
	for _, agentData := range detailedAgents {
		agent := processAgentData(agentData)
		enhanced = append(enhanced, agent)
	}

	// Sort by name for consistent display
	sort.Slice(enhanced, func(i, j int) bool {
		return enhanced[i].Name < enhanced[j].Name
	})

	return enhanced, nil
}

// processAgentData converts raw agent data from registry into EnhancedAgent
func processAgentData(data map[string]interface{}) EnhancedAgent {
	agent := EnhancedAgent{
		ID:        getString(data, "id"),
		Name:      getString(data, "name"),
		AgentType: getString(data, "agent_type"),
		Status:    getString(data, "status"),
		Endpoint:  getString(data, "endpoint"),
		Version:   getString(data, "version"),
		Config:    getMapInterface(data, "config"),
		Labels:    getMapInterface(data, "labels"),
	}

	// Parse timestamps
	if createdStr := getString(data, "created_at"); createdStr != "" {
		if t, err := time.Parse(time.RFC3339, createdStr); err == nil {
			agent.CreatedAt = t
		}
	}
	if updatedStr := getString(data, "updated_at"); updatedStr != "" {
		if t, err := time.Parse(time.RFC3339, updatedStr); err == nil {
			agent.UpdatedAt = t
		}
	}
	// Try both field names for last heartbeat/seen
	if lastSeenStr := getString(data, "last_seen"); lastSeenStr != "" {
		if t, err := time.Parse(time.RFC3339, lastSeenStr); err == nil {
			agent.LastHeartbeat = &t
		}
	} else if lastHeartbeatStr := getString(data, "last_heartbeat"); lastHeartbeatStr != "" {
		if t, err := time.Parse(time.RFC3339, lastHeartbeatStr); err == nil {
			agent.LastHeartbeat = &t
		}
	}

	// Process capabilities/tools
	if capabilities, ok := data["capabilities"].([]interface{}); ok {
		for _, cap := range capabilities {
			if capMap, ok := cap.(map[string]interface{}); ok {
				tool := ToolInfo{
					Name:         getString(capMap, "name"),        // capability name from API
					Capability:   getString(capMap, "name"),        // same as name
					FunctionName: getString(capMap, "function_name"),
					Version:      getString(capMap, "version"),
				}
				// Parse tags if present
				if tagsSlice, ok := capMap["tags"].([]string); ok {
					tool.Tags = tagsSlice
				} else if tagsData, ok := capMap["tags"].([]interface{}); ok {
					for _, tag := range tagsData {
						if tagStr, ok := tag.(string); ok {
							tool.Tags = append(tool.Tags, tagStr)
						}
					}
				} else if tagsStr, ok := capMap["tags"].(string); ok && tagsStr != "" && tagsStr != "[]" {
					// Handle case where tags come as JSON string
					var tags []string
					if err := json.Unmarshal([]byte(tagsStr), &tags); err == nil {
						tool.Tags = tags
					} else {
						// Handle case where tags come as plain string like "[system time clock]"
						if strings.HasPrefix(tagsStr, "[") && strings.HasSuffix(tagsStr, "]") {
							// Remove brackets and split by spaces
							cleanTags := strings.Trim(tagsStr, "[]")
							if cleanTags != "" {
								tool.Tags = strings.Fields(cleanTags)
							}
						}
					}
				}
				if id := getFloat(capMap, "id"); id > 0 {
					tool.ID = int(id)
				}
				agent.Tools = append(agent.Tools, tool)
			}
		}
	}

	// Extract dependency counts from API response
	if totalDeps := getFloat(data, "total_dependencies"); totalDeps >= 0 {
		agent.DependenciesTotal = int(totalDeps)
	}
	if resolvedDeps := getFloat(data, "dependencies_resolved"); resolvedDeps >= 0 {
		agent.DependenciesResolved = int(resolvedDeps)
	}

	// Parse dependency resolutions from API
	if depResolutions, ok := data["dependency_resolutions"].([]interface{}); ok {
		for _, depRes := range depResolutions {
			if depResMap, ok := depRes.(map[string]interface{}); ok {
				resolution := DependencyResolution{
					FunctionName:    getString(depResMap, "function_name"),
					Capability:      getString(depResMap, "capability"),
					MCPTool:         getString(depResMap, "mcp_tool"),
					ProviderAgentID: getString(depResMap, "provider_agent_id"),
					Endpoint:        getString(depResMap, "endpoint"),
					Status:          getString(depResMap, "status"),
				}

				// Parse tags if present
				if tagsSlice, ok := depResMap["tags"].([]string); ok {
					resolution.Tags = tagsSlice
				} else if tagsData, ok := depResMap["tags"].([]interface{}); ok {
					for _, tag := range tagsData {
						if tagStr, ok := tag.(string); ok {
							resolution.Tags = append(resolution.Tags, tagStr)
						}
					}
				}

				agent.DependencyResolutions = append(agent.DependencyResolutions, resolution)
			}
		}
	}

	// For now, use placeholder dependencies list (could be enhanced to show actual dependency details)
	agent.Dependencies = calculateDependencies(agent.Tools)

	return agent
}

// Helper functions for data extraction
func getString(data map[string]interface{}, key string) string {
	if val, ok := data[key]; ok {
		if str, ok := val.(string); ok {
			return str
		}
	}
	return ""
}

func getFloat(data map[string]interface{}, key string) float64 {
	if val, ok := data[key]; ok {
		switch v := val.(type) {
		case float64:
			return v
		case int:
			return float64(v)
		case int64:
			return float64(v)
		case int32:
			return float64(v)
		}
	}
	return -1 // Return -1 to indicate field doesn't exist
}

func getMapInterface(data map[string]interface{}, key string) map[string]interface{} {
	if val, ok := data[key]; ok {
		if m, ok := val.(map[string]interface{}); ok {
			return m
		}
	}
	return map[string]interface{}{}
}

// calculateDependencies extracts dependencies from tools (placeholder implementation)
func calculateDependencies(tools []ToolInfo) []Dependency {
	var deps []Dependency
	// In a real implementation, this would query the registry for dependency resolution
	// For now, return empty slice
	return deps
}

func countResolvedDependencies(deps []Dependency) int {
	resolved := 0
	for _, dep := range deps {
		if dep.Status == "resolved" {
			resolved++
		}
	}
	return resolved
}

// enrichWithProcessInfo adds process information to enhanced agents
func enrichWithProcessInfo(agents []EnhancedAgent, processes []ProcessInfo) []EnhancedAgent {
	processMap := make(map[string]ProcessInfo)
	for _, proc := range processes {
		if proc.Type == "agent" {
			processMap[proc.Name] = proc
		}
	}

	for i := range agents {
		if proc, exists := processMap[agents[i].Name]; exists {
			agents[i].PID = proc.PID
			agents[i].FilePath = proc.FilePath
			agents[i].StartTime = proc.StartTime
		}
	}

	return agents
}

// filterEnhancedAgents applies name filtering to enhanced agents
func filterEnhancedAgents(agents []EnhancedAgent, pattern string) []EnhancedAgent {
	if pattern == "" {
		return agents
	}

	var filtered []EnhancedAgent
	pattern = strings.ToLower(pattern)

	for _, agent := range agents {
		if strings.Contains(strings.ToLower(agent.Name), pattern) ||
			strings.Contains(strings.ToLower(agent.ID), pattern) {
			filtered = append(filtered, agent)
		}
	}
	return filtered
}

// outputEnhancedJSON outputs the enhanced data in JSON format
func outputEnhancedJSON(output ListOutput) error {
	data, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}
	fmt.Println(string(data))
	return nil
}

// outputDockerComposeStyle creates a beautiful docker-compose-style table display
func outputDockerComposeStyle(output ListOutput, verbose, noDeps, wide bool) error {
	// Show registry status first
	showRegistryStatus(output.Registry)

	if len(output.Agents) == 0 {
		fmt.Println("No agents found")
		return nil
	}

	// Calculate column widths for beautiful alignment
	nameWidth, statusWidth, typeWidth, endpointWidth := calculateColumnWidths(output.Agents, wide)

	// Print header
	printTableHeader(nameWidth, statusWidth, typeWidth, endpointWidth, noDeps, wide, verbose)
	printTableSeparator(nameWidth, statusWidth, typeWidth, endpointWidth, noDeps, wide, verbose)

	// Print agent rows
	for _, agent := range output.Agents {
		printAgentRow(agent, nameWidth, statusWidth, typeWidth, endpointWidth, noDeps, wide, verbose)
	}

	// Show additional details if verbose
	if verbose {
		fmt.Println()
		printVerboseDetails(output.Agents)
	}

	return nil
}

// showRegistryStatus displays registry status with proper formatting
func showRegistryStatus(registry RegistryStatus) {
	statusColor := getStatusColor(registry.Status)
	fmt.Printf("Registry: %s%s%s", statusColor, registry.Status, colorReset)

	if registry.URL != "" {
		fmt.Printf(" (%s)", registry.URL)
	}

	if registry.Status == "running" && registry.AgentCount > 0 {
		fmt.Printf(" - %d agents", registry.AgentCount)
	}

	if registry.Uptime != "" {
		fmt.Printf(" - uptime %s", registry.Uptime)
	}

	fmt.Println()
	fmt.Println()
}

// formatAgentTypeDisplay converts agent type to friendly display name
func formatAgentTypeDisplay(agentType string) string {
	switch agentType {
	case "mcp_agent":
		return "Agent"
	case "api":
		return "API"
	case "mesh_tool":
		return "Tool"
	case "decorator_agent":
		return "Agent"
	default:
		return "Unknown"
	}
}

// calculateColumnWidths determines optimal column widths for table alignment
func calculateColumnWidths(agents []EnhancedAgent, wide bool) (nameWidth, statusWidth, typeWidth, endpointWidth int) {
	nameWidth = 15 // minimum width
	statusWidth = 10
	typeWidth = 5 // minimum width for "Type"
	endpointWidth = 20

	for _, agent := range agents {
		if len(agent.Name) > nameWidth {
			nameWidth = len(agent.Name)
		}
		if len(agent.Status) > statusWidth {
			statusWidth = len(agent.Status)
		}
		// Calculate type width
		displayType := formatAgentTypeDisplay(agent.AgentType)
		if len(displayType) > typeWidth {
			typeWidth = len(displayType)
		}
		// Always calculate endpoint width for standard view
		if len(agent.Endpoint) > endpointWidth {
			endpointWidth = len(agent.Endpoint)
		}
	}

	// Add padding
	nameWidth += 2
	statusWidth += 2
	typeWidth += 2
	// Always add endpoint padding for standard view
	endpointWidth += 2

	return nameWidth, statusWidth, typeWidth, endpointWidth
}

// printTableHeader prints the docker-compose-style table header
func printTableHeader(nameWidth, statusWidth, typeWidth, endpointWidth int, noDeps, wide, verbose bool) {
	fmt.Printf("%-*s %-*s %-*s", nameWidth, "NAME", typeWidth, "TYPE", statusWidth, "STATUS")

	if !noDeps {
		fmt.Printf(" %-8s", "DEPS")
	}

	// Always show endpoint in standard view, tools only in wide mode
	fmt.Printf(" %-*s", endpointWidth, "ENDPOINT")

	if wide {
		fmt.Printf(" %-6s", "TOOLS")
		fmt.Printf(" %-12s", "SINCE")
	} else {
		// In standard view, SINCE goes at the end
		fmt.Printf(" %-12s", "SINCE")
	}

	if verbose || wide {
		fmt.Printf(" %-*s", maxCapabilityDisplayWidth, "CAPABILITIES")
	}

	fmt.Println()
}

// printTableSeparator prints a separator line
func printTableSeparator(nameWidth, statusWidth, typeWidth, endpointWidth int, noDeps, wide, verbose bool) {
	totalWidth := nameWidth + statusWidth + typeWidth + 13 // base width including TYPE column
	if !noDeps {
		totalWidth += 9
	}
	// Always include endpoint width in standard view
	totalWidth += endpointWidth + 1
	// Always include SINCE width (12 + 1 for spacing)
	totalWidth += 13
	if wide {
		totalWidth += 7 // for tools column
	}
	if verbose || wide {
		totalWidth += maxCapabilityDisplayWidth + 1
	}

	fmt.Println(strings.Repeat("-", totalWidth))
}

// printAgentRow prints a single agent row in the table
func printAgentRow(agent EnhancedAgent, nameWidth, statusWidth, typeWidth, endpointWidth int, noDeps, wide, verbose bool) {
	// Name column
	fmt.Printf("%-*s", nameWidth, truncateStringForList(agent.Name, nameWidth-2))

	// Type column
	agentTypeDisplay := formatAgentTypeDisplay(agent.AgentType)
	fmt.Printf(" %-*s", typeWidth, agentTypeDisplay)

	// Status column with color
	statusColor := getStatusColor(agent.Status)
	fmt.Printf(" %s%-*s%s", statusColor, statusWidth-1, agent.Status, colorReset)

	// Dependencies column (if not hidden)
	if !noDeps {
		depsStr := formatDependencies(agent.DependenciesResolved, agent.DependenciesTotal)
		// Print dependency string without width specification to avoid color code issues
		fmt.Printf(" %s", depsStr)
		// Pad with spaces to maintain alignment (8 chars total: 3 for "X/Y" + padding)
		depsVisualLen := len(fmt.Sprintf("%d/%d", agent.DependenciesResolved, agent.DependenciesTotal))
		padding := 8 - depsVisualLen
		if padding > 0 {
			fmt.Printf("%s", strings.Repeat(" ", padding))
		}
	}

	// Endpoint column (always shown)
	endpoint := formatEndpoint(agent.Endpoint)
	fmt.Printf(" %-*s", endpointWidth, truncateStringForList(endpoint, endpointWidth-2))

	// Tools count and SINCE (only in wide mode)
	if wide {
		fmt.Printf(" %-6s", fmt.Sprintf("%d", len(agent.Tools)))
		since := formatSince(agent)
		fmt.Printf(" %-12s", since)
	} else {
		// In standard view, SINCE goes at the end
		since := formatSince(agent)
		fmt.Printf(" %-12s", since)
	}

	// Capabilities column (if verbose or wide) - always at the end
	if verbose || wide {
		capabilities := formatCapabilitiesForWide(agent.Tools)
		fmt.Printf(" %-*s", maxCapabilityDisplayWidth, truncateStringForList(capabilities, maxCapabilityDisplayWidth))
	}

	fmt.Println()
}

// Helper functions for formatting
func getStatusColor(status string) string {
	switch strings.ToLower(status) {
	case "healthy", "running":
		return colorGreen
	case "degraded", "warning":
		return colorYellow
	case "unhealthy", "failed", "error":
		return colorRed
	default:
		return colorReset
	}
}

func formatDependencies(resolved, total int) string {
	// Always show the dependency count, even if 0/0
	color := colorGreen
	if resolved < total {
		if resolved == 0 {
			color = colorRed    // No dependencies resolved
		} else {
			color = colorYellow // Partially resolved
		}
	}
	// Fully resolved (or no dependencies) = green
	return fmt.Sprintf("%s%d/%d%s", color, resolved, total, colorReset)
}

func formatSince(agent EnhancedAgent) string {
	var since time.Time
	if agent.LastHeartbeat != nil && !agent.LastHeartbeat.IsZero() {
		since = *agent.LastHeartbeat
	} else if !agent.StartTime.IsZero() {
		since = agent.StartTime
	} else if !agent.CreatedAt.IsZero() {
		since = agent.CreatedAt
	} else {
		return "-"
	}
	return formatDuration(time.Since(since))
}

func formatEndpoint(endpoint string) string {
	if endpoint == "" {
		return "-"
	}

	// Parse and format URL nicely
	if parsed, err := url.Parse(endpoint); err == nil {
		if parsed.Host != "" {
			return parsed.Host
		}
	}

	// Handle stdio:// endpoints
	if strings.HasPrefix(endpoint, "stdio://") {
		return "stdio"
	}

	return endpoint
}

func truncateStringForList(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	if maxLen <= 3 {
		return s[:maxLen]
	}
	return s[:maxLen-3] + "..."
}

// printVerboseDetails shows additional information in verbose mode
func printVerboseDetails(agents []EnhancedAgent) {
	for _, agent := range agents {
		fmt.Printf("=== %s ===\n", agent.Name)
		fmt.Printf("  ID: %s\n", agent.ID)
		fmt.Printf("  Endpoint: %s\n", agent.Endpoint)
		fmt.Printf("  Version: %s\n", agent.Version)

		if agent.PID > 0 {
			fmt.Printf("  PID: %d\n", agent.PID)
		}

		if agent.FilePath != "" {
			fmt.Printf("  File: %s\n", agent.FilePath)
		}

		if len(agent.Tools) > 0 {
			fmt.Printf("  Tools:\n")
			for _, tool := range agent.Tools {
				fmt.Printf("    - %s (%s)\n", tool.Name, tool.Capability)
			}
		}

		fmt.Println()
	}
}

func formatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%.0fs", d.Seconds())
	}
	if d < time.Hour {
		return fmt.Sprintf("%.0fm", d.Minutes())
	}
	if d < 24*time.Hour {
		hours := int(d.Hours())
		minutes := int(d.Minutes()) % 60
		if minutes == 0 {
			return fmt.Sprintf("%dh", hours)
		}
		return fmt.Sprintf("%dh%dm", hours, minutes)
	}
	days := int(d.Hours()) / 24
	hours := int(d.Hours()) % 24
	if hours == 0 {
		return fmt.Sprintf("%dd", days)
	}
	return fmt.Sprintf("%dd%dh", days, hours)
}

// determineRegistryURL resolves the final registry URL based on flags and config
func determineRegistryURL(config *CLIConfig, registryURL, registryHost string, registryPort int, registryScheme string) string {
	// Priority: explicit registry-url flag > individual flags > config

	// If full URL is provided, use it directly
	if registryURL != "" {
		if parsed, err := url.Parse(registryURL); err == nil && parsed.Scheme != "" && parsed.Host != "" {
			return registryURL
		}
	}

	// Build URL from individual components
	host := config.RegistryHost
	port := config.RegistryPort
	scheme := "http"

	// Override with flags if provided
	if registryHost != "" {
		host = registryHost
	}
	if registryPort > 0 {
		port = registryPort
	}
	if registryScheme != "" {
		scheme = registryScheme
	}

	return fmt.Sprintf("%s://%s:%d", scheme, host, port)
}

// Global HTTP client for registry connections
var registryHTTPClient = &http.Client{
	Timeout: 10 * time.Second,
}

// configureHTTPClient sets up the HTTP client with the specified timeout
func configureHTTPClient(timeoutSeconds int) {
	registryHTTPClient = &http.Client{
		Timeout: time.Duration(timeoutSeconds) * time.Second,
	}
}

// filterAgentsSince filters agents by last activity time
func filterAgentsSince(agents []EnhancedAgent, since string) ([]EnhancedAgent, error) {
	duration, err := time.ParseDuration(since)
	if err != nil {
		return nil, fmt.Errorf("invalid duration format: %s (use formats like 1h, 30m, 24h)", since)
	}

	cutoff := time.Now().Add(-duration)
	var filtered []EnhancedAgent

	for _, agent := range agents {
		var lastActivity time.Time

		if agent.LastHeartbeat != nil {
			lastActivity = *agent.LastHeartbeat
		} else if !agent.UpdatedAt.IsZero() {
			lastActivity = agent.UpdatedAt
		} else if !agent.CreatedAt.IsZero() {
			lastActivity = agent.CreatedAt
		} else {
			continue // Skip agents with no time information
		}

		if lastActivity.After(cutoff) {
			filtered = append(filtered, agent)
		}
	}

	return filtered, nil
}

// filterHealthyAgents filters for only healthy agents
func filterHealthyAgents(agents []EnhancedAgent) []EnhancedAgent {
	var filtered []EnhancedAgent
	for _, agent := range agents {
		if strings.ToLower(agent.Status) == "healthy" || strings.ToLower(agent.Status) == "running" {
			filtered = append(filtered, agent)
		}
	}
	return filtered
}

// outputAgentDetails shows detailed information for a specific agent
func outputAgentDetails(agents []EnhancedAgent, agentID string, jsonOutput bool) error {
	var targetAgent *EnhancedAgent

	// Find the requested agent
	for _, agent := range agents {
		if agent.ID == agentID {
			targetAgent = &agent
			break
		}
	}

	if targetAgent == nil {
		return fmt.Errorf("agent with ID '%s' not found", agentID)
	}

	if jsonOutput {
		jsonData, err := json.MarshalIndent(targetAgent, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to encode agent details as JSON: %w", err)
		}
		fmt.Println(string(jsonData))
		return nil
	}

	// Show detailed agent information in vertical format
	fmt.Printf("%sAgent Details: %s%s\n", colorBlue, agentID, colorReset)
	fmt.Println(strings.Repeat("=", 80))

	// Basic information
	fmt.Printf("%-20s: %s\n", "Name", targetAgent.Name)
	fmt.Printf("%-20s: %s\n", "Type", formatAgentTypeDisplay(targetAgent.AgentType))
	fmt.Printf("%-20s: %s%s%s\n", "Status", getStatusColor(targetAgent.Status), targetAgent.Status, colorReset)
	fmt.Printf("%-20s: %s\n", "Endpoint", targetAgent.Endpoint)
	if targetAgent.Version != "" {
		fmt.Printf("%-20s: %s\n", "Version", targetAgent.Version)
	}

	// Dependency information
	depsStr := formatDependencies(targetAgent.DependenciesResolved, targetAgent.DependenciesTotal)
	fmt.Printf("%-20s: %s\n", "Dependencies", depsStr)

	// Timing information
	if targetAgent.LastHeartbeat != nil {
		fmt.Printf("%-20s: %s (%s ago)\n", "Last Seen",
			targetAgent.LastHeartbeat.Format("2006-01-02 15:04:05"),
			formatDuration(time.Since(*targetAgent.LastHeartbeat)))
	}
	if !targetAgent.CreatedAt.IsZero() {
		fmt.Printf("%-20s: %s\n", "Created", targetAgent.CreatedAt.Format("2006-01-02 15:04:05"))
	}
	if !targetAgent.UpdatedAt.IsZero() {
		fmt.Printf("%-20s: %s\n", "Updated", targetAgent.UpdatedAt.Format("2006-01-02 15:04:05"))
	}

	// Process information (if available)
	if targetAgent.PID > 0 {
		fmt.Printf("%-20s: %d\n", "PID", targetAgent.PID)
	}
	if targetAgent.FilePath != "" {
		fmt.Printf("%-20s: %s\n", "File Path", targetAgent.FilePath)
	}
	if !targetAgent.StartTime.IsZero() {
		fmt.Printf("%-20s: %s (running for %s)\n", "Start Time",
			targetAgent.StartTime.Format("2006-01-02 15:04:05"),
			formatDuration(time.Since(targetAgent.StartTime)))
	}

	// Capabilities/Tools
	if len(targetAgent.Tools) > 0 {
		fmt.Printf("\n%sCapabilities (%d):%s\n", colorBlue, len(targetAgent.Tools), colorReset)
		fmt.Println(strings.Repeat("-", 80))

		// Print table header
		fmt.Printf("%-25s %-30s %-10s %-15s\n", "CAPABILITY", "MCP TOOL", "VERSION", "TAGS")
		fmt.Println(strings.Repeat("-", 80))

		// Print each capability as a table row
		for _, tool := range targetAgent.Tools {
			capability := tool.Capability
			if capability == "" {
				capability = tool.Name
			}

			functionName := tool.FunctionName
			if functionName == "" {
				functionName = tool.Name
			}

			version := tool.Version
			if version == "" {
				version = "-"
			}

			tags := "-"
			if len(tool.Tags) > 0 {
				tags = strings.Join(tool.Tags, ",")
			}

			fmt.Printf("%-25s %-30s %-10s %-15s\n",
				capability,
				functionName,
				version,
				tags)
		}
	}

	// Dependency Resolutions
	if len(targetAgent.DependencyResolutions) > 0 {
		fmt.Printf("\n%sDependencies (%d):%s\n", colorBlue, len(targetAgent.DependencyResolutions), colorReset)
		fmt.Println(strings.Repeat("-", 80))

		// Print table header
		fmt.Printf("%-30s %-30s %-40s\n", "DEPENDENCY", "MCP TOOL", "ENDPOINT")
		fmt.Println(strings.Repeat("-", 80))

		// Print each dependency as a table row
		for _, dep := range targetAgent.DependencyResolutions {
			mcpTool := dep.MCPTool
			url := dep.Endpoint
			lineColor := ""

			// Handle unresolved dependencies - show entire line in red
			if dep.Status == "unresolved" {
				mcpTool = "NOT FOUND"
				url = "-"
				lineColor = colorRed
			}

			fmt.Printf("%s%-30s %-30s %-40s%s\n",
				lineColor,
				dep.Capability,
				mcpTool,
				url,
				colorReset)
		}
	}

	// Configuration (if available)
	if len(targetAgent.Config) > 0 {
		fmt.Printf("\n%sConfiguration:%s\n", colorBlue, colorReset)
		fmt.Println(strings.Repeat("-", 80))
		for key, value := range targetAgent.Config {
			fmt.Printf("  %s: %v\n", key, value)
		}
	}

	// Labels (if available)
	if len(targetAgent.Labels) > 0 {
		fmt.Printf("\n%sLabels:%s\n", colorBlue, colorReset)
		fmt.Println(strings.Repeat("-", 80))
		for key, value := range targetAgent.Labels {
			fmt.Printf("  %s: %v\n", key, value)
		}
	}

	return nil
}

// formatCapabilitiesForWide formats capabilities list for wide display with truncation
func formatCapabilitiesForWide(tools []ToolInfo) string {
	if len(tools) == 0 {
		return "-"
	}

	var capabilities []string
	for _, tool := range tools {
		if tool.Name != "" {
			capabilities = append(capabilities, tool.Name)
		} else if tool.Capability != "" {
			capabilities = append(capabilities, tool.Capability)
		}
	}

	if len(capabilities) == 0 {
		return "-"
	}

	// Join capabilities with commas
	result := strings.Join(capabilities, ", ")

	// Truncate if too long
	if len(result) <= maxCapabilityDisplayWidth {
		return result
	}

	// Find where to truncate and add "(X more)"
	truncated := ""
	count := 0
	currentLen := 0

	for i, cap := range capabilities {
		newLen := currentLen + len(cap)
		if i > 0 {
			newLen += 2 // for ", "
		}

		// Check if adding this capability would exceed limit (accounting for "(X more)")
		remaining := len(capabilities) - i - 1
		if remaining > 0 {
			moreText := fmt.Sprintf(" (%d more)", remaining)
			if newLen+len(moreText) > maxCapabilityDisplayWidth {
				truncated += fmt.Sprintf(" (%d more)", remaining)
				break
			}
		}

		if i > 0 {
			truncated += ", "
			currentLen += 2
		}
		truncated += cap
		currentLen += len(cap)
		count++
	}

	return truncated
}
