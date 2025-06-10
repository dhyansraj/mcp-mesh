package cli

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// NewListCommand creates the list command
func NewListCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List running agents and registry status",
		Long: `List all running MCP Mesh agents and registry status.

This command queries the registry for active agents and shows local process information.
It is READ-ONLY and does not modify or stop any processes.

Examples:
  mcp-mesh-dev list                    # Show all agents and registry status
  mcp-mesh-dev list --agents           # Show only agents
  mcp-mesh-dev list --json             # Output in JSON format
  mcp-mesh-dev list --filter hello     # Filter agents by name pattern`,
		RunE: runListCommand,
	}

	// Add flags matching Python CLI
	cmd.Flags().Bool("agents", false, "Show only agents")
	cmd.Flags().Bool("services", false, "Show only services")
	cmd.Flags().String("filter", "", "Filter by name pattern")
	cmd.Flags().Bool("json", false, "Output in JSON format")
	cmd.Flags().Bool("verbose", false, "Show detailed information")

	return cmd
}

// ListOutput represents the complete output structure
type ListOutput struct {
	Registry RegistryStatus  `json:"registry"`
	Agents   []AgentInfo     `json:"agents"`
	Processes []ProcessInfo  `json:"processes"`
	Timestamp time.Time      `json:"timestamp"`
}

// RegistryStatus represents registry status information
type RegistryStatus struct {
	Status     string `json:"status"`
	URL        string `json:"url,omitempty"`
	AgentCount int    `json:"agent_count,omitempty"`
	Error      string `json:"error,omitempty"`
	Uptime     string `json:"uptime,omitempty"`
}

// AgentInfo combines registry agent data with process info
type AgentInfo struct {
	ID           string    `json:"id"`
	Name         string    `json:"name"`
	Status       string    `json:"status"`
	Capabilities []string  `json:"capabilities"`
	LastSeen     time.Time `json:"last_seen"`
	Version      string    `json:"version,omitempty"`
	Description  string    `json:"description,omitempty"`
	PID          int       `json:"pid,omitempty"`
	FilePath     string    `json:"file_path,omitempty"`
	StartTime    time.Time `json:"start_time,omitempty"`
}

func runListCommand(cmd *cobra.Command, args []string) error {
	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get flags
	showAgentsOnly, _ := cmd.Flags().GetBool("agents")
	showServicesOnly, _ := cmd.Flags().GetBool("services")
	filterPattern, _ := cmd.Flags().GetString("filter")
	jsonOutput, _ := cmd.Flags().GetBool("json")
	verbose, _ := cmd.Flags().GetBool("verbose")

	// Collect all information
	output := ListOutput{
		Timestamp: time.Now(),
	}

	// Check registry status
	registryURL := config.GetRegistryURL()
	var registryAgents []RegistryAgent

	if IsRegistryRunning(registryURL) {
		output.Registry = RegistryStatus{
			Status: "running",
			URL:    registryURL,
		}

		// Get agents from registry
		agents, err := GetRegistryAgents(registryURL)
		if err != nil {
			output.Registry.Error = err.Error()
		} else {
			registryAgents = agents
			output.Registry.AgentCount = len(agents)
		}
	} else {
		output.Registry = RegistryStatus{
			Status: "not running",
		}
	}

	// Get local process information
	processes, err := GetRunningProcesses()
	if err != nil {
		if !jsonOutput {
			fmt.Printf("Warning: failed to get process information: %v\n", err)
		}
	} else {
		output.Processes = processes
	}

	// Combine registry agents with process information
	output.Agents = combineAgentInfo(registryAgents, processes)

	// Apply filters
	if filterPattern != "" {
		output.Agents = filterAgents(output.Agents, filterPattern)
		output.Processes = filterProcesses(output.Processes, filterPattern)
	}

	// Output results
	if jsonOutput {
		return outputJSON(output, showAgentsOnly, showServicesOnly)
	}

	return outputHuman(output, showAgentsOnly, showServicesOnly, verbose)
}

func combineAgentInfo(registryAgents []RegistryAgent, processes []ProcessInfo) []AgentInfo {
	var combined []AgentInfo
	agentMap := make(map[string]ProcessInfo)

	// Create map of agent processes by name
	for _, proc := range processes {
		if proc.Type == "agent" {
			agentMap[proc.Name] = proc
		}
	}

	// Combine registry data with process data
	for _, regAgent := range registryAgents {
		agent := AgentInfo{
			ID:           regAgent.ID,
			Name:         regAgent.Name,
			Status:       regAgent.Status,
			Capabilities: regAgent.Capabilities,
			LastSeen:     regAgent.LastSeen,
			Version:      regAgent.Version,
			Description:  regAgent.Description,
		}

		// Add process information if available
		if proc, exists := agentMap[regAgent.Name]; exists {
			agent.PID = proc.PID
			agent.FilePath = proc.FilePath
			agent.StartTime = proc.StartTime
			delete(agentMap, regAgent.Name) // Remove from map to avoid duplicates
		}

		combined = append(combined, agent)
	}

	// Add any local processes that aren't in the registry
	for _, proc := range agentMap {
		agent := AgentInfo{
			Name:         proc.Name,
			Status:       "local_only",
			PID:          proc.PID,
			FilePath:     proc.FilePath,
			StartTime:    proc.StartTime,
			Capabilities: []string{}, // No capabilities known for local-only agents
		}
		combined = append(combined, agent)
	}

	return combined
}

