package cli

import (
	"bufio"
	"fmt"
	"io/fs"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"os/user"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"mcp-mesh/src/core/cli/handlers"
	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
)

// Language constants for agent detection
const (
	langPython     = "python"
	langTypeScript = "typescript"
	langJava       = "java"
)

// isAgentFile returns true if the path is a valid agent file (.py, .ts, .js, .yaml, .yml, .jar, .java)
// or a directory containing known language markers (pom.xml, main.py, package.json, etc.)
func isAgentFile(path string) bool {
	ext := filepath.Ext(path)
	switch ext {
	case ".py", ".ts", ".js", ".yaml", ".yml", ".jar", ".java":
		return true
	}

	info, err := os.Stat(path)
	if err == nil && info.IsDir() {
		for _, markers := range handlers.LanguageMarkers {
			for _, marker := range markers {
				if _, err := os.Stat(filepath.Join(path, marker)); err == nil {
					return true
				}
			}
		}
	}

	return false
}

// isJavaProject checks if the given path is a Java agent (JAR file or Maven project)
func isJavaProject(agentPath string) bool {
	if strings.HasSuffix(strings.ToLower(agentPath), ".jar") {
		return true
	}
	info, err := os.Stat(agentPath)
	if err != nil {
		return false
	}
	dir := agentPath
	if !info.IsDir() {
		dir = filepath.Dir(agentPath)
	}
	// Check for pom.xml in the directory or parent directories
	javaHandler := &handlers.JavaHandler{}
	_, err = javaHandler.FindProjectRoot(dir)
	return err == nil
}

// isPythonProject checks if the given path is a Python agent
func isPythonProject(agentPath string) bool {
	lowerPath := strings.ToLower(agentPath)
	if strings.HasSuffix(lowerPath, ".py") || strings.HasSuffix(lowerPath, ".yaml") || strings.HasSuffix(lowerPath, ".yml") {
		// Check if it's detected as Python by the language handler
		handler := handlers.DetectLanguage(agentPath)
		return handler.Language() == langPython
	}
	info, err := os.Stat(agentPath)
	if err != nil {
		return false
	}
	if info.IsDir() {
		handler := handlers.DetectLanguage(agentPath)
		return handler.Language() == langPython
	}
	return false
}

// createJavaWatcher creates an AgentWatcher for a Java Maven project
func createJavaWatcher(agentPath string, env []string, workingDir, user, group string, quiet bool) (*AgentWatcher, error) {
	// Resolve project root
	projectDir := agentPath
	if info, err := os.Stat(agentPath); err == nil && !info.IsDir() {
		projectDir = filepath.Dir(agentPath)
	}
	absProjectDir, err := filepath.Abs(projectDir)
	if err != nil {
		return nil, fmt.Errorf("failed to get absolute path for %s: %w", projectDir, err)
	}
	javaHandler := &handlers.JavaHandler{}
	projectRoot, err := javaHandler.FindProjectRoot(absProjectDir)
	if err != nil {
		return nil, fmt.Errorf("cannot find Maven project: %w", err)
	}

	finalWorkingDir := projectRoot
	if workingDir != "" {
		absWorkingDir, err := AbsolutePath(workingDir)
		if err != nil {
			return nil, fmt.Errorf("invalid working directory: %w", err)
		}
		finalWorkingDir = absWorkingDir
	}

	// Add Java-specific environment variables
	javaEnv := []string{
		"SPRING_MAIN_BANNER_MODE=off",
	}
	fullEnv := append(env, javaEnv...)

	// Build command factory - creates a fresh cmd each restart
	cmdFactory := func() *exec.Cmd {
		cmd := exec.Command("mvn", "spring-boot:run", "-q")
		cmd.Env = fullEnv
		cmd.Dir = finalWorkingDir
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		// Set user/group if specified
		if user != "" || group != "" {
			_ = setProcessCredentials(cmd, user, group)
		}
		return cmd
	}

	watchDir := filepath.Join(projectRoot, "src")
	// If src directory doesn't exist, watch the project root
	if _, err := os.Stat(watchDir); os.IsNotExist(err) {
		watchDir = projectRoot
	}

	config := WatchConfig{
		ProjectRoot:   projectRoot,
		WatchDir:      watchDir,
		Extensions:    []string{".java", ".yml", ".yaml", ".properties", ".xml"},
		ExcludeDirs:   []string{"target", ".git", ".idea", "node_modules", ".mvn"},
		DebounceDelay: getWatchDebounceDelay(),
		PortDelay:     getWatchPortDelay(),
		StopTimeout:   3 * time.Second,
		AgentName:     filepath.Base(projectRoot),
	}

	return NewAgentWatcher(config, cmdFactory, quiet), nil
}

// createPythonWatcher creates an AgentWatcher for a Python agent
func createPythonWatcher(agentPath string, env []string, workingDir, user, group string, quiet bool) (*AgentWatcher, error) {
	// Create the non-watch command to get all the resolved paths and env
	// We pass watch=false to get the plain python command
	templateCmd, err := createPythonAgentCommand(agentPath, env, workingDir, user, group, false)
	if err != nil {
		return nil, err
	}

	// Extract the resolved values from the template command
	resolvedEnv := templateCmd.Env
	resolvedDir := templateCmd.Dir
	resolvedArgs := templateCmd.Args // e.g., ["/path/to/python", "/path/to/script.py"]

	// Build command factory
	cmdFactory := func() *exec.Cmd {
		cmd := exec.Command(resolvedArgs[0], resolvedArgs[1:]...)
		cmd.Env = resolvedEnv
		cmd.Dir = resolvedDir
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		cmd.Stdin = os.Stdin
		cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
		if user != "" || group != "" {
			_ = setProcessCredentials(cmd, user, group)
		}
		return cmd
	}

	// Watch the script's parent directory (same as Python reload.py does)
	watchDir := resolvedDir

	config := WatchConfig{
		ProjectRoot:   resolvedDir,
		WatchDir:      watchDir,
		Extensions:    []string{".py", ".jinja2", ".j2", ".yaml", ".yml"},
		ExcludeDirs:   []string{"__pycache__", ".git", ".venv", "venv", ".pytest_cache", ".mypy_cache", "node_modules", ".eggs", ".egg-info"},
		DebounceDelay: getWatchDebounceDelay(),
		PortDelay:     getWatchPortDelay(),
		StopTimeout:   3 * time.Second,
		AgentName:     extractAgentName(agentPath),
	}

	return NewAgentWatcher(config, cmdFactory, quiet), nil
}

