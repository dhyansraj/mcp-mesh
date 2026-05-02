package cli

import (
	"encoding/xml"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"

	"mcp-mesh/src/core/cli/handlers"
	"mcp-mesh/src/core/cli/lifecycle"
)

// envGroupID is the env var forkToBackground uses to thread the wrapper's
// group-id through to the forked child. Direct (non-detach) invocations
// don't see this var and synthesize their own group-id.
const envGroupID = "MCP_MESH_GROUP_ID"

// uiOnlyDepSentinel is the placeholder agent name used to keep a UI deps file
// non-empty when `meshctl start --ui` is called with no agents. Lets the
// refcount machinery report "UI is in use" even with no real agents.
//
// NOTE: All sentinel names MUST start with "_". The lifecycle layer (gc.go,
// enumerate.go) treats any deps entry beginning with "_" as a sentinel: GC
// never reaps it for "missing PID" liveness, ListAgents never returns it, and
// only `meshctl stop` (no args) clears it via lifecycle.PruneSentinelDeps so a
// "stop everything" command can bring down a standalone --ui session.
const uiOnlyDepSentinel = "_ui_only_"

// resolveGroupID returns the active group-id for this meshctl invocation.
// Forked-detach children inherit via env; everyone else mints a fresh ID.
func resolveGroupID() lifecycle.GroupID {
	if v := os.Getenv(envGroupID); v != "" {
		if g, err := lifecycle.Parse(v); err == nil {
			return g
		}
	}
	return lifecycle.NewGroupID()
}

// agentNameCache caches extracted agent names to avoid repeated parsing
// Uses sync.Map for thread-safe concurrent access when starting multiple agents
var agentNameCache sync.Map

// Standard mode
func startStandardMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	quiet, _ := cmd.Flags().GetBool("quiet")

	// Note: Prerequisites are validated in runStartCommand before reaching here

	// Resolve the group-id for this invocation. Forked-detach children inherit
	// via env (set by forkToBackground); direct invocations mint a fresh ID.
	// All agents started by this invocation share this ID and will register as
	// dependents of registry/UI under it, so stop can refcount correctly.
	group := resolveGroupID()

	// Determine registry URL from flags or config
	registryURL := determineStartRegistryURL(cmd, config)

	// locallyStartedRegistryPID records the PID of a registry that was started by
	// THIS meshctl invocation. It's threaded through to runAgentsInForeground via
	// startAgentsWithEnv so shutdown can decide whether to kill the registry.
	// 0 means this meshctl did not start a registry (e.g., it was already running,
	// started by another meshctl) and shutdown will leave it alone.
	var locallyStartedRegistryPID int

	// Check if registry is running. Wrapped in WithStartLock so concurrent
	// meshctl invocations racing to start the registry serialize on the start
	// path: loser of the race acquires the lock, re-checks IsRegistryRunning,
	// finds it true, and falls into the reuse branch.
	if !IsRegistryRunning(registryURL) {
		// Only attempt to start registry if connecting to localhost
		registryHost := getRegistryHostFromURL(registryURL, config.RegistryHost)
		if isLocalhostRegistry(registryHost) {
			err := lifecycle.WithStartLock(lifecycle.ServiceRegistry, func() error {
				// Re-check inside the lock — winner of the race already started it.
				if IsRegistryRunning(registryURL) {
					return nil
				}
				if !quiet {
					fmt.Printf("Registry not found at %s, starting embedded registry...\n", registryURL)
				}

				registryPort := getRegistryPortFromURL(registryURL, config.RegistryPort)
				if !IsPortAvailable(registryHost, registryPort) {
					return fmt.Errorf("cannot start registry: port %d is already in use on %s", registryPort, registryHost)
				}

				// Port is free, but another registry might be running on a different
				// port. The PID guard catches this case without interfering with
				// concurrent starts on the same port (handled by port check above).
				pm2, pidErr := NewPIDManager()
				if pidErr == nil {
					existingPID, err := pm2.ReadPID("registry")
					if err == nil && existingPID > 0 && existingPID != os.Getpid() && IsProcessAlive(existingPID) {
						return fmt.Errorf("a registry is already running (PID %d) but not reachable at %s. Stop it with 'meshctl stop --registry' and try again", existingPID, registryURL)
					}
				}

				registryPID, err := startRegistryWithOptions(config, true, cmd)
				if err != nil {
					return fmt.Errorf("failed to start registry: %w", err)
				}

				startupTimeout, _ := cmd.Flags().GetInt("startup-timeout")
				if startupTimeout == 0 {
					startupTimeout = config.StartupTimeout
				}
				if err := WaitForRegistry(registryURL, time.Duration(startupTimeout)*time.Second); err != nil {
					return fmt.Errorf("registry startup timeout: %w", err)
				}
				locallyStartedRegistryPID = registryPID
				return nil
			})
			if err != nil {
				return err
			}
		} else {
			// Remote registry - cannot start, must connect to existing
			return fmt.Errorf("cannot connect to remote registry at %s - please ensure the registry is running", registryURL)
		}
	}

	// Start UI server if --ui flag is set (before agents, which may block in foreground).
	// Lock-acquire failure is non-fatal: warn (inside helper) and continue without UI.
	_ = maybeStartUIServer(cmd, config, registryURL)

	// Build environment for agents
	agentEnv := buildAgentEnvironment(cmd, registryURL, config)

	return startAgentsWithEnv(args, agentEnv, cmd, config, locallyStartedRegistryPID, group)
}