func filterAgents(agents []AgentInfo, pattern string) []AgentInfo {
	var filtered []AgentInfo
	pattern = strings.ToLower(pattern)

	for _, agent := range agents {
		if strings.Contains(strings.ToLower(agent.Name), pattern) ||
		   strings.Contains(strings.ToLower(agent.Description), pattern) {
			filtered = append(filtered, agent)
		}
	}
	return filtered
}

func filterProcesses(processes []ProcessInfo, pattern string) []ProcessInfo {
	var filtered []ProcessInfo
	pattern = strings.ToLower(pattern)

	for _, proc := range processes {
		if strings.Contains(strings.ToLower(proc.Name), pattern) ||
		   strings.Contains(strings.ToLower(proc.Command), pattern) {
			filtered = append(filtered, proc)
		}
	}
	return filtered
}

func outputJSON(output ListOutput, agentsOnly, servicesOnly bool) error {
	var result interface{}

	if agentsOnly {
		result = map[string]interface{}{
			"agents":    output.Agents,
			"timestamp": output.Timestamp,
		}
	} else if servicesOnly {
		result = map[string]interface{}{
			"registry":  output.Registry,
			"processes": output.Processes,
			"timestamp": output.Timestamp,
		}
	} else {
		result = output
	}

	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	fmt.Println(string(data))
	return nil
}

func outputHuman(output ListOutput, agentsOnly, servicesOnly, verbose bool) error {
	if !agentsOnly {
		// Show registry status
		fmt.Printf("Registry: %s", output.Registry.Status)
		if output.Registry.URL != "" {
			fmt.Printf(" (%s)", output.Registry.URL)
		}
		if output.Registry.Error != "" {
			fmt.Printf(" - Error: %s", output.Registry.Error)
		}
		fmt.Printf("\n")

		if output.Registry.Status == "running" {
			fmt.Printf("  Registered agents: %d\n", output.Registry.AgentCount)
		}
		fmt.Printf("\n")
	}

	if !servicesOnly {
		// Show agents
		if len(output.Agents) == 0 {
			fmt.Println("No agents found")
		} else {
			fmt.Printf("Agents (%d):\n", len(output.Agents))
			for _, agent := range output.Agents {
				fmt.Printf("  %-20s %s", agent.Name, agent.Status)

				if agent.PID > 0 {
					fmt.Printf(" (PID: %d)", agent.PID)
				}

				if len(agent.Capabilities) > 0 {
					fmt.Printf(" [%s]", strings.Join(agent.Capabilities, ", "))
				}

				if !agent.LastSeen.IsZero() {
					fmt.Printf(" (last seen: %s)", formatDuration(time.Since(agent.LastSeen)))
				}

				fmt.Printf("\n")

				if verbose || agent.Description != "" {
					if agent.Description != "" {
						fmt.Printf("    Description: %s\n", agent.Description)
					}

					if agent.FilePath != "" {
						fmt.Printf("    File: %s\n", agent.FilePath)
					}

					if verbose && agent.Version != "" {
						fmt.Printf("    Version: %s\n", agent.Version)
					}

					if verbose && !agent.StartTime.IsZero() {
						fmt.Printf("    Started: %s\n", agent.StartTime.Format("2006-01-02 15:04:05"))
					}
				}
			}
		}
		fmt.Printf("\n")
	}

	if !agentsOnly {
		// Show local processes
		registryProcesses := make([]ProcessInfo, 0)
		otherProcesses := make([]ProcessInfo, 0)

		for _, proc := range output.Processes {
			if proc.Type == "registry" {
				registryProcesses = append(registryProcesses, proc)
			} else if proc.Type != "agent" { // Don't show agents here as they're shown above
				otherProcesses = append(otherProcesses, proc)
			}
		}

		if len(registryProcesses) > 0 {
			fmt.Printf("Registry Processes (%d):\n", len(registryProcesses))
			for _, proc := range registryProcesses {
				uptime := time.Since(proc.StartTime)
				fmt.Printf("  %-20s %s (PID: %d, uptime: %s)\n",
					proc.Name, proc.Status, proc.PID, formatDuration(uptime))
			}
			fmt.Printf("\n")
		}

		if len(otherProcesses) > 0 {
			fmt.Printf("Other Processes (%d):\n", len(otherProcesses))
			for _, proc := range otherProcesses {
				uptime := time.Since(proc.StartTime)
				fmt.Printf("  %-20s %s (PID: %d, uptime: %s)\n",
					proc.Name, proc.Status, proc.PID, formatDuration(uptime))
			}
		}
	}

	return nil
}

func formatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%.0fs", d.Seconds())
	}
	if d < time.Hour {
		return fmt.Sprintf("%.0fm%.0fs", d.Minutes(), d.Seconds()-(d.Truncate(time.Minute).Seconds()))
	}
	hours := int(d.Hours())
	minutes := int(d.Minutes()) % 60
	return fmt.Sprintf("%dh%dm", hours, minutes)
}