// resolveAllAgentPaths resolves folder paths to entry point files.
// Supports both folder names (auto-detect entry point) and full file paths.
// Returns resolved file paths or error if any path cannot be resolved.
//
// Examples:
//
//	["my-agent"]                    → ["/abs/path/my-agent/main.py"]
//	["my-agent/src/index.ts"]       → ["/abs/path/my-agent/src/index.ts"]
//	["agent1", "agent2/main.py"]    → ["/abs/path/agent1/main.py", "/abs/path/agent2/main.py"]
func resolveAllAgentPaths(args []string) ([]string, error) {
	resolved := make([]string, 0, len(args))

	for _, arg := range args {
		resolvedPath, _, err := handlers.ResolveEntryPoint(arg)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve %q: %w", arg, err)
		}
		resolved = append(resolved, resolvedPath)
	}

	return resolved, nil
}

// NewStartCommand creates the start command
func NewStartCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "start [agents...]",
		Short: "Start MCP agent with mesh runtime",
		Long: `Start one or more MCP agents with mesh runtime support.

Supports Python (.py), TypeScript (.ts, .js), and Java (Maven/Spring Boot) agents.
If no registry is running, a local registry will be started automatically.
The registry service can also be started independently using --registry-only.

Examples:
  meshctl start                              # Start registry only
  meshctl start examples/hello_world.py     # Start Python agent
  meshctl start src/index.ts                # Start TypeScript agent
  meshctl start examples/java/my-agent      # Start Java agent (Maven project)
  meshctl start my-agent.jar                # Start Java agent (JAR file)
  meshctl start --registry-only              # Start only the registry service
  meshctl start agent1.py agent2.ts         # Start multiple agents (mixed languages)`,
		Args: cobra.ArbitraryArgs,
		RunE: runStartCommand,
	}

	// Core functionality flags
	cmd.Flags().Bool("registry-only", false, "Start registry service only")
	cmd.Flags().String("registry-url", "", "External registry URL to connect to")
	cmd.Flags().Bool("connect-only", false, "Connect to external registry without embedding")

	// Registry configuration flags
	cmd.Flags().String("registry-host", "", "Registry host address (default: localhost)")
	cmd.Flags().Int("registry-port", 0, "Registry port number (default: 8000)")
	cmd.Flags().String("db-path", "", "Database file path (default: ./dev_registry.db)")

	// Logging and debug flags
	cmd.Flags().Bool("debug", false, "Enable debug mode")
	cmd.Flags().String("log-level", "", "Set log level (TRACE, DEBUG, INFO, WARN, ERROR) (default: INFO). TRACE enables SQL logging.")
	cmd.Flags().Bool("verbose", false, "Enable verbose output")
	cmd.Flags().Bool("quiet", false, "Suppress non-error output")

	// Health monitoring flags
	cmd.Flags().Int("health-check-interval", 0, "Health check interval in seconds (default: 30)")
	cmd.Flags().Int("startup-timeout", 0, "Agent startup timeout in seconds (default: 30)")
	cmd.Flags().Int("shutdown-timeout", 0, "Graceful shutdown timeout in seconds (default: 30)")

	// Background service flags
	cmd.Flags().BoolP("detach", "d", false, "Run in detached mode (detach)")
	cmd.Flags().String("pid-file", "", "Deprecated: PID files are now per-agent in ~/.mcp-mesh/pids/")
	cmd.Flags().MarkDeprecated("pid-file", "PID files are now managed per-agent in ~/.mcp-mesh/pids/")

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

	// Development flags
	cmd.Flags().BoolP("watch", "w", false, "Watch files and restart on changes")

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
	detach, _ := cmd.Flags().GetBool("detach")

	// Validate flag combinations
	if err := validateFlagCombinations(cmd); err != nil {
		return err
	}

	// Resolve folder paths to entry point files (issue #474)
	// This allows `meshctl start my-agent` instead of `meshctl start my-agent/main.py`
	resolvedArgs := args
	if len(args) > 0 {
		var err error
		resolvedArgs, err = resolveAllAgentPaths(args)
		if err != nil {
			return err
		}
	}

	// Run pre-flight checks BEFORE forking to background (issue #444)
	// This ensures validation errors are shown to the user, not hidden in log files
	quiet, _ := cmd.Flags().GetBool("quiet")
	if len(resolvedArgs) > 0 {
		if err := runPrerequisiteValidation(resolvedArgs, quiet); err != nil {
			return err
		}
	}

	// Handle detach mode FIRST - before other modes
	// This ensures log redirection is set up before any other processing
	if detach {
		return startBackgroundMode(cmd, resolvedArgs, config)
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
		return startConnectOnlyMode(cmd, resolvedArgs, registryURL, config)
	}

	// If no agents provided, start registry only
	if len(resolvedArgs) == 0 {
		fmt.Println("No agents specified, starting registry only")
		return startRegistryOnlyMode(cmd, config)
	}

	// Standard agent startup mode
	return startStandardMode(cmd, resolvedArgs, config)
}