// Connect-only mode
func startConnectOnlyMode(cmd *cobra.Command, args []string, registryURL string, config *CLIConfig) error {
	if len(args) == 0 {
		return fmt.Errorf("agent file required in connect-only mode")
	}

	quiet, _ := cmd.Flags().GetBool("quiet")

	// Note: Prerequisites are validated in runStartCommand before reaching here

	// Resolve group-id (same rationale as startStandardMode).
	group := resolveGroupID()

	// Validate registry connection
	if !IsRegistryRunning(registryURL) {
		return fmt.Errorf("cannot connect to registry at %s", registryURL)
	}

	if !quiet {
		fmt.Printf("Connecting to external registry at %s\n", registryURL)
	}

	// Build environment for agents
	agentEnv := buildAgentEnvironment(cmd, registryURL, config)

	// Start agents with external registry. Pass 0 for locallyStartedRegistryPID
	// because connect-only mode never starts a registry — the external one must
	// remain running after this meshctl exits.
	return startAgentsWithEnv(args, agentEnv, cmd, config, 0, group)
}

// Background mode
func startBackgroundMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	// Note: We no longer check a single global PID file here.
	// Per-agent PID files are written by startAgentsWithEnv when agents start.
	// This allows running multiple 'meshctl start --detach' commands for different agents.

	// Fork to detach
	return forkToBackground(cmd, args, config)
}

// Build agent environment with all flag support
func buildAgentEnvironment(cmd *cobra.Command, registryURL string, config *CLIConfig) []string {
	env := os.Environ()

	// Add registry configuration
	env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_URL=%s", registryURL))
	env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_HOST=%s", config.RegistryHost))
	env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_PORT=%d", config.RegistryPort))

	// Add database path
	env = append(env, fmt.Sprintf("MCP_MESH_DATABASE_URL=sqlite:///%s", config.DBPath))

	// Add logging configuration
	env = append(env, fmt.Sprintf("MCP_MESH_LOG_LEVEL=%s", config.LogLevel))
	env = append(env, fmt.Sprintf("MCP_MESH_DEBUG_MODE=%t", config.DebugMode))

	// Also set MCP_MESH_DEBUG for Python decorator compatibility
	if config.DebugMode {
		env = append(env, "MCP_MESH_DEBUG=true")
	}

	// Add custom environment variables from --env flag
	customEnv, _ := cmd.Flags().GetStringArray("env")
	env = append(env, customEnv...)

	// Add agent-specific overrides
	if agentName, _ := cmd.Flags().GetString("agent-name"); agentName != "" {
		env = append(env, fmt.Sprintf("MCP_MESH_AGENT_NAME=%s", agentName))
	}

	if agentVersion, _ := cmd.Flags().GetString("agent-version"); agentVersion != "" {
		env = append(env, fmt.Sprintf("MCP_MESH_AGENT_VERSION=%s", agentVersion))
	}

	capabilities, _ := cmd.Flags().GetStringArray("capabilities")
	if len(capabilities) > 0 {
		env = append(env, fmt.Sprintf("MCP_MESH_AGENT_CAPABILITIES=%s", strings.Join(capabilities, ",")))
	}

	return env
}

