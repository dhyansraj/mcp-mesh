package cli

import (
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// NewStartCommand creates the start command
func NewStartCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "start [agents...]",
		Short: "Start MCP agent with mesh runtime",
		Long: `Start one or more MCP agents with mesh runtime support.

If no registry is running, a local registry will be started automatically.
The registry service can also be started independently using --registry-only.

Examples:
  mcp-mesh-dev start                              # Start registry only
  mcp-mesh-dev start examples/hello_world.py     # Start agent (and registry if needed)
  mcp-mesh-dev start --registry-only              # Start only the registry service
  mcp-mesh-dev start agent1.py agent2.py         # Start multiple agents`,
		Args: cobra.ArbitraryArgs,
		RunE: runStartCommand,
	}

	// Core functionality flags
	cmd.Flags().Bool("registry-only", false, "Start registry service only")
	cmd.Flags().String("registry-url", "", "External registry URL to connect to")
	cmd.Flags().Bool("connect-only", false, "Connect to external registry without embedding")

	// Registry configuration flags
	cmd.Flags().String("registry-host", "", "Registry host address (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port number (default: 8080)")
	cmd.Flags().String("db-path", "", "Database file path (default: ./dev_registry.db)")

	// Logging and debug flags
	cmd.Flags().Bool("debug", false, "Enable debug mode")
	cmd.Flags().String("log-level", "", "Set log level (DEBUG, INFO, WARN, ERROR) (default: INFO)")
	cmd.Flags().Bool("verbose", false, "Enable verbose output")
	cmd.Flags().Bool("quiet", false, "Suppress non-error output")

	// Development workflow flags
	cmd.Flags().Bool("auto-restart", true, "Auto-restart agent on file changes")
	cmd.Flags().Bool("watch-files", true, "Watch Python files for changes")
	cmd.Flags().String("watch-pattern", "*.py", "File pattern to watch")

	// Health monitoring flags
	cmd.Flags().Int("health-check-interval", 0, "Health check interval in seconds (default: 30)")
	cmd.Flags().Int("startup-timeout", 0, "Agent startup timeout in seconds (default: 30)")
	cmd.Flags().Int("shutdown-timeout", 0, "Graceful shutdown timeout in seconds (default: 30)")

	// Background service flags
	cmd.Flags().Bool("background", false, "Run as background service")
	cmd.Flags().String("pid-file", "./mcp_mesh_dev.pid", "PID file for background service")

	// Advanced configuration flags
	cmd.Flags().String("config-file", "", "Custom configuration file path")
	cmd.Flags().Bool("reset-config", false, "Reset configuration to defaults")
	cmd.Flags().StringSlice("env", []string{}, "Additional environment variables (KEY=VALUE)")
	cmd.Flags().String("env-file", "", "Environment file to load (.env format)")

	// Agent-specific flags
	cmd.Flags().String("agent-name", "", "Override agent name")
	cmd.Flags().StringSlice("capabilities", []string{}, "Override agent capabilities")
	cmd.Flags().String("agent-version", "", "Override agent version")
	cmd.Flags().String("working-dir", "", "Working directory for agent processes")

	// User and security flags
	cmd.Flags().String("user", "", "Run agent as specific user (Unix only)")
	cmd.Flags().String("group", "", "Run agent as specific group (Unix only)")
	cmd.Flags().Bool("secure", false, "Enable secure connections")
	cmd.Flags().String("cert-file", "", "TLS certificate file")
	cmd.Flags().String("key-file", "", "TLS private key file")

	return cmd
}