// Environment file loading
func loadEnvironmentFile(envFile string) error {
	file, err := os.Open(envFile)
	if err != nil {
		return fmt.Errorf("cannot open environment file: %w", err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if err := setEnvironmentVariable(line); err != nil {
			return fmt.Errorf("invalid environment variable in %s: %s", envFile, line)
		}
	}

	return scanner.Err()
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
				return fmt.Errorf("invalid log level: %s (must be TRACE, DEBUG, INFO, WARNING, ERROR, or CRITICAL)", logLevel)
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
	if cmd.Flags().Changed("detach") {
		detach, _ := cmd.Flags().GetBool("detach")
		config.EnableBackground = detach
	}

	return nil
}

// Registry-only mode
func startRegistryOnlyMode(cmd *cobra.Command, config *CLIConfig) error {
	pm := GetGlobalProcessManager()
	// Update ProcessManager config with current config (including command-line flags)
	pm.config = config
	quiet, _ := cmd.Flags().GetBool("quiet")

	if !quiet {
		fmt.Printf("Starting MCP Mesh registry on %s:%d\n", config.RegistryHost, config.RegistryPort)
	}

	// Check if registry is already running via HTTP (primary check)
	registryURL := config.GetRegistryURL()
	if IsRegistryRunning(registryURL) {
		if !quiet {
			fmt.Printf("Registry is already running at %s\n", registryURL)
		}
		return fmt.Errorf("registry is already running at %s", registryURL)
	}

	// Check if port is available (secondary check for better error messages)
	if !IsPortAvailable(config.RegistryHost, config.RegistryPort) {
		return fmt.Errorf("port %d is already in use on %s - another service may be using this port", config.RegistryPort, config.RegistryHost)
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

	detach, _ := cmd.Flags().GetBool("detach")
	if detach {
		if !quiet {
			fmt.Printf("Registry started in detach (PID: %d)\n", processInfo.PID)
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

	// Don't start CLI health monitoring when we have an embedded registry
	// The registry will handle health monitoring internally

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

	// Start agents with external registry
	return startAgentsWithEnv(args, agentEnv, cmd, config)
}

// Background mode
func startBackgroundMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	// Note: We no longer check a single global PID file here.
	// Per-agent PID files are written by startAgentsWithEnv when agents start.
	// This allows running multiple 'meshctl start --detach' commands for different agents.

	// Fork to detach
	return forkToBackground(cmd, args, config)
}

// Standard mode
func startStandardMode(cmd *cobra.Command, args []string, config *CLIConfig) error {
	quiet, _ := cmd.Flags().GetBool("quiet")

	// Note: Prerequisites are validated in runStartCommand before reaching here

	// Determine registry URL from flags or config
	registryURL := determineStartRegistryURL(cmd, config)

	// Check if registry is running
	if !IsRegistryRunning(registryURL) {
		// Only attempt to start registry if connecting to localhost
		registryHost := getRegistryHostFromURL(registryURL, config.RegistryHost)
		if isLocalhostRegistry(registryHost) {
			if !quiet {
				fmt.Printf("Registry not found at %s, starting embedded registry...\n", registryURL)
			}

			// Check if we can start a registry (port available)
			registryPort := getRegistryPortFromURL(registryURL, config.RegistryPort)
			if !IsPortAvailable(registryHost, registryPort) {
				return fmt.Errorf("cannot start registry: port %d is already in use on %s", registryPort, registryHost)
			}

			// Start registry in detach
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
		} else {
			// Remote registry - cannot start, must connect to existing
			return fmt.Errorf("cannot connect to remote registry at %s - please ensure the registry is running", registryURL)
		}
	}

	// Build environment for agents
	agentEnv := buildAgentEnvironment(cmd, registryURL, config)

	return startAgentsWithEnv(args, agentEnv, cmd, config)
}

// isLocalhostRegistry checks if the registry host is localhost/local
func isLocalhostRegistry(host string) bool {
	switch strings.ToLower(host) {
	case "localhost", "127.0.0.1", "::1", "0.0.0.0":
		return true
	default:
		return false
	}
}

// PrerequisiteError represents a failed prerequisite check with remediation info
type PrerequisiteError struct {
	Check       string
	Message     string
	Remediation string
}

func (e *PrerequisiteError) Error() string {
	return e.Message
}

// runPrerequisiteValidation validates agent prerequisites and displays errors.
// Extracted to avoid duplication between startStandardMode and startConnectOnlyMode.
func runPrerequisiteValidation(agentPaths []string, quiet bool) error {
	if err := validateAgentPrerequisites(agentPaths, quiet); err != nil {
		if prereqErr, ok := err.(*PrerequisiteError); ok {
			fmt.Printf("\n❌ Prerequisite check failed: %s\n\n", prereqErr.Check)
			fmt.Printf("%s\n\n", prereqErr.Message)
			fmt.Printf("%s\n", prereqErr.Remediation)
			return fmt.Errorf("prerequisite check failed")
		}
		return err
	}
	return nil
}

// validateAgentPrerequisites performs upfront validation of all prerequisites
// before spawning any agents. Returns nil if all checks pass.
func validateAgentPrerequisites(agentPaths []string, quiet bool) error {
	if !quiet {
		fmt.Println("Validating prerequisites...")
	}

	// Group agents by language using handlers package
	pythonAgents := []string{}
	tsAgents := []string{}
	javaAgents := []string{}
	for _, agentPath := range agentPaths {
		handler := handlers.DetectLanguage(agentPath)
		lang := handler.Language()
		switch lang {
		case langPython:
			pythonAgents = append(pythonAgents, agentPath)
		case langTypeScript:
			tsAgents = append(tsAgents, agentPath)
		case langJava:
			javaAgents = append(javaAgents, agentPath)
		default:
			return &PrerequisiteError{
				Check:   "Agent file",
				Message: fmt.Sprintf("Unknown file type: %s", agentPath),
				Remediation: `MCP Mesh supports .py, .ts, .js, .java, and .jar files.
Use 'meshctl scaffold' to generate a new agent.`,
			}
		}
	}

	// Validate Python prerequisites if we have Python agents
	var pythonEnv *PythonEnvironment
	if len(pythonAgents) > 0 {
		var err error
		pythonEnv, err = DetectPythonEnvironment()
		if err != nil {
			cwd, _ := os.Getwd()
			return &PrerequisiteError{
				Check:   "Python environment",
				Message: fmt.Sprintf("Python environment check failed: %v", err),
				Remediation: fmt.Sprintf(`MCP Mesh requires a .venv directory in your current working directory.

Current directory: %s

To fix this issue:
  1. Navigate to your project directory (where your agents are)
  2. Create a virtual environment: python3.11 -m venv .venv
  3. Activate it: source .venv/bin/activate
  4. Install mcp-mesh: pip install mcp-mesh
  5. Run meshctl start from this directory

Run 'meshctl man prerequisite' for detailed setup instructions.`, cwd),
			}
		}

		// Check for mcp-mesh package
		if !checkMcpMeshPackage(pythonEnv.PythonExecutable) {
			return &PrerequisiteError{
				Check:   "mcp-mesh package",
				Message: "mcp-mesh package not found in Python environment.",
				Remediation: fmt.Sprintf(`To fix this issue:
  1. Activate your virtual environment (if using one)
  2. Install the mcp-mesh package:
     %s -m pip install mcp-mesh

Run 'meshctl man prerequisite' for detailed setup instructions.`, pythonEnv.PythonExecutable),
			}
		}
	}

	// Validate TypeScript prerequisites if we have TypeScript agents
	if len(tsAgents) > 0 {
		if err := validateTypeScriptPrerequisites(tsAgents, quiet); err != nil {
			return err
		}
	}

	// Validate Java prerequisites if we have Java agents
	if len(javaAgents) > 0 {
		if err := validateJavaPrerequisites(javaAgents, quiet); err != nil {
			return err
		}
	}

	// Validate agent file/directory paths exist
	for _, agentPath := range agentPaths {
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return &PrerequisiteError{
				Check:   "Agent path",
				Message: fmt.Sprintf("Invalid agent path: %s", agentPath),
				Remediation: `To fix this issue:
  1. Verify the agent file/directory exists at the specified path
  2. Use an absolute path or ensure the relative path is correct from your current directory
  3. Check file permissions`,
			}
		}

		// Check if path exists (file or directory - Java agents use directories)
		if _, err := os.Stat(absPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Agent path",
				Message: fmt.Sprintf("Agent path not found: %s", absPath),
				Remediation: fmt.Sprintf(`To fix this issue:
  1. Verify the path exists: ls -la %s
  2. Check if you're in the correct directory
  3. Create the agent or use 'meshctl scaffold' to generate one`, absPath),
			}
		}
	}

	if !quiet {
		fmt.Printf("✅ All prerequisites validated successfully\n")
		if pythonEnv != nil {
			fmt.Printf("   Python: %s (%s)\n", pythonEnv.Version, pythonEnv.PythonExecutable)
			if pythonEnv.IsVirtualEnv {
				fmt.Printf("   Virtual environment: %s\n", pythonEnv.VenvPath)
			}
		}
		if len(tsAgents) > 0 {
			fmt.Printf("   TypeScript: node_modules with @mcpmesh/sdk\n")
		}
		if len(javaAgents) > 0 {
			fmt.Printf("   Java: Maven project with mcp-mesh-spring-boot-starter\n")
		}
	}

	return nil
}

// validateTypeScriptPrerequisites checks TypeScript-specific requirements
// Checks each agent's directory for node_modules and @mcpmesh/sdk
func validateTypeScriptPrerequisites(agentPaths []string, quiet bool) error {
	// 1. Check npx is available (for running tsx)
	if _, err := exec.LookPath("npx"); err != nil {
		return &PrerequisiteError{
			Check:   "npx command",
			Message: "npx command not found.",
			Remediation: `npx is required to run TypeScript agents.

To fix this issue:
  1. Install Node.js (v18+) which includes npx
  2. Verify installation: npx --version`,
		}
	}

	// 2. Check each agent's directory for node_modules and @mcpmesh/sdk
	for _, agentPath := range agentPaths {
		absPath, err := AbsolutePath(agentPath)
		if err != nil {
			return &PrerequisiteError{
				Check:   "Agent file path",
				Message: fmt.Sprintf("Invalid agent path: %s", agentPath),
				Remediation: fmt.Sprintf(`The specified agent path could not be resolved.

Agent: %s

To fix this issue:
  1. Verify the path is correct
  2. Use an absolute path or a path relative to the current directory
  3. Run meshctl start again`, agentPath),
			}
		}

		// Check agent file exists BEFORE walking up directories
		if _, err := os.Stat(absPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Agent file",
				Message: fmt.Sprintf("Agent file not found: %s", absPath),
				Remediation: fmt.Sprintf(`The specified TypeScript agent file does not exist.

Agent: %s

To fix this issue:
  1. Verify the file path is correct
  2. Ensure you're running meshctl from the correct directory
  3. Check that the agent file has been created
  4. Run meshctl start again`, agentPath),
			}
		}

		// Find project root by looking for node_modules or package.json
		agentDir := filepath.Dir(absPath)
		projectDir := findNodeProjectRoot(agentDir)
		if projectDir == "" {
			return &PrerequisiteError{
				Check:   "Node.js project",
				Message: fmt.Sprintf("No package.json or node_modules found for agent: %s", agentPath),
				Remediation: fmt.Sprintf(`MCP Mesh TypeScript agents require a Node.js project setup.

Agent: %s

To fix this issue:
  1. Navigate to the agent's project directory
  2. Run: npm init -y
  3. Install dependencies: npm install @mcpmesh/sdk
  4. Run meshctl start again`, agentPath),
			}
		}

		// Check node_modules exists
		nodeModulesPath := filepath.Join(projectDir, "node_modules")
		if _, err := os.Stat(nodeModulesPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Node.js dependencies",
				Message: fmt.Sprintf("node_modules not found in: %s", projectDir),
				Remediation: fmt.Sprintf(`MCP Mesh TypeScript agents require npm dependencies.

Project: %s

To fix this issue:
  1. Navigate to: %s
  2. Install dependencies: npm install
  3. Run meshctl start again`, projectDir, projectDir),
			}
		}

		// Check @mcpmesh/sdk is installed
		sdkPath := filepath.Join(nodeModulesPath, "@mcpmesh", "sdk")
		if _, err := os.Stat(sdkPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "@mcpmesh/sdk package",
				Message: fmt.Sprintf("@mcpmesh/sdk not found in: %s", projectDir),
				Remediation: fmt.Sprintf(`To fix this issue:
  1. Navigate to: %s
  2. Install the package: npm install @mcpmesh/sdk
  3. Run meshctl start again`, projectDir),
			}
		}
	}

	return nil
}

