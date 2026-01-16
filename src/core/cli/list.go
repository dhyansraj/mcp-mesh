package cli

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// Color constants for beautiful output
const (
	colorReset   = "\033[0m"
	colorRed     = "\033[31m"
	colorGreen   = "\033[32m"
	colorYellow  = "\033[33m"
	colorBlue    = "\033[34m"
	colorMagenta = "\033[35m"
	colorCyan    = "\033[36m"
	colorGray    = "\033[37m"
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

By default, only healthy agents are shown. Use --all to see all agents
including unhealthy/expired ones.

Examples:
  meshctl list                                    # Show healthy agents only (default)
  meshctl list --all                              # Show all agents including unhealthy
  meshctl list --json                             # Output in JSON format
  meshctl list --filter hello                     # Filter agents by name pattern
  meshctl list --no-deps                          # Hide dependency status
  meshctl list --wide                             # Show endpoints and tool counts
  meshctl list --registry-url http://remote:8000  # Connect to remote registry
  meshctl list --registry-host prod.example.com   # Connect to remote host
  meshctl list --registry-port 9000               # Use custom port

Tools listing:
  meshctl list --tools                            # List all tools across all agents
  meshctl list -t                                 # Short form (list all tools)
  meshctl list --tools=get_current_time           # Show tool call spec and input schema
  meshctl list --tools=system-agent:get_time      # Show tool details for specific agent`,
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
	cmd.Flags().Bool("all", false, "Show all agents including unhealthy/expired (default: healthy only)")

	// Tools listing - use --tools to list all, --tools=<name> for specific tool details
	cmd.Flags().StringP("tools", "t", "", "List tools: use --tools or -t to list all, --tools=<tool> for details")
	cmd.Flags().Lookup("tools").NoOptDefVal = "all" // "all" means list all tools

	// Remote registry connection flags
	cmd.Flags().String("registry-url", "", "Registry URL (overrides host/port)")
	cmd.Flags().String("registry-host", "", "Registry host (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port (default: 8000)")
	cmd.Flags().String("registry-scheme", "http", "Registry URL scheme (http/https)")
	cmd.Flags().Bool("insecure", false, "Skip TLS certificate verification")
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
	Status         string    `json:"status"`
	URL            string    `json:"url,omitempty"`
	AgentCount     int       `json:"agent_count,omitempty"`
	HealthyCount   int       `json:"healthy_count,omitempty"`
	UnhealthyCount int       `json:"unhealthy_count,omitempty"`
	Error          string    `json:"error,omitempty"`
	Uptime         string    `json:"uptime,omitempty"`
	StartTime      time.Time `json:"start_time,omitempty"`
}

// EnhancedAgent contains comprehensive agent information for display
type EnhancedAgent struct {
	ID                       string                   `json:"id"`
	Name                     string                   `json:"name"`
	AgentType                string                   `json:"agent_type"`
	Status                   string                   `json:"status"`
	Runtime                  string                   `json:"runtime,omitempty"`
	Endpoint                 string                   `json:"endpoint"`
	Tools                    []ToolInfo               `json:"tools"`
	Dependencies             []Dependency             `json:"dependencies"`
	DependencyResolutions    []DependencyResolution   `json:"dependency_resolutions,omitempty"`
	LLMToolResolutions       []LLMToolResolution      `json:"llm_tool_resolutions,omitempty"`
	LLMProviderResolutions   []LLMProviderResolution  `json:"llm_provider_resolutions,omitempty"`
	DependenciesResolved     int                      `json:"dependencies_resolved"`
	DependenciesTotal        int                      `json:"dependencies_total"`
	LastHeartbeat            *time.Time               `json:"last_heartbeat,omitempty"`
	CreatedAt                time.Time                `json:"created_at"`
	UpdatedAt                time.Time                `json:"updated_at"`
	Version                  string                   `json:"version,omitempty"`
	PID                      int                      `json:"pid,omitempty"`
	FilePath                 string                   `json:"file_path,omitempty"`
	StartTime                time.Time                `json:"start_time,omitempty"`
	Config                   map[string]interface{}   `json:"config,omitempty"`
	Labels                   map[string]interface{}   `json:"labels,omitempty"`
}

// ToolFilter represents a single filter specification for matching tools
type ToolFilter struct {
	Capability string   `json:"capability,omitempty"`
	Tags       []string `json:"tags,omitempty"`
	Version    string   `json:"version,omitempty"`
	Namespace  string   `json:"namespace,omitempty"`
}

// LLMToolFilter represents LLM tool filter specification from @mesh.llm decorator
type LLMToolFilter struct {
	Filter     []ToolFilter `json:"filter,omitempty"`
	FilterMode string       `json:"filter_mode,omitempty"`
}

// LLMProvider represents LLM provider specification for mesh delegation
type LLMProvider struct {
	Capability string   `json:"capability,omitempty"`
	Tags       []string `json:"tags,omitempty"`
	Version    string   `json:"version,omitempty"`
	Namespace  string   `json:"namespace,omitempty"`
}