// Start agents with environment.
// locallyStartedRegistryPID is the PID of a registry that this meshctl invocation
// started itself (0 if it did not start one); it's threaded through to
// runAgentsInForeground so shutdown can decide whether to kill the registry.
// groupID is the lifecycle group-id this invocation belongs to (used to write
// .group files and register registry/UI deps).
func startAgentsWithEnv(agentPaths []string, env []string, cmd *cobra.Command, config *CLIConfig, locallyStartedRegistryPID int, groupID lifecycle.GroupID) error {
	var agentCmds []*exec.Cmd
	var watchers []*AgentWatcher
	workingDir, _ := cmd.Flags().GetString("working-dir")
	user, _ := cmd.Flags().GetString("user")
	posixGroup, _ := cmd.Flags().GetString("group")
	detach, _ := cmd.Flags().GetBool("detach")
	quiet, _ := cmd.Flags().GetBool("quiet")
	watch, _ := cmd.Flags().GetBool("watch")
	uiEnabled, _ := cmd.Flags().GetBool("ui")

	// Check if stdout is redirected (not a terminal) - indicates background/forked mode
	// In this case, we create per-agent log files even though detach=false
	isBackgroundMode := !isTerminal(os.Stdout)

	// Initialize log manager once if we'll need it (avoid creating per-agent)
	var lm *LogManager
	if detach || isBackgroundMode {
		var err error
		lm, err = NewLogManager()
		if err != nil {
			return fmt.Errorf("failed to initialize log manager: %w", err)
		}
	}

	if watch && !quiet {
		fmt.Println("🔄 Watch mode enabled - agents will restart on file changes")
	}

	// Names of agents that the lifecycle layer will track for this invocation.
	// Filled in two places:
	//   - direct-detach (-d) path below, where we WriteAgent inline
	//   - foreground/runAgentsInForeground, which manages its own RegisterDep
	// Used here to RegisterDep registry/UI deps once per detach invocation
	// before returning.
	var detachAgentNames []string

	for _, agentPath := range agentPaths {
		// Convert to absolute path
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return fmt.Errorf("invalid agent path %s: %w", agentPath, err)
		}

		// Defense-in-depth: refuse-if-running. The parent runStartCommand
		// already performs this check before forkToBackground, but foreground
		// + connect-only callers reach here directly. Re-checking here also
		// closes a tiny race where another meshctl could win between the
		// parent check and the child spawn.
		if name := extractAgentName(absPath); name != "" {
			running, pid, rerr := lifecycle.IsAgentRunning(name)
			if rerr != nil {
				return fmt.Errorf("failed to check if agent %s is running: %w", name, rerr)
			}
			if running {
				return fmt.Errorf("agent '%s' is already running (PID %d). Stop it first with 'meshctl stop %s'.", name, pid, name)
			}
		}

		if !quiet {
			fmt.Printf("Starting agent: %s\n", absPath)
		}

		// Generate per-agent TLS cert and augment env if --tls-auto is enabled
		agentEnv := env
		if config.TLSAuto && config.TLSAutoConfigRef != nil {
			agentName := extractAgentName(absPath)
			certPath, keyPath, err := config.TLSAutoConfigRef.GenerateAgentCert(agentName)
			if err != nil {
				return fmt.Errorf("failed to generate TLS cert for agent %s: %w", agentName, err)
			}
			agentEnv = append(append([]string{}, env...), config.TLSAutoConfigRef.GetAgentTLSEnv(certPath, keyPath)...)
		}

		// For Java agents with watch mode, use AgentWatcher instead of bash wrapper
		if watch && isJavaProject(absPath) {
			watcher, err := createJavaWatcher(absPath, agentEnv, workingDir, user, posixGroup, quiet)
			if err != nil {
				return fmt.Errorf("failed to create watcher for %s: %w", agentPath, err)
			}

			if lm != nil {
				agentName := watcher.config.AgentName
				watcher.config.LogFileFactory = func() (*os.File, error) {
					lm.RotateLogs(agentName)
					return lm.CreateLogFile(agentName)
				}
			}

			watchers = append(watchers, watcher)
			continue
		}

		// For Python agents with watch mode, use AgentWatcher instead of reload_runner
		if watch && isPythonProject(absPath) {
			watcher, err := createPythonWatcher(absPath, agentEnv, workingDir, user, posixGroup, quiet)
			if err != nil {
				return fmt.Errorf("failed to create watcher for %s: %w", agentPath, err)
			}

			if lm != nil {
				agentName := watcher.config.AgentName
				watcher.config.LogFileFactory = func() (*os.File, error) {
					lm.RotateLogs(agentName)
					return lm.CreateLogFile(agentName)
				}
			}

			watchers = append(watchers, watcher)
			continue
		}

		// Create agent command with enhanced environment
		agentCmd, err := createAgentCommand(absPath, agentEnv, workingDir, user, posixGroup, watch)
		if err != nil {
			return fmt.Errorf("failed to prepare agent %s: %w", agentPath, err)
		}

		// Create per-agent log files if:
		// 1. Running in direct detach mode (-d flag), OR
		// 2. Running in background mode (stdout redirected, not a terminal)
		if detach || isBackgroundMode {
			// Extract agent name from @mesh.agent decorator, fall back to filename
			agentName := extractAgentName(absPath)

			// Rotate existing logs
			if err := lm.RotateLogs(agentName); err != nil && !quiet {
				fmt.Printf("Warning: failed to rotate logs for %s: %v\n", agentName, err)
			}

			// Create log file and redirect output
			logFile, err := lm.CreateLogFile(agentName)
			if err != nil {
				return fmt.Errorf("failed to create log file for %s: %w", agentName, err)
			}
			agentCmd.Stdout = logFile
			agentCmd.Stderr = logFile

			if err := agentCmd.Start(); err != nil {
				logFile.Close()
				return fmt.Errorf("failed to start agent %s: %w", agentPath, err)
			}

			// Write PID + group file via the lifecycle layer so stop can find
			// the agent and unregister its registry/UI deps.
			if err := lifecycle.WriteAgent(agentName, agentCmd.Process.Pid, groupID); err != nil && !quiet {
				fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
			}
			detachAgentNames = append(detachAgentNames, agentName)

			// Record agent process
			agentProc := ProcessInfo{
				PID:       agentCmd.Process.Pid,
				Name:      agentName,
				Type:      "agent",
				Command:   agentCmd.String(),
				StartTime: time.Now(),
				Status:    "running",
				FilePath:  absPath,
			}
			if err := AddRunningProcess(agentProc); err != nil && !quiet {
				fmt.Printf("Warning: failed to record agent process: %v\n", err)
			}

			if !quiet {
				fmt.Printf("Agent %s started (PID: %d)\n", agentName, agentCmd.Process.Pid)
			}
		} else {
			// For foreground mode, we'll start the process later
			agentCmds = append(agentCmds, agentCmd)
		}
	}

	if (detach || isBackgroundMode) && len(watchers) == 0 {
		// Direct-detach / background path: agents are already running with their
		// own log files. Register them as registry/UI dependents so stop can
		// refcount the services correctly, then return.
		registerInvocationDeps(groupID, detachAgentNames, uiEnabled, quiet)
		return nil
	}

	// If running in foreground, start agents and wait
	if len(agentCmds) > 0 || len(watchers) > 0 {
		return runAgentsInForeground(agentCmds, watchers, cmd, config, locallyStartedRegistryPID, groupID, uiEnabled)
	}

	return nil
}

// registerInvocationDeps registers this invocation's agents (and the UI
// sentinel if --ui was set) as dependents of registry and UI. Called from the
// detach/background path AND foreground after agents are running. Safe to call
// with no agents — UI sentinel still gets registered if uiEnabled is true.
func registerInvocationDeps(group lifecycle.GroupID, agents []string, uiEnabled, quiet bool) {
	if len(agents) > 0 {
		if err := lifecycle.RegisterDep(lifecycle.ServiceRegistry, group, agents); err != nil && !quiet {
			fmt.Printf("Warning: failed to register registry deps: %v\n", err)
		}
		if uiEnabled {
			if err := lifecycle.RegisterDep(lifecycle.ServiceUI, group, agents); err != nil && !quiet {
				fmt.Printf("Warning: failed to register UI deps: %v\n", err)
			}
		}
		return
	}
	// No agents but UI requested — register the sentinel so the UI deps file
	// is non-empty and IsServiceRefcountZero correctly reports the UI is in use.
	if uiEnabled {
		if err := lifecycle.RegisterDep(lifecycle.ServiceUI, group, []string{uiOnlyDepSentinel}); err != nil && !quiet {
			fmt.Printf("Warning: failed to register UI sentinel dep: %v\n", err)
		}
	}
}

