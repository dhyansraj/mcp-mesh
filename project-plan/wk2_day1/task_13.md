# Task 13: Complete Flag Coverage for Start Command (30 minutes)

## Overview: Critical Architecture Preservation
**⚠️ IMPORTANT**: This migration only replaces the registry service and CLI with Go. ALL Python decorator functionality must remain unchanged:
- `@mesh_agent` decorator analysis and metadata extraction (Python)
- Dependency injection and resolution (Python) 
- Service discovery and proxy creation (Python)
- Auto-registration and heartbeat mechanisms (Python)

**Reference Documents**:
- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/decorators/mesh_agent.py` - Core decorator implementation
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/server/registry_server.py` - Current registry API

## CRITICAL PRESERVATION REQUIREMENT
**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI start command flag functionality.

**Reference Preservation**:
- Keep ALL Python CLI start command code as reference during migration
- Test EVERY existing start command flag and option combination
- Maintain IDENTICAL behavior for all start command variations
- Preserve ALL flag validation and error handling

**Implementation Validation**:
- Each Go start command flag must pass Python CLI behavior tests
- Flag combinations must work identically to Python version
- Environment variable integration must be preserved

## Objective
Implement complete flag coverage for start command maintaining identical behavior to Python

## Reference
`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/` directory

## Detailed Implementation