func runStartCommand(cmd *cobra.Command, args []string) error {
	// Handle reset-config flag first
	resetConfig, _ := cmd.Flags().GetBool("reset-config")
	if resetConfig {
		if err := ResetConfig(); err != nil {
			return fmt.Errorf("failed to reset configuration: %w", err)
		}
		fmt.Println("Configuration reset to defaults")
	}

	// Load configuration from file if specified
	configFile, _ := cmd.Flags().GetString("config-file")
	var config *CLIConfig
	var err error

	if configFile != "" {
		config, err = LoadConfigFromFile(configFile)
		if err != nil {
			return fmt.Errorf("failed to load config from %s: %w", configFile, err)
		}
	} else {
		config, err = LoadConfig()
		if err != nil {
			return fmt.Errorf("failed to load configuration: %w", err)
		}
	}


	// Load environment file if specified
	envFile, _ := cmd.Flags().GetString("env-file")
	if envFile != "" {
		if err := loadEnvironmentFile(envFile); err != nil {
			return fmt.Errorf("failed to load environment file %s: %w", envFile, err)
		}
	}

	// Apply additional environment variables
	envVars, _ := cmd.Flags().GetStringSlice("env")
	for _, envVar := range envVars {
		if err := setEnvironmentVariable(envVar); err != nil {
			return fmt.Errorf("invalid environment variable %s: %w", envVar, err)
		}
	}

	// Override config with command line flags
	if err := applyAllStartFlags(cmd, config); err != nil {
		return err
	}

	// Parse core mode flags
	registryOnly, _ := cmd.Flags().GetBool("registry-only")
	registryURL, _ := cmd.Flags().GetString("registry-url")
	connectOnly, _ := cmd.Flags().GetBool("connect-only")
	background, _ := cmd.Flags().GetBool("background")

	// Validate flag combinations
	if err := validateFlagCombinations(cmd); err != nil {
		return err
	}

	// Handle registry-only mode
	if registryOnly {
		return startRegistryOnlyMode(cmd, config)
	}

	// Handle connect-only mode
	if connectOnly {
		if registryURL == "" {
			return fmt.Errorf("--registry-url required with --connect-only")
		}
		return startConnectOnlyMode(cmd, args, registryURL, config)
	}

	// Handle background mode
	if background {
		return startBackgroundMode(cmd, args, config)
	}

	// If no agents provided, start registry only
	if len(args) == 0 {
		fmt.Println("No agents specified, starting registry only")
		return startRegistryOnlyMode(cmd, config)
	}

	// Standard agent startup mode
	return startStandardMode(cmd, args, config)
}

// Environment file loading
func loadEnvironmentFile(envFile string) error {
	file, err := os.Open(envFile)
	if err != nil {
		return fmt.Errorf("cannot open environment file: %w", err)
	}
	defer file.Close()

	// Read and parse .env format
	var lines []string
	fmt.Fscanf(file, "%s", &lines)

	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if err := setEnvironmentVariable(line); err != nil {
			return fmt.Errorf("invalid environment variable in %s: %s", envFile, line)
		}
	}

	return nil
}

// Set environment variable from KEY=VALUE format
func setEnvironmentVariable(envVar string) error {
	parts := strings.SplitN(envVar, "=", 2)
	if len(parts) != 2 {
		return fmt.Errorf("environment variable must be in KEY=VALUE format")
	}

	key := strings.TrimSpace(parts[0])
	value := strings.TrimSpace(parts[1])

	if key == "" {
		return fmt.Errorf("environment variable key cannot be empty")
	}

	return os.Setenv(key, value)
}

// Validate flag combinations
func validateFlagCombinations(cmd *cobra.Command) error {
	registryOnly, _ := cmd.Flags().GetBool("registry-only")
	connectOnly, _ := cmd.Flags().GetBool("connect-only")
	registryURL, _ := cmd.Flags().GetString("registry-url")

	if registryOnly && connectOnly {
		return fmt.Errorf("--registry-only and --connect-only flags are mutually exclusive")
	}

	if connectOnly && registryURL == "" {
		return fmt.Errorf("--registry-url is required when using --connect-only")
	}

	if registryOnly && registryURL != "" {
		return fmt.Errorf("--registry-url cannot be used with --registry-only")
	}

	return nil
}

// Apply all start flags to configuration
func applyAllStartFlags(cmd *cobra.Command, config *CLIConfig) error {
	// Registry configuration
	if cmd.Flags().Changed("registry-port") {
		port, _ := cmd.Flags().GetInt("registry-port")
		if port > 0 {
			config.RegistryPort = port
		}
	}

	if cmd.Flags().Changed("registry-host") {
		host, _ := cmd.Flags().GetString("registry-host")
		if host != "" {
			config.RegistryHost = host
		}
	}

	if cmd.Flags().Changed("db-path") {
		dbPath, _ := cmd.Flags().GetString("db-path")
		if dbPath != "" {
			absPath, err := AbsolutePath(dbPath)
			if err != nil {
				return fmt.Errorf("invalid db-path: %w", err)
			}
			config.DBPath = absPath
		}
	}

	// Logging configuration
	if cmd.Flags().Changed("log-level") {
		logLevel, _ := cmd.Flags().GetString("log-level")
		if logLevel != "" {
			if !ValidateLogLevel(logLevel) {
				return fmt.Errorf("invalid log level: %s (must be DEBUG, INFO, WARNING, ERROR, or CRITICAL)", logLevel)
			}
			config.LogLevel = logLevel
		}
	}

	if cmd.Flags().Changed("debug") {
		debug, _ := cmd.Flags().GetBool("debug")
		config.DebugMode = debug
		if debug {
			config.LogLevel = "DEBUG"
		}
	}

	// Health and timeout configuration
	if cmd.Flags().Changed("health-check-interval") {
		interval, _ := cmd.Flags().GetInt("health-check-interval")
		if interval > 0 {
			config.HealthCheckInterval = interval
		}
	}

	if cmd.Flags().Changed("startup-timeout") {
		timeout, _ := cmd.Flags().GetInt("startup-timeout")
		if timeout > 0 {
			config.StartupTimeout = timeout
		}
	}

	if cmd.Flags().Changed("shutdown-timeout") {
		timeout, _ := cmd.Flags().GetInt("shutdown-timeout")
		if timeout > 0 {
			config.ShutdownTimeout = timeout
		}
	}

	// Background service configuration
	if cmd.Flags().Changed("background") {
		background, _ := cmd.Flags().GetBool("background")
		config.EnableBackground = background
	}

	return nil
}