func runAgentsInForeground(agentCmds []*exec.Cmd, watchers []*AgentWatcher, cmd *cobra.Command, config *CLIConfig, locallyStartedRegistryPID int, groupID lifecycle.GroupID, uiEnabled bool) error {
	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Println("Agents are running. Press Ctrl+C to stop all services.")
	}

	// Names of all agents this invocation manages (flat or watch-mode). Used
	// at shutdown for RemoveAgent + UnregisterDep, and at startup for
	// registerInvocationDeps.
	var trackedNames []string

	// localAgentPIDs tracks the PIDs of agents started by THIS invocation.
	// Used at shutdown to kill only our own children — we deliberately do
	// NOT use GetRunningProcesses() for cleanup, because that reads a
	// globally-shared processes.json that would cause cross-instance cascade
	// kills.
	//
	// Map (not slice) so entries can be REMOVED when a child exits naturally
	// — otherwise the OS could reuse the PID for an unrelated process and
	// the shutdown loop would kill the wrong thing.
	var localAgentPIDsMu sync.Mutex
	localAgentPIDs := make(map[int]struct{})

	// Start non-watch agents
	for i, agentCmd := range agentCmds {
		if err := agentCmd.Start(); err != nil {
			return fmt.Errorf("failed to start agent: %w", err)
		}

		agentName := fmt.Sprintf("agent-%d", i)
		for _, arg := range agentCmd.Args {
			if strings.HasSuffix(arg, ".py") {
				agentName = filepath.Base(arg)
				agentName = strings.TrimSuffix(agentName, ".py")
				break
			}
		}
		trackedNames = append(trackedNames, agentName)
		localAgentPIDsMu.Lock()
		localAgentPIDs[agentCmd.Process.Pid] = struct{}{}
		localAgentPIDsMu.Unlock()

		// Write PID + group via lifecycle so stop can find and unregister this agent.
		if err := lifecycle.WriteAgent(agentName, agentCmd.Process.Pid, groupID); err != nil && !quiet {
			fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
		}

		agentProc := ProcessInfo{
			PID:       agentCmd.Process.Pid,
			Name:      agentName,
			Type:      "agent",
			Command:   agentCmd.String(),
			StartTime: time.Now(),
			Status:    "running",
		}
		if err := AddRunningProcess(agentProc); err != nil && !quiet {
			fmt.Printf("Warning: failed to record agent process: %v\n", err)
		}

		// Reaper goroutine: drop the PID from the live set when the child exits
		// naturally so the shutdown loop doesn't target a recycled PID.
		go func(c *exec.Cmd, name string) {
			if err := c.Wait(); err != nil && !quiet {
				fmt.Printf("Agent exited with error: %v\n", err)
			}
			localAgentPIDsMu.Lock()
			delete(localAgentPIDs, c.Process.Pid)
			localAgentPIDsMu.Unlock()
			RemoveRunningProcess(c.Process.Pid)
			_ = lifecycle.RemoveAgent(name)
		}(agentCmd, agentName)
	}

	// Watch-mode agents: PIDUpdateCallback fires on initial start and on every
	// restart. Each callback rewrites <name>.pid + <name>.group via the
	// lifecycle layer — no per-parent-PID namespacing needed because group-id
	// is now the disambiguator across concurrent meshctl invocations.
	//
	// Also write a <agent>.watcher.pid sidecar pointing at THIS meshctl process:
	// stop reads it to kill the watcher BEFORE the agent so the watcher can't
	// respawn the agent on a stale FS event between agent-death and stop-exit.
	// One file per agent (1:1 with the watcher); cleaned up by RemoveAgent on
	// graceful shutdown and by GC if this meshctl crashes.
	watcherOwnerPID := os.Getpid()
	for _, w := range watchers {
		name := w.config.AgentName
		w.config.PIDUpdateCallback = func(pid int) {
			if err := lifecycle.WriteAgent(name, pid, groupID); err != nil && !quiet {
				fmt.Printf("Warning: failed to update PID file for %s: %v\n", name, err)
			}
		}
		if err := lifecycle.WriteWatcher(name, watcherOwnerPID); err != nil && !quiet {
			fmt.Printf("Warning: failed to write watcher PID file for %s: %v\n", name, err)
		}
	}

	// Start watchers in goroutines.
	for _, w := range watchers {
		go func(watcher *AgentWatcher) {
			if err := watcher.Start(); err != nil && !quiet {
				fmt.Printf("Watcher error: %v\n", err)
			}
		}(w)
	}

	// Brief settle for watchers to spawn their initial agent processes.
	time.Sleep(1 * time.Second)

	// Best-effort initial PID write in case PIDUpdateCallback fired late.
	for _, w := range watchers {
		agentName := w.config.AgentName
		trackedNames = append(trackedNames, agentName)

		if pid := w.GetPID(); pid > 0 {
			if err := lifecycle.WriteAgent(agentName, pid, groupID); err != nil && !quiet {
				fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
			}
		}

		agentProc := ProcessInfo{
			PID:       w.GetPID(),
			Name:      agentName,
			Type:      "agent",
			Command:   "watcher:" + agentName,
			StartTime: time.Now(),
			Status:    "running",
		}
		if err := AddRunningProcess(agentProc); err != nil && !quiet {
			fmt.Printf("Warning: failed to record watcher process: %v\n", err)
		}
	}

	// Register registry/UI deps now that all agents are written.
	registerInvocationDeps(groupID, trackedNames, uiEnabled, quiet)

	// Wait for signal
	<-sigChan
	if !quiet {
		fmt.Println("\nShutting down all services...")
	}

	// Stop watchers (their managed agent process is signaled by the watcher).
	for _, w := range watchers {
		w.Stop()
	}
	for _, w := range watchers {
		w.Wait()
	}

	// Stop non-watch agents.
	shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
	if shutdownTimeout == 0 {
		shutdownTimeout = config.ShutdownTimeout
	}
	shutdownDuration := time.Duration(shutdownTimeout) * time.Second

	localAgentPIDsMu.Lock()
	pidsToKill := make([]int, 0, len(localAgentPIDs))
	for pid := range localAgentPIDs {
		pidsToKill = append(pidsToKill, pid)
	}
	localAgentPIDsMu.Unlock()

	if len(pidsToKill) > 0 {
		var wg sync.WaitGroup
		for _, pid := range pidsToKill {
			wg.Add(1)
			go func(agentPID int) {
				defer wg.Done()
				if !quiet {
					fmt.Printf("Stopping agent (PID: %d)\n", agentPID)
				}
				if err := KillProcess(agentPID, shutdownDuration); err != nil && !quiet {
					fmt.Printf("Failed to stop agent (PID %d): %v\n", agentPID, err)
				}
				RemoveRunningProcess(agentPID)
			}(pid)
		}
		wg.Wait()

		// Grace period for agents to complete unregister HTTP calls before the
		// registry goes away (matches the existing behavior).
		time.Sleep(500 * time.Millisecond)
	}

	// Stop registry ONLY if this meshctl instance started it.
	if locallyStartedRegistryPID > 0 && IsProcessAlive(locallyStartedRegistryPID) {
		if !quiet {
			fmt.Printf("Stopping registry (PID: %d)\n", locallyStartedRegistryPID)
		}
		if err := KillProcess(locallyStartedRegistryPID, shutdownDuration); err != nil && !quiet {
			fmt.Printf("Failed to stop registry: %v\n", err)
		}
		RemoveRunningProcess(locallyStartedRegistryPID)
		_ = lifecycle.RemoveService(lifecycle.ServiceRegistry)
	}

	// Clean up agent PID/.group files and unregister deps. Idempotent.
	for _, name := range trackedNames {
		_ = lifecycle.RemoveAgent(name)
	}
	if len(trackedNames) > 0 {
		_ = lifecycle.UnregisterDep(lifecycle.ServiceRegistry, groupID, trackedNames)
		if uiEnabled {
			_ = lifecycle.UnregisterDep(lifecycle.ServiceUI, groupID, trackedNames)
		}
	} else if uiEnabled {
		_ = lifecycle.UnregisterDep(lifecycle.ServiceUI, groupID, []string{uiOnlyDepSentinel})
	}

	return nil
}

