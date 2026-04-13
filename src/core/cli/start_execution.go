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
)

// agentNameCache caches extracted agent names to avoid repeated parsing
// Uses sync.Map for thread-safe concurrent access when starting multiple agents
var agentNameCache sync.Map

// Standard mode
func startStandardMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	quiet, _ := cmd.Flags().GetBool("quiet")

	// Note: Prerequisites are validated in runStartCommand before reaching here

	// Determine registry URL from flags or config
	registryURL := determineStartRegistryURL(cmd, config)

	// locallyStartedRegistryPID records the PID of a registry that was started by
	// THIS meshctl invocation. It's threaded through to runAgentsInForeground via
	// startAgentsWithEnv so shutdown can decide whether to kill the registry.
	// 0 means this meshctl did not start a registry (e.g., it was already running,
	// started by another meshctl) and shutdown will leave it alone.
	var locallyStartedRegistryPID int

	// Check if registry is running
	if !IsRegistryRunning(registryURL) {
		// Only attempt to start registry if connecting to localhost
		registryHost := getRegistryHostFromURL(registryURL, config.RegistryHost)
		if isLocalhostRegistry(registryHost) {
			if !quiet {
				fmt.Printf("Registry not found at %s, starting embedded registry...\n", registryURL)
			}

			// Enforce single-registry constraint
			pm2, pidErr := NewPIDManager()
			if pidErr == nil {
				existingPID, err := pm2.ReadPID("registry")
				if err == nil && existingPID > 0 && existingPID != os.Getpid() && IsProcessAlive(existingPID) {
					return fmt.Errorf("a registry is already running (PID %d) but not reachable at %s. Stop it with 'meshctl stop --registry' and try again", existingPID, registryURL)
				}
			}

			// Check if we can start a registry (port available)
			registryPort := getRegistryPortFromURL(registryURL, config.RegistryPort)
			if !IsPortAvailable(registryHost, registryPort) {
				return fmt.Errorf("cannot start registry: port %d is already in use on %s", registryPort, registryHost)
			}

			// Start registry in detach. startRegistryWithOptions returns the child
			// PID directly once registryCmd.Start() succeeds, so we don't need a
			// goroutine wrapper here — and deriving ownership from the explicit
			// return value is safer than re-reading the globally shared
			// registry.pid file (which is vulnerable to cross-instance races and
			// stale entries from unrelated meshctl processes).
			registryPID, err := startRegistryWithOptions(config, true, cmd)
			if err != nil {
				return fmt.Errorf("failed to start registry: %w", err)
			}

			// Wait for registry to be ready
			startupTimeout, _ := cmd.Flags().GetInt("startup-timeout")
			if startupTimeout == 0 {
				startupTimeout = config.StartupTimeout
			}
			if err := WaitForRegistry(registryURL, time.Duration(startupTimeout)*time.Second); err != nil {
				return fmt.Errorf("registry startup timeout: %w", err)
			}

			// This meshctl instance started the registry — capture ownership
			// directly from the explicit return value so shutdown can clean it up.
			// We deliberately avoid pm.ReadPID("registry") here: registry.pid is a
			// globally shared file and reading it would let a stale or racing
			// entry from another meshctl instance look like ownership, which is
			// exactly the cross-instance tracking bug this PR fixes for agents.
			locallyStartedRegistryPID = registryPID
		} else {
			// Remote registry - cannot start, must connect to existing
			return fmt.Errorf("cannot connect to remote registry at %s - please ensure the registry is running", registryURL)
		}
	}

	// Start UI server if --ui flag is set (before agents, which may block in foreground)
	maybeStartUIServer(cmd, config, registryURL)

	// Build environment for agents
	agentEnv := buildAgentEnvironment(cmd, registryURL, config)

	return startAgentsWithEnv(args, agentEnv, cmd, config, locallyStartedRegistryPID)
}

