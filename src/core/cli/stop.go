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
			// Already dead at enumeration time — safe to remove the stale PID
			// file. Treat this as a successful no-op: the user's intent was
			// "stop this agent" and the agent is confirmed not running, so the
			// outer "could not be stopped" error would actively mislead them.
			if !quiet {
				fmt.Printf("Agent '%s' is not running (cleaning stale PID file)\n", name)
			}
			pm.RemovePID(name)
			stoppedAny = true
		} else {
			if !quiet {
				fmt.Printf("Stopping agent '%s' (PID: %d)...\n", name, pid)
			}
			if err := stopProcess(pid, timeout, force); err != nil {
				// Process is still alive — preserve the PID file so the user can
				// retry with `meshctl stop <name>`.
				if !quiet {
					fmt.Printf("Warning: failed to stop agent '%s' (PID %d): %v (tracking preserved for retry)\n", name, pid, err)
				}
			} else {
				if !quiet {
					fmt.Printf("Agent '%s' stopped\n", name)
				}
				stoppedAny = true
				pm.RemovePID(name)
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
		if err := stopProcess(match.PID, timeout, force); err != nil {
			// Process survived — do NOT remove the watch-mode PID file, and do NOT
			// add this parent to touchedParents (so the watcher parent is not killed).
			if !quiet {
				fmt.Printf("Warning: failed to stop agent '%s' (PID %d): %v (tracking preserved for retry)\n", name, match.PID, err)
			}
		} else {
			if !quiet {
				fmt.Printf("Agent '%s' stopped\n", name)
			}
			stoppedAny = true
			pm.RemoveWatchAgentPID(name, match.ParentPID)
			touchedParents[match.ParentPID] = true
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
		suggestions := suggestAgentNames(pm, name)
		if len(suggestions) > 0 {
			return fmt.Errorf("agent '%s' is not running. Did you mean: %s?",
				name, strings.Join(quoteStrings(suggestions), ", "))
		}
		return fmt.Errorf("agent '%s' is not running", name)
	}
	if !stoppedAny {
		return fmt.Errorf("agent '%s' could not be stopped (still running, tracking preserved for retry)", name)
	}
	// Partial success (some instances died, others survived) is reported via the
	// per-instance warnings above and returns nil so the overall CLI flow continues.
	return nil
}

// stopWatcherParentIfEmpty stops the watcher-parent meshctl process with the
// given PID only if it has no remaining live watch-mode agents under it.
//
// Tracking file cleanup is driven by enumeration and invariant-safe:
//   - Case 1 (live agents remain): prune stale tracking files whose agents
//     are gone, keep the parent alive, return.
//   - Case 2 (no live agents, parent already dead): prune all tracking files.
//   - Case 3 (no live agents, parent still alive, kill succeeds): prune after
//     kill is confirmed.
//   - Case 4 (no live agents, parent still alive, kill FAILS): preserve ALL
//     tracking files so `meshctl stop` can retry later.
//
// The invariant is: tracking files for a parent are pruned ONLY when we can
// prove the parent either didn't need killing (keep-alive) or was successfully
// killed. A failed kill must leave tracking intact for retry.
//
// The `name` argument is used purely for log messages.
func stopWatcherParentIfEmpty(pm *PIDManager, name string, parentPID int, timeout time.Duration, force, quiet bool) {
	// Enumerate all watcher-parent tracking entries for this parent PID. Unlike
	// FindWatchAgentsByParent, this returns entries regardless of whether the
	// parent process is alive — used to drive stale-file cleanup.
	allParents, err := pm.FindWatchParentsByPID(parentPID)
	if err != nil {
		// Conservative: a transient enumeration error should not cause us to
		// kill a potentially-healthy parent or touch any tracking files.
		if !quiet {
			fmt.Printf("Warning: failed to enumerate watcher-parent tracking for PID %d: %v (keeping alive)\n", parentPID, err)
		}
		return
	}

	remaining, err := pm.FindWatchAgentsByParent(parentPID)
	if err != nil {
		if !quiet {
			fmt.Printf("Warning: failed to enumerate live agents under PID %d: %v (keeping alive)\n", parentPID, err)
		}
		return
	}

	// Case 1: live agents remain under this parent — keep it alive and
	// prune any stale watcher-parent tracking files whose agents are gone.
	// Safe to prune here because we are NOT attempting to kill the parent;
	// the parent stays alive and the remaining live agents are tracked by
	// their own entries.
	if len(remaining) > 0 {
		liveNames := make(map[string]bool, len(remaining))
		for _, r := range remaining {
			liveNames[r.Name] = true
		}
		for _, wp := range allParents {
			if !liveNames[wp.Name] {
				pm.RemovePIDFile(wp.PIDFile)
			}
		}
		if !quiet {
			fmt.Printf("Watcher parent (PID: %d) still has %d agent(s), keeping alive\n", parentPID, len(remaining))
		}
		return
	}

	// Case 2: no live agents under this parent — attempt to kill it.
	// CRITICAL: do NOT prune tracking files yet. If the kill fails, the
	// user needs those files intact to retry `meshctl stop`. We prune
	// ONLY after confirming the parent is dead.

	if !IsProcessAlive(parentPID) {
		// Parent is already dead (e.g., exited on its own between
		// enumeration and now). Safe to prune all its tracking files.
		for _, wp := range allParents {
			pm.RemovePIDFile(wp.PIDFile)
		}
		return
	}

	if !quiet {
		fmt.Printf("Stopping watcher for '%s' (PID: %d)...\n", name, parentPID)
	}

	// Signal the parent meshctl process directly — NOT its process group — so we don't
	// take down unrelated siblings sharing the same group (registry, UI, etc).
	proc, perr := os.FindProcess(parentPID)
	if perr == nil {
		if sigErr := proc.Signal(syscall.SIGTERM); sigErr != nil && !quiet {
			fmt.Printf("Warning: failed to signal watcher for '%s': %v\n", name, sigErr)
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
			// Bounded poll for zombie reap — see waitForProcessDeath.
			waitForProcessDeath(parentPID, 500*time.Millisecond)
		}
	}

	if IsProcessAlive(parentPID) {
		// Kill failed — PRESERVE all tracking files so the user can retry.
		if !quiet {
			fmt.Printf("Warning: watcher for '%s' (PID: %d) may still be running — tracking files preserved\n", name, parentPID)
		}
		return
	}

	if !quiet {
		fmt.Printf("Watcher for '%s' stopped\n", name)
	}

	// Parent confirmed dead. Now safe to prune every watcher-parent tracking
	// file for it. Re-enumerate to catch any file that may have appeared since
	// the first enumeration (rare but defensive).
	leftovers, _ := pm.FindWatchParentsByPID(parentPID)
	for _, wp := range leftovers {
		pm.RemovePIDFile(wp.PIDFile)
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
	//
	// The representative name is used only for log output inside
	// stopWatcherParentIfEmpty; file cleanup is driven by enumeration, so
	// watcher-parent tracking files for all agents sharing the parent are
	// pruned even though we only call the function once per parent.
	parentPIDs := make(map[int]string) // parentPID -> representative name (for log messages)
	for _, agent := range agents {
		if agent.ParentPID > 0 {
			if _, ok := parentPIDs[agent.ParentPID]; !ok {
				parentPIDs[agent.ParentPID] = agent.Name
			}
		}
	}
	// Sort parent PIDs before iterating so log output is deterministic across
	// runs (matches the pattern in stopSpecificAgent).
	sortedParents := make([]int, 0, len(parentPIDs))
	for pid := range parentPIDs {
		sortedParents = append(sortedParents, pid)
	}
	sort.Ints(sortedParents)
	for _, parentPID := range sortedParents {
		stopWatcherParentIfEmpty(pm, parentPIDs[parentPID], parentPID, timeout, force, quiet)
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

// waitForProcessDeath polls IsProcessAlive for up to `limit` after a kill
// signal, returning true if the process died within the window. Used to let
// zombies be reaped across process boundaries — IsProcessAlive returns true
// for unreaped zombies because signal 0 only fails with ESRCH after the
// kernel fully reclaims the PID. A fixed short sleep is not enough when the
// killing meshctl is not the agent's parent: reaping depends on the spawning
// meshctl's exec.Cmd.Wait goroutine being scheduled, which may take longer
// than a handful of milliseconds on a loaded system.
func waitForProcessDeath(pid int, limit time.Duration) bool {
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if !IsProcessAlive(pid) {
			return true
		}
		time.Sleep(20 * time.Millisecond)
	}
	return !IsProcessAlive(pid)
}

// stopProcess gracefully stops a process and its entire process group
// (SIGTERM to process group, then SIGKILL after timeout).
// This ensures child processes (e.g., npx -> tsx -> node) are also terminated.
//
// Returns nil only if the process is confirmed dead. Returns an error if the
// process is still alive after the SIGKILL path (D-state, hung zombie parent,
// permission issue, pid reuse, etc.). Callers rely on this return value to
// decide whether to remove tracking files or preserve them for retry.
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
		// Let the kernel propagate the SIGKILL before the final liveness check.
		if !waitForProcessDeath(pid, 500*time.Millisecond) {
			return fmt.Errorf("process %d still alive after SIGKILL", pid)
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

	// Give the kernel a brief window to propagate SIGKILL and tear the
	// process down. SIGKILL usually succeeds, but there are edge cases
	// (D-state uninterruptible sleep, unreaped zombie with a hung parent,
	// permission denial, PID reuse, etc.) where the process may still
	// appear alive; we must report that to the caller so it can preserve
	// tracking files for a retry instead of silently losing them.
	if !waitForProcessDeath(pid, 500*time.Millisecond) {
		return fmt.Errorf("process %d still alive after SIGKILL", pid)
	}

	return nil
}

// cleanupAllFiles deletes database, log files, and PID files
func cleanupAllFiles(pm *PIDManager, quiet bool) error {
	if !quiet {
		fmt.Println("\nCleaning up...")
	}

	var deletedDB, deletedLogs, deletedPIDs int

	// Delete the registry database file from the mesh home directory
	homeDir, _ := os.UserHomeDir()
	registryDBFile := filepath.Join(homeDir, ".mcp-mesh", "mcp_mesh_registry.db")
	if err := os.Remove(registryDBFile); err == nil {
		deletedDB++
		if !quiet {
			fmt.Printf("  Deleted: %s\n", registryDBFile)
		}
	}
	// Remove SQLite WAL and SHM companion files
	for _, suffix := range []string{"-wal", "-shm"} {
		companion := registryDBFile + suffix
		if err := os.Remove(companion); err == nil {
			deletedDB++
			if !quiet {
				fmt.Printf("  Deleted: %s\n", companion)
			}
		}
	}

	// Also clean up any legacy DB file in the current directory
	const legacyDBFile = "mcp_mesh_registry.db"
	if err := os.Remove(legacyDBFile); err == nil {
		deletedDB++
		if !quiet {
			fmt.Printf("  Deleted: %s (legacy location)\n", legacyDBFile)
		}
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		os.Remove(legacyDBFile + suffix)
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

// suggestAgentNames returns up to 3 names of running agents that look similar
// to the queried name. Used by stopSpecificAgent to provide "Did you mean?"
// hints when the exact name isn't tracked — covers the common case where a
// user types a partial or mesh-registered name instead of the script-derived
// one (or vice versa).
//
// Matching is heuristic: substring match in either direction (query contains
// candidate, or candidate contains query). Good enough for typical typos and
// the digest-api/api class of mismatches. Not a full edit-distance implementation.
func suggestAgentNames(pm *PIDManager, query string) []string {
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		return nil
	}
	q := strings.ToLower(query)
	if q == "" {
		return nil
	}
	// Collect all matching candidates first, then sort deterministically
	// before capping. This decouples the function's output order from
	// ListRunningProcesses' iteration order.
	var candidates []string
	seen := make(map[string]bool)
	for _, p := range processes {
		if p.Type != "agent" || !p.Running {
			continue
		}
		if seen[p.Name] {
			continue
		}
		n := strings.ToLower(p.Name)
		if strings.Contains(n, q) || strings.Contains(q, n) {
			candidates = append(candidates, p.Name)
			seen[p.Name] = true
		}
	}
	sort.Strings(candidates)
	// Cap to 3 suggestions after sorting so the returned set is stable.
	if len(candidates) > 3 {
		candidates = candidates[:3]
	}
	return candidates
}

// quoteStrings wraps each string in single quotes for user-facing messages.
func quoteStrings(ss []string) []string {
	out := make([]string, len(ss))
	for i, s := range ss {
		out[i] = "'" + s + "'"
	}
	return out
}