func forkToBackground(cobraCmd *cobra.Command, args []string, config *CLIConfig) error {
	// Mint a fresh group-id for this detach invocation. Threaded to the forked
	// child via MCP_MESH_GROUP_ID so the child writes per-agent .group files
	// pointing back at this same group. The child's WriteService(registry/ui)
	// and WriteAgent calls are now the ONLY writers of those PID files —
	// forkToBackground used to clobber them with the wrapper's own PID, which
	// is exactly the bug this PR fixes.
	group := lifecycle.NewGroupID()

	// Create a new command to run in detach
	cmdArgs := []string{os.Args[0], "start"}
	cmdArgs = append(cmdArgs, args...)

	// Add all the flags to the detach command
	cobraCmd.Flags().Visit(func(flag *pflag.Flag) {
		// Don't pass detach flag to avoid infinite loop
		// Don't pass deprecated pid-file flag
		if flag.Name != "detach" && flag.Name != "pid-file" {
			// Handle boolean flags differently - don't pass "true" as a value
			// as it gets interpreted as a positional argument
			if flag.Value.Type() == "bool" {
				if flag.Value.String() == "true" {
					cmdArgs = append(cmdArgs, "--"+flag.Name)
				}
				// If false, don't pass the flag at all
			} else if flag.Value.Type() == "stringArray" {
				// StringArray flags need each value as a separate --flag argument
				vals, _ := cobraCmd.Flags().GetStringArray(flag.Name)
				for _, v := range vals {
					cmdArgs = append(cmdArgs, "--"+flag.Name, v)
				}
			} else if flag.Value.Type() == "stringSlice" {
				// StringSlice has the same bracket-serialization issue as StringArray
				vals, _ := cobraCmd.Flags().GetStringSlice(flag.Name)
				for _, v := range vals {
					cmdArgs = append(cmdArgs, "--"+flag.Name, v)
				}
			} else {
				cmdArgs = append(cmdArgs, "--"+flag.Name, flag.Value.String())
			}
		}
	})

	cmd := exec.Command(cmdArgs[0], cmdArgs[1:]...)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Env = os.Environ()
	// Pass the group-id to the forked child so its agents write the right
	// .group files and register deps under this group.
	cmd.Env = append(cmd.Env, fmt.Sprintf("%s=%s", envGroupID, group.String()))

	// Inject TLS-related --env values into the forked process environment.
	// The forked meshctl needs these for its own registry health checks
	// (e.g., MCP_MESH_TLS_CA for SPIRE/Vault setups where the registry runs HTTPS).
	if envVals, err := cobraCmd.Flags().GetStringArray("env"); err == nil {
		for _, envVar := range envVals {
			if strings.HasPrefix(envVar, "MCP_MESH_TLS_") {
				cmd.Env = append(cmd.Env, envVar)
			}
		}
	}

	// Determine log name (agent name or "registry")
	registryOnly, _ := cobraCmd.Flags().GetBool("registry-only")
	var logName string
	if registryOnly || len(args) == 0 {
		logName = "registry"
	} else if len(args) == 1 && isAgentFile(args[0]) {
		logName = getAgentNameFallback(args[0])
	} else {
		// Multiple agents - use first agent name for primary log
		logName = "meshctl"
	}

	// Set up log file for detached process
	lm, err := NewLogManager()
	if err != nil {
		return fmt.Errorf("failed to initialize log manager: %w", err)
	}

	// Rotate existing logs
	quiet, _ := cobraCmd.Flags().GetBool("quiet")
	if err := lm.RotateLogs(logName); err != nil && !quiet {
		fmt.Printf("Warning: failed to rotate logs for %s: %v\n", logName, err)
	}

	// Create log file and redirect output
	logFile, err := lm.CreateLogFile(logName)
	if err != nil {
		return fmt.Errorf("failed to create log file for %s: %w", logName, err)
	}
	cmd.Stdout = logFile
	cmd.Stderr = logFile

	// Start the process
	if err := cmd.Start(); err != nil {
		logFile.Close()
		return fmt.Errorf("failed to start detach process: %w", err)
	}

	// Write a transient wrapper-<group>.pid marker. This is the ONLY PID file
	// the wrapper writes — agent .pid files and registry/ui .pid files come
	// from the forked child writing the REAL PIDs.
	//
	// Why no longer write registry.pid / ui.pid / <agent>.pid here:
	// the wrapper meshctl exits within milliseconds (after fork+log setup) but
	// the registry/UI/agent children outlive it. Writing the wrapper PID into
	// those files used to look like the source of truth to `meshctl stop`,
	// causing it to send SIGTERM to a long-dead PID — which the OS may have
	// recycled — while the actual services kept running. That orphaned them.
	// The forked child re-overwrites those files when it starts the real
	// processes, but only when it actually starts them; reuse paths (registry
	// already running, UI already running) used to leave the bogus wrapper
	// PIDs in place. The fix is: never write wrapper PID into those files.
	//
	// The wrapper marker is just for GC to clean up if the child dies before
	// writing any real PID files (unusual but possible if startup fails).
	if err := lifecycle.WriteWrapperPID(group, cmd.Process.Pid); err != nil && !quiet {
		fmt.Printf("Warning: failed to write wrapper marker: %v\n", err)
	}

	// Extract agent names from args (used for both display and the sync barrier).
	var agentNames []string
	for _, arg := range args {
		if isAgentFile(arg) {
			absPath, _ := filepath.Abs(arg)
			name := extractAgentName(absPath)
			agentNames = append(agentNames, name)
		}
	}

	if !quiet {
		if len(agentNames) == 1 {
			fmt.Printf("Started '%s' in detach\n", agentNames[0])
			fmt.Printf("Logs: ~/.mcp-mesh/logs/%s.log\n", agentNames[0])
			fmt.Printf("Use 'meshctl logs %s' to view or 'meshctl stop %s' to stop\n", agentNames[0], agentNames[0])
		} else if len(agentNames) > 1 {
			fmt.Printf("Starting %d agents in detach: %s\n", len(agentNames), strings.Join(agentNames, ", "))
			fmt.Printf("Logs: ~/.mcp-mesh/logs/<agent>.log\n")
			fmt.Printf("Use 'meshctl logs <agent>' to view or 'meshctl stop' to stop all\n")
		} else {
			fmt.Printf("Started in detach\n")
			fmt.Printf("Use 'meshctl logs <agent>' to view logs or 'meshctl stop' to stop\n")
		}
	}

	// Sync barrier: wait for the forked child to write the PID file(s) we expect
	// before returning. Without this, an immediate follow-up `meshctl stop` or
	// `meshctl start` (e.g. in lifecycle tests) races against the child's
	// startup work (validators, Maven warmup, language runtime init) and either
	// sees "no agents running" or trips an "already running" check on a
	// late-arriving PID file. See GitHub issue #844.
	uiEnabled, _ := cobraCmd.Flags().GetBool("ui")
	connectOnly, _ := cobraCmd.Flags().GetBool("connect-only")
	expectedFiles := determineExpectedPIDFiles(agentNames, registryOnly, connectOnly, uiEnabled)
	if len(expectedFiles) == 0 {
		// Nothing meaningful to wait for (e.g. malformed args). Return without
		// barrier rather than block forever — the wrapper marker is still in
		// place so GC can clean up if the child died.
		return nil
	}
	if err := waitForChildPIDFiles(cmd, expectedFiles, forkSyncBarrierTimeout); err != nil {
		// Hard error: the contract of `meshctl start -d` is "after this returns,
		// the agent is registered." Soft-warning here would let the original
		// race resurface for any caller (tests, scripts, humans) that relied on
		// the contract. Drop the wrapper marker so a retry isn't blocked by a
		// stale wrapper-<group>.pid pointing at the failed fork.
		_ = lifecycle.RemoveWrapperPID(group)
		return fmt.Errorf("forked meshctl did not register within %v: %w", forkSyncBarrierTimeout, err)
	}

	return nil
}