// validateJavaPrerequisites checks Java-specific requirements
// Checks for Java 17+ and Maven installation
func validateJavaPrerequisites(agentPaths []string, quiet bool) error {
	// 1. Check Java is available
	javaPath, err := exec.LookPath("java")
	if err != nil {
		return &PrerequisiteError{
			Check:   "java command",
			Message: "java command not found.",
			Remediation: `Java 17+ is required to run Java agents.

To fix this issue:
  1. Install JDK 17+ from https://adoptium.net/
  2. Verify installation: java -version`,
		}
	}

	// 2. Check Java version is 17+
	javaVersion, err := getJavaMajorVersion()
	if err != nil {
		return &PrerequisiteError{
			Check:   "java version",
			Message: fmt.Sprintf("Could not determine Java version: %v", err),
			Remediation: `Java 17+ is required to run Java agents.

To fix this issue:
  1. Install JDK 17+ from https://adoptium.net/
  2. Verify installation: java -version`,
		}
	}

	if javaVersion < 17 {
		return &PrerequisiteError{
			Check:   "java version",
			Message: fmt.Sprintf("Java %d found, but Java 17+ is required.", javaVersion),
			Remediation: fmt.Sprintf(`Java 17+ is required to run Java agents.

Current Java: %s (version %d)

To fix this issue:
  1. Install JDK 17+ from https://adoptium.net/
  2. Update your PATH to use the new Java
  3. Verify: java -version`, javaPath, javaVersion),
		}
	}

	// 3. Check Maven is available
	if _, err := exec.LookPath("mvn"); err != nil {
		return &PrerequisiteError{
			Check:   "mvn command",
			Message: "mvn command not found.",
			Remediation: `Maven is required to build and run Java agents.

To fix this issue:
  1. Install Maven from https://maven.apache.org/
  2. Verify installation: mvn --version`,
		}
	}

	// 4. Check each agent's directory for pom.xml
	for _, agentPath := range agentPaths {
		// Handle JAR files - they don't need pom.xml
		if strings.HasSuffix(strings.ToLower(agentPath), ".jar") {
			if _, err := os.Stat(agentPath); os.IsNotExist(err) {
				return &PrerequisiteError{
					Check:   "JAR file",
					Message: fmt.Sprintf("JAR file not found: %s", agentPath),
					Remediation: fmt.Sprintf(`The specified JAR file does not exist.

JAR: %s

To fix this issue:
  1. Verify the path is correct
  2. Build the JAR: mvn package
  3. Run meshctl start again`, agentPath),
				}
			}
			continue
		}

		// For directories or pom.xml paths, check for pom.xml
		projectDir := agentPath
		if info, err := os.Stat(agentPath); err == nil && !info.IsDir() {
			projectDir = filepath.Dir(agentPath)
		}

		pomPath := filepath.Join(projectDir, "pom.xml")
		if _, err := os.Stat(pomPath); os.IsNotExist(err) {
			return &PrerequisiteError{
				Check:   "Maven project",
				Message: fmt.Sprintf("pom.xml not found in: %s", projectDir),
				Remediation: fmt.Sprintf(`MCP Mesh Java agents require a Maven project with pom.xml.

Project: %s

To fix this issue:
  1. Ensure the path points to a Maven project
  2. Verify pom.xml exists in the project root
  3. Run meshctl start again`, projectDir),
			}
		}
	}

	return nil
}

