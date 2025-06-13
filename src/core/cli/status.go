package cli

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// NewStatusCommand creates the status command
func NewStatusCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show detailed status of MCP Mesh services",
		Long: `Show detailed status information for all MCP Mesh services.

This includes registry status, agent health, process information, and connectivity status.

Examples:
  mcp-mesh-dev status                  # Show basic status
  mcp-mesh-dev status --verbose        # Show detailed information
  mcp-mesh-dev status --json           # Output in JSON format`,
		RunE: runStatusCommand,
	}

	// Add flags matching Python CLI
	cmd.Flags().Bool("verbose", false, "Show detailed status information")
	cmd.Flags().Bool("json", false, "Output status in JSON format")

	return cmd
}

// StatusOutput represents the complete status information
type StatusOutput struct {
	Overall   OverallStatus   `json:"overall"`
	Registry  RegistryStatus  `json:"registry"`
	Agents    []AgentStatus   `json:"agents"`
	Processes []ProcessStatus `json:"processes"`
	System    SystemStatus    `json:"system"`
	Timestamp time.Time       `json:"timestamp"`
}

// OverallStatus represents the overall system health
type OverallStatus struct {
	Status     string `json:"status"` // "healthy", "degraded", "unhealthy"
	Message    string `json:"message"`
	AgentCount int    `json:"agent_count"`
}

// AgentStatus represents detailed agent status
type AgentStatus struct {
	EnhancedAgent
	Health       string        `json:"health"`
	ResponseTime time.Duration `json:"response_time,omitempty"`
	Uptime       time.Duration `json:"uptime,omitempty"`
}

// ProcessStatus represents detailed process status
type ProcessStatus struct {
	ProcessInfo
	Uptime       time.Duration `json:"uptime"`
	IsResponding bool          `json:"is_responding"`
	MemoryUsage  string        `json:"memory_usage,omitempty"`
	CPUUsage     string        `json:"cpu_usage,omitempty"`
}

// SystemStatus represents system-level information
type SystemStatus struct {
	ConfigPath      string `json:"config_path"`
	ProcessFilePath string `json:"process_file_path"`
	DatabasePath    string `json:"database_path"`
	LogLevel        string `json:"log_level"`
}

func runStatusCommand(cmd *cobra.Command, args []string) error {
	// Get process manager
	pm := GetGlobalProcessManager()

	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get flags
	verbose, _ := cmd.Flags().GetBool("verbose")
	jsonOutput, _ := cmd.Flags().GetBool("json")

	// Collect status information
	status := StatusOutput{
		Timestamp: time.Now(),
	}

	// System status
	status.System = SystemStatus{
		ConfigPath:      "~/.mcp_mesh/cli_config.json", // Default config path
		ProcessFilePath: pm.stateFile,
		DatabasePath:    config.DBPath,
		LogLevel:        config.LogLevel,
	}

	// Registry status
	registryURL := config.GetRegistryURL()
	var registryAgents []RegistryAgent

	if IsRegistryRunning(registryURL) {
		status.Registry = RegistryStatus{
			Status: "running",
			URL:    registryURL,
		}

		// Get agents from registry
		agents, err := GetRegistryAgents(registryURL)
		if err != nil {
			status.Registry.Error = err.Error()
		} else {
			registryAgents = agents
			status.Registry.AgentCount = len(agents)
		}
	} else {
		status.Registry = RegistryStatus{
			Status: "not running",
		}
	}

	// Process status using process manager
	processes := pm.GetAllProcesses()
	status.Processes = make([]ProcessStatus, 0, len(processes))

	for _, proc := range processes {
		processStatus := ProcessStatus{
			ProcessInfo: ProcessInfo{
				PID:       proc.PID,
				Name:      proc.Name,
				Type:      proc.ServiceType,
				Command:   proc.Command,
				StartTime: proc.StartTime,
				Status:    proc.Status,
				FilePath:  proc.Command, // Use command as file path for compatibility
			},
			Uptime:       time.Since(proc.StartTime),
			IsResponding: proc.Status == "running",
		}

		// Add resource usage if verbose
		if verbose {
			// Note: Would need additional libraries like gopsutil for detailed resource usage
			processStatus.MemoryUsage = "N/A"
			processStatus.CPUUsage = "N/A"
		}

		status.Processes = append(status.Processes, processStatus)
	}

	// Agent status - combine registry and process manager information
	combinedAgents := combineAgentInfoFromPM(registryAgents, processes)
	status.Agents = make([]AgentStatus, len(combinedAgents))

	for i, agent := range combinedAgents {
		agentStatus := AgentStatus{
			EnhancedAgent: agent,
			Health:        determineAgentHealth(agent),
		}

		if !agent.StartTime.IsZero() {
			agentStatus.Uptime = time.Since(agent.StartTime)
		}

		status.Agents[i] = agentStatus
	}

	// Overall status
	status.Overall = determineOverallStatus(status.Registry, status.Agents)

	// Output results
	if jsonOutput {
		data, err := json.MarshalIndent(status, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(data))
		return nil
	}

	return outputStatusHuman(status, verbose)
}

func determineAgentHealth(agent EnhancedAgent) string {
	if agent.PID > 0 && !IsProcessAlive(agent.PID) {
		return "dead"
	}

	if agent.Status == "healthy" {
		return "healthy"
	} else if agent.Status == "degraded" {
		return "degraded"
	} else if agent.Status == "local_only" {
		return "local_only"
	} else {
		return "unknown"
	}
}