// forkSyncBarrierTimeout bounds how long forkToBackground waits for the forked
// child to write its PID file(s). Generous default — Java/Maven cold-cache +
// Spring Boot startup observed up to 120s; multi-agent starts gate on slowest,
// with CPU/memory contention adding overhead. If insufficient, error message
// is self-explanatory.
const forkSyncBarrierTimeout = 180 * time.Second

// determineExpectedPIDFiles returns the absolute PID file paths that the
// forked child meshctl is expected to write. Used by the post-fork sync
// barrier to know when the child has finished registering.
//
// Rationale for which files we wait for:
//   - registry-only / no-args: child runs registry-only mode → registry.pid.
//   - --connect-only: registry is external; child only writes per-agent .pid.
//   - agents present: per-agent .pid files (registry.pid is conditional on
//     whether the registry was already running, so we can't reliably wait
//     for it — the agent .pid implies the child got past registry setup).
//   - --ui only (no agents, not registry-only): standalone UI session →
//     ui.pid.
func determineExpectedPIDFiles(agentNames []string, registryOnly, connectOnly, uiEnabled bool) []string {
	if registryOnly {
		return []string{lifecycle.PIDFile(lifecycle.ServiceRegistry)}
	}
	if len(agentNames) > 0 {
		out := make([]string, 0, len(agentNames))
		for _, n := range agentNames {
			out = append(out, lifecycle.PIDFile(n))
		}
		return out
	}
	if uiEnabled {
		return []string{lifecycle.PIDFile(lifecycle.ServiceUI)}
	}
	if !connectOnly {
		// No agents and not UI-only: child will fall into the "no agents
		// specified, starting registry only" branch in start.go.
		return []string{lifecycle.PIDFile(lifecycle.ServiceRegistry)}
	}
	return nil
}