// Connect-only mode
func startConnectOnlyMode(cmd *cobra.Command, args []string, registryURL string, config *CLIConfig) error {
	if len(args) == 0 {
		return fmt.Errorf("agent file required in connect-only mode")
	}

	quiet, _ := cmd.Flags().GetBool("quiet")

	// Note: Prerequisites are validated in runStartCommand before reaching here

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
	return startAgentsWithEnv(args, agentEnv, cmd, config, 0)
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
func startAgentsWithEnv(agentPaths []string, env []string, cmd *cobra.Command, config *CLIConfig, locallyStartedRegistryPID int) error {
	var agentCmds []*exec.Cmd
	var watchers []*AgentWatcher
	workingDir, _ := cmd.Flags().GetString("working-dir")
	user, _ := cmd.Flags().GetString("user")
	group, _ := cmd.Flags().GetString("group")
	detach, _ := cmd.Flags().GetBool("detach")
	quiet, _ := cmd.Flags().GetBool("quiet")
	watch, _ := cmd.Flags().GetBool("watch")

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

	for _, agentPath := range agentPaths {
		// Convert to absolute path
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return fmt.Errorf("invalid agent path %s: %w", agentPath, err)
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
			watcher, err := createJavaWatcher(absPath, agentEnv, workingDir, user, group, quiet)
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
			watcher, err := createPythonWatcher(absPath, agentEnv, workingDir, user, group, quiet)
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
		agentCmd, err := createAgentCommand(absPath, agentEnv, workingDir, user, group, watch)
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

			// Write PID file for this agent
			pm, err := NewPIDManager()
			if err == nil {
				if err := pm.WritePID(agentName, agentCmd.Process.Pid); err != nil && !quiet {
					fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
				}
			}

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
		// In detach or background mode, agents are already started with their own log files
		// Just return (the parent forkToBackground will handle user messages)
		// But if we have watchers, fall through to runAgentsInForeground to keep process alive
		return nil
	}

	// If running in foreground, start agents and wait
	if len(agentCmds) > 0 || len(watchers) > 0 {
		return runAgentsInForeground(agentCmds, watchers, cmd, config, locallyStartedRegistryPID)
	}

	return nil
}

func runAgentsInForeground(agentCmds []*exec.Cmd, watchers []*AgentWatcher, cmd *cobra.Command, config *CLIConfig, locallyStartedRegistryPID int) error {
	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Println("Agents are running. Press Ctrl+C to stop all services.")
	}

	// Initialize PID manager for tracking
	pm, pmErr := NewPIDManager()

	// Capture parent meshctl PID once — used for watch-mode PID file namespacing.
	parentPID := os.Getpid()

	// Track agent names for cleanup, split by flow:
	//   nonWatchNames -> flat <name>.pid files written via pm.WritePID
	//   watchNames    -> watch-mode <name>.<parentPID>.pid + watcher-parent files
	var nonWatchNames []string
	var watchNames []string

	// localNonWatchAgentPIDs tracks the PIDs of non-watch agents started by THIS
	// runAgentsInForeground invocation. Used at shutdown to kill only our own
	// children — we deliberately do NOT use GetRunningProcesses() for cleanup,
	// because ~/.mcp-mesh/processes.json is a globally shared file across all
	// meshctl instances, and reading it would cause cross-instance cascade kills.
	//
	// A set (map[int]struct{}) is used rather than a slice so entries can be
	// REMOVED when a child exits naturally (via the c.Wait() goroutine below).
	// Without removal, a child that dies before shutdown would leave its PID in
	// the slice, and shutdown's KillProcess loop would target a PID the OS may
	// have since reused for an unrelated process — killing the wrong thing.
	//
	// The mutex guards all reads and writes because the Wait goroutine runs on a
	// different goroutine from the signal-driven shutdown path.
	var localNonWatchAgentPIDsMu sync.Mutex
	localNonWatchAgentPIDs := make(map[int]struct{})

	// Start all agents
	for i, agentCmd := range agentCmds {
		// Start the command
		if err := agentCmd.Start(); err != nil {
			return fmt.Errorf("failed to start agent: %w", err)
		}

		// Extract agent name from command args (look for .py file)
		agentName := fmt.Sprintf("agent-%d", i)
		for _, arg := range agentCmd.Args {
			if strings.HasSuffix(arg, ".py") {
				agentName = filepath.Base(arg)
				agentName = strings.TrimSuffix(agentName, ".py")
				break
			}
		}
		nonWatchNames = append(nonWatchNames, agentName)
		localNonWatchAgentPIDsMu.Lock()
		localNonWatchAgentPIDs[agentCmd.Process.Pid] = struct{}{}
		localNonWatchAgentPIDsMu.Unlock()

		// Write PID file for this agent (non-watch: flat layout)
		if pmErr == nil {
			if err := pm.WritePID(agentName, agentCmd.Process.Pid); err != nil && !quiet {
				fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
			}
		}

		// Record the process
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

		// Run in goroutine to wait for completion
		go func(c *exec.Cmd, name string) {
			if err := c.Wait(); err != nil && !quiet {
				fmt.Printf("Agent exited with error: %v\n", err)
			}
			// Drop this PID from the live shutdown set so the shutdown loop
			// doesn't target a PID the OS may have since reused.
			localNonWatchAgentPIDsMu.Lock()
			delete(localNonWatchAgentPIDs, c.Process.Pid)
			localNonWatchAgentPIDsMu.Unlock()
			RemoveRunningProcess(c.Process.Pid)
			// Clean up PID file when agent exits
			if pmErr == nil {
				pm.RemovePID(name)
			}
		}(agentCmd, agentName)
	}

	// Set PID update callbacks for watchers so PID files track the actual agent process.
	// The callback fires on initial start and on every file-change restart.
	// Watch-mode PID files are namespaced per parent meshctl PID to avoid collisions
	// between independent `meshctl start -d -w` invocations that track agents with the
	// same name (see #706 cascading-shutdown bug).
	for _, w := range watchers {
		name := w.config.AgentName // capture for closure
		w.config.PIDUpdateCallback = func(pid int) {
			if pmErr == nil {
				if err := pm.WriteWatchAgentPID(name, parentPID, pid); err != nil && !quiet {
					fmt.Printf("Warning: failed to update PID file for %s: %v\n", name, err)
				}
			}
		}
	}

	// Start all watchers (each blocks in its own goroutine)
	for _, w := range watchers {
		go func(watcher *AgentWatcher) {
			if err := watcher.Start(); err != nil && !quiet {
				fmt.Printf("Watcher error: %v\n", err)
			}
		}(w)
	}

	// Wait briefly for watchers to start their initial agent processes
	time.Sleep(1 * time.Second)

	// Fallback: write initial PID files in case PIDUpdateCallback fired before pm was ready.
	// The callback is the primary mechanism; this is best-effort for the initial startup window.
	for _, w := range watchers {
		agentName := w.config.AgentName
		watchNames = append(watchNames, agentName)

		pid := w.GetPID()
		if pmErr == nil && pid > 0 {
			if err := pm.WriteWatchAgentPID(agentName, parentPID, pid); err != nil && !quiet {
				fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
			}
		}

		// Record the process for tracking
		agentProc := ProcessInfo{
			PID:       pid,
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

	// Track the watcher parent process (this meshctl CLI process) so meshctl stop can kill it.
	// Without this, stopping a watched agent kills only the agent subprocess, leaving
	// the watcher parent alive to potentially respawn or hold resources (#706).
	// Files are namespaced per parent PID so independent `meshctl start -d -w` invocations
	// that track same-named agents don't collide.
	if len(watchers) > 0 && pmErr == nil {
		for _, w := range watchers {
			if err := pm.WriteWatchParentPID(w.config.AgentName, parentPID); err != nil && !quiet {
				fmt.Printf("Warning: failed to write watcher parent PID for %s: %v\n", w.config.AgentName, err)
			}
		}
	}

	// Wait for signal
	<-sigChan
	if !quiet {
		fmt.Println("\nShutting down all services...")
	}

	// Stop all watchers
	for _, w := range watchers {
		w.Stop()
	}
	for _, w := range watchers {
		w.Wait()
	}

	// Clean up watcher PID files and watcher-parent PID files
	if pmErr == nil {
		for _, w := range watchers {
			pm.RemoveWatchAgentPID(w.config.AgentName, parentPID)
			pm.RemoveWatchParentPID(w.config.AgentName, parentPID)
		}
	}

	// Stop non-watch agents started by this meshctl invocation.
	// We intentionally do NOT call GetRunningProcesses() here — that reads
	// ~/.mcp-mesh/processes.json which is globally shared across all meshctl
	// instances, and killing entries from it would cascade into unrelated
	// instances' agents and registries (the #706-related cascading-shutdown bug).
	shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
	if shutdownTimeout == 0 {
		shutdownTimeout = config.ShutdownTimeout
	}
	shutdownDuration := time.Duration(shutdownTimeout) * time.Second

	// Snapshot the live PID set under the mutex. Iterating the map directly
	// while the Wait goroutine may still be deleting entries would race.
	localNonWatchAgentPIDsMu.Lock()
	pidsToKill := make([]int, 0, len(localNonWatchAgentPIDs))
	for pid := range localNonWatchAgentPIDs {
		pidsToKill = append(pidsToKill, pid)
	}
	localNonWatchAgentPIDsMu.Unlock()

	if len(pidsToKill) > 0 {
		var wg sync.WaitGroup
		for _, pid := range pidsToKill {
			wg.Add(1)
			go func(agentPID int) {
				defer wg.Done()
				if !quiet {
					fmt.Printf("Stopping non-watch agent (PID: %d)\n", agentPID)
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

	// Stop the registry ONLY if this meshctl instance started it.
	// If locallyStartedRegistryPID is 0, the registry was either already running
	// when we started or was started by a different meshctl instance — leaving
	// it alone is correct because stopping it would break other instances.
	if locallyStartedRegistryPID > 0 && IsProcessAlive(locallyStartedRegistryPID) {
		if !quiet {
			fmt.Printf("Stopping registry (PID: %d)\n", locallyStartedRegistryPID)
		}
		if err := KillProcess(locallyStartedRegistryPID, shutdownDuration); err != nil && !quiet {
			fmt.Printf("Failed to stop registry: %v\n", err)
		}
		RemoveRunningProcess(locallyStartedRegistryPID)
	}

	// Clean up all PID files for tracked agents.
	// Non-watch agents use flat layout; watch agents use per-parent-PID namespacing.
	if pmErr == nil {
		for _, name := range nonWatchNames {
			pm.RemovePID(name)
		}
		for _, name := range watchNames {
			pm.RemoveWatchAgentPID(name, parentPID)
			pm.RemoveWatchParentPID(name, parentPID)
		}
	}

	return nil
}

func forkToBackground(cobraCmd *cobra.Command, args []string, config *CLIConfig) error {
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

	// Write PID files so meshctl stop can find this detached process.
	// The forked child will eventually write its own agent PID files, but
	// we write the child meshctl PID now so stop has something to kill
	// even if it runs before the child finishes starting agents.
	pm, pidErr := NewPIDManager()
	if pidErr == nil {
		for _, arg := range args {
			if isAgentFile(arg) {
				absPath, _ := filepath.Abs(arg)
				name := extractAgentName(absPath)
				pm.WritePID(name, cmd.Process.Pid)
			}
		}
		// Write registry PID only when the child will start a registry.
		// UI-only forks (--ui without agents or --registry-only) connect to
		// an existing registry instead of starting one.
		startUI, _ := cobraCmd.Flags().GetBool("ui")
		uiOnly := startUI && len(args) == 0 && !registryOnly
		if !uiOnly {
			pm.WritePID("registry", cmd.Process.Pid)
		}
		// Write UI PID as a safety net — the child will start a UI server
		// and write its own PID, but this ensures stop can find the wrapper.
		if startUI {
			pm.WritePID("ui", cmd.Process.Pid)
		}
	}

	if !quiet {
		// Extract agent names from args for display (use decorator name if available)
		var agentNames []string
		for _, arg := range args {
			if isAgentFile(arg) {
				absPath, _ := filepath.Abs(arg)
				name := extractAgentName(absPath)
				agentNames = append(agentNames, name)
			}
		}

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

	return nil
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