func determineOverallStatus(registry RegistryStatus, agents []AgentStatus) OverallStatus {
	healthyAgents := 0
	degradedAgents := 0
	deadAgents := 0

	for _, agent := range agents {
		switch agent.Health {
		case "healthy":
			healthyAgents++
		case "degraded":
			degradedAgents++
		case "dead":
			deadAgents++
		}
	}

	status := OverallStatus{
		AgentCount: len(agents),
	}

	if registry.Status != "running" {
		status.Status = "unhealthy"
		status.Message = "Registry is not running"
	} else if deadAgents > 0 {
		status.Status = "unhealthy"
		status.Message = fmt.Sprintf("%d agents are dead", deadAgents)
	} else if degradedAgents > 0 {
		status.Status = "degraded"
		status.Message = fmt.Sprintf("%d agents are degraded", degradedAgents)
	} else if len(agents) == 0 {
		status.Status = "healthy"
		status.Message = "Registry running, no agents"
	} else {
		status.Status = "healthy"
		status.Message = "All services healthy"
	}

	return status
}

func outputStatusHuman(status StatusOutput, verbose bool) error {
	// Overall status
	statusSymbol := getStatusSymbol(status.Overall.Status)
	fmt.Printf("Overall Status: %s %s\n", statusSymbol, status.Overall.Status)
	fmt.Printf("Message: %s\n", status.Overall.Message)
	fmt.Printf("\n")

	// Registry status
	registrySymbol := getStatusSymbol(status.Registry.Status)
	fmt.Printf("Registry: %s %s", registrySymbol, status.Registry.Status)
	if status.Registry.URL != "" {
		fmt.Printf(" (%s)", status.Registry.URL)
	}
	fmt.Printf("\n")

	if status.Registry.Error != "" {
		fmt.Printf("  Error: %s\n", status.Registry.Error)
	}
	if status.Registry.Status == "running" {
		fmt.Printf("  Registered agents: %d\n", status.Registry.AgentCount)
	}
	fmt.Printf("\n")

	// Agents
	if len(status.Agents) > 0 {
		fmt.Printf("Agents (%d):\n", len(status.Agents))
		for _, agent := range status.Agents {
			healthSymbol := getStatusSymbol(agent.Health)
			fmt.Printf("  %s %-20s %s", healthSymbol, agent.Name, agent.Health)

			if agent.PID > 0 {
				fmt.Printf(" (PID: %d)", agent.PID)
			}

			if agent.Uptime > 0 {
				fmt.Printf(" (uptime: %s)", formatDuration(agent.Uptime))
			}

			fmt.Printf("\n")

			if verbose {
				if len(agent.Tools) > 0 {
					var toolNames []string
					for _, tool := range agent.Tools {
						toolNames = append(toolNames, tool.Name)
					}
					fmt.Printf("    Tools: %s\n", strings.Join(toolNames, ", "))
				}
				if agent.FilePath != "" {
					fmt.Printf("    File: %s\n", agent.FilePath)
				}
				if agent.LastHeartbeat != nil {
					fmt.Printf("    Last heartbeat: %s ago\n", formatDuration(time.Since(*agent.LastHeartbeat)))
				}
			}
		}
		fmt.Printf("\n")
	}

	// Processes
	if len(status.Processes) > 0 {
		fmt.Printf("Processes (%d):\n", len(status.Processes))
		for _, proc := range status.Processes {
			aliveSymbol := "✓"
			if !proc.IsResponding {
				aliveSymbol = "✗"
			}

			fmt.Printf("  %s %-20s %s (PID: %d, uptime: %s)\n",
				aliveSymbol, proc.Name, proc.Type, proc.PID, formatDuration(proc.Uptime))

			if verbose {
				fmt.Printf("    Command: %s\n", proc.Command)
				if proc.FilePath != "" {
					fmt.Printf("    File: %s\n", proc.FilePath)
				}
				if proc.MemoryUsage != "" {
					fmt.Printf("    Memory: %s, CPU: %s\n", proc.MemoryUsage, proc.CPUUsage)
				}
			}
		}
		fmt.Printf("\n")
	}

	// System information
	if verbose {
		fmt.Printf("System:\n")
		fmt.Printf("  Config: %s\n", status.System.ConfigPath)
		fmt.Printf("  Processes: %s\n", status.System.ProcessFilePath)
		fmt.Printf("  Database: %s\n", status.System.DatabasePath)
		fmt.Printf("  Log level: %s\n", status.System.LogLevel)
		fmt.Printf("  Timestamp: %s\n", status.Timestamp.Format(time.RFC3339))
	}

	return nil
}

// combineAgentInfoFromPM combines registry and process manager information
func combineAgentInfoFromPM(registryAgents []RegistryAgent, processes map[string]*ProcessInfo) []EnhancedAgent {
	agentMap := make(map[string]EnhancedAgent)

	// Add registry agents
	for _, regAgent := range registryAgents {
		agentMap[regAgent.Name] = EnhancedAgent{
			Name:   regAgent.Name,
			Status: regAgent.Status,
			Tools:  []ToolInfo{}, // Convert capabilities if needed
		}
	}

	// Add process information
	for name, proc := range processes {
		if proc.ServiceType == "agent" {
			agent := agentMap[name]
			agent.Name = name
			agent.PID = proc.PID
			agent.StartTime = proc.StartTime
			agent.FilePath = proc.Command

			// If not in registry, mark as local_only
			if agent.Status == "" {
				agent.Status = "local_only"
			}

			agentMap[name] = agent
		}
	}

	// Convert to slice
	var agents []EnhancedAgent
	for _, agent := range agentMap {
		agents = append(agents, agent)
	}

	return agents
}

func getStatusSymbol(status string) string {
	switch status {
	case "healthy", "running":
		return "✓"
	case "degraded":
		return "⚠"
	case "unhealthy", "dead", "not running":
		return "✗"
	default:
		return "?"
	}
}