### 7.1: Complete start command flag coverage
```go
func NewStartCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "start [agent.py]",
        Short: "Start MCP agent with mesh runtime",
        Long:  "Start MCP agent with full mesh capabilities and registry integration",
        Args:  cobra.MaximumNArgs(1),
        RunE:  startAgent,
    }
    
    // Core functionality flags
    cmd.Flags().Bool("registry-only", false, "Start registry service only")
    cmd.Flags().String("registry-url", "", "External registry URL to connect to")
    cmd.Flags().Bool("connect-only", false, "Connect to external registry without embedding")
    
    // Registry configuration flags
    cmd.Flags().String("registry-host", "localhost", "Registry host address")
    cmd.Flags().Int("registry-port", 8080, "Registry port number")
    cmd.Flags().String("db-path", "./dev_registry.db", "Database file path")
    
    // Logging and debug flags
    cmd.Flags().Bool("debug", false, "Enable debug mode")
    cmd.Flags().String("log-level", "INFO", "Set log level (DEBUG, INFO, WARN, ERROR)")
    cmd.Flags().Bool("verbose", false, "Enable verbose output")
    cmd.Flags().Bool("quiet", false, "Suppress non-error output")
    
    // Development workflow flags
    cmd.Flags().Bool("auto-restart", true, "Auto-restart agent on file changes")
    cmd.Flags().Bool("watch-files", true, "Watch Python files for changes")
    cmd.Flags().String("watch-pattern", "*.py", "File pattern to watch")
    
    // Health monitoring flags
    cmd.Flags().Int("health-check-interval", 30, "Health check interval in seconds")
    cmd.Flags().Int("startup-timeout", 30, "Agent startup timeout in seconds")
    cmd.Flags().Int("shutdown-timeout", 30, "Graceful shutdown timeout in seconds")
    
    // Background service flags
    cmd.Flags().Bool("background", false, "Run as background service")
    cmd.Flags().String("pid-file", "./mcp_mesh_dev.pid", "PID file for background service")
    
    // Advanced configuration flags
    cmd.Flags().String("config-file", "", "Custom configuration file path")
    cmd.Flags().Bool("reset-config", false, "Reset configuration to defaults")
    cmd.Flags().StringSlice("env", []string{}, "Additional environment variables (KEY=VALUE)")
    
    // Agent-specific flags
    cmd.Flags().String("agent-name", "", "Override agent name")
    cmd.Flags().StringSlice("capabilities", []string{}, "Override agent capabilities")
    cmd.Flags().String("agent-version", "", "Override agent version")
    
    // Network and security flags
    cmd.Flags().Bool("secure", false, "Enable secure connections")
    cmd.Flags().String("cert-file", "", "TLS certificate file")
    cmd.Flags().String("key-file", "", "TLS private key file")
    
    return cmd
}

func startAgent(cmd *cobra.Command, args []string) error {
    // Parse all flags
    registryOnly, _ := cmd.Flags().GetBool("registry-only")
    registryURL, _ := cmd.Flags().GetString("registry-url")
    connectOnly, _ := cmd.Flags().GetBool("connect-only")
    debug, _ := cmd.Flags().GetBool("debug")
    logLevel, _ := cmd.Flags().GetString("log-level")
    background, _ := cmd.Flags().GetBool("background")
    
    // Configure logging
    if err := configureLogging(logLevel, debug); err != nil {
        return fmt.Errorf("failed to configure logging: %w", err)
    }
    
    // Handle registry-only mode
    if registryOnly {
        return startRegistryOnlyMode(cmd)
    }
    
    // Handle connect-only mode
    if connectOnly {
        if registryURL == "" {
            return fmt.Errorf("--registry-url required with --connect-only")
        }
        return startConnectOnlyMode(cmd, args, registryURL)
    }
    
    // Handle background mode
    if background {
        return startBackgroundMode(cmd, args)
    }
    
    // Standard agent startup
    return startStandardMode(cmd, args)
}

func startRegistryOnlyMode(cmd *cobra.Command) error {
    registryHost, _ := cmd.Flags().GetString("registry-host")
    registryPort, _ := cmd.Flags().GetInt("registry-port")
    dbPath, _ := cmd.Flags().GetString("db-path")
    
    config := &RegistryConfig{
        Host:   registryHost,
        Port:   registryPort,
        DbPath: dbPath,
    }
    
    fmt.Printf("Starting registry on %s:%d\n", registryHost, registryPort)
    return startRegistryService(config)
}

func startConnectOnlyMode(cmd *cobra.Command, args []string, registryURL string) error {
    if len(args) == 0 {
        return fmt.Errorf("agent file required in connect-only mode")
    }
    
    // Validate registry connection
    if !isRegistryReachable(registryURL) {
        return fmt.Errorf("cannot connect to registry at %s", registryURL)
    }
    
    agentEnv := buildAgentEnvironment(cmd, registryURL)
    return startPythonAgentWithEnv(args[0], agentEnv)
}

func startBackgroundMode(cmd *cobra.Command, args []string) error {
    pidFile, _ := cmd.Flags().GetString("pid-file")
    
    // Check if already running
    if isProcessRunning(pidFile) {
        return fmt.Errorf("background service already running (PID file: %s)", pidFile)
    }
    
    // Fork to background
    return forkToBackground(cmd, args, pidFile)
}

func startStandardMode(cmd *cobra.Command, args []string) error {
    registryHost, _ := cmd.Flags().GetString("registry-host")
    registryPort, _ := cmd.Flags().GetInt("registry-port")
    autoRestart, _ := cmd.Flags().GetBool("auto-restart")
    watchFiles, _ := cmd.Flags().GetBool("watch-files")
    
    registryURL := fmt.Sprintf("http://%s:%d", registryHost, registryPort)
    
    // Check if registry is running
    if !isRegistryReachable(registryURL) {
        fmt.Printf("Registry not found at %s, starting embedded registry...\n", registryURL)
        
        registryConfig := &RegistryConfig{
            Host:   registryHost,
            Port:   registryPort,
            DbPath: cmd.Flag("db-path").Value.String(),
        }
        
        // Start registry in background
        go func() {
            if err := startRegistryService(registryConfig); err != nil {
                log.Printf("Registry startup failed: %v", err)
            }
        }()
        
        // Wait for registry to be ready
        timeout, _ := cmd.Flags().GetInt("startup-timeout")
        if err := waitForRegistry(registryURL, time.Duration(timeout)*time.Second); err != nil {
            return fmt.Errorf("registry startup timeout: %w", err)
        }
    }
    
    // Start agent if specified
    if len(args) > 0 {
        agentEnv := buildAgentEnvironment(cmd, registryURL)
        
        if watchFiles && autoRestart {
            return startAgentWithFileWatching(args[0], agentEnv, cmd)
        }
        
        return startPythonAgentWithEnv(args[0], agentEnv)
    }
    
    // Registry-only mode if no agent specified
    fmt.Printf("Registry running at %s (no agent specified)\n", registryURL)
    return waitForInterrupt()
}

func buildAgentEnvironment(cmd *cobra.Command, registryURL string) []string {
    env := os.Environ()
    
    // Add registry configuration
    env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_URL=%s", registryURL))
    
    registryHost, _ := cmd.Flags().GetString("registry-host")
    registryPort, _ := cmd.Flags().GetInt("registry-port")
    env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_HOST=%s", registryHost))
    env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_PORT=%d", registryPort))
    
    // Add database path
    dbPath, _ := cmd.Flags().GetString("db-path")
    env = append(env, fmt.Sprintf("MCP_MESH_DATABASE_URL=sqlite:///%s", dbPath))
    
    // Add logging configuration
    logLevel, _ := cmd.Flags().GetString("log-level")
    env = append(env, fmt.Sprintf("MCP_MESH_LOG_LEVEL=%s", logLevel))
    
    // Add debug mode
    debug, _ := cmd.Flags().GetBool("debug")
    env = append(env, fmt.Sprintf("MCP_MESH_DEBUG_MODE=%t", debug))
    
    // Add custom environment variables
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

func startAgentWithFileWatching(agentPath string, env []string, cmd *cobra.Command) error {
    watchPattern, _ := cmd.Flags().GetString("watch-pattern")
    
    // Implementation for file watching and auto-restart
    watcher, err := fsnotify.NewWatcher()
    if err != nil {
        return fmt.Errorf("failed to create file watcher: %w", err)
    }
    defer watcher.Close()
    
    // Add watch for agent file and directory
    agentDir := filepath.Dir(agentPath)
    if err := watcher.Add(agentDir); err != nil {
        return fmt.Errorf("failed to watch directory %s: %w", agentDir, err)
    }
    
    var agentCmd *exec.Cmd
    
    // Start agent initially
    agentCmd = startPythonAgentAsync(agentPath, env)
    
    // Watch for file changes
    for {
        select {
        case event := <-watcher.Events:
            if matched, _ := filepath.Match(watchPattern, filepath.Base(event.Name)); matched {
                if event.Op&fsnotify.Write == fsnotify.Write {
                    fmt.Printf("File changed: %s, restarting agent...\n", event.Name)
                    
                    // Gracefully stop current agent
                    if agentCmd != nil && agentCmd.Process != nil {
                        agentCmd.Process.Signal(os.Interrupt)
                        agentCmd.Wait()
                    }
                    
                    // Start new agent instance
                    agentCmd = startPythonAgentAsync(agentPath, env)
                }
            }
        case err := <-watcher.Errors:
            return fmt.Errorf("file watcher error: %w", err)
        }
    }
}
```

## Success Criteria
- [ ] **CRITICAL**: Complete flag coverage for start command matching Python CLI exactly
- [ ] **CRITICAL**: All flag combinations work identically to Python implementation
- [ ] **CRITICAL**: Environment variable injection matches Python behavior exactly
- [ ] **CRITICAL**: File watching and auto-restart functionality preserved
- [ ] **CRITICAL**: Background service mode works identically
- [ ] **CRITICAL**: Registry embedding logic matches Python CLI exactly