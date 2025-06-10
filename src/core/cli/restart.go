package cli

import (
	"fmt"
	"time"

	"github.com/spf13/cobra"
)

// NewRestartCommand creates the restart command and restart-agent subcommand
func NewRestartCommand() *cobra.Command {
	restartCmd := &cobra.Command{
		Use:   "restart",
		Short: "Restart MCP Mesh services",
		Long: `Restart all MCP Mesh services or specific agents.

This command stops existing services and then starts them again.

Examples:
  mcp-mesh-dev restart                 # Restart all services
  mcp-mesh-dev restart --timeout 60    # Custom shutdown timeout
  mcp-mesh-dev restart --reset-config  # Reset to default configuration`,
		RunE: runRestartCommand,
	}

	// Add restart-agent as a subcommand
	restartAgentCmd := &cobra.Command{
		Use:   "restart-agent AGENT_NAME",
		Short: "Restart a specific agent",
		Long: `Restart a specific MCP agent by name.

The agent will be gracefully stopped and then restarted with the same configuration.

Examples:
  mcp-mesh-dev restart-agent hello_world   # Restart the hello_world agent
  mcp-mesh-dev restart-agent hello_world --timeout 60  # Custom timeout`,
		Args: cobra.ExactArgs(1),
		RunE: runRestartAgentCommand,
	}

	// Add flags to main restart command
	restartCmd.Flags().Int("timeout", 0, "Timeout for graceful shutdown in seconds (default: 30)")
	restartCmd.Flags().Bool("reset-config", false, "Reset to default configuration instead of preserving current settings")

	// Add flags to restart-agent subcommand
	restartAgentCmd.Flags().Int("timeout", 0, "Timeout for graceful shutdown in seconds (default: 30)")

	// Add subcommand to main command
	restartCmd.AddCommand(restartAgentCmd)

	return restartCmd
}

func runRestartCommand(cmd *cobra.Command, args []string) error {
	// Get process manager
	pm := GetGlobalProcessManager()

	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get flags
	timeoutFlag, _ := cmd.Flags().GetInt("timeout")
	resetConfig, _ := cmd.Flags().GetBool("reset-config")

	// Determine timeout
	timeout := time.Duration(config.ShutdownTimeout) * time.Second
	if timeoutFlag > 0 {
		timeout = time.Duration(timeoutFlag) * time.Second
	}

	// Get current running processes to know what to restart
	processes := pm.GetAllProcesses()

	if len(processes) == 0 {
		fmt.Println("No MCP Mesh services are currently running")
		fmt.Println("Use 'mcp-mesh-dev start' to start services")
		return nil
	}

	// Collect process information for restart
	processesToRestart := make(map[string]*ProcessInfo)
	for name, info := range processes {
		processesToRestart[name] = info
	}

	fmt.Printf("Restarting %d services...\n", len(processes))

	// Step 1: Stop all services gracefully
	fmt.Println("Stopping existing services...")
	errors := pm.StopAllProcesses(timeout)
	if len(errors) > 0 {
		for _, err := range errors {
			fmt.Printf("Warning: %v\n", err)
		}
	}

	// Step 2: Reset config if requested
	if resetConfig {
		fmt.Println("Resetting configuration to defaults...")
		config = DefaultConfig()
		if err := SaveConfig(config); err != nil {
			fmt.Printf("Warning: failed to save default config: %v\n", err)
		}
	}

	// Step 3: Wait a moment for cleanup
	time.Sleep(2 * time.Second)

	// Step 4: Restart services using the process manager
	fmt.Println("Starting services...")

	var restartErrors []error

	// Start registry first if it was running
	for _, info := range processesToRestart {
		if info.ServiceType == "registry" {
			_, err := pm.StartRegistryProcess(config.RegistryPort, config.DBPath, info.Metadata)
			if err != nil {
				restartErrors = append(restartErrors, fmt.Errorf("failed to restart registry: %w", err))
			} else {
				fmt.Printf("Registry restarted successfully\n")
			}
			break
		}
	}

	// Start agents
	for _, info := range processesToRestart {
		if info.ServiceType == "agent" {
			_, err := pm.StartAgentProcess(info.Command, info.Metadata)
			if err != nil {
				restartErrors = append(restartErrors, fmt.Errorf("failed to restart agent %s: %w", info.Name, err))
			} else {
				fmt.Printf("Agent %s restarted successfully\n", info.Name)
			}
		}
	}

	if len(restartErrors) > 0 {
		fmt.Printf("Restart completed with %d errors:\n", len(restartErrors))
		for _, err := range restartErrors {
			fmt.Printf("  - %v\n", err)
		}
		return fmt.Errorf("some services failed to restart")
	}

	fmt.Println("All services restarted successfully")
	return nil
}

func runRestartAgentCommand(cmd *cobra.Command, args []string) error {
	agentName := args[0]

	// Get process manager
	pm := GetGlobalProcessManager()

	// Load configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get flags
	timeoutFlag, _ := cmd.Flags().GetInt("timeout")

	// Determine timeout
	timeout := time.Duration(config.ShutdownTimeout) * time.Second
	if timeoutFlag > 0 {
		timeout = time.Duration(timeoutFlag) * time.Second
	}

	// Check if agent exists
	info, exists := pm.GetProcess(agentName)
	if !exists {
		return fmt.Errorf("agent '%s' is not currently running", agentName)
	}

	if info.ServiceType != "agent" {
		return fmt.Errorf("'%s' is not an agent process", agentName)
	}

	if info.Command == "" {
		return fmt.Errorf("cannot restart agent '%s': command not available", agentName)
	}

	fmt.Printf("Restarting agent '%s'...\n", agentName)

	// Use the process manager's restart functionality
	newInfo, err := pm.RestartProcess(agentName, "", info.Metadata, timeout)
	if err != nil {
		return fmt.Errorf("failed to restart agent '%s': %w", agentName, err)
	}

	fmt.Printf("Agent '%s' restarted successfully (PID: %d)\n", agentName, newInfo.PID)
	return nil
}