// LLMToolResolution represents a resolved LLM tool from @mesh.llm filter
type LLMToolResolution struct {
	FunctionName       string   `json:"function_name"`
	FilterCapability   string   `json:"filter_capability,omitempty"`
	FilterTags         []string `json:"filter_tags,omitempty"`
	FilterMode         string   `json:"filter_mode,omitempty"`
	MCPTool            string   `json:"mcp_tool,omitempty"`
	ProviderCapability string   `json:"provider_capability,omitempty"`
	ProviderAgentID    string   `json:"provider_agent_id,omitempty"`
	Endpoint           string   `json:"endpoint,omitempty"`
	Status             string   `json:"status"`
}

// LLMProviderResolution represents a resolved LLM provider from @mesh.llm provider
type LLMProviderResolution struct {
	FunctionName       string   `json:"function_name"`
	RequiredCapability string   `json:"required_capability"`
	RequiredTags       []string `json:"required_tags,omitempty"`
	MCPTool            string   `json:"mcp_tool,omitempty"`
	ProviderAgentID    string   `json:"provider_agent_id,omitempty"`
	Endpoint           string   `json:"endpoint,omitempty"`
	Status             string   `json:"status"`
}

// ToolInfo represents tool/capability information
type ToolInfo struct {
	ID           int            `json:"id"`
	Name         string         `json:"name"`
	Capability   string         `json:"capability"`
	FunctionName string         `json:"function_name"`
	Version      string         `json:"version"`
	Tags         []string       `json:"tags,omitempty"`
	Dependencies []string       `json:"dependencies,omitempty"`
	LLMFilter    *LLMToolFilter `json:"llm_filter,omitempty"`
	LLMProvider  *LLMProvider   `json:"llm_provider,omitempty"`
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
	showAll, _ := cmd.Flags().GetBool("all")

	// Tools listing flag
	toolsFlag, _ := cmd.Flags().GetString("tools")
	toolsFlagChanged := cmd.Flags().Changed("tools")

	// Registry connection flags
	registryURL, _ := cmd.Flags().GetString("registry-url")
	registryHost, _ := cmd.Flags().GetString("registry-host")
	registryPort, _ := cmd.Flags().GetInt("registry-port")
	registryScheme, _ := cmd.Flags().GetString("registry-scheme")
	insecure, _ := cmd.Flags().GetBool("insecure")
	timeout, _ := cmd.Flags().GetInt("timeout")

	// Determine final registry URL
	finalRegistryURL := determineRegistryURL(config, registryURL, registryHost, registryPort, registryScheme)

	// Configure HTTP client with timeout and TLS settings
	configureHTTPClientWithTLS(timeout, insecure)

	// Handle tools listing mode
	if toolsFlagChanged {
		return runToolsListCommand(finalRegistryURL, toolsFlag, jsonOutput, !showAll)
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

	// Apply time-based filtering
	if sinceFlag != "" {
		filtered, err := filterAgentsSince(output.Agents, sinceFlag)
		if err != nil {
			return fmt.Errorf("invalid --since duration: %w", err)
		}
		output.Agents = filtered
	}

	// Apply healthy-only filter by default (unless --all is specified)
	if !showAll {
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

		// Get agent count with healthy/unhealthy breakdown
		if agents, err := getDetailedAgents(registryURL); err == nil {
			status.AgentCount = len(agents)
			for _, agent := range agents {
				agentStatus := strings.ToLower(getString(agent, "status"))
				if agentStatus == "healthy" || agentStatus == "running" {
					status.HealthyCount++
				} else {
					status.UnhealthyCount++
				}
			}
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
	Runtime              *string     `json:"runtime,omitempty"`
	Endpoint             string      `json:"endpoint"`
	Version              *string     `json:"version,omitempty"`
	LastSeen             *time.Time  `json:"last_seen,omitempty"`
	TotalDependencies    int         `json:"total_dependencies"`
	DependenciesResolved int         `json:"dependencies_resolved"`
	Capabilities         []struct {
		Name         string         `json:"name"`
		Version      string         `json:"version"`
		FunctionName string         `json:"function_name"`
		Description  *string        `json:"description,omitempty"`
		Tags         []string       `json:"tags,omitempty"`
		LlmFilter    *LLMToolFilter `json:"llm_filter,omitempty"`
		LlmProvider  *LLMProvider   `json:"llm_provider,omitempty"`
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
	LLMToolResolutions []struct {
		ConsumerFunctionName string   `json:"function_name"`
		FilterCapability     string   `json:"filter_capability,omitempty"`
		FilterTags           []string `json:"filter_tags,omitempty"`
		FilterMode           string   `json:"filter_mode,omitempty"`
		ProviderAgentID      string   `json:"provider_agent_id,omitempty"`
		ProviderFunctionName string   `json:"mcp_tool,omitempty"`
		ProviderCapability   string   `json:"provider_capability,omitempty"`
		Endpoint             string   `json:"endpoint,omitempty"`
		Status               string   `json:"status"`
	} `json:"llm_tool_resolutions,omitempty"`
	LLMProviderResolutions []struct {
		ConsumerFunctionName string   `json:"function_name"`
		RequiredCapability   string   `json:"required_capability"`
		RequiredTags         []string `json:"required_tags,omitempty"`
		ProviderAgentID      string   `json:"provider_agent_id,omitempty"`
		ProviderFunctionName string   `json:"mcp_tool,omitempty"`
		Endpoint             string   `json:"endpoint,omitempty"`
		Status               string   `json:"status"`
	} `json:"llm_provider_resolutions,omitempty"`
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

		if agent.Runtime != nil {
			agentMap["runtime"] = *agent.Runtime
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
			if cap.LlmFilter != nil {
				capMap["llm_filter"] = cap.LlmFilter
			}
			if cap.LlmProvider != nil {
				capMap["llm_provider"] = cap.LlmProvider
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

		// Convert LLM tool resolutions to the expected format
		// Use API field names for consistency
		if len(agent.LLMToolResolutions) > 0 {
			llmToolRes := make([]interface{}, len(agent.LLMToolResolutions))
			for j, res := range agent.LLMToolResolutions {
				resMap := map[string]interface{}{
					"function_name":       res.ConsumerFunctionName,
					"filter_capability":   res.FilterCapability,
					"filter_mode":         res.FilterMode,
					"provider_agent_id":   res.ProviderAgentID,
					"mcp_tool":            res.ProviderFunctionName,
					"provider_capability": res.ProviderCapability,
					"endpoint":            res.Endpoint,
					"status":              res.Status,
				}
				if len(res.FilterTags) > 0 {
					resMap["filter_tags"] = res.FilterTags
				}
				llmToolRes[j] = resMap
			}
			agentMap["llm_tool_resolutions"] = llmToolRes
		}

		// Convert LLM provider resolutions to the expected format
		// Use API field names for consistency
		if len(agent.LLMProviderResolutions) > 0 {
			llmProviderRes := make([]interface{}, len(agent.LLMProviderResolutions))
			for j, res := range agent.LLMProviderResolutions {
				resMap := map[string]interface{}{
					"function_name":     res.ConsumerFunctionName,
					"required_capability": res.RequiredCapability,
					"provider_agent_id": res.ProviderAgentID,
					"mcp_tool":          res.ProviderFunctionName,
					"endpoint":          res.Endpoint,
					"status":            res.Status,
				}
				if len(res.RequiredTags) > 0 {
					resMap["required_tags"] = res.RequiredTags
				}
				llmProviderRes[j] = resMap
			}
			agentMap["llm_provider_resolutions"] = llmProviderRes
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
		Runtime:   getString(data, "runtime"),
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
				// Parse LLM filter if present
				if llmFilter, ok := capMap["llm_filter"].(*LLMToolFilter); ok {
					tool.LLMFilter = llmFilter
				} else if llmFilterMap, ok := capMap["llm_filter"].(map[string]interface{}); ok {
					tool.LLMFilter = parseLLMToolFilter(llmFilterMap)
				}
				// Parse LLM provider if present
				if llmProvider, ok := capMap["llm_provider"].(*LLMProvider); ok {
					tool.LLMProvider = llmProvider
				} else if llmProviderMap, ok := capMap["llm_provider"].(map[string]interface{}); ok {
					tool.LLMProvider = parseLLMProvider(llmProviderMap)
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

	// Parse LLM tool resolutions from API
	if llmToolResolutions, ok := data["llm_tool_resolutions"].([]interface{}); ok {
		for _, res := range llmToolResolutions {
			if resMap, ok := res.(map[string]interface{}); ok {
				// Try both field name formats for compatibility
				funcName := getString(resMap, "function_name")
				if funcName == "" {
					funcName = getString(resMap, "consumer_function_name")
				}
				mcpTool := getString(resMap, "mcp_tool")
				if mcpTool == "" {
					mcpTool = getString(resMap, "provider_function_name")
				}
				resolution := LLMToolResolution{
					FunctionName:       funcName,
					FilterCapability:   getString(resMap, "filter_capability"),
					FilterMode:         getString(resMap, "filter_mode"),
					MCPTool:            mcpTool,
					ProviderCapability: getString(resMap, "provider_capability"),
					ProviderAgentID:    getString(resMap, "provider_agent_id"),
					Endpoint:           getString(resMap, "endpoint"),
					Status:             getString(resMap, "status"),
				}

				// Parse filter tags if present
				if tagsSlice, ok := resMap["filter_tags"].([]string); ok {
					resolution.FilterTags = tagsSlice
				} else if tagsData, ok := resMap["filter_tags"].([]interface{}); ok {
					for _, tag := range tagsData {
						if tagStr, ok := tag.(string); ok {
							resolution.FilterTags = append(resolution.FilterTags, tagStr)
						}
					}
				}

				agent.LLMToolResolutions = append(agent.LLMToolResolutions, resolution)
			}
		}
	}

	// Parse LLM provider resolutions from API
	if llmProviderResolutions, ok := data["llm_provider_resolutions"].([]interface{}); ok {
		for _, res := range llmProviderResolutions {
			if resMap, ok := res.(map[string]interface{}); ok {
				// Try both field name formats for compatibility
				funcName := getString(resMap, "function_name")
				if funcName == "" {
					funcName = getString(resMap, "consumer_function_name")
				}
				mcpTool := getString(resMap, "mcp_tool")
				if mcpTool == "" {
					mcpTool = getString(resMap, "provider_function_name")
				}
				resolution := LLMProviderResolution{
					FunctionName:       funcName,
					RequiredCapability: getString(resMap, "required_capability"),
					MCPTool:            mcpTool,
					ProviderAgentID:    getString(resMap, "provider_agent_id"),
					Endpoint:           getString(resMap, "endpoint"),
					Status:             getString(resMap, "status"),
				}

				// Parse required tags if present
				if tagsSlice, ok := resMap["required_tags"].([]string); ok {
					resolution.RequiredTags = tagsSlice
				} else if tagsData, ok := resMap["required_tags"].([]interface{}); ok {
					for _, tag := range tagsData {
						if tagStr, ok := tag.(string); ok {
							resolution.RequiredTags = append(resolution.RequiredTags, tagStr)
						}
					}
				}

				agent.LLMProviderResolutions = append(agent.LLMProviderResolutions, resolution)
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

// parseToolFilterSpec converts a map to ToolFilter (for LLM filter parsing)
func parseToolFilterSpec(data map[string]interface{}) ToolFilter {
	tf := ToolFilter{
		Capability: getString(data, "capability"),
		Version:    getString(data, "version"),
		Namespace:  getString(data, "namespace"),
	}
	// Parse tags
	if tagsSlice, ok := data["tags"].([]string); ok {
		tf.Tags = tagsSlice
	} else if tagsData, ok := data["tags"].([]interface{}); ok {
		for _, tag := range tagsData {
			if tagStr, ok := tag.(string); ok {
				tf.Tags = append(tf.Tags, tagStr)
			}
		}
	}
	return tf
}

func parseLLMToolFilter(data map[string]interface{}) *LLMToolFilter {
	if len(data) == 0 {
		return nil
	}
	llmFilter := &LLMToolFilter{
		FilterMode: getString(data, "filter_mode"),
	}
	// Parse filter array
	if filterArray, ok := data["filter"].([]interface{}); ok {
		for _, item := range filterArray {
			if filterMap, ok := item.(map[string]interface{}); ok {
				llmFilter.Filter = append(llmFilter.Filter, parseToolFilterSpec(filterMap))
			}
		}
	}
	return llmFilter
}

// parseLLMProvider converts a map to LLMProvider
func parseLLMProvider(data map[string]interface{}) *LLMProvider {
	if len(data) == 0 {
		return nil
	}
	provider := &LLMProvider{
		Capability: getString(data, "capability"),
		Version:    getString(data, "version"),
		Namespace:  getString(data, "namespace"),
	}
	// Parse tags
	if tagsSlice, ok := data["tags"].([]string); ok {
		provider.Tags = tagsSlice
	} else if tagsData, ok := data["tags"].([]interface{}); ok {
		for _, tag := range tagsData {
			if tagStr, ok := tag.(string); ok {
				provider.Tags = append(provider.Tags, tagStr)
			}
		}
	}
	return provider
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
	nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth := calculateColumnWidths(output.Agents, wide)

	// Print header
	printTableHeader(nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth, noDeps, wide, verbose)
	printTableSeparator(nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth, noDeps, wide, verbose)

	// Print agent rows
	for _, agent := range output.Agents {
		printAgentRow(agent, nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth, noDeps, wide, verbose)
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

	if registry.Status == "running" {
		// Show healthy/unhealthy breakdown
		fmt.Printf(" - %s%d healthy%s", colorGreen, registry.HealthyCount, colorReset)
		if registry.UnhealthyCount > 0 {
			fmt.Printf(", %s%d unhealthy/expired%s", colorGray, registry.UnhealthyCount, colorReset)
		}
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
func calculateColumnWidths(agents []EnhancedAgent, wide bool) (nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth int) {
	nameWidth = 15 // minimum width
	runtimeWidth = 12 // minimum width for "RUNTIME" header + padding (TypeScript = 10 chars)
	statusWidth = 10
	typeWidth = 5 // minimum width for "Type"
	endpointWidth = 20

	for _, agent := range agents {
		if len(agent.Name) > nameWidth {
			nameWidth = len(agent.Name)
		}
		// Use display format for width calculation (e.g., "TypeScript" not "typescript")
		runtimeDisplay := formatRuntimeDisplay(agent.Runtime)
		if len(runtimeDisplay) > runtimeWidth-2 {
			runtimeWidth = len(runtimeDisplay) + 2
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
	runtimeWidth += 2
	statusWidth += 2
	typeWidth += 2
	// Always add endpoint padding for standard view
	endpointWidth += 2

	return nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth
}

// printTableHeader prints the docker-compose-style table header
func printTableHeader(nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth int, noDeps, wide, verbose bool) {
	fmt.Printf("%-*s %-*s %-*s %-*s", nameWidth, "NAME", runtimeWidth, "RUNTIME", typeWidth, "TYPE", statusWidth, "STATUS")

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
func printTableSeparator(nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth int, noDeps, wide, verbose bool) {
	totalWidth := nameWidth + runtimeWidth + statusWidth + typeWidth + 13 // base width including TYPE and RUNTIME columns
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
func printAgentRow(agent EnhancedAgent, nameWidth, runtimeWidth, statusWidth, typeWidth, endpointWidth int, noDeps, wide, verbose bool) {
	// Name column
	fmt.Printf("%-*s", nameWidth, truncateStringForList(agent.Name, nameWidth-2))

	// Runtime column with color (pad first, then colorize to avoid alignment issues)
	runtime := agent.Runtime
	if runtime == "" {
		runtime = "-"
	}
	runtimeDisplay := formatRuntimeDisplay(runtime)
	runtimePadded := fmt.Sprintf("%-*s", runtimeWidth, runtimeDisplay)
	fmt.Printf(" %s%s%s", getRuntimeColor(runtime), runtimePadded, colorReset)

	// Type column
	agentTypeDisplay := formatAgentTypeDisplay(agent.AgentType)
	fmt.Printf(" %-*s", typeWidth, agentTypeDisplay)

	// Status column with color (pad first, then colorize)
	statusPadded := fmt.Sprintf("%-*s", statusWidth, agent.Status)
	fmt.Printf(" %s%s%s", getStatusColor(agent.Status), statusPadded, colorReset)

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

// getRuntimeColor returns the color for a runtime type
func getRuntimeColor(runtime string) string {
	switch strings.ToLower(runtime) {
	case "python":
		return colorGreen
	case "typescript":
		return colorCyan
	default:
		return colorReset
	}
}

// formatRuntimeDisplay returns the display name for a runtime
func formatRuntimeDisplay(runtime string) string {
	switch strings.ToLower(runtime) {
	case "python":
		return "Python"
	case "typescript":
		return "TypeScript"
	default:
		return runtime
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

// configureHTTPClientWithTLS sets up the HTTP client with timeout and optional TLS skip
func configureHTTPClientWithTLS(timeoutSeconds int, insecure bool) {
	transport := &http.Transport{}

	if insecure {
		transport.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
	}

	registryHTTPClient = &http.Client{
		Timeout:   time.Duration(timeoutSeconds) * time.Second,
		Transport: transport,
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

	// Find the requested agent by ID
	for _, agent := range agents {
		if agent.ID == agentID {
			targetAgent = &agent
			break
		}
	}

	if targetAgent == nil {
		return fmt.Errorf("agent '%s' not found", agentID)
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
	if targetAgent.Runtime != "" {
		fmt.Printf("%-20s: %s%s%s\n", "Runtime", getRuntimeColor(targetAgent.Runtime), formatRuntimeDisplay(targetAgent.Runtime), colorReset)
	}
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

	// LLM Tool Filters (from @mesh.llm decorator wiring to tools)
	var llmFilterTools []ToolInfo
	for _, tool := range targetAgent.Tools {
		if tool.LLMFilter != nil && len(tool.LLMFilter.Filter) > 0 {
			llmFilterTools = append(llmFilterTools, tool)
		}
	}
	if len(llmFilterTools) > 0 {
		fmt.Printf("\n%sLLM Tool Filters (%d):%s\n", colorBlue, len(llmFilterTools), colorReset)
		fmt.Println(strings.Repeat("-", 80))
		fmt.Printf("%-25s %-15s %-20s %-20s\n", "CAPABILITY", "FILTER MODE", "FILTER CAPABILITY", "FILTER TAGS")
		fmt.Println(strings.Repeat("-", 80))

		for _, tool := range llmFilterTools {
			capability := tool.Capability
			if capability == "" {
				capability = tool.Name
			}

			filterMode := "-"
			if tool.LLMFilter != nil && tool.LLMFilter.FilterMode != "" {
				filterMode = tool.LLMFilter.FilterMode
			}

			// Iterate through each filter spec in the filter array
			if tool.LLMFilter != nil && len(tool.LLMFilter.Filter) > 0 {
				for i, filterSpec := range tool.LLMFilter.Filter {
					filterCapability := "-"
					filterTags := "-"

					if filterSpec.Capability != "" {
						filterCapability = filterSpec.Capability
					}
					if len(filterSpec.Tags) > 0 {
						filterTags = strings.Join(filterSpec.Tags, ",")
					}

					// Only show capability name on first row for this tool
					displayCapability := capability
					displayFilterMode := filterMode
					if i > 0 {
						displayCapability = ""
						displayFilterMode = ""
					}

					fmt.Printf("%-25s %-15s %-20s %-20s\n",
						displayCapability,
						displayFilterMode,
						filterCapability,
						filterTags)
				}
			}
		}
	}

	// LLM Tool Resolutions (resolved tools from @mesh.llm filter)
	if len(targetAgent.LLMToolResolutions) > 0 {
		fmt.Printf("\n%sLLM Tool Resolutions (%d):%s\n", colorBlue, len(targetAgent.LLMToolResolutions), colorReset)
		fmt.Println(strings.Repeat("-", 100))
		fmt.Printf("%-20s %-20s %-25s %-35s\n", "FUNCTION", "FILTER", "MCP TOOL", "ENDPOINT")
		fmt.Println(strings.Repeat("-", 100))

		for _, res := range targetAgent.LLMToolResolutions {
			mcpTool := res.MCPTool
			endpoint := res.Endpoint
			lineColor := ""

			// Build filter description
			filterDesc := res.FilterCapability
			if len(res.FilterTags) > 0 {
				filterDesc = strings.Join(res.FilterTags, ",")
			}
			if filterDesc == "" {
				filterDesc = "-"
			}

			// Handle unresolved - show entire line in red
			if res.Status == "unresolved" {
				mcpTool = "NOT FOUND"
				endpoint = "-"
				lineColor = colorRed
			}

			fmt.Printf("%s%-20s %-20s %-25s %-35s%s\n",
				lineColor,
				truncateStringForList(res.FunctionName, 18),
				truncateStringForList(filterDesc, 18),
				truncateStringForList(mcpTool, 23),
				truncateStringForList(endpoint, 33),
				colorReset)
		}
	}

	// LLM Providers (mesh delegation)
	var llmProviderTools []ToolInfo
	for _, tool := range targetAgent.Tools {
		if tool.LLMProvider != nil {
			llmProviderTools = append(llmProviderTools, tool)
		}
	}
	if len(llmProviderTools) > 0 {
		fmt.Printf("\n%sLLM Providers (%d):%s\n", colorBlue, len(llmProviderTools), colorReset)
		fmt.Println(strings.Repeat("-", 80))
		fmt.Printf("%-25s %-25s %-15s %-15s\n", "CAPABILITY", "PROVIDER CAPABILITY", "PROVIDER TAGS", "PROVIDER VER")
		fmt.Println(strings.Repeat("-", 80))

		for _, tool := range llmProviderTools {
			capability := tool.Capability
			if capability == "" {
				capability = tool.Name
			}

			providerCapability := "-"
			providerTags := "-"
			providerVersion := "-"

			if tool.LLMProvider != nil {
				if tool.LLMProvider.Capability != "" {
					providerCapability = tool.LLMProvider.Capability
				}
				if len(tool.LLMProvider.Tags) > 0 {
					providerTags = strings.Join(tool.LLMProvider.Tags, ",")
				}
				if tool.LLMProvider.Version != "" {
					providerVersion = tool.LLMProvider.Version
				}
			}

			fmt.Printf("%-25s %-25s %-15s %-15s\n",
				capability,
				providerCapability,
				providerTags,
				providerVersion)
		}
	}

	// LLM Provider Resolutions (resolved providers from @mesh.llm provider)
	if len(targetAgent.LLMProviderResolutions) > 0 {
		fmt.Printf("\n%sLLM Provider Resolutions (%d):%s\n", colorBlue, len(targetAgent.LLMProviderResolutions), colorReset)
		fmt.Println(strings.Repeat("-", 100))
		fmt.Printf("%-20s %-20s %-25s %-35s\n", "FUNCTION", "REQUIRED CAP", "MCP TOOL", "ENDPOINT")
		fmt.Println(strings.Repeat("-", 100))

		for _, res := range targetAgent.LLMProviderResolutions {
			mcpTool := res.MCPTool
			endpoint := res.Endpoint
			lineColor := ""

			requiredCap := res.RequiredCapability
			if requiredCap == "" {
				requiredCap = "-"
			}

			// Handle unresolved - show entire line in red
			if res.Status == "unresolved" {
				mcpTool = "NOT FOUND"
				endpoint = "-"
				lineColor = colorRed
			}

			fmt.Printf("%s%-20s %-20s %-25s %-35s%s\n",
				lineColor,
				truncateStringForList(res.FunctionName, 18),
				truncateStringForList(requiredCap, 18),
				truncateStringForList(mcpTool, 23),
				truncateStringForList(endpoint, 33),
				colorReset)
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

// ToolListItem represents a tool for the tools listing
type ToolListItem struct {
	ToolName    string `json:"tool_name"`
	AgentName   string `json:"agent_name"`
	AgentID     string `json:"agent_id"`
	Capability  string `json:"capability"`
	Description string `json:"description"`
	Version     string `json:"version"`
	Tags        string `json:"tags"`
	Endpoint    string `json:"endpoint"`
}

// runToolsListCommand handles the --tools flag
func runToolsListCommand(registryURL, toolSpec string, jsonOutput, healthyOnly bool) error {
	// Get enhanced agents from registry
	enhancedAgents, err := getEnhancedAgents(registryURL)
	if err != nil {
		return fmt.Errorf("failed to get agents from registry: %w", err)
	}

	// Filter healthy agents if requested
	if healthyOnly {
		enhancedAgents = filterHealthyAgents(enhancedAgents)
	}

	// Collect all tools
	var allTools []ToolListItem
	for _, agent := range enhancedAgents {
		for _, tool := range agent.Tools {
			toolItem := ToolListItem{
				ToolName:   tool.FunctionName,
				AgentName:  agent.Name,
				AgentID:    agent.ID,
				Capability: tool.Capability,
				Version:    tool.Version,
				Endpoint:   agent.Endpoint,
			}
			if tool.FunctionName == "" {
				toolItem.ToolName = tool.Name
			}
			if len(tool.Tags) > 0 {
				toolItem.Tags = strings.Join(tool.Tags, ",")
			}
			allTools = append(allTools, toolItem)
		}
	}

	// If no specific tool requested (or "all" from NoOptDefVal), list all tools
	if toolSpec == "" || toolSpec == "all" {
		return outputToolsList(allTools, jsonOutput)
	}

	// Parse tool specifier (agent:tool or just tool)
	agentName, toolName := parseToolSpec(toolSpec)

	// If agent name specified, resolve with prefix matching
	var targetAgentID string
	if agentName != "" {
		matchResult := ResolveAgentByPrefix(enhancedAgents, agentName, healthyOnly)
		if err := matchResult.FormattedError(); err != nil {
			return err
		}
		targetAgentID = matchResult.Agent.ID
	}

	// Find the specific tool
	var matchedTool *ToolListItem
	var matchedAgent *EnhancedAgent
	for _, agent := range enhancedAgents {
		// If agent was resolved via prefix, use that specific agent
		if targetAgentID != "" && agent.ID != targetAgentID {
			continue
		}
		for _, tool := range agent.Tools {
			funcName := tool.FunctionName
			if funcName == "" {
				funcName = tool.Name
			}
			if funcName == toolName {
				toolItem := ToolListItem{
					ToolName:   funcName,
					AgentName:  agent.Name,
					AgentID:    agent.ID,
					Capability: tool.Capability,
					Version:    tool.Version,
					Endpoint:   agent.Endpoint,
				}
				if len(tool.Tags) > 0 {
					toolItem.Tags = strings.Join(tool.Tags, ",")
				}
				matchedTool = &toolItem
				matchedAgent = &agent
				break
			}
		}
		if matchedTool != nil {
			break
		}
	}

	if matchedTool == nil {
		if agentName != "" {
			return fmt.Errorf("tool '%s' not found on agent '%s'", toolName, agentName)
		}
		return fmt.Errorf("tool '%s' not found on any agent", toolName)
	}

	// Get detailed tool information from agent
	return outputToolDetails(matchedTool, matchedAgent, registryURL, jsonOutput)
}

// parseToolSpec parses "agent:tool" or "tool" format
func parseToolSpec(spec string) (agentName, toolName string) {
	parts := strings.SplitN(spec, ":", 2)
	if len(parts) == 2 {
		return parts[0], parts[1]
	}
	return "", parts[0]
}

// outputToolsList outputs the list of all tools
func outputToolsList(tools []ToolListItem, jsonOutput bool) error {
	if jsonOutput {
		data, err := json.MarshalIndent(tools, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(data))
		return nil
	}

	if len(tools) == 0 {
		fmt.Println("No tools found")
		return nil
	}

	// Sort by tool name
	sort.Slice(tools, func(i, j int) bool {
		return tools[i].ToolName < tools[j].ToolName
	})

	// Calculate column widths
	toolWidth := 25
	agentWidth := 20
	capWidth := 20

	for _, tool := range tools {
		if len(tool.ToolName) > toolWidth-2 {
			toolWidth = len(tool.ToolName) + 2
		}
		if len(tool.AgentName) > agentWidth-2 {
			agentWidth = len(tool.AgentName) + 2
		}
		if len(tool.Capability) > capWidth-2 {
			capWidth = len(tool.Capability) + 2
		}
	}

	// Limit widths
	if toolWidth > 40 {
		toolWidth = 40
	}
	if agentWidth > 30 {
		agentWidth = 30
	}
	if capWidth > 25 {
		capWidth = 25
	}

	// Print header
	fmt.Printf("%-*s %-*s %-*s %s\n", toolWidth, "TOOL", agentWidth, "AGENT", capWidth, "CAPABILITY", "TAGS")
	fmt.Println(strings.Repeat("-", toolWidth+agentWidth+capWidth+20))

	// Print tools
	for _, tool := range tools {
		tags := tool.Tags
		if tags == "" {
			tags = "-"
		}
		fmt.Printf("%-*s %-*s %-*s %s\n",
			toolWidth, truncateStringForList(tool.ToolName, toolWidth-2),
			agentWidth, truncateStringForList(tool.AgentName, agentWidth-2),
			capWidth, truncateStringForList(tool.Capability, capWidth-2),
			tags)
	}

	fmt.Printf("\n%d tool(s) found\n", len(tools))
	return nil
}

// MCPToolSchema represents the input schema from tools/list
type MCPToolSchema struct {
	Type       string                       `json:"type"`
	Properties map[string]MCPPropertySchema `json:"properties,omitempty"`
	Required   []string                     `json:"required,omitempty"`
}

// MCPPropertySchema represents a property in the input schema
type MCPPropertySchema struct {
	Type        string   `json:"type"`
	Description string   `json:"description,omitempty"`
	Default     any      `json:"default,omitempty"`
	Enum        []string `json:"enum,omitempty"`
}

// MCPToolInfo represents tool info from tools/list response
type MCPToolInfo struct {
	Name        string      `json:"name"`
	Description string      `json:"description,omitempty"`
	InputSchema interface{} `json:"inputSchema"` // Raw JSON schema for accurate display
}

// outputToolDetails outputs detailed information for a specific tool
func outputToolDetails(tool *ToolListItem, agent *EnhancedAgent, registryURL string, jsonOutput bool) error {
	// Try to get detailed tool info from agent via MCP tools/list (through registry proxy)
	var mcpTool *MCPToolInfo
	if agent != nil && agent.Endpoint != "" {
		mcpTool = getToolDetailsFromAgent(agent.Endpoint, tool.ToolName, registryURL)
	}

	if jsonOutput {
		output := map[string]interface{}{
			"tool_name":  tool.ToolName,
			"agent_name": tool.AgentName,
			"agent_id":   tool.AgentID,
			"capability": tool.Capability,
			"endpoint":   tool.Endpoint,
			"version":    tool.Version,
			"tags":       tool.Tags,
		}
		if mcpTool != nil {
			output["description"] = mcpTool.Description
			output["input_schema"] = mcpTool.InputSchema
		}
		data, err := json.MarshalIndent(output, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(data))
		return nil
	}

	// Pretty print tool details
	fmt.Printf("%sTool: %s%s\n", colorBlue, tool.ToolName, colorReset)
	fmt.Printf("Agent: %s\n", tool.AgentName)
	fmt.Printf("Capability: %s\n", tool.Capability)
	if mcpTool != nil && mcpTool.Description != "" {
		fmt.Printf("Description: %s\n", mcpTool.Description)
	}
	if tool.Version != "" {
		fmt.Printf("Version: %s\n", tool.Version)
	}
	if tool.Tags != "" {
		fmt.Printf("Tags: %s\n", tool.Tags)
	}

	// Print input schema as raw JSON
	fmt.Printf("\n%sInput Schema:%s\n", colorBlue, colorReset)
	if mcpTool != nil && mcpTool.InputSchema != nil {
		schemaJSON, err := json.MarshalIndent(mcpTool.InputSchema, "  ", "  ")
		if err == nil {
			fmt.Printf("  %s\n", string(schemaJSON))
		} else {
			fmt.Println("  (failed to format schema)")
		}
	} else {
		fmt.Println("  (no schema available)")
	}

	// Print example usage
	fmt.Printf("\n%sExample:%s\n", colorBlue, colorReset)
	fmt.Printf("  meshctl call %s '<json-args>'\n", tool.ToolName)

	return nil
}

// getToolDetailsFromAgent fetches tool details from the agent via MCP tools/list
// Routes through registry proxy to reach agents in Docker/K8s networks
func getToolDetailsFromAgent(endpoint, toolName, registryURL string) *MCPToolInfo {
	// Build MCP request for tools/list
	mcpReq := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "tools/list",
		"params":  map[string]interface{}{},
	}

	reqBody, err := json.Marshal(mcpReq)
	if err != nil {
		return nil
	}

	// Route through registry proxy (same as meshctl call --use-proxy)
	agentHostPort := strings.TrimPrefix(endpoint, "http://")
	agentHostPort = strings.TrimPrefix(agentHostPort, "https://")
	mcpURL := fmt.Sprintf("%s/proxy/%s/mcp", strings.TrimSuffix(registryURL, "/"), agentHostPort)

	req, err := http.NewRequest("POST", mcpURL, strings.NewReader(string(reqBody)))
	if err != nil {
		return nil
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")

	resp, err := registryHTTPClient.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil
	}

	// Read response body
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil
	}

	// Parse SSE if needed
	bodyStr := string(body)
	jsonData := body
	if strings.HasPrefix(bodyStr, "event:") || strings.Contains(resp.Header.Get("Content-Type"), "text/event-stream") {
		for _, line := range strings.Split(bodyStr, "\n") {
			if strings.HasPrefix(line, "data:") {
				jsonData = []byte(strings.TrimSpace(strings.TrimPrefix(line, "data:")))
				break
			}
		}
	}

	// Parse response
	var mcpResp struct {
		Result struct {
			Tools []MCPToolInfo `json:"tools"`
		} `json:"result"`
	}
	if err := json.Unmarshal(jsonData, &mcpResp); err != nil {
		return nil
	}

	// Find the specific tool
	for _, t := range mcpResp.Result.Tools {
		if t.Name == toolName {
			return &t
		}
	}

	return nil
}

// buildExampleArgs builds example JSON arguments from schema
func buildExampleArgs(schema MCPToolSchema) string {
	if len(schema.Properties) == 0 {
		return "{}"
	}

	args := make(map[string]interface{})
	for propName, prop := range schema.Properties {
		// Check if required
		isRequired := false
		for _, req := range schema.Required {
			if req == propName {
				isRequired = true
				break
			}
		}

		// Only include required fields in example
		if !isRequired {
			continue
		}

		// Generate example value based on type
		switch prop.Type {
		case "string":
			if len(prop.Enum) > 0 {
				args[propName] = prop.Enum[0]
			} else {
				args[propName] = "example"
			}
		case "number", "integer":
			args[propName] = 1
		case "boolean":
			args[propName] = true
		case "array":
			args[propName] = []interface{}{"item1", "item2"}
		case "object":
			args[propName] = map[string]interface{}{}
		default:
			args[propName] = "value"
		}
	}

	jsonBytes, _ := json.Marshal(args)
	return string(jsonBytes)
}