// Registry-only mode
func startRegistryOnlyMode(cmd *cobra.Command, config *CLIConfig) error {
	pm := GetGlobalProcessManager()
	quiet, _ := cmd.Flags().GetBool("quiet")

	if !quiet {
		fmt.Printf("Starting MCP Mesh registry on %s:%d\n", config.RegistryHost, config.RegistryPort)
	}

	// Check if registry is already running
	if info, exists := pm.GetProcess("registry"); exists && info.Status == "running" {
		return fmt.Errorf("registry is already running (PID: %d)", info.PID)
	}

	// Check if port is available
	if !IsPortAvailable(config.RegistryHost, config.RegistryPort) {
		return fmt.Errorf("port %d is already in use on %s", config.RegistryPort, config.RegistryHost)
	}

	// Setup security if specified
	secure, _ := cmd.Flags().GetBool("secure")
	if secure {
		certFile, _ := cmd.Flags().GetString("cert-file")
		keyFile, _ := cmd.Flags().GetString("key-file")
		if certFile == "" || keyFile == "" {
			return fmt.Errorf("--cert-file and --key-file required when using --secure")
		}
		// TODO: Implement TLS configuration
	}

	// Start registry using process manager
	metadata := map[string]interface{}{
		"secure": secure,
	}

	processInfo, err := pm.StartRegistryProcess(config.RegistryPort, config.DBPath, metadata)
	if err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	background, _ := cmd.Flags().GetBool("background")
	if background {
		if !quiet {
			fmt.Printf("Registry started in background (PID: %d)\n", processInfo.PID)
			fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		}
		return nil
	}

	// Foreground mode - wait for signal
	if !quiet {
		fmt.Printf("Registry started (PID: %d)\n", processInfo.PID)
		fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		fmt.Println("Registry is running. Press Ctrl+C to stop.")
	}

	// Start health monitoring
	pm.StartHealthMonitoring()

	// Wait for shutdown signal
	signalHandler := GetGlobalSignalHandler()
	signalHandler.WaitForShutdown()

	return nil
}

// Connect-only mode
func startConnectOnlyMode(cmd *cobra.Command, args []string, registryURL string, config *CLIConfig) error {
	if len(args) == 0 {
		return fmt.Errorf("agent file required in connect-only mode")
	}

	// Validate registry connection
	if !IsRegistryRunning(registryURL) {
		return fmt.Errorf("cannot connect to registry at %s", registryURL)
	}

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Printf("Connecting to external registry at %s\n", registryURL)
	}

	// Build environment for agents
	agentEnv := buildAgentEnvironment(cmd, registryURL, config)

	// Start agents with external registry
	return startAgentsWithEnv(args, agentEnv, cmd, config)
}

// Background mode
func startBackgroundMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	pidFile, _ := cmd.Flags().GetString("pid-file")

	// Check if already running
	if isProcessRunning(pidFile) {
		return fmt.Errorf("background service already running (PID file: %s)", pidFile)
	}

	// Fork to background
	return forkToBackground(cmd, args, pidFile, config)
}

// Standard mode
func startStandardMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	registryURL := config.GetRegistryURL()
	autoRestart, _ := cmd.Flags().GetBool("auto-restart")
	watchFiles, _ := cmd.Flags().GetBool("watch-files")

	// Check if registry is running
	if !IsRegistryRunning(registryURL) {
		quiet, _ := cmd.Flags().GetBool("quiet")
		if !quiet {
			fmt.Printf("Registry not found at %s, starting embedded registry...\n", registryURL)
		}

		// Start registry in background
		go func() {
			if err := startRegistryWithOptions(config, true, cmd); err != nil {
				fmt.Printf("Registry startup failed: %v\n", err)
			}
		}()

		// Wait for registry to be ready
		startupTimeout, _ := cmd.Flags().GetInt("startup-timeout")
		if startupTimeout == 0 {
			startupTimeout = config.StartupTimeout
		}
		if err := WaitForRegistry(registryURL, time.Duration(startupTimeout)*time.Second); err != nil {
			return fmt.Errorf("registry startup timeout: %w", err)
		}
	}

	// Build environment for agents
	agentEnv := buildAgentEnvironment(cmd, registryURL, config)

	// Start agents with file watching if enabled
	if watchFiles && autoRestart {
		return startAgentsWithFileWatching(args, agentEnv, cmd, config)
	}

	return startAgentsWithEnv(args, agentEnv, cmd, config)
}

