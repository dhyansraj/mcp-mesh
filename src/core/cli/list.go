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

// NewListCommand creates the list command
func NewListCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List running agents with docker-compose style display",
		Long: `List all running MCP Mesh agents with a beautiful table display.

Shows agent status, dependency resolution, uptime, and endpoint information
in a docker-compose-style format for easy monitoring.

Examples:
  mcp-mesh-dev list                                    # Show beautiful table with all agents
  mcp-mesh-dev list --json                             # Output in JSON format
  mcp-mesh-dev list --filter hello                     # Filter agents by name pattern
  mcp-mesh-dev list --no-deps                          # Hide dependency status
  mcp-mesh-dev list --wide                             # Show endpoints and tool counts
  mcp-mesh-dev list --registry-url http://remote:8000  # Connect to remote registry
  mcp-mesh-dev list --registry-host prod.example.com   # Connect to remote host
  mcp-mesh-dev list --registry-port 9000               # Use custom port`,
		RunE: runListCommand,
	}

	// Enhanced flags for better UX
	cmd.Flags().String("filter", "", "Filter by name pattern")
	cmd.Flags().Bool("json", false, "Output in JSON format")
	cmd.Flags().Bool("verbose", false, "Show detailed information")
	cmd.Flags().Bool("no-deps", false, "Hide dependency status")
	cmd.Flags().Bool("wide", false, "Show additional columns")

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
	ID                   string                 `json:"id"`
	Name                 string                 `json:"name"`
	Status               string                 `json:"status"`
	Endpoint             string                 `json:"endpoint"`
	Tools                []ToolInfo             `json:"tools"`
	Dependencies         []Dependency           `json:"dependencies"`
	DependenciesResolved int                    `json:"dependencies_resolved"`
	DependenciesTotal    int                    `json:"dependencies_total"`
	LastHeartbeat        *time.Time             `json:"last_heartbeat,omitempty"`
	CreatedAt            time.Time              `json:"created_at"`
	UpdatedAt            time.Time              `json:"updated_at"`
	Version              string                 `json:"version,omitempty"`
	PID                  int                    `json:"pid,omitempty"`
	FilePath             string                 `json:"file_path,omitempty"`
	StartTime            time.Time              `json:"start_time,omitempty"`
	Config               map[string]interface{} `json:"config,omitempty"`
	Labels               map[string]interface{} `json:"labels,omitempty"`
}

// ToolInfo represents tool/capability information
type ToolInfo struct {
	ID           int      `json:"id"`
	Name         string   `json:"name"`
	Capability   string   `json:"capability"`
	Version      string   `json:"version"`
	Dependencies []string `json:"dependencies,omitempty"`
}

