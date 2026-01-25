package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"
)

// NewStopCommand creates the stop command
func NewStopCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stop [name]",
		Short: "Stop detached agents and registry",
		Long: `Stop agents and/or registry running in detached mode.

Without arguments, stops all agents and the registry.
With a name argument, stops only that specific agent.

Examples:
  meshctl stop                    # Stop all agents + registry
  meshctl stop my-agent           # Stop specific agent
  meshctl stop --registry         # Stop only registry
  meshctl stop --agents           # Stop all agents, keep registry
  meshctl stop --keep-registry    # Stop all agents, keep registry (alias)
  meshctl stop --clean            # Stop all + delete db, logs, pids`,
		Args: cobra.MaximumNArgs(1),
		RunE: runStopCommand,
	}

	cmd.Flags().Bool("registry", false, "Stop only the registry")
	cmd.Flags().Bool("agents", false, "Stop all agents, keep registry running")
	cmd.Flags().Bool("keep-registry", false, "Stop all agents, keep registry running (alias for --agents)")
	cmd.Flags().Int("timeout", 10, "Shutdown timeout in seconds per process")
	cmd.Flags().Bool("force", false, "Force kill without graceful shutdown")
	cmd.Flags().Bool("quiet", false, "Suppress output messages")
	cmd.Flags().Bool("clean", false, "Delete database, logs, and PID files after stopping all processes")

	return cmd
}

func runStopCommand(cmd *cobra.Command, args []string) error {
	registryOnly, _ := cmd.Flags().GetBool("registry")
	agentsOnly, _ := cmd.Flags().GetBool("agents")
	keepRegistry, _ := cmd.Flags().GetBool("keep-registry")
	timeout, _ := cmd.Flags().GetInt("timeout")
	force, _ := cmd.Flags().GetBool("force")
	quiet, _ := cmd.Flags().GetBool("quiet")
	clean, _ := cmd.Flags().GetBool("clean")

	// --keep-registry is alias for --agents
	if keepRegistry {
		agentsOnly = true
	}

	// Validate flag combinations
	if registryOnly && agentsOnly {
		return fmt.Errorf("cannot use --registry and --agents together")
	}

	// --clean only works when stopping all (no args, not with --registry or --agents)
	if clean && (len(args) == 1 || registryOnly || agentsOnly) {
		return fmt.Errorf("--clean can only be used when stopping all processes (no agent name, --registry, or --agents)")
	}

	// Create PID manager
	pm, err := NewPIDManager()
	if err != nil {
		return fmt.Errorf("failed to initialize PID manager: %w", err)
	}

	// Clean stale PID files first
	cleaned, _ := pm.CleanStalePIDFiles()
	if len(cleaned) > 0 && !quiet {
		for _, name := range cleaned {
			fmt.Printf("Cleaned stale PID file for: %s\n", name)
		}
	}

	shutdownTimeout := time.Duration(timeout) * time.Second

	// Handle specific agent stop
	if len(args) == 1 {
		agentName := args[0]
		return stopSpecificAgent(pm, agentName, shutdownTimeout, force, quiet)
	}

	// Handle --registry flag
	if registryOnly {
		return stopRegistry(pm, shutdownTimeout, force, quiet)
	}

	// Handle --agents flag (stop agents, keep registry)
	if agentsOnly {
		return stopAllAgents(pm, shutdownTimeout, force, quiet)
	}

	// Default: stop all (agents + registry)
	if err := stopAll(pm, shutdownTimeout, force, quiet); err != nil {
		return err
	}

	// Clean up files if --clean flag is set
	if clean {
		if err := cleanupAllFiles(pm, quiet); err != nil {
			return fmt.Errorf("cleanup failed: %w", err)
		}
	}

	return nil
}

// stopSpecificAgent stops a single agent by name
func stopSpecificAgent(pm *PIDManager, name string, timeout time.Duration, force, quiet bool) error {
	pid, err := pm.ReadPID(name)
	if err != nil {
		if os.IsNotExist(err) {
			return fmt.Errorf("agent '%s' is not running in background", name)
		}
		return fmt.Errorf("failed to read PID for %s: %w", name, err)
	}

	if !IsProcessAlive(pid) {
		// Process is dead, clean up PID file
		pm.RemovePID(name)
		if !quiet {
			fmt.Printf("Agent '%s' is not running (cleaned stale PID file)\n", name)
		}
		return nil
	}

	if !quiet {
		fmt.Printf("Stopping agent '%s' (PID: %d)...\n", name, pid)
	}

	if err := stopProcess(pid, timeout, force); err != nil {
		return fmt.Errorf("failed to stop agent '%s': %w", name, err)
	}

	pm.RemovePID(name)

	if !quiet {
		fmt.Printf("Agent '%s' stopped\n", name)
	}

	return nil
}

