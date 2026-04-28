package cli

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"mcp-mesh/src/core/cli/lifecycle"
)

// NewStopCommand creates the stop command
func NewStopCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stop [name ...]",
		Short: "Stop detached agents and registry",
		Long: `Stop agents and/or registry running in detached mode.

Without arguments, stops all agents, the UI server, and the registry.
With name argument(s), stops only those specific agent(s); the registry/UI
servers are kept alive if other agents still depend on them.

Examples:
  meshctl stop                    # Stop all agents + UI + registry
  meshctl stop my-agent           # Stop specific agent
  meshctl stop agent1 agent2      # Stop multiple agents
  meshctl stop --registry         # Stop only the registry (force-kill, warns if deps)
  meshctl stop --ui               # Stop only the UI server (force-kill, warns if deps)
  meshctl stop --agents           # Stop all agents, keep registry/UI
  meshctl stop --keep-registry    # Stop everything except the registry
  meshctl stop --keep-ui          # Stop everything except the UI server
  meshctl stop --clean            # Stop all + delete db, logs, pids`,
		Args: cobra.ArbitraryArgs,
		RunE: runStopCommand,
	}

	cmd.Flags().Bool("registry", false, "Stop only the registry (force-kill; WARNs if other groups still depend on it)")
	cmd.Flags().Bool("ui", false, "Stop only the UI server (force-kill; WARNs if other groups still depend on it)")
	cmd.Flags().Bool("agents", false, "Stop all agents, keep registry and UI server running")
	cmd.Flags().Bool("keep-registry", false, "Stop everything except the registry")
	cmd.Flags().Bool("keep-ui", false, "Stop everything except the UI server")
	cmd.Flags().Int("timeout", 10, "Shutdown timeout in seconds per process")
	cmd.Flags().Bool("force", false, "Force kill without graceful shutdown")
	cmd.Flags().Bool("quiet", false, "Suppress output messages")
	cmd.Flags().Bool("clean", false, "Delete database, logs, and PID files after stopping all processes")

	return cmd
}