// getJavaMajorVersion returns the major Java version (e.g., 17, 21)
func getJavaMajorVersion() (int, error) {
	cmd := exec.Command("java", "-version")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return 0, err
	}

	// Parse version from output like:
	// openjdk version "17.0.13" 2024-10-15
	// or: java version "1.8.0_291"
	outputStr := string(output)
	versionRe := regexp.MustCompile(`version "(\d+)(?:\.(\d+))?`)
	matches := versionRe.FindStringSubmatch(outputStr)
	if len(matches) < 2 {
		return 0, fmt.Errorf("could not parse Java version from: %s", outputStr)
	}

	majorVersion, err := strconv.Atoi(matches[1])
	if err != nil {
		return 0, fmt.Errorf("invalid Java version number: %s", matches[1])
	}

	// Handle old versioning (1.8 = Java 8)
	if majorVersion == 1 && len(matches) > 2 {
		minorVersion, _ := strconv.Atoi(matches[2])
		return minorVersion, nil
	}

	return majorVersion, nil
}

// findNodeProjectRoot walks up directories to find package.json or node_modules
func findNodeProjectRoot(startDir string) string {
	dir := startDir
	for {
		// Check for package.json
		if _, err := os.Stat(filepath.Join(dir, "package.json")); err == nil {
			return dir
		}
		// Check for node_modules
		if _, err := os.Stat(filepath.Join(dir, "node_modules")); err == nil {
			return dir
		}

		// Move up one directory
		parent := filepath.Dir(dir)
		if parent == dir {
			// Reached root
			return ""
		}
		dir = parent
	}
}