// stopRegistry stops only the registry
func stopRegistry(pm *PIDManager, timeout time.Duration, force, quiet bool) error {
	registry, err := pm.GetRegistry()
	if err != nil {
		return fmt.Errorf("failed to check registry status: %w", err)
	}

	if registry == nil {
		if !quiet {
			fmt.Println("Registry is not running in background")
		}
		return nil
	}

	if !quiet {
		fmt.Printf("Stopping registry (PID: %d)...\n", registry.PID)
	}

	if err := stopProcess(registry.PID, timeout, force); err != nil {
		return fmt.Errorf("failed to stop registry: %w", err)
	}

	pm.RemovePID("registry")

	if !quiet {
		fmt.Println("Registry stopped")
	}

	return nil
}

// stopAllAgents stops all agents but keeps the registry running (parallel)
func stopAllAgents(pm *PIDManager, timeout time.Duration, force, quiet bool) error {
	agents, err := pm.GetRunningAgents()
	if err != nil {
		return fmt.Errorf("failed to list agents: %w", err)
	}

	if len(agents) == 0 {
		if !quiet {
			fmt.Println("No agents running in background")
		}
		return nil
	}

	if !quiet {
		fmt.Printf("Stopping %d agent(s) in parallel...\n", len(agents))
	}

	// Stop agents in parallel
	var wg sync.WaitGroup
	var mu sync.Mutex
	var stopped, failed int

	for _, agent := range agents {
		wg.Add(1)
		go func(agent PIDInfo) {
			defer wg.Done()

			if !quiet {
				fmt.Printf("Stopping agent '%s' (PID: %d)...\n", agent.Name, agent.PID)
			}

			if err := stopProcess(agent.PID, timeout, force); err != nil {
				mu.Lock()
				if !quiet {
					fmt.Printf("Failed to stop agent '%s': %v\n", agent.Name, err)
				}
				failed++
				mu.Unlock()
				return
			}

			pm.RemovePIDFile(agent.PIDFile)

			mu.Lock()
			stopped++
			if !quiet {
				fmt.Printf("Agent '%s' stopped\n", agent.Name)
			}
			mu.Unlock()
		}(agent)
	}

	wg.Wait()

	if !quiet {
		fmt.Printf("\nStopped %d agent(s)", stopped)
		if failed > 0 {
			fmt.Printf(", %d failed", failed)
		}
		fmt.Println()
	}

	if failed > 0 {
		return fmt.Errorf("%d agent(s) failed to stop", failed)
	}

	return nil
}

// stopAll stops all agents and the registry (agents in parallel, registry last)
func stopAll(pm *PIDManager, timeout time.Duration, force, quiet bool) error {
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		return fmt.Errorf("failed to list processes: %w", err)
	}

	// Separate agents and registry
	var agents []PIDInfo
	var registry *PIDInfo
	for _, proc := range processes {
		if !proc.Running {
			continue
		}
		if proc.Type == "registry" {
			registry = &proc
		} else {
			agents = append(agents, proc)
		}
	}

	if len(agents) == 0 && registry == nil {
		if !quiet {
			fmt.Println("No agents running in background. Use 'meshctl start --detach' to run agents in background.")
		}
		return nil
	}

	var stopped, failed int
	var mu sync.Mutex

	// Stop agents in parallel
	if len(agents) > 0 {
		if !quiet {
			fmt.Printf("Stopping %d agent(s) in parallel...\n", len(agents))
		}

		var wg sync.WaitGroup
		for _, agent := range agents {
			wg.Add(1)
			go func(proc PIDInfo) {
				defer wg.Done()

				if !quiet {
					fmt.Printf("Stopping agent '%s' (PID: %d)...\n", proc.Name, proc.PID)
				}

				if err := stopProcess(proc.PID, timeout, force); err != nil {
					mu.Lock()
					if !quiet {
						fmt.Printf("Failed to stop agent '%s': %v\n", proc.Name, err)
					}
					failed++
					mu.Unlock()
					return
				}

				pm.RemovePIDFile(proc.PIDFile)

				mu.Lock()
				stopped++
				if !quiet {
					fmt.Printf("Agent '%s' stopped\n", proc.Name)
				}
				mu.Unlock()
			}(agent)
		}
		wg.Wait()
	}

	// Stop registry last (sequential)
	if registry != nil {
		if !quiet {
			fmt.Printf("Stopping registry (PID: %d)...\n", registry.PID)
		}

		if err := stopProcess(registry.PID, timeout, force); err != nil {
			if !quiet {
				fmt.Printf("Failed to stop registry: %v\n", err)
			}
			failed++
		} else {
			pm.RemovePIDFile(registry.PIDFile)
			stopped++
			if !quiet {
				fmt.Println("Registry stopped")
			}
		}
	}

	if !quiet {
		fmt.Printf("\nStopped %d process(es)", stopped)
		if failed > 0 {
			fmt.Printf(", %d failed", failed)
		}
		fmt.Println()
	}

	if failed > 0 {
		return fmt.Errorf("%d process(es) failed to stop", failed)
	}

	return nil
}