func startRegistryWithOptions(config *CLIConfig, background bool, cmd *cobra.Command) error {
	// Start the registry service
	registryCmd, err := startRegistryService(config)
	if err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	if background {
		// Start in background
		if err := registryCmd.Start(); err != nil {
			return fmt.Errorf("failed to start registry in background: %w", err)
		}

		// Record the process
		proc := ProcessInfo{
			PID:       registryCmd.Process.Pid,
			Name:      "mcp-mesh-registry",
			Type:      "registry",
			Command:   registryCmd.String(),
			StartTime: time.Now(),
			Status:    "running",
		}
		if err := AddRunningProcess(proc); err != nil {
			fmt.Printf("Warning: failed to record process: %v\n", err)
		}

		quiet, _ := cmd.Flags().GetBool("quiet")
		if !quiet {
			fmt.Printf("Registry started in background (PID: %d)\n", registryCmd.Process.Pid)
			fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		}
		return nil
	}

	// Start in foreground
	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Record the process
	proc := ProcessInfo{
		PID:       registryCmd.Process.Pid,
		Name:      "mcp-mesh-registry",
		Type:      "registry",
		Command:   registryCmd.String(),
		StartTime: time.Now(),
		Status:    "running",
	}
	if err := AddRunningProcess(proc); err != nil {
		fmt.Printf("Warning: failed to record process: %v\n", err)
	}

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Printf("Registry started (PID: %d)\n", registryCmd.Process.Pid)
		fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		fmt.Print("Waiting for registry to be ready...")
	}

	// Wait for registry to be ready
	if err := WaitForRegistry(config.GetRegistryURL(), time.Duration(config.StartupTimeout)*time.Second); err != nil {
		return fmt.Errorf("registry failed to start: %w", err)
	}

	if !quiet {
		fmt.Println(" ✓")
		fmt.Println("Registry is running. Press Ctrl+C to stop.")
	}

	// Setup signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Wait for signal
	<-sigChan
	if !quiet {
		fmt.Println("\nShutting down registry...")
	}

	// Remove from process list
	RemoveRunningProcess(registryCmd.Process.Pid)

	// Kill the process
	shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
	if shutdownTimeout == 0 {
		shutdownTimeout = config.ShutdownTimeout
	}
	return KillProcess(registryCmd.Process.Pid, time.Duration(shutdownTimeout)*time.Second)
}