// checkMcpMeshPackage checks if mcp-mesh package is installed.
// This checks for the user-facing "mcp-mesh" pip package (imports as mcp_mesh or mesh).
// Note: checkMcpMeshRuntime in python_env.go checks for mcp_mesh_runtime (the internal runtime)
// and mcp (the base MCP package). Both are needed but serve different purposes.
func checkMcpMeshPackage(pythonExec string) bool {
	// Check for mcp_mesh (the actual package)
	cmd := exec.Command(pythonExec, "-c", "import mcp_mesh")
	if cmd.Run() == nil {
		return true
	}

	// Also check for the mesh module (alternative import)
	cmd = exec.Command(pythonExec, "-c", "import mesh")
	return cmd.Run() == nil
}

// determineStartRegistryURL resolves the registry URL for start command based on flags and config
func determineStartRegistryURL(cmd *cobra.Command, config *CLIConfig) string {
	// Check if registry-url flag is provided
	if registryURL, _ := cmd.Flags().GetString("registry-url"); registryURL != "" {
		return registryURL
	}

	// Build URL from individual flags or config
	host := config.RegistryHost
	port := config.RegistryPort

	// Override with flags if provided
	if cmd.Flags().Changed("registry-host") {
		if flagHost, _ := cmd.Flags().GetString("registry-host"); flagHost != "" {
			host = flagHost
		}
	}
	if cmd.Flags().Changed("registry-port") {
		if flagPort, _ := cmd.Flags().GetInt("registry-port"); flagPort > 0 {
			port = flagPort
		}
	}

	return fmt.Sprintf("http://%s:%d", host, port)
}

// getRegistryHostFromURL extracts the host from a registry URL, fallback to config host
func getRegistryHostFromURL(registryURL, fallbackHost string) string {
	if parsed, err := url.Parse(registryURL); err == nil && parsed.Host != "" {
		// Extract just the hostname (without port)
		if colonIndex := strings.Index(parsed.Host, ":"); colonIndex != -1 {
			return parsed.Host[:colonIndex]
		}
		return parsed.Host
	}
	return fallbackHost
}

// getRegistryPortFromURL extracts the port from a registry URL, fallback to config port
func getRegistryPortFromURL(registryURL string, fallbackPort int) int {
	if parsed, err := url.Parse(registryURL); err == nil && parsed.Host != "" {
		// Extract port if present
		if colonIndex := strings.Index(parsed.Host, ":"); colonIndex != -1 {
			if portStr := parsed.Host[colonIndex+1:]; portStr != "" {
				if port, err := strconv.Atoi(portStr); err == nil {
					return port
				}
			}
		}
	}
	return fallbackPort
}