// stopProcess gracefully stops a process and its entire process group
// (SIGTERM to process group, then SIGKILL after timeout)
// This ensures child processes (e.g., npx -> tsx -> node) are also terminated
func stopProcess(pid int, timeout time.Duration, force bool) error {
	// Verify process exists
	if !IsProcessAlive(pid) {
		return nil // Already dead
	}

	// If force, skip graceful shutdown - kill entire process group immediately
	if force {
		if err := syscall.Kill(-pid, syscall.SIGKILL); err != nil {
			// Try single process kill as fallback
			if process, err := os.FindProcess(pid); err == nil {
				process.Kill()
			}
		}
		return nil
	}

	// Send SIGTERM to the entire process group for graceful shutdown
	// The negative PID means "kill process group with PGID = abs(pid)"
	// This works because we set Setpgid: true when starting, making PID = PGID
	if err := syscall.Kill(-pid, syscall.SIGTERM); err != nil {
		// Process group might not exist (old agent without Setpgid)
		// Fall back to single process termination
		if process, err := os.FindProcess(pid); err == nil {
			process.Signal(syscall.SIGTERM)
		} else if !IsProcessAlive(pid) {
			return nil // Process already dead
		}
	}

	// Wait for process to exit
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !IsProcessAlive(pid) {
			return nil // Process exited gracefully
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Timeout reached, force kill the entire process group
	if err := syscall.Kill(-pid, syscall.SIGKILL); err != nil {
		// Fall back to single process kill
		if process, err := os.FindProcess(pid); err == nil {
			process.Kill()
		}
	}

	// Final check
	if IsProcessAlive(pid) {
		return fmt.Errorf("failed to kill process after timeout")
	}

	return nil
}

// cleanupAllFiles deletes database, log files, and PID files
func cleanupAllFiles(pm *PIDManager, quiet bool) error {
	if !quiet {
		fmt.Println("\nCleaning up...")
	}

	var deletedDB, deletedLogs, deletedPIDs int

	// Delete the registry database file (only the known mcp_mesh_registry.db)
	const registryDBFile = "mcp_mesh_registry.db"
	if err := os.Remove(registryDBFile); err == nil {
		deletedDB++
		if !quiet {
			fmt.Printf("  Deleted: %s\n", registryDBFile)
		}
	}

	// Delete log files
	lm, err := NewLogManager()
	if err == nil {
		logsDir := lm.GetLogsDir()
		entries, _ := os.ReadDir(logsDir)
		for _, entry := range entries {
			if !entry.IsDir() {
				logPath := filepath.Join(logsDir, entry.Name())
				if err := os.Remove(logPath); err == nil {
					deletedLogs++
				}
			}
		}
		if deletedLogs > 0 && !quiet {
			fmt.Printf("  Deleted: %d log file(s)\n", deletedLogs)
		}
	}

	// Delete PID files
	pidsDir := pm.GetPIDsDir()
	entries, _ := os.ReadDir(pidsDir)
	for _, entry := range entries {
		if !entry.IsDir() {
			pidPath := filepath.Join(pidsDir, entry.Name())
			if err := os.Remove(pidPath); err == nil {
				deletedPIDs++
			}
		}
	}
	if deletedPIDs > 0 && !quiet {
		fmt.Printf("  Deleted: %d PID file(s)\n", deletedPIDs)
	}

	if !quiet {
		if deletedDB == 0 && deletedLogs == 0 && deletedPIDs == 0 {
			fmt.Println("  Nothing to clean")
		} else {
			fmt.Println("✅ Cleanup complete")
		}
	}

	return nil
}