// waitForChildPIDFiles polls until all expectedFiles exist or the child exits
// or the timeout fires. 50ms poll interval is below human perception and
// negligible relative to the multi-second startup costs we're guarding
// against. A pipe-based handshake would be tighter but requires plumbing a
// signal mechanism into the child meshctl — the polling design keeps the
// child unchanged.
//
// Child-exit detection uses a background Wait() goroutine rather than
// Signal(0): a freshly-exited unwaited child is a zombie, and Signal(0)
// returns nil for zombies on Linux/Darwin, which would let us spin until the
// timeout instead of failing fast.
func waitForChildPIDFiles(cmd *exec.Cmd, expectedFiles []string, timeout time.Duration) error {
	exited := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(exited)
	}()

	deadline := time.After(timeout)
	const pollInterval = 50 * time.Millisecond
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	check := func() bool {
		for _, f := range expectedFiles {
			if _, err := os.Stat(f); err != nil {
				return false
			}
		}
		return true
	}

	if check() {
		return nil
	}
	for {
		select {
		case <-exited:
			if check() {
				return nil
			}
			return fmt.Errorf("forked child (pid %d) exited before writing PID file(s) %v", cmd.Process.Pid, expectedFiles)
		case <-deadline:
			return fmt.Errorf("timed out after %v waiting for PID file(s) %v", timeout, expectedFiles)
		case <-ticker.C:
			if check() {
				return nil
			}
		}
	}
}

// isTerminal checks if the given file is a terminal (TTY)
func isTerminal(f *os.File) bool {
	if f == nil {
		return false
	}
	stat, err := f.Stat()
	if err != nil {
		return false
	}
	// Check if the file mode indicates it's a character device (terminal)
	return (stat.Mode() & os.ModeCharDevice) != 0
}

// extractAgentName extracts the agent name from agent configuration.
// For Python: extracts from @mesh.agent(name="...") decorator
// For TypeScript: extracts from mesh(server, { name: "..." }) call
// For Java: extracts from @MeshAgent(name="...") annotation or pom.xml artifactId
// Falls back to the script filename if extraction fails.
// Results are cached to avoid repeated file parsing.
func extractAgentName(scriptPath string) string {
	// Check cache first (thread-safe)
	if cached, ok := agentNameCache.Load(scriptPath); ok {
		return cached.(string)
	}

	handler := handlers.DetectLanguage(scriptPath)
	lang := handler.Language()

	var agentName string
	switch lang {
	case langTypeScript:
		agentName = extractTypeScriptAgentName(scriptPath)
	case langPython:
		agentName = extractPythonAgentName(scriptPath)
	case langJava:
		agentName = extractJavaAgentName(scriptPath)
	}

	if agentName != "" {
		agentNameCache.Store(scriptPath, agentName)
		return agentName
	}

	// Fallback: use filename without extension
	fallback := getAgentNameFallback(scriptPath)
	agentNameCache.Store(scriptPath, fallback)
	return fallback
}

// getAgentNameFallback returns a fallback name based on the file path
func getAgentNameFallback(scriptPath string) string {
	fallback := filepath.Base(scriptPath)
	// Remove common extensions
	fallback = strings.TrimSuffix(fallback, ".py")
	fallback = strings.TrimSuffix(fallback, ".ts")
	fallback = strings.TrimSuffix(fallback, ".js")
	fallback = strings.TrimSuffix(fallback, ".java")
	fallback = strings.TrimSuffix(fallback, ".jar")

	// If filename is "main" or "index", use parent directory name instead (#382)
	if fallback == "main" || fallback == "index" {
		dir := filepath.Dir(scriptPath)
		parentName := filepath.Base(dir)
		// Handle edge case: if dir is "." use actual current directory name
		if parentName == "." {
			if cwd, err := os.Getwd(); err == nil {
				parentName = filepath.Base(cwd)
			}
		}
		// For TypeScript, check if we're in a src directory
		if parentName == "src" {
			grandparentDir := filepath.Dir(dir)
			grandparentName := filepath.Base(grandparentDir)
			if grandparentName != "" && grandparentName != "." {
				parentName = grandparentName
			}
		}
		// Only use parentName if it's meaningful
		if parentName != "" && parentName != "." {
			fallback = parentName
		}
	}

	return fallback
}

