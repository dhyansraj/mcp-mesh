package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"
)

// NewStopCommand creates the stop command
func NewStopCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stop [name ...]",
		Short: "Stop detached agents and registry",
		Long: `Stop agents and/or registry running in detached mode.

Without arguments, stops all agents and the registry.
With name argument(s), stops only those specific agent(s).

Examples:
  meshctl stop                    # Stop all agents + registry
  meshctl stop my-agent           # Stop specific agent
  meshctl stop agent1 agent2      # Stop multiple agents
  meshctl stop --registry         # Stop only registry
  meshctl stop --agents           # Stop all agents, keep registry
  meshctl stop --keep-registry    # Stop all agents, keep registry (alias)
  meshctl stop --clean            # Stop all + delete db, logs, pids`,
		Args: cobra.ArbitraryArgs,
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
	if clean && (len(args) > 0 || registryOnly || agentsOnly) {
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

	// Handle specific agent stop (one or more names)
	if len(args) > 0 {
		var failures []string
		for _, name := range args {
			if err := stopSpecificAgent(pm, name, shutdownTimeout, force, quiet); err != nil {
				failures = append(failures, fmt.Sprintf("%s: %v", name, err))
				if !quiet {
					fmt.Printf("Warning: failed to stop %s: %v\n", name, err)
				}
			}
		}
		if len(failures) > 0 {
			return fmt.Errorf("failed to stop %d agent(s): %s", len(failures), strings.Join(failures, "; "))
		}
		return nil
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

// stopSpecificAgent stops all instances (flat and/or watch-mode) of an agent by name.
// Returns an error if no running instances were found.
//
// Under the per-parent-PID namespacing scheme, the same agent name may have:
//   - one flat (non-watch) instance, tracked as <name>.pid
//   - zero or more watch-mode instances, each tracked as <name>.<parent_pid>.pid
//     under a different watcher-parent meshctl process
//
// We stop all of them and then, for each distinct watcher-parent we touched,
// decide whether to kill the parent process based on whether any watch-mode
// agents still live under it.
func stopSpecificAgent(pm *PIDManager, name string, timeout time.Duration, force, quiet bool) error {
	foundAny := false
	stoppedAny := false

	// 1. Flat/non-watch mode instance (if any)
	if pid, err := pm.ReadPID(name); err == nil {
		foundAny = true
		if !IsProcessAlive(pid) {
			// Already dead at enumeration time — safe to remove the stale PID file.
			if !quiet {
				fmt.Printf("Agent '%s' is not running (cleaning stale PID file)\n", name)
			}
			pm.RemovePID(name)
		} else {
			if !quiet {
				fmt.Printf("Stopping agent '%s' (PID: %d)...\n", name, pid)
			}
			stopErr := stopProcess(pid, timeout, force)
			// Re-check liveness after stopProcess regardless of its return value — the
			// SIGKILL path can succeed even when the graceful path returned an error.
			if !IsProcessAlive(pid) {
				if !quiet {
					fmt.Printf("Agent '%s' stopped\n", name)
				}
				stoppedAny = true
				pm.RemovePID(name)
			} else {
				// Process survived — preserve the PID file so the user can retry with
				// `meshctl stop <name>` (otherwise name-based lookup would fail).
				if !quiet {
					if stopErr != nil {
						fmt.Printf("Warning: agent '%s' (PID %d) is still running after stop attempt (%v); tracking file preserved for retry\n", name, pid, stopErr)
					} else {
						fmt.Printf("Warning: agent '%s' (PID %d) is still running after stop attempt; tracking file preserved for retry\n", name, pid)
					}
				}
			}
		}
	}

	// 2. All watch-mode instances of this name (may be multiple across different parent PIDs)
	watchMatches, err := pm.FindWatchAgentsByName(name)
	if err != nil {
		return fmt.Errorf("failed to enumerate watch-mode instances: %w", err)
	}

	// Track which parents we successfully cleaned up so we can run shared-watcher
	// cleanup once per parent afterwards. We deliberately only add a parent here
	// after the agent under it dies — if ANY agent under a parent failed to die,
	// the parent should NOT be considered for stopWatcherParentIfEmpty so the
	// watcher stays alive to potentially recover or report the state.
	touchedParents := make(map[int]bool)

	for _, match := range watchMatches {
		foundAny = true
		if !quiet {
			fmt.Printf("Stopping agent '%s' (PID: %d, watcher parent: %d)...\n", name, match.PID, match.ParentPID)
		}
		stopErr := stopProcess(match.PID, timeout, force)
		// Re-check liveness after stopProcess regardless of its return value.
		if !IsProcessAlive(match.PID) {
			if !quiet {
				fmt.Printf("Agent '%s' stopped\n", name)
			}
			stoppedAny = true
			pm.RemoveWatchAgentPID(name, match.ParentPID)
			touchedParents[match.ParentPID] = true
		} else {
			// Process survived — do NOT remove the watch-mode PID file, and do NOT
			// add this parent to touchedParents (so the watcher parent is not killed).
			if !quiet {
				if stopErr != nil {
					fmt.Printf("Warning: agent '%s' (PID %d) is still running after stop attempt (%v); tracking file preserved for retry\n", name, match.PID, stopErr)
				} else {
					fmt.Printf("Warning: agent '%s' (PID %d) is still running after stop attempt; tracking file preserved for retry\n", name, match.PID)
				}
			}
		}
	}

	// 3. For each parent we touched, decide whether to stop its watcher process.
	//    Rule: if the parent has no remaining watch-mode agents alive, stop it.
	//    Sort parent PIDs before iterating so log output is deterministic across runs.
	sortedParents := make([]int, 0, len(touchedParents))
	for parentPID := range touchedParents {
		sortedParents = append(sortedParents, parentPID)
	}
	sort.Ints(sortedParents)
	for _, parentPID := range sortedParents {
		stopWatcherParentIfEmpty(pm, name, parentPID, timeout, force, quiet)
	}

	if !foundAny {
		return fmt.Errorf("agent '%s' is not running", name)
	}
	if !stoppedAny {
		return fmt.Errorf("agent '%s' could not be stopped (still running, tracking preserved for retry)", name)
	}
	// Partial success (some instances died, others survived) is reported via the
	// per-instance warnings above and returns nil so the overall CLI flow continues.
	return nil
}

// stopWatcherParentIfEmpty stops the watcher-parent meshctl process with the given PID
// only if it has no remaining live watch-mode agents under it. The name argument is used
// purely for log messages.
//
// This replaces the old countWatcherParentsWithPID-based approach: instead of counting
// sibling watcher-parent PID files (which collided under the old naming scheme), we now
// enumerate the actual agent entries that reference this parent_pid in their filename,
// which is the authoritative source of truth.
func stopWatcherParentIfEmpty(pm *PIDManager, name string, parentPID int, timeout time.Duration, force, quiet bool) {
	// Count remaining live agents under this parent.
	remaining, err := pm.FindWatchAgentsByParent(parentPID)
	if err == nil && len(remaining) > 0 {
		if !quiet {
			fmt.Printf("Watcher parent (PID: %d) still has %d other agent(s), keeping alive\n", parentPID, len(remaining))
		}
		return
	}

	// No remaining agents — safe to remove this name's watcher-parent tracking file and kill the parent.
	pm.RemoveWatchParentPID(name, parentPID)

	if !IsProcessAlive(parentPID) {
		return
	}

	if !quiet {
		fmt.Printf("Stopping watcher for '%s' (PID: %d)...\n", name, parentPID)
	}

	// Signal the parent meshctl process directly — NOT its process group — so we don't
	// take down unrelated siblings sharing the same group (registry, UI, etc).
	if proc, err := os.FindProcess(parentPID); err == nil {
		if err := proc.Signal(syscall.SIGTERM); err != nil && !quiet {
			fmt.Printf("Warning: failed to signal watcher for '%s': %v\n", name, err)
		}
		// Wait briefly for graceful exit, then force kill.
		deadline := time.Now().Add(timeout)
		for time.Now().Before(deadline) {
			if !IsProcessAlive(parentPID) {
				break
			}
			time.Sleep(100 * time.Millisecond)
		}
		if IsProcessAlive(parentPID) {
			proc.Kill()
		}
	}

	if IsProcessAlive(parentPID) {
		if !quiet {
			fmt.Printf("Warning: watcher for '%s' (PID: %d) may still be running\n", name, parentPID)
		}
	} else if !quiet {
		fmt.Printf("Watcher for '%s' stopped\n", name)
	}
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

	// Stop watcher parent processes sequentially after all agents are stopped.
	// Build the set of distinct parent PIDs from the killed watch-mode agents,
	// then call stopWatcherParentIfEmpty once per parent. This avoids double-
	// signalling the same parent when multiple agents share it (#706).
	parentPIDs := make(map[int]string) // parentPID -> representative name (for log messages)
	for _, agent := range agents {
		if agent.ParentPID > 0 {
			if _, ok := parentPIDs[agent.ParentPID]; !ok {
				parentPIDs[agent.ParentPID] = agent.Name
			}
		}
	}
	for parentPID, repName := range parentPIDs {
		stopWatcherParentIfEmpty(pm, repName, parentPID, timeout, force, quiet)
	}

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

	// Separate agents, watcher parents, UI, and registry
	var agents []PIDInfo
	var watcherParents []PIDInfo
	var uiProc *PIDInfo
	var registry *PIDInfo
	for _, proc := range processes {
		if !proc.Running {
			continue
		}
		switch proc.Type {
		case "registry":
			registry = &proc
		case "ui":
			uiProc = &proc
		case "watcher-parent":
			watcherParents = append(watcherParents, proc)
		default:
			agents = append(agents, proc)
		}
	}

	if len(agents) == 0 && len(watcherParents) == 0 && uiProc == nil && registry == nil {
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

	// Stop watcher parent processes after agents are stopped.
	// These are meshctl CLI processes that host watcher goroutines (#706).
	// In stopAll, we intentionally kill all watcher parents in parallel since
	// we're tearing everything down — no need for the shared-parent counting
	// logic used by stopAllAgents/stopWatcherParent.
	if len(watcherParents) > 0 {
		var wg sync.WaitGroup
		for _, wp := range watcherParents {
			wg.Add(1)
			go func(proc PIDInfo) {
				defer wg.Done()

				if !quiet {
					fmt.Printf("Stopping watcher '%s' (PID: %d)...\n", proc.Name, proc.PID)
				}

				if err := stopProcess(proc.PID, timeout, force); err != nil {
					mu.Lock()
					if !quiet {
						fmt.Printf("Failed to stop watcher '%s': %v\n", proc.Name, err)
					}
					failed++
					mu.Unlock()
					return
				}

				pm.RemovePIDFile(proc.PIDFile)

				mu.Lock()
				stopped++
				if !quiet {
					fmt.Printf("Watcher '%s' stopped\n", proc.Name)
				}
				mu.Unlock()
			}(wp)
		}
		wg.Wait()
	}

	// Stop UI server before registry (UI depends on registry)
	if uiProc != nil {
		if !quiet {
			fmt.Printf("Stopping UI server (PID: %d)...\n", uiProc.PID)
		}

		if err := stopProcess(uiProc.PID, timeout, force); err != nil {
			if !quiet {
				fmt.Printf("Failed to stop UI server: %v\n", err)
			}
			failed++
		} else {
			pm.RemovePIDFile(uiProc.PIDFile)
			stopped++
			if !quiet {
				fmt.Println("UI server stopped")
			}
		}
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

	// Note: We don't do a final IsProcessAlive check here because:
	// 1. SIGKILL cannot be caught/ignored, so the process will die
	// 2. There may be a brief window where the process is a zombie
	//    before being reaped, and IsProcessAlive returns true for zombies
	// 3. The old code didn't have this check and worked fine

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
