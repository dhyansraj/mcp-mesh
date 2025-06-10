package cli

import (
	"fmt"
	"time"

	"github.com/spf13/cobra"
)

// NewStopCommand creates the stop command
func NewStopCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stop",
		Short: "Stop running MCP Mesh services",
		Long: `Stop all running MCP Mesh services including agents and registry.

By default, attempts graceful shutdown with SIGTERM, followed by SIGKILL if needed.

Examples:
  mcp-mesh-dev stop                    # Stop all services gracefully
  mcp-mesh-dev stop --force            # Force stop all services
  mcp-mesh-dev stop --agent hello      # Stop only the 'hello' agent
  mcp-mesh-dev stop --timeout 60       # Set custom shutdown timeout`,
		RunE: runStopCommand,
	}

	// Add flags matching Python CLI
	cmd.Flags().Bool("force", false, "Force stop services without graceful shutdown")
	cmd.Flags().Int("timeout", 0, "Timeout for graceful shutdown in seconds (default: 30)")
	cmd.Flags().String("agent", "", "Stop only the specified agent")

	return cmd
}

func runStopCommand(cmd *cobra.Command, args []string) error {
	// Get process manager
	pm := GetGlobalProcessManager()

	// Load configuration for default timeout
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get flags
	force, _ := cmd.Flags().GetBool("force")
	timeoutFlag, _ := cmd.Flags().GetInt("timeout")
	agentName, _ := cmd.Flags().GetString("agent")

	// Determine timeout
	timeout := time.Duration(config.ShutdownTimeout) * time.Second
	if timeoutFlag > 0 {
		timeout = time.Duration(timeoutFlag) * time.Second
	}

	// Get all managed processes
	processes := pm.GetAllProcesses()

	if len(processes) == 0 {
		fmt.Println("No MCP Mesh services are currently running")
		return nil
	}

	// Handle specific agent stop
	if agentName != "" {
		if info, exists := pm.GetProcess(agentName); exists {
			fmt.Printf("Stopping %s (PID: %d)...", agentName, info.PID)

			var err error
			if force {
				err = pm.TerminateProcess(agentName, timeout)
			} else {
				err = pm.StopProcess(agentName, timeout)
			}

			if err != nil {
				fmt.Printf(" ✗ Failed: %v\n", err)
				return err
			} else {
				fmt.Printf(" ✓\n")
				fmt.Printf("Agent '%s' stopped successfully\n", agentName)
			}
		} else {
			return fmt.Errorf("agent '%s' is not running", agentName)
		}
		return nil
	}

	// Stop all processes
	fmt.Printf("Stopping %d MCP Mesh services...\n", len(processes))

	var errors []error
	if force {
		// Force terminate all processes
		for name, info := range processes {
			fmt.Printf("Force stopping %s (PID: %d)...", name, info.PID)
			if err := pm.TerminateProcess(name, timeout); err != nil {
				fmt.Printf(" ✗ Failed: %v\n", err)
				errors = append(errors, fmt.Errorf("failed to stop %s: %w", name, err))
			} else {
				fmt.Printf(" ✓\n")
			}
		}
	} else {
		// Graceful shutdown using process manager
		shutdownErrors := pm.StopAllProcesses(timeout)
		for _, err := range shutdownErrors {
			fmt.Printf("Error during shutdown: %v\n", err)
		}
		errors = append(errors, shutdownErrors...)
	}

	// Report results
	successful := len(processes) - len(errors)
	fmt.Printf("Stopped %d of %d services\n", successful, len(processes))

	if len(errors) > 0 {
		return fmt.Errorf("failed to stop some services (see errors above)")
	}

	return nil
}