// extractTypeScriptAgentName extracts the agent name from mesh(server, { name: "..." })
func extractTypeScriptAgentName(scriptPath string) string {
	content, err := os.ReadFile(scriptPath)
	if err != nil {
		return ""
	}

	// Match mesh(server, { name: "..." }) or mesh(server, { name: '...' })
	// This regex handles multi-line mesh() calls
	meshPattern := regexp.MustCompile(`mesh\s*\(\s*\w+\s*,\s*\{[\s\S]*?name\s*:\s*["']([^"']+)["'][\s\S]*?\}\s*\)`)
	matches := meshPattern.FindSubmatch(content)
	if len(matches) >= 2 {
		return string(matches[1])
	}

	return ""
}

// extractPythonAgentName extracts the agent name from @mesh.agent(name="...") decorator
func extractPythonAgentName(scriptPath string) string {
	// Python script to extract agent name using AST
	// Handles all valid Python decorator syntaxes:
	//   @mesh.agent(name="hello")
	//   @mesh.agent(name='hello')
	//   @mesh.agent(\n    name="hello"\n)
	//   @mesh.agent(auto_run=True, name="hello")
	// Specifically matches mesh.agent (not other .agent decorators)
	pythonScript := `
import ast,sys
try:
    with open(sys.argv[1]) as f:
        for n in ast.walk(ast.parse(f.read())):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
                # Check for mesh.agent specifically
                if n.func.attr=='agent' and isinstance(n.func.value,ast.Name) and n.func.value.id=='mesh':
                    for k in n.keywords:
                        if k.arg=='name' and isinstance(k.value,ast.Constant):
                            print(k.value.value)
                            sys.exit(0)
except:
    pass
`
	// Find a Python executable - try .venv first, then system Python
	pythonExec := findPythonForAST()
	if pythonExec == "" {
		return ""
	}

	// Run Python script to extract agent name
	cmd := exec.Command(pythonExec, "-c", pythonScript, scriptPath)
	output, err := cmd.Output()
	if err != nil {
		return ""
	}

	return strings.TrimSpace(string(output))
}

// findPythonForAST finds a Python executable for AST parsing.
// Tries .venv first, then falls back to system Python.
func findPythonForAST() string {
	// Try .venv in current directory first (cross-platform)
	venvPython := filepath.Join(".venv", "bin", "python")
	if runtime.GOOS == "windows" {
		venvPython = filepath.Join(".venv", "Scripts", "python.exe")
	}
	if _, err := os.Stat(venvPython); err == nil {
		return venvPython
	}

	// Fall back to system Python
	candidates := []string{"python3", "python"}
	for _, candidate := range candidates {
		if path, err := exec.LookPath(candidate); err == nil {
			return path
		}
	}

	return ""
}

// extractJavaAgentName extracts the agent name from @MeshAgent annotation or pom.xml
func extractJavaAgentName(projectPath string) string {
	// If it's a JAR file, use the JAR filename
	if strings.HasSuffix(strings.ToLower(projectPath), ".jar") {
		name := filepath.Base(projectPath)
		name = strings.TrimSuffix(name, ".jar")
		// Remove version suffix if present (e.g., "agent-1.0.0" -> "agent")
		if idx := strings.LastIndex(name, "-"); idx != -1 {
			// Check if what follows is a version number
			suffix := name[idx+1:]
			if len(suffix) > 0 && (suffix[0] >= '0' && suffix[0] <= '9') {
				name = name[:idx]
			}
		}
		return name
	}

	// Find the project root (directory with pom.xml)
	projectDir := projectPath
	if info, err := os.Stat(projectPath); err == nil && !info.IsDir() {
		projectDir = filepath.Dir(projectPath)
	}

	// Try to extract from @MeshAgent(name = "...") annotation in .java files
	meshAgentRe := regexp.MustCompile(`@MeshAgent\s*\([\s\S]*?name\s*=\s*"([^"]+)"`)
	srcDir := filepath.Join(projectDir, "src")
	if _, err := os.Stat(srcDir); err == nil {
		var foundName string
		filepath.WalkDir(srcDir, func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return filepath.SkipDir
			}
			if d.IsDir() || !strings.HasSuffix(path, ".java") {
				return nil
			}
			content, readErr := os.ReadFile(path)
			if readErr != nil {
				return nil
			}
			if matches := meshAgentRe.FindSubmatch(content); len(matches) > 1 {
				foundName = string(matches[1])
				return filepath.SkipAll
			}
			return nil
		})
		if foundName != "" {
			return foundName
		}
	}

	// Try to extract project artifactId from pom.xml (not parent's)
	pomPath := filepath.Join(projectDir, "pom.xml")
	if content, err := os.ReadFile(pomPath); err == nil {
		type pomParent struct {
			ArtifactId string `xml:"artifactId"`
		}
		type pomProject struct {
			ArtifactId string    `xml:"artifactId"`
			Parent     pomParent `xml:"parent"`
		}
		var pom pomProject
		if err := xml.Unmarshal(content, &pom); err == nil && pom.ArtifactId != "" {
			return pom.ArtifactId
		}
	}

	// Fallback to directory name
	return filepath.Base(projectDir)
}