// Dependency represents a resolved dependency
type Dependency struct {
	Name     string `json:"name"`
	Status   string `json:"status"` // "resolved", "missing", "unhealthy"
	AgentID  string `json:"agent_id,omitempty"`
	Endpoint string `json:"endpoint,omitempty"`
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

	// Apply filters
	if filterPattern != "" {
		output.Agents = filterEnhancedAgents(output.Agents, filterPattern)
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

// getDetailedAgents fetches detailed agent information from registry
func getDetailedAgents(registryURL string) ([]map[string]interface{}, error) {
	agentsURL := registryURL + "/agents"
	resp, err := registryHTTPClient.Get(agentsURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("registry returned status %d", resp.StatusCode)
	}

	var response struct {
		Agents []map[string]interface{} `json:"agents"`
		Count  int                      `json:"count"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode registry response: %w", err)
	}

	return response.Agents, nil
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
		ID:       getString(data, "id"),
		Name:     getString(data, "name"),
		Status:   getString(data, "status"),
		Endpoint: getString(data, "endpoint"),
		Version:  getString(data, "version"),
		Config:   getMapInterface(data, "config"),
		Labels:   getMapInterface(data, "labels"),
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
	if lastHeartbeatStr := getString(data, "last_heartbeat"); lastHeartbeatStr != "" {
		if t, err := time.Parse(time.RFC3339, lastHeartbeatStr); err == nil {
			agent.LastHeartbeat = &t
		}
	}

	// Process capabilities/tools
	if capabilities, ok := data["capabilities"].([]interface{}); ok {
		for _, cap := range capabilities {
			if capMap, ok := cap.(map[string]interface{}); ok {
				tool := ToolInfo{
					Name:       getString(capMap, "name"),
					Capability: getString(capMap, "capability"),
					Version:    getString(capMap, "version"),
				}
				if id := getFloat(capMap, "id"); id > 0 {
					tool.ID = int(id)
				}
				agent.Tools = append(agent.Tools, tool)
			}
		}
	}

	// Calculate dependencies (simplified for now - in real implementation, would query dependencies)
	agent.Dependencies = calculateDependencies(agent.Tools)
	agent.DependenciesTotal = len(agent.Dependencies)
	agent.DependenciesResolved = countResolvedDependencies(agent.Dependencies)

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
		if f, ok := val.(float64); ok {
			return f
		}
	}
	return 0
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
	nameWidth, statusWidth, endpointWidth := calculateColumnWidths(output.Agents, wide)

	// Print header
	printTableHeader(nameWidth, statusWidth, endpointWidth, noDeps, wide)
	printTableSeparator(nameWidth, statusWidth, endpointWidth, noDeps, wide)

	// Print agent rows
	for _, agent := range output.Agents {
		printAgentRow(agent, nameWidth, statusWidth, endpointWidth, noDeps, wide)
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

// calculateColumnWidths determines optimal column widths for table alignment
func calculateColumnWidths(agents []EnhancedAgent, wide bool) (nameWidth, statusWidth, endpointWidth int) {
	nameWidth = 15 // minimum width
	statusWidth = 10
	endpointWidth = 20

	for _, agent := range agents {
		if len(agent.Name) > nameWidth {
			nameWidth = len(agent.Name)
		}
		if len(agent.Status) > statusWidth {
			statusWidth = len(agent.Status)
		}
		if wide && len(agent.Endpoint) > endpointWidth {
			endpointWidth = len(agent.Endpoint)
		}
	}

	// Add padding
	nameWidth += 2
	statusWidth += 2
	if wide {
		endpointWidth += 2
	}

	return nameWidth, statusWidth, endpointWidth
}

// printTableHeader prints the docker-compose-style table header
func printTableHeader(nameWidth, statusWidth, endpointWidth int, noDeps, wide bool) {
	fmt.Printf("%-*s %-*s", nameWidth, "NAME", statusWidth, "STATUS")

	if !noDeps {
		fmt.Printf(" %-8s", "DEPS")
	}

	fmt.Printf(" %-12s", "SINCE")

	if wide {
		fmt.Printf(" %-*s", endpointWidth, "ENDPOINT")
		fmt.Printf(" %-6s", "TOOLS")
	}

	fmt.Println()
}

// printTableSeparator prints a separator line
func printTableSeparator(nameWidth, statusWidth, endpointWidth int, noDeps, wide bool) {
	totalWidth := nameWidth + statusWidth + 13 // base width
	if !noDeps {
		totalWidth += 9
	}
	if wide {
		totalWidth += endpointWidth + 7
	}

	fmt.Println(strings.Repeat("-", totalWidth))
}

// printAgentRow prints a single agent row in the table
func printAgentRow(agent EnhancedAgent, nameWidth, statusWidth, endpointWidth int, noDeps, wide bool) {
	// Name column
	fmt.Printf("%-*s", nameWidth, truncateStringForList(agent.Name, nameWidth-2))

	// Status column with color
	statusColor := getStatusColor(agent.Status)
	fmt.Printf(" %s%-*s%s", statusColor, statusWidth-1, agent.Status, colorReset)

	// Dependencies column (if not hidden)
	if !noDeps {
		depsStr := formatDependencies(agent.DependenciesResolved, agent.DependenciesTotal)
		fmt.Printf(" %-8s", depsStr)
	}

	// Since column (uptime)
	since := formatSince(agent)
	fmt.Printf(" %-12s", since)

	// Wide mode columns
	if wide {
		// Endpoint column
		endpoint := formatEndpoint(agent.Endpoint)
		fmt.Printf(" %-*s", endpointWidth, truncateStringForList(endpoint, endpointWidth-2))

		// Tools count
		fmt.Printf(" %-6s", fmt.Sprintf("%d", len(agent.Tools)))
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
	if total == 0 {
		return "-"
	}
	color := colorGreen
	if resolved < total {
		color = colorYellow
	}
	if resolved == 0 && total > 0 {
		color = colorRed
	}
	return fmt.Sprintf("%s%d/%d%s", color, resolved, total, colorReset)
}

func formatSince(agent EnhancedAgent) string {
	var since time.Time
	if !agent.StartTime.IsZero() {
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