func startAgents(agentPaths []string, config *CLIConfig, background bool) error {
	// Ensure registry is running
	if !IsRegistryRunning(config.GetRegistryURL()) {
		fmt.Printf("Registry not found, starting local registry on %s:%d\n", config.RegistryHost, config.RegistryPort)

		// Find available port if needed
		if !IsPortAvailable(config.RegistryHost, config.RegistryPort) {
			availablePort, err := FindAvailablePort(config.RegistryHost, config.RegistryPort)
			if err != nil {
				return fmt.Errorf("no available port found: %w", err)
			}
			fmt.Printf("Port %d in use, using port %d instead\n", config.RegistryPort, availablePort)
			config.RegistryPort = availablePort
		}

		// Start registry in background
		registryCmd, err := startRegistryService(config)
		if err != nil {
			return fmt.Errorf("failed to start registry: %w", err)
		}

		if err := registryCmd.Start(); err != nil {
			return fmt.Errorf("failed to start registry: %w", err)
		}

		// Record registry process
		registryProc := ProcessInfo{
			PID:       registryCmd.Process.Pid,
			Name:      "mcp-mesh-registry",
			Type:      "registry",
			Command:   registryCmd.String(),
			StartTime: time.Now(),
			Status:    "running",
		}
		if err := AddRunningProcess(registryProc); err != nil {
			fmt.Printf("Warning: failed to record registry process: %v\n", err)
		}

		// Wait for registry to be ready
		fmt.Print("Waiting for registry to be ready...")
		if err := WaitForRegistry(config.GetRegistryURL(), time.Duration(config.StartupTimeout)*time.Second); err != nil {
			return fmt.Errorf("registry failed to start: %w", err)
		}
		fmt.Println(" ✓")
	}

	// Start all agents
	var agentCmds []*exec.Cmd
	for _, agentPath := range agentPaths {
		// Convert to absolute path
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return fmt.Errorf("invalid agent path %s: %w", agentPath, err)
		}

		fmt.Printf("Starting agent: %s\n", absPath)

		cmd, err := StartPythonAgent(absPath, config)
		if err != nil {
			return fmt.Errorf("failed to prepare agent %s: %w", agentPath, err)
		}

		if background {
			if err := cmd.Start(); err != nil {
				return fmt.Errorf("failed to start agent %s: %w", agentPath, err)
			}
		} else {
			agentCmds = append(agentCmds, cmd)
		}

		// Record agent process
		agentProc := ProcessInfo{
			PID:       cmd.Process.Pid,
			Name:      filepath.Base(agentPath),
			Type:      "agent",
			Command:   cmd.String(),
			StartTime: time.Now(),
			Status:    "running",
			FilePath:  absPath,
		}
		if err := AddRunningProcess(agentProc); err != nil {
			fmt.Printf("Warning: failed to record agent process: %v\n", err)
		}

		fmt.Printf("Agent %s started (PID: %d)\n", filepath.Base(agentPath), cmd.Process.Pid)
	}

	if background {
		fmt.Printf("All agents started in background\n")
		fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		return nil
	}

	// If running in foreground, start agents and wait
	if len(agentCmds) > 0 {
		// Setup signal handling
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

		fmt.Println("Agents are running. Press Ctrl+C to stop all services.")

		// Start all agents
		for _, cmd := range agentCmds {
			go func(c *exec.Cmd) {
				if err := c.Run(); err != nil {
					fmt.Printf("Agent exited with error: %v\n", err)
				}
			}(cmd)
		}

		// Wait for signal
		<-sigChan
		fmt.Println("\nShutting down all services...")

		// Stop all processes
		processes, err := GetRunningProcesses()
		if err == nil {
			for _, proc := range processes {
				fmt.Printf("Stopping %s (PID: %d)\n", proc.Name, proc.PID)
				if err := KillProcess(proc.PID, time.Duration(config.ShutdownTimeout)*time.Second); err != nil {
					fmt.Printf("Failed to stop %s: %v\n", proc.Name, err)
				}
				RemoveRunningProcess(proc.PID)
			}
		}
	}

	return nil
}

func startRegistryService(config *CLIConfig) (*exec.Cmd, error) {
	// Prepare the registry command
	registryBinary := "./mcp-mesh-registry"

	// Check if binary exists, if not try to build it
	if _, err := os.Stat(registryBinary); os.IsNotExist(err) {
		// Try building the registry
		fmt.Println("Building registry service...")
		buildCmd := exec.Command("go", "build", "-o", registryBinary, "./cmd/mcp-mesh-registry")

		// Ensure Go is in PATH
		env := os.Environ()
		pathFound := false
		for i, envVar := range env {
			if strings.HasPrefix(envVar, "PATH=") {
				env[i] = "PATH=/usr/local/go/bin:" + envVar[5:]
				pathFound = true
				break
			}
		}
		if !pathFound {
			env = append(env, "PATH=/usr/local/go/bin")
		}
		buildCmd.Env = env

		if err := buildCmd.Run(); err != nil {
			return nil, fmt.Errorf("failed to build registry: %w", err)
		}
		fmt.Println("Registry built successfully")
	}

	// Create registry command
	cmd := exec.Command(registryBinary,
		"-host", config.RegistryHost,
		"-port", fmt.Sprintf("%d", config.RegistryPort),
	)

	// Set up environment
	cmd.Env = append(os.Environ(), config.GetRegistryEnvironmentVariables()...)

	// Set up stdio
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	return cmd, nil
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
	customEnv, _ := cmd.Flags().GetStringSlice("env")
	env = append(env, customEnv...)

	// Add agent-specific overrides
	if agentName, _ := cmd.Flags().GetString("agent-name"); agentName != "" {
		env = append(env, fmt.Sprintf("MCP_MESH_AGENT_NAME=%s", agentName))
	}

	if agentVersion, _ := cmd.Flags().GetString("agent-version"); agentVersion != "" {
		env = append(env, fmt.Sprintf("MCP_MESH_AGENT_VERSION=%s", agentVersion))
	}

	capabilities, _ := cmd.Flags().GetStringSlice("capabilities")
	if len(capabilities) > 0 {
		env = append(env, fmt.Sprintf("MCP_MESH_AGENT_CAPABILITIES=%s", strings.Join(capabilities, ",")))
	}

	return env
}