func runStopCommand(cmd *cobra.Command, args []string) error {
	registryOnly, _ := cmd.Flags().GetBool("registry")
	uiOnly, _ := cmd.Flags().GetBool("ui")
	agentsOnly, _ := cmd.Flags().GetBool("agents")
	keepRegistry, _ := cmd.Flags().GetBool("keep-registry")
	keepUI, _ := cmd.Flags().GetBool("keep-ui")
	timeout, _ := cmd.Flags().GetInt("timeout")
	force, _ := cmd.Flags().GetBool("force")
	quiet, _ := cmd.Flags().GetBool("quiet")
	clean, _ := cmd.Flags().GetBool("clean")

	// Validate flag combinations
	if registryOnly && uiOnly {
		return fmt.Errorf("cannot use --registry and --ui together")
	}
	if (registryOnly || uiOnly) && agentsOnly {
		return fmt.Errorf("cannot use --registry/--ui with --agents")
	}

	// --clean only works when stopping all (no args, not with --registry/--ui/--agents)
	if clean && (len(args) > 0 || registryOnly || uiOnly || agentsOnly) {
		return fmt.Errorf("--clean can only be used when stopping all processes")
	}

	// Create PID manager (still used by --clean and the suggestion helper)
	pm, err := NewPIDManager()
	if err != nil {
		return fmt.Errorf("failed to initialize PID manager: %w", err)
	}

	// GC sweep — drops dead-PID bookkeeping (agent .pid + .group, stale wrapper
	// markers, dead deps entries, empty deps files). NEVER kills processes.
	// Subsumes the legacy pm.CleanStalePIDFiles() call.
	if report, sweepErr := lifecycle.Sweep(); sweepErr == nil && !quiet {
		if report.DeadAgentPIDsCleaned > 0 || report.StaleGroupFilesPruned > 0 ||
			report.StaleWrapperPIDs > 0 || report.StaleWatcherPIDs > 0 ||
			report.StaleDepsEntries > 0 || report.EmptyDepsFilesRemoved > 0 {
			fmt.Printf("GC: cleaned %d dead PID(s), %d orphan group file(s), %d stale wrapper(s), %d stale watcher(s), %d dead deps entry(ies), %d empty deps file(s)\n",
				report.DeadAgentPIDsCleaned, report.StaleGroupFilesPruned,
				report.StaleWrapperPIDs, report.StaleWatcherPIDs,
				report.StaleDepsEntries, report.EmptyDepsFilesRemoved)
		}
	}

	// --force shrinks the SIGTERM phase to zero so KillVerifyAndCleanup goes
	// straight to SIGKILL.
	shutdownTimeout := time.Duration(timeout) * time.Second
	if force {
		shutdownTimeout = 0
	}

	// Handle specific agent stop (one or more names)
	if len(args) > 0 {
		var failures []string
		for _, name := range args {
			if err := stopSpecificAgent(pm, name, shutdownTimeout, quiet, keepRegistry, keepUI); err != nil {
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

	// --registry: force-kill only the registry, after WARNing about deps.
	if registryOnly {
		return stopServiceForce(lifecycle.ServiceRegistry, "registry", shutdownTimeout, quiet)
	}

	// --ui: force-kill only the UI, after WARNing about deps.
	if uiOnly {
		return stopServiceForce(lifecycle.ServiceUI, "UI server", shutdownTimeout, quiet)
	}

	// --agents: stop all agents, keep registry and UI running regardless.
	if agentsOnly {
		return stopAllAgents(shutdownTimeout, quiet)
	}

	// Default: stop everything, modulated by --keep-registry / --keep-ui.
	if err := stopAll(shutdownTimeout, quiet, keepRegistry, keepUI); err != nil {
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

// stopSpecificAgent stops a single agent by name and unregisters its
// dependencies on the registry/UI. The registry and UI are NOT stopped here
// — they're refcounted via deps files and only stopped when the last
// dependent group goes away (handled by stopAll).
//
// Returns an error if no PID file exists for the agent (with a "did you mean"
// hint), or if the kill couldn't be verified within the timeout. A successful
// stop removes both <agent>.pid and <agent>.group, and unregisters the agent
// from registry/deps and ui/deps for its group.
func stopSpecificAgent(pm *PIDManager, name string, timeout time.Duration, quiet, keepRegistry, keepUI bool) error {
	entry, err := lifecycle.LookupAgent(name)
	if err != nil {
		return fmt.Errorf("lookup %s: %w", name, err)
	}
	if entry == nil {
		// Agent not tracked. Suggest similar names if any are running.
		suggestions := suggestAgentNames(pm, name)
		if len(suggestions) > 0 {
			return fmt.Errorf("agent '%s' is not running. Did you mean: %s?",
				name, strings.Join(quoteStrings(suggestions), ", "))
		}
		return fmt.Errorf("agent '%s' is not running", name)
	}

	// Read the group BEFORE killing — KillVerifyAndCleanup removes the .group
	// file on success, after which we'd no longer be able to find the right
	// deps file to unregister from. Distinguish "no .group file" (fine — older
	// agent or services) from "garbled .group file" (loud warn — silently
	// treating corruption as no-group would orphan deps entries forever).
	group, gErr := lifecycle.LookupGroup(name)
	if gErr != nil && !errors.Is(gErr, lifecycle.ErrNoGroup) {
		fmt.Fprintf(os.Stderr, "warning: %v\n", gErr)
		group = ""
	}

	// Watch-mode wrapper: if a watcher meshctl owns this agent, kill it FIRST.
	// Otherwise the watcher would respawn the agent the moment the next file
	// system event fires (which can be triggered by anything, including unrelated
	// `git checkout`). Killing the watcher then the agent guarantees no respawn.
	killWatcherForAgent(name, timeout, quiet)

	if !entry.Alive {
		if !quiet {
			fmt.Printf("Agent '%s' is not running (cleaning stale PID file)\n", name)
		}
	} else if !quiet {
		fmt.Printf("Stopping agent '%s' (PID: %d)...\n", name, entry.PID)
	}

	killed, err := lifecycle.KillVerifyAndCleanup(name, timeout)
	if err != nil {
		return fmt.Errorf("agent '%s' could not be stopped (%v) — tracking preserved for retry", name, err)
	}
	if killed && !quiet {
		fmt.Printf("Agent '%s' stopped\n", name)
	}

	// Unregister from registry/UI deps so refcount can drop to zero.
	if group != "" {
		_ = lifecycle.UnregisterDep(lifecycle.ServiceRegistry, group, []string{name})
		_ = lifecycle.UnregisterDep(lifecycle.ServiceUI, group, []string{name})
	}

	// Symmetric refcount reap: if this was the last dependent for either
	// service, stop the service too (subject to --keep-* flags). Without this,
	// `meshctl stop <agent>` leaves the registry/UI orphaned even when nothing
	// else depends on them. The mass-stop path goes through stopAll which calls
	// stopServiceIfRefcountZero — this block does the same for the per-agent
	// path so both routes converge on the same end state.
	if !keepRegistry {
		stopServiceIfRefcountZero(lifecycle.ServiceRegistry, "registry", timeout, quiet)
	}
	if !keepUI {
		stopServiceIfRefcountZero(lifecycle.ServiceUI, "UI server", timeout, quiet)
	}
	return nil
}

// killWatcherForAgent stops the watch-mode meshctl wrapper that owns the
// given agent, if any. Reads <agent>.watcher.pid; if the PID is alive, sends
// SIGTERM (then SIGKILL on timeout) to that meshctl process so it can't
// respawn the agent after we kill it.
//
// The watcher's signal handler runs `terminateAgent` on each managed
// AgentWatcher, so a graceful TERM should also kill the agent — but the
// caller MUST still kill the agent explicitly afterward to be defensive
// against signal-handling edge cases (e.g., the watcher already dead but its
// .pid file stale, or the agent leaking out of the watcher's process group).
//
// Idempotent: missing .watcher.pid is a no-op. Failure to verify the kill is
// logged (when not quiet) but doesn't return an error — the caller's job is
// to kill the agent regardless.
func killWatcherForAgent(agent string, timeout time.Duration, quiet bool) {
	pid, err := lifecycle.ReadWatcherPID(agent)
	if err != nil || pid == 0 {
		return
	}
	if !lifecycle.IsAlive(pid) {
		// Watcher already gone — just clean the stale sidecar.
		_ = lifecycle.RemoveWatcher(agent)
		return
	}
	if !quiet {
		fmt.Printf("Stopping watcher for '%s' (PID: %d)...\n", agent, pid)
	}
	// We can't reuse KillVerifyAndCleanup because that's keyed on the
	// <name>.pid file convention and would try to remove <agent>.watcher (no
	// such file). Inline the TERM+poll+KILL dance against the bare PID, then
	// remove the sidecar by hand.
	if killProcessByPID(pid, timeout) {
		_ = lifecycle.RemoveWatcher(agent)
		if !quiet {
			fmt.Printf("Watcher for '%s' stopped\n", agent)
		}
		return
	}
	if !quiet {
		fmt.Printf("Warning: watcher for '%s' (PID %d) did not exit cleanly\n", agent, pid)
	}
	// Even on verify failure, remove the sidecar so a subsequent stop doesn't
	// keep finding the same dead-process PID. The agent kill that follows
	// will surface any real "process won't die" condition.
	_ = lifecycle.RemoveWatcher(agent)
}

// killProcessByPID is a lightweight TERM-then-KILL helper for PIDs that don't
// have a corresponding <name>.pid file in the lifecycle layer (specifically
// watcher meshctl processes). Returns true on confirmed death (including
// zombie state — see lifecycle.KillVerifyAndCleanup commentary).
func killProcessByPID(pid int, timeout time.Duration) bool {
	if pid <= 0 || !lifecycle.IsAlive(pid) {
		return true
	}
	// SIGTERM the process group first (the watcher meshctl was started with
	// Setpgid in forkToBackground, so its group includes the watcher's
	// agent grandchild). Group signal also helps if the watcher isn't
	// process-group leader for some reason.
	_ = syscall.Kill(-pid, syscall.SIGTERM)
	_ = syscall.Kill(pid, syscall.SIGTERM)
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !lifecycle.IsAlive(pid) {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	// Force kill if SIGTERM didn't take.
	_ = syscall.Kill(-pid, syscall.SIGKILL)
	_ = syscall.Kill(pid, syscall.SIGKILL)
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !lifecycle.IsAlive(pid) {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	return !lifecycle.IsAlive(pid)
}

// stopAllAgents stops every agent on disk in parallel, but never touches the
// registry or UI services. After the agents die, their group files are gone
// so deps can be unregistered correctly.
func stopAllAgents(timeout time.Duration, quiet bool) error {
	agents, err := lifecycle.ListAgents()
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

	var (
		wg                   sync.WaitGroup
		mu                   sync.Mutex
		stopped, failed      int
		// (group, service) -> agent names to unregister, batched per group.
	)
	depUnregister := make(map[string]map[string][]string) // service -> group -> agents

	for _, agent := range agents {
		wg.Add(1)
		go func(a lifecycle.AgentEntry) {
			defer wg.Done()
			// Watch-mode wrapper goes first — see stopSpecificAgent commentary.
			killWatcherForAgent(a.Name, timeout, quiet)
			if !quiet {
				mu.Lock()
				fmt.Printf("Stopping agent '%s' (PID: %d)...\n", a.Name, a.PID)
				mu.Unlock()
			}
			_, err := lifecycle.KillVerifyAndCleanup(a.Name, timeout)
			mu.Lock()
			defer mu.Unlock()
			if err != nil {
				if !quiet {
					fmt.Printf("Failed to stop agent '%s': %v\n", a.Name, err)
				}
				failed++
				return
			}
			stopped++
			if !quiet {
				fmt.Printf("Agent '%s' stopped\n", a.Name)
			}
			if a.Group != "" {
				for _, svc := range []string{lifecycle.ServiceRegistry, lifecycle.ServiceUI} {
					if depUnregister[svc] == nil {
						depUnregister[svc] = map[string][]string{}
					}
					gid := a.Group.String()
					depUnregister[svc][gid] = append(depUnregister[svc][gid], a.Name)
				}
			}
		}(agent)
	}
	wg.Wait()

	// Apply deps unregistration once per (service, group). Must happen AFTER
	// all kills so a single deps-file rewrite captures the full batch.
	for svc, byGroup := range depUnregister {
		for gid, names := range byGroup {
			g, _ := lifecycle.Parse(gid)
			_ = lifecycle.UnregisterDep(svc, g, names)
		}
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

// stopAll stops agents, then UI, then registry. UI/registry are skipped if
// the corresponding --keep-* flag is set OR if their refcount is non-zero
// after the agents die (means another group still depends on them).
//
// Refcount is the canonical signal — even with --keep-* unset, a service
// stays up if a separate `meshctl start` invocation registered a dep on it.
// Stopping a service while another group depends on it is the explicit job
// of `meshctl stop --registry` / `--ui`.
func stopAll(timeout time.Duration, quiet, keepRegistry, keepUI bool) error {
	if err := stopAllAgents(timeout, quiet); err != nil {
		// Continue to service shutdown even if some agents failed; the user's
		// intent was "stop everything" and partial progress is preferable to
		// leaving services up.
		if !quiet {
			fmt.Printf("Warning: %v\n", err)
		}
	}

	// Drop sentinel deps entries (e.g. "_ui_only_" from a standalone
	// `meshctl start --ui`) before refcount checks. Sentinels exist to keep
	// per-agent stops from accidentally tearing down a separately-started
	// service, but a no-args `meshctl stop` is the universal shutdown — the
	// user's intent is "everything off", and a standalone UI must come down
	// with it (only --keep-ui can save it).
	if !keepUI {
		_ = lifecycle.PruneSentinelDeps(lifecycle.ServiceUI)
	}
	if !keepRegistry {
		_ = lifecycle.PruneSentinelDeps(lifecycle.ServiceRegistry)
	}

	// UI before registry (UI depends on registry).
	if !keepUI {
		stopServiceIfRefcountZero(lifecycle.ServiceUI, "UI server", timeout, quiet)
	} else if !quiet {
		fmt.Println("Keeping UI server alive (--keep-ui)")
	}

	if !keepRegistry {
		stopServiceIfRefcountZero(lifecycle.ServiceRegistry, "registry", timeout, quiet)
	} else if !quiet {
		fmt.Println("Keeping registry alive (--keep-registry)")
	}

	return nil
}

// stopServiceIfRefcountZero stops the service ONLY when no group has agents
// listed in its deps directory. Otherwise leaves it alone — another live
// `meshctl start` group still depends on it.
func stopServiceIfRefcountZero(service, displayName string, timeout time.Duration, quiet bool) {
	zero, err := lifecycle.IsServiceRefcountZero(service)
	if err != nil {
		if !quiet {
			fmt.Printf("Warning: refcount check for %s failed: %v\n", displayName, err)
		}
		return
	}
	if !zero {
		groups, _ := lifecycle.DepsForService(service)
		if !quiet {
			fmt.Printf("Keeping %s alive (refcount=%d, group(s): %s)\n",
				displayName, len(groups), formatGroups(groups))
		}
		return
	}

	// Only stop the service if its PID file is present and the process is alive.
	info, err := lifecycle.LookupService(service)
	if err != nil || info == nil {
		return
	}
	if !info.Alive {
		_ = lifecycle.RemoveService(service)
		return
	}
	if !quiet {
		fmt.Printf("Stopping %s (PID: %d)...\n", displayName, info.PID)
	}
	if _, err := lifecycle.KillVerifyAndCleanup(service, timeout); err != nil {
		if !quiet {
			fmt.Printf("Failed to stop %s: %v\n", displayName, err)
		}
		return
	}
	if !quiet {
		fmt.Printf("%s stopped\n", displayName)
	}
}

// stopServiceForce always kills the service. If groups still depend on it,
// emit a stderr WARN listing the dependent group-ids first; then proceed.
// Per user decision Q2: --registry / --ui never refuse — they always force-kill
// and just warn loudly.
func stopServiceForce(service, displayName string, timeout time.Duration, quiet bool) error {
	groups, err := lifecycle.DepsForService(service)
	if err != nil {
		return fmt.Errorf("refcount check for %s: %w", displayName, err)
	}
	if len(groups) > 0 {
		fmt.Fprintf(os.Stderr, "WARN: stopping %s with %d dependent group(s): %s\n",
			displayName, len(groups), formatGroups(groups))
	}

	info, err := lifecycle.LookupService(service)
	if err != nil {
		return err
	}
	if info == nil {
		if !quiet {
			fmt.Printf("%s is not running in background\n", displayName)
		}
		return nil
	}
	if !info.Alive {
		_ = lifecycle.RemoveService(service)
		if !quiet {
			fmt.Printf("%s is not running (cleaned stale PID file)\n", displayName)
		}
		return nil
	}
	if !quiet {
		fmt.Printf("Stopping %s (PID: %d)...\n", displayName, info.PID)
	}
	if _, err := lifecycle.KillVerifyAndCleanup(service, timeout); err != nil {
		return fmt.Errorf("failed to stop %s: %w", displayName, err)
	}
	if !quiet {
		fmt.Printf("%s stopped\n", displayName)
	}
	return nil
}

// formatGroups joins GroupIDs into a comma-separated display string. Order
// is whatever DepsForService returned (already sorted lexicographically).
func formatGroups(groups []lifecycle.GroupID) string {
	if len(groups) == 0 {
		return ""
	}
	out := make([]string, len(groups))
	for i, g := range groups {
		out[i] = g.String()
	}
	return strings.Join(out, ", ")
}

// cleanupAllFiles deletes database, log files, and PID files
func cleanupAllFiles(pm *PIDManager, quiet bool) error {
	if !quiet {
		fmt.Println("\nCleaning up...")
	}

	var deletedDB, deletedLogs, deletedPIDs int

	// Delete the registry database file from the mesh home directory
	homeDir, err := os.UserHomeDir()
	if err == nil {
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

	// Delete PID files (and .group files, deps files, lock files — everything
	// in the lifecycle directories).
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

	// Also wipe deps directories.
	for _, depDir := range []string{lifecycle.RegistryDepsDir(), lifecycle.UIDepsDir()} {
		entries, _ := os.ReadDir(depDir)
		for _, entry := range entries {
			if !entry.IsDir() {
				if err := os.Remove(filepath.Join(depDir, entry.Name())); err == nil {
					deletedPIDs++
				}
			}
		}
	}

	if deletedPIDs > 0 && !quiet {
		fmt.Printf("  Deleted: %d PID/deps file(s)\n", deletedPIDs)
	}

	if !quiet {
		if deletedDB == 0 && deletedLogs == 0 && deletedPIDs == 0 {
			fmt.Println("  Nothing to clean")
		} else {
			fmt.Println("Cleanup complete")
		}
	}

	return nil
}

// suggestAgentNames returns up to 3 names of running agents that look similar
// to the queried name. Used by stopSpecificAgent to provide "Did you mean?"
// hints when the exact name isn't tracked.
func suggestAgentNames(_ *PIDManager, query string) []string {
	agents, err := lifecycle.ListAgents()
	if err != nil {
		return nil
	}
	q := strings.ToLower(query)
	if q == "" {
		return nil
	}
	var candidates []string
	seen := make(map[string]bool)
	for _, a := range agents {
		if !a.Alive {
			continue
		}
		if seen[a.Name] {
			continue
		}
		n := strings.ToLower(a.Name)
		if strings.Contains(n, q) || strings.Contains(q, n) {
			candidates = append(candidates, a.Name)
			seen[a.Name] = true
		}
	}
	sort.Strings(candidates)
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