func startRegistryWithOptions(config *CLIConfig, detach bool, cmd *cobra.Command) error {
	// Start the registry service
	registryCmd, err := startRegistryService(config)
	if err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	if detach {
		// Set up log file for detached registry
		lm, err := NewLogManager()
		if err != nil {
			return fmt.Errorf("failed to initialize log manager: %w", err)
		}

		// Rotate existing logs
		quiet, _ := cmd.Flags().GetBool("quiet")
		if err := lm.RotateLogs("registry"); err != nil && !quiet {
			fmt.Printf("Warning: failed to rotate logs for registry: %v\n", err)
		}

		// Create log file and redirect output
		logFile, err := lm.CreateLogFile("registry")
		if err != nil {
			return fmt.Errorf("failed to create log file for registry: %w", err)
		}
		registryCmd.Stdout = logFile
		registryCmd.Stderr = logFile

		// Start in detach
		if err := registryCmd.Start(); err != nil {
			logFile.Close()
			return fmt.Errorf("failed to start registry in detach: %w", err)
		}

		// Write PID file for registry
		pm, err := NewPIDManager()
		if err == nil {
			if err := pm.WritePID("registry", registryCmd.Process.Pid); err != nil {
				fmt.Printf("Warning: failed to write PID file for registry: %v\n", err)
			}
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

		if !quiet {
			fmt.Printf("Registry started in detach (PID: %d)\n", registryCmd.Process.Pid)
			fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
			fmt.Printf("Logs: ~/.mcp-mesh/logs/registry.log\n")
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

func startAgents(agentPaths []string, config *CLIConfig, detach bool) error {
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

		// Start registry in detach
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

		if detach {
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

	if detach {
		fmt.Printf("All agents started in detach\n")
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
	// Try to find registry binary in multiple locations
	localPaths := []string{
		"./bin/mcp-mesh-registry",   // Relative to current working directory
		"./mcp-mesh-registry",       // For compatibility with process_lifecycle.go
		"./build/mcp-mesh-registry", // Build directory
	}

	var registryBinary string
	var binaryFound bool

	// Check local paths first
	for _, path := range localPaths {
		if _, err := os.Stat(path); err == nil {
			registryBinary = path
			binaryFound = true
			break
		}
	}

	// If not found locally, check system PATH
	if !binaryFound {
		if path, err := exec.LookPath("mcp-mesh-registry"); err == nil {
			registryBinary = path
			binaryFound = true
		}
	}

	// Build possiblePaths for error message
	possiblePaths := append(localPaths, "mcp-mesh-registry (in PATH)")

	// If binary not found, try to build it
	if !binaryFound {
		// Use bin/ directory for consistency with Makefile
		registryBinary = "./bin/mcp-mesh-registry"

		// Check if we have the source to build from
		if _, err := os.Stat("./cmd/mcp-mesh-registry"); err == nil {
			fmt.Println("Registry binary not found, building from source...")

			// Ensure bin directory exists
			if err := os.MkdirAll("./bin", 0755); err != nil {
				return nil, fmt.Errorf("failed to create bin directory: %w", err)
			}

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
				return nil, fmt.Errorf("failed to build registry from source: %w", err)
			}
			fmt.Println("Registry built successfully")
		} else {
			// No source available, cannot build
			return nil, fmt.Errorf("registry binary not found at any of these locations: %v. Please ensure the binary is built or run 'make build' to compile it", possiblePaths)
		}
	}

	// Create registry command
	cmd := exec.Command(registryBinary,
		"-host", config.RegistryHost,
		"-port", fmt.Sprintf("%d", config.RegistryPort),
	)

	// Set up environment
	cmd.Env = append(os.Environ(), config.GetRegistryEnvironmentVariables()...)

	// Set up process group for proper signal handling (Unix only)
	platformManager := NewPlatformProcessManager()
	platformManager.setProcessGroup(cmd)

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

		// For Java agents with watch mode, use AgentWatcher instead of bash wrapper
		if watch && isJavaProject(absPath) {
			watcher, err := createJavaWatcher(absPath, env, workingDir, user, group, quiet)
			if err != nil {
				return fmt.Errorf("failed to create watcher for %s: %w", agentPath, err)
			}

			watchers = append(watchers, watcher)
			continue
		}

		// For Python agents with watch mode, use AgentWatcher instead of reload_runner
		if watch && isPythonProject(absPath) {
			watcher, err := createPythonWatcher(absPath, env, workingDir, user, group, quiet)
			if err != nil {
				return fmt.Errorf("failed to create watcher for %s: %w", agentPath, err)
			}

			watchers = append(watchers, watcher)
			continue
		}

		// Create agent command with enhanced environment
		agentCmd, err := createAgentCommand(absPath, env, workingDir, user, group, watch)
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
		return runAgentsInForeground(agentCmds, watchers, cmd, config)
	}

	return nil
}

// Create agent command with language detection and environment setup
func createAgentCommand(agentPath string, env []string, workingDir, user, group string, watch bool) (*exec.Cmd, error) {
	handler := handlers.DetectLanguage(agentPath)
	lang := handler.Language()

	switch lang {
	case langTypeScript:
		return createTypeScriptAgentCommand(agentPath, env, workingDir, user, group, watch)
	case langPython:
		return createPythonAgentCommand(agentPath, env, workingDir, user, group, watch)
	case langJava:
		return createJavaAgentCommand(agentPath, env, workingDir, user, group, watch)
	default:
		return nil, fmt.Errorf("unsupported file type: %s (use .py, .ts, .js, .java, or .jar)", agentPath)
	}
}

// createTypeScriptAgentCommand creates a command for TypeScript/JavaScript agents
func createTypeScriptAgentCommand(agentPath string, env []string, workingDir, user, group string, watch bool) (*exec.Cmd, error) {
	// Convert script path to absolute path
	absScriptPath, err := filepath.Abs(agentPath)
	if err != nil {
		return nil, fmt.Errorf("failed to get absolute path for %s: %w", agentPath, err)
	}

	finalWorkingDir := filepath.Dir(absScriptPath)

	// Override working directory if specified in command line
	if workingDir != "" {
		absWorkingDir, err := AbsolutePath(workingDir)
		if err != nil {
			return nil, fmt.Errorf("invalid working directory: %w", err)
		}
		finalWorkingDir = absWorkingDir
	}

	// Create command based on file extension
	var cmd *exec.Cmd
	ext := filepath.Ext(agentPath)

	if watch {
		// For watch mode with TypeScript, use npx tsx --watch
		if ext == ".ts" {
			cmd = exec.Command("npx", "tsx", "--watch", absScriptPath)
		} else {
			// For .js files, use node with --watch (Node 18+)
			cmd = exec.Command("node", "--watch", absScriptPath)
		}
	} else {
		if ext == ".ts" {
			// Use npx tsx for TypeScript files
			cmd = exec.Command("npx", "tsx", absScriptPath)
		} else {
			// Use node for JavaScript files
			cmd = exec.Command("node", absScriptPath)
		}
	}

	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set up process group for proper signal handling (Unix only)
	// This ensures that when we stop the agent, we kill the entire process tree
	// (npx -> tsx -> node) rather than just the parent process
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	// Set user and group (Unix only)
	if user != "" || group != "" {
		if err := setProcessCredentials(cmd, user, group); err != nil {
			return nil, fmt.Errorf("failed to set process credentials: %w", err)
		}
	}

	return cmd, nil
}

// createPythonAgentCommand creates a command for Python agents (including YAML configs)
func createPythonAgentCommand(agentPath string, env []string, workingDir, user, group string, watch bool) (*exec.Cmd, error) {
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

	// Create command to run the Python script
	// The mcp_mesh_runtime will be auto-imported via site-packages
	// Watch mode is handled by AgentWatcher at the caller level
	cmd := exec.Command(pythonExec, scriptPath)
	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set up process group for proper signal handling (Unix only)
	// This ensures that when we stop the agent, we kill the entire process tree
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	// Set user and group (Unix only)
	if user != "" || group != "" {
		if err := setProcessCredentials(cmd, user, group); err != nil {
			return nil, fmt.Errorf("failed to set process credentials: %w", err)
		}
	}

	return cmd, nil
}

// createJavaAgentCommand creates a command for Java agents (Maven/Spring Boot or JAR)
func createJavaAgentCommand(agentPath string, env []string, workingDir, user, group string, watch bool) (*exec.Cmd, error) {
	var cmd *exec.Cmd
	var finalWorkingDir string

	// Check if it's a JAR file
	if strings.HasSuffix(strings.ToLower(agentPath), ".jar") {
		// Convert JAR path to absolute path
		absJarPath, err := filepath.Abs(agentPath)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", agentPath, err)
		}

		finalWorkingDir = filepath.Dir(absJarPath)

		// Override working directory if specified in command line
		if workingDir != "" {
			absWorkingDir, err := AbsolutePath(workingDir)
			if err != nil {
				return nil, fmt.Errorf("invalid working directory: %w", err)
			}
			finalWorkingDir = absWorkingDir
		}

		// Run JAR directly with java -jar
		cmd = exec.Command("java", "-jar", absJarPath)
	} else {
		// Maven project - find the project root (directory with pom.xml)
		projectDir := agentPath

		// If agentPath is a file, get its directory
		if info, err := os.Stat(agentPath); err == nil && !info.IsDir() {
			projectDir = filepath.Dir(agentPath)
		}

		// Convert to absolute path
		absProjectDir, err := filepath.Abs(projectDir)
		if err != nil {
			return nil, fmt.Errorf("failed to get absolute path for %s: %w", projectDir, err)
		}

		// Walk up to find pom.xml if not in current directory
		javaHandler := &handlers.JavaHandler{}
		projectRoot, err := javaHandler.FindProjectRoot(absProjectDir)
		if err != nil {
			return nil, fmt.Errorf("cannot find Maven project: %w", err)
		}

		finalWorkingDir = projectRoot

		// Override working directory if specified in command line
		if workingDir != "" {
			absWorkingDir, err := AbsolutePath(workingDir)
			if err != nil {
				return nil, fmt.Errorf("invalid working directory: %w", err)
			}
			finalWorkingDir = absWorkingDir
		}

		// Use mvn spring-boot:run
		cmd = exec.Command("mvn", "spring-boot:run", "-q")
	}

	// Add Java-specific environment variables
	javaEnv := []string{
		"SPRING_MAIN_BANNER_MODE=off", // Disable Spring Boot banner for cleaner output
	}
	env = append(env, javaEnv...)

	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	cmd.Dir = finalWorkingDir

	// Set up process group for proper signal handling (Unix only)
	// This ensures that when we stop the agent, we kill the entire process tree
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

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

func runAgentsInForeground(agentCmds []*exec.Cmd, watchers []*AgentWatcher, cmd *cobra.Command, config *CLIConfig) error {
	// Setup signal handling
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Println("Agents are running. Press Ctrl+C to stop all services.")
	}

	// Initialize PID manager for tracking
	pm, pmErr := NewPIDManager()

	// Track agent names for cleanup
	var agentNames []string

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
		agentNames = append(agentNames, agentName)

		// Write PID file for this agent
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
			RemoveRunningProcess(c.Process.Pid)
			// Clean up PID file when agent exits
			if pmErr == nil {
				pm.RemovePID(name)
			}
		}(agentCmd, agentName)
	}

	// Start all watchers (each blocks in its own goroutine)
	for _, w := range watchers {
		go func(watcher *AgentWatcher) {
			if err := watcher.Start(); err != nil && !quiet {
				fmt.Printf("Watcher error: %v\n", err)
			}
		}(w)
	}

	// Write PID files for watcher-managed agents
	// Use meshctl's own PID — when meshctl stop sends SIGTERM, signal handler cleans up watchers
	for _, w := range watchers {
		agentName := w.config.AgentName
		agentNames = append(agentNames, agentName)

		if pmErr == nil {
			if err := pm.WritePID(agentName, os.Getpid()); err != nil && !quiet {
				fmt.Printf("Warning: failed to write PID file for %s: %v\n", agentName, err)
			}
		}

		// Record the process for tracking
		agentProc := ProcessInfo{
			PID:       os.Getpid(),
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

	// Clean up watcher PID files
	if pmErr == nil {
		for _, w := range watchers {
			pm.RemovePID(w.config.AgentName)
		}
	}

	// Stop all processes - agents first, registry last (issue #442)
	processes, err := GetRunningProcesses()
	if err == nil {
		shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
		if shutdownTimeout == 0 {
			shutdownTimeout = config.ShutdownTimeout
		}

		// Separate agents from registry
		var agents []ProcessInfo
		var registry *ProcessInfo
		for i := range processes {
			if processes[i].Type == "registry" {
				registry = &processes[i]
			} else {
				agents = append(agents, processes[i])
			}
		}

		// Stop agents first (in parallel)
		if len(agents) > 0 {
			var wg sync.WaitGroup
			for _, proc := range agents {
				wg.Add(1)
				go func(p ProcessInfo) {
					defer wg.Done()
					if !quiet {
						fmt.Printf("Stopping %s (PID: %d)\n", p.Name, p.PID)
					}
					if err := KillProcess(p.PID, time.Duration(shutdownTimeout)*time.Second); err != nil && !quiet {
						fmt.Printf("Failed to stop %s: %v\n", p.Name, err)
					}
					RemoveRunningProcess(p.PID)
				}(proc)
			}
			wg.Wait()

			// Grace period for agents to complete unregister HTTP calls
			time.Sleep(500 * time.Millisecond)
		}

		// Stop registry last
		if registry != nil {
			if !quiet {
				fmt.Printf("Stopping %s (PID: %d)\n", registry.Name, registry.PID)
			}
			if err := KillProcess(registry.PID, time.Duration(shutdownTimeout)*time.Second); err != nil && !quiet {
				fmt.Printf("Failed to stop %s: %v\n", registry.Name, err)
			}
			RemoveRunningProcess(registry.PID)
		}
	}

	// Clean up all PID files for tracked agents
	if pmErr == nil {
		for _, name := range agentNames {
			pm.RemovePID(name)
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
			} else {
				cmdArgs = append(cmdArgs, "--"+flag.Name, flag.Value.String())
			}
		}
	})

	cmd := exec.Command(cmdArgs[0], cmdArgs[1:]...)
	cmd.Env = os.Environ()

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

	// Note: We no longer write a global PID file here.
	// Per-agent PID files are written by startAgentsWithEnv when agents start.
	// Use 'meshctl stop' to stop agents by name.

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

// agentNameCache caches extracted agent names to avoid repeated parsing
// Uses sync.Map for thread-safe concurrent access when starting multiple agents
var agentNameCache sync.Map

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
			if err != nil || foundName != "" {
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

	// Try to extract from pom.xml artifactId
	pomPath := filepath.Join(projectDir, "pom.xml")
	if content, err := os.ReadFile(pomPath); err == nil {
		// Extract artifactId as name (simple regex, not full XML parsing)
		// Look for <artifactId> that's not inside a <parent> block
		artifactIdRe := regexp.MustCompile(`(?s)<project[^>]*>.*?<artifactId>([^<]+)</artifactId>`)
		if matches := artifactIdRe.FindSubmatch(content); len(matches) > 1 {
			return string(matches[1])
		}
	}

	// Fallback to directory name
	return filepath.Base(projectDir)
}