// Start agents with environment
func startAgentsWithEnv(agentPaths []string, env []string, cmd *cobra.Command, config *CLIConfig) error {
	var agentCmds []*exec.Cmd
	workingDir, _ := cmd.Flags().GetString("working-dir")
	user, _ := cmd.Flags().GetString("user")
	group, _ := cmd.Flags().GetString("group")
	background, _ := cmd.Flags().GetBool("background")
	quiet, _ := cmd.Flags().GetBool("quiet")

	for _, agentPath := range agentPaths {
		// Convert to absolute path
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return fmt.Errorf("invalid agent path %s: %w", agentPath, err)
		}

		if !quiet {
			fmt.Printf("Starting agent: %s\n", absPath)
		}

		// Create agent command with enhanced environment
		agentCmd, err := createAgentCommand(absPath, env, workingDir, user, group)
		if err != nil {
			return fmt.Errorf("failed to prepare agent %s: %w", agentPath, err)
		}

		if background {
			if err := agentCmd.Start(); err != nil {
				return fmt.Errorf("failed to start agent %s: %w", agentPath, err)
			}

			// Record agent process
			agentProc := ProcessInfo{
				PID:       agentCmd.Process.Pid,
				Name:      filepath.Base(agentPath),
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
				fmt.Printf("Agent %s started (PID: %d)\n", filepath.Base(agentPath), agentCmd.Process.Pid)
			}
		} else {
			// For foreground mode, we'll start the process later
			agentCmds = append(agentCmds, agentCmd)
		}
	}

	if background {
		if !quiet {
			fmt.Printf("All agents started in background\n")
		}
		return nil
	}

	// If running in foreground, start agents and wait
	if len(agentCmds) > 0 {
		return runAgentsInForeground(agentCmds, cmd, config)
	}

	return nil
}

// Start agents with file watching and auto-restart
func startAgentsWithFileWatching(agentPaths []string, env []string, cmd *cobra.Command, config *CLIConfig) error {
	watchPattern, _ := cmd.Flags().GetString("watch-pattern")
	quiet, _ := cmd.Flags().GetBool("quiet")

	// Create file watcher
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("failed to create file watcher: %w", err)
	}
	defer watcher.Close()

	// Watch directories for all agent files
	watchedDirs := make(map[string]bool)
	for _, agentPath := range agentPaths {
		agentDir := filepath.Dir(agentPath)
		if !watchedDirs[agentDir] {
			if err := watcher.Add(agentDir); err != nil {
				return fmt.Errorf("failed to watch directory %s: %w", agentDir, err)
			}
			watchedDirs[agentDir] = true
		}
	}

	// Start agents initially
	agentCmds := make(map[string]*exec.Cmd)
	for _, agentPath := range agentPaths {
		cmd, err := startSingleAgent(agentPath, env, cmd)
		if err != nil {
			return fmt.Errorf("failed to start agent %s: %w", agentPath, err)
		}
		agentCmds[agentPath] = cmd
	}

	if !quiet {
		fmt.Println("File watching enabled. Agents will auto-restart on file changes.")
		fmt.Println("Press Ctrl+C to stop all services.")
	}

	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Watch for file changes
	for {
		select {
		case event := <-watcher.Events:
			if matched, _ := filepath.Match(watchPattern, filepath.Base(event.Name)); matched {
				if event.Op&fsnotify.Write == fsnotify.Write {
					if !quiet {
						fmt.Printf("File changed: %s, restarting affected agents...\n", event.Name)
					}

					// Restart agents in the affected directory
					changedDir := filepath.Dir(event.Name)
					for agentPath, agentCmd := range agentCmds {
						if filepath.Dir(agentPath) == changedDir {
							// Gracefully stop current agent
							if agentCmd != nil && agentCmd.Process != nil {
								agentCmd.Process.Signal(os.Interrupt)
								agentCmd.Wait()
							}

							// Start new agent instance
							newCmd, err := startSingleAgent(agentPath, env, cmd)
							if err != nil {
								fmt.Printf("Failed to restart agent %s: %v\n", agentPath, err)
							} else {
								agentCmds[agentPath] = newCmd
								if !quiet {
									fmt.Printf("Agent %s restarted\n", filepath.Base(agentPath))
								}
							}
						}
					}
				}
			}
		case err := <-watcher.Errors:
			return fmt.Errorf("file watcher error: %w", err)
		case <-sigChan:
			if !quiet {
				fmt.Println("\nShutting down all services...")
			}
			// Stop all agents
			for _, agentCmd := range agentCmds {
				if agentCmd != nil && agentCmd.Process != nil {
					shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
					if shutdownTimeout == 0 {
						shutdownTimeout = config.ShutdownTimeout
					}
					KillProcess(agentCmd.Process.Pid, time.Duration(shutdownTimeout)*time.Second)
				}
			}
			return nil
		}
	}
}

// Create agent command with Python environment detection and hybrid config support
func createAgentCommand(agentPath string, env []string, workingDir, user, group string) (*exec.Cmd, error) {
	var pythonExec string
	var scriptPath string
	var finalWorkingDir string

	// Check if this is a YAML config file or Python script
	if filepath.Ext(agentPath) == ".yaml" || filepath.Ext(agentPath) == ".yml" {
		// YAML config mode
		config, err := LoadAgentConfig(agentPath)
		if err != nil {
			return nil, fmt.Errorf("failed to load agent config: %w", err)
		}

		// Validate config
		if err := ValidateAgentConfig(config); err != nil {
			return nil, fmt.Errorf("invalid agent config: %w", err)
		}

		// Use specified Python interpreter or detect environment
		if config.PythonInterpreter != "" {
			pythonExec = config.PythonInterpreter
		} else {
			pythonEnv, err := DetectPythonEnvironment()
			if err != nil {
				return nil, fmt.Errorf("Python environment detection failed: %w", err)
			}

			// Ensure mcp-mesh-runtime is available
			if err := EnsureMcpMeshRuntime(pythonEnv); err != nil {
				return nil, fmt.Errorf("package management failed: %w", err)
			}

			pythonExec = pythonEnv.PythonExecutable
		}

		// Convert script path to absolute path
		absScriptPath, err := filepath.Abs(config.Script)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", config.Script, err)
		}
		scriptPath = absScriptPath
		finalWorkingDir = config.GetWorkingDirectory()

		// Merge environment variables from config
		configEnv := config.GetEnvironmentVariables()
		env = mergeEnvironmentVariables(env, configEnv)
	} else {
		// Simple .py mode - detect Python environment
		pythonEnv, err := DetectPythonEnvironment()
		if err != nil {
			return nil, fmt.Errorf("Python environment detection failed: %w", err)
		}

		// Ensure mcp-mesh-runtime is available
		if err := EnsureMcpMeshRuntime(pythonEnv); err != nil {
			return nil, fmt.Errorf("package management failed: %w", err)
		}

		pythonExec = pythonEnv.PythonExecutable

		// Convert script path to absolute path
		absScriptPath, err := filepath.Abs(agentPath)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", agentPath, err)
		}
		scriptPath = absScriptPath
		finalWorkingDir = filepath.Dir(absScriptPath)
	}

	// Override working directory if specified in command line
	if workingDir != "" {
		absWorkingDir, err := AbsolutePath(workingDir)
		if err != nil {
			return nil, fmt.Errorf("invalid working directory: %w", err)
		}
		finalWorkingDir = absWorkingDir
	}

	// Create command to run the Python script directly
	// The mcp_mesh_runtime will be auto-imported via site-packages
	cmd := exec.Command(pythonExec, scriptPath)
	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set user and group (Unix only)
	if user != "" || group != "" {
		if err := setProcessCredentials(cmd, user, group); err != nil {
			return nil, fmt.Errorf("failed to set process credentials: %w", err)
		}
	}

	return cmd, nil
}

// mergeEnvironmentVariables merges two environment variable slices
func mergeEnvironmentVariables(env1, env2 []string) []string {
	envMap := make(map[string]string)

	// Parse first environment
	for _, envVar := range env1 {
		parts := strings.SplitN(envVar, "=", 2)
		if len(parts) == 2 {
			envMap[parts[0]] = parts[1]
		}
	}

	// Parse and merge second environment (overwrites)
	for _, envVar := range env2 {
		parts := strings.SplitN(envVar, "=", 2)
		if len(parts) == 2 {
			envMap[parts[0]] = parts[1]
		}
	}

	// Convert back to slice
	var result []string
	for key, value := range envMap {
		result = append(result, fmt.Sprintf("%s=%s", key, value))
	}

	return result
}

// Set process credentials (Unix only)
func setProcessCredentials(cmd *exec.Cmd, username, groupname string) error {
	// This is Unix-specific functionality
	if username == "" && groupname == "" {
		return nil
	}

	// Parse user ID
	var uid, gid uint32
	if username != "" {
		u, err := user.Lookup(username)
		if err != nil {
			return fmt.Errorf("user %s not found: %w", username, err)
		}
		parsedUID, err := strconv.ParseUint(u.Uid, 10, 32)
		if err != nil {
			return fmt.Errorf("invalid user ID for %s: %w", username, err)
		}
		uid = uint32(parsedUID)

		// Use primary group if no specific group provided
		if groupname == "" {
			parsedGID, err := strconv.ParseUint(u.Gid, 10, 32)
			if err != nil {
				return fmt.Errorf("invalid group ID for user %s: %w", username, err)
			}
			gid = uint32(parsedGID)
		}
	}

	// Parse group ID
	if groupname != "" {
		g, err := user.LookupGroup(groupname)
		if err != nil {
			return fmt.Errorf("group %s not found: %w", groupname, err)
		}
		parsedGID, err := strconv.ParseUint(g.Gid, 10, 32)
		if err != nil {
			return fmt.Errorf("invalid group ID for %s: %w", groupname, err)
		}
		gid = uint32(parsedGID)
	}

	// Set credentials (Unix only)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Credential: &syscall.Credential{
			Uid: uid,
			Gid: gid,
		},
	}

	return nil
}

// Helper functions
func startSingleAgent(agentPath string, env []string, cmd *cobra.Command) (*exec.Cmd, error) {
	workingDir, _ := cmd.Flags().GetString("working-dir")
	user, _ := cmd.Flags().GetString("user")
	group, _ := cmd.Flags().GetString("group")

	agentCmd, err := createAgentCommand(agentPath, env, workingDir, user, group)
	if err != nil {
		return nil, err
	}

	if err := agentCmd.Start(); err != nil {
		return nil, err
	}

	return agentCmd, nil
}

func runAgentsInForeground(agentCmds []*exec.Cmd, cmd *cobra.Command, config *CLIConfig) error {
	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Println("Agents are running. Press Ctrl+C to stop all services.")
	}

	// Start all agents
	for i, agentCmd := range agentCmds {
		// Start the command
		if err := agentCmd.Start(); err != nil {
			return fmt.Errorf("failed to start agent: %w", err)
		}

		// Record the process
		agentProc := ProcessInfo{
			PID:       agentCmd.Process.Pid,
			Name:      fmt.Sprintf("agent-%d", i),
			Type:      "agent",
			Command:   agentCmd.String(),
			StartTime: time.Now(),
			Status:    "running",
		}
		if err := AddRunningProcess(agentProc); err != nil && !quiet {
			fmt.Printf("Warning: failed to record agent process: %v\n", err)
		}

		// Run in goroutine to wait for completion
		go func(c *exec.Cmd) {
			if err := c.Wait(); err != nil && !quiet {
				fmt.Printf("Agent exited with error: %v\n", err)
			}
			RemoveRunningProcess(c.Process.Pid)
		}(agentCmd)
	}

	// Wait for signal
	<-sigChan
	if !quiet {
		fmt.Println("\nShutting down all services...")
	}

	// Stop all processes
	processes, err := GetRunningProcesses()
	if err == nil {
		shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
		if shutdownTimeout == 0 {
			shutdownTimeout = config.ShutdownTimeout
		}

		for _, proc := range processes {
			if !quiet {
				fmt.Printf("Stopping %s (PID: %d)\n", proc.Name, proc.PID)
			}
			if err := KillProcess(proc.PID, time.Duration(shutdownTimeout)*time.Second); err != nil && !quiet {
				fmt.Printf("Failed to stop %s: %v\n", proc.Name, err)
			}
			RemoveRunningProcess(proc.PID)
		}
	}

	return nil
}

// Background service helpers
func isProcessRunning(pidFile string) bool {
	data, err := os.ReadFile(pidFile)
	if err != nil {
		return false
	}

	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return false
	}

	// Check if process is still running
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}

	// Send signal 0 to check if process exists
	err = process.Signal(syscall.Signal(0))
	return err == nil
}

func forkToBackground(cobraCmd *cobra.Command, args []string, pidFile string, config *CLIConfig) error {
	// Create a new command to run in background
	cmdArgs := []string{os.Args[0], "start"}
	cmdArgs = append(cmdArgs, args...)

	// Add all the flags to the background command
	cobraCmd.Flags().Visit(func(flag *pflag.Flag) {
		if flag.Name != "background" { // Don't pass background flag to avoid infinite loop
			cmdArgs = append(cmdArgs, "--"+flag.Name, flag.Value.String())
		}
	})

	cmd := exec.Command(cmdArgs[0], cmdArgs[1:]...)
	cmd.Env = os.Environ()

	// Start the process
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start background process: %w", err)
	}

	// Write PID file
	if err := os.WriteFile(pidFile, []byte(fmt.Sprintf("%d", cmd.Process.Pid)), 0644); err != nil {
		return fmt.Errorf("failed to write PID file: %w", err)
	}

	quiet, _ := cobraCmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Printf("Started in background (PID: %d, PID file: %s)\n", cmd.Process.Pid, pidFile)
	}

	return nil
}
