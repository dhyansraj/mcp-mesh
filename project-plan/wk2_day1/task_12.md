# Task 12: Configuration System Implementation (30 minutes)

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
**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI configuration system functionality.

**Reference Preservation**:
- Keep ALL Python CLI configuration handling code as reference during migration
- Test EVERY configuration precedence rule and file handling behavior
- Maintain IDENTICAL configuration loading, saving, and environment variable handling
- Preserve ALL configuration file formats and directory structures

**Implementation Validation**:
- Configuration precedence must work identically to Python (CLI > config file > env vars > defaults)
- File operations must match Python implementation exactly
- Environment variable handling must be identical

## Objective
Implement complete configuration system with file handling, environment variables, and precedence rules maintaining identical behavior to Python

## Reference
`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/config.py` directory

## Detailed Implementation

### 6.1: Complete configuration system implementation
```go
// Complete configuration handling with precedence
type CLIConfig struct {
    // Registry settings
    RegistryPort int    `json:"registry_port"`      // default: 8080
    RegistryHost string `json:"registry_host"`      // default: "localhost"
    
    // Database settings
    DbPath string `json:"db_path"`                 // default: "./dev_registry.db"
    
    // Logging settings
    LogLevel string `json:"log_level"`             // default: "INFO"
    
    // Health monitoring
    HealthCheckInterval int `json:"health_check_interval"` // default: 30
    
    // Development settings
    AutoRestart bool `json:"auto_restart"`         // default: true
    WatchFiles  bool `json:"watch_files"`          // default: true
    DebugMode   bool `json:"debug_mode"`           // default: false
    
    // Timeout settings
    StartupTimeout  int `json:"startup_timeout"`   // default: 30
    ShutdownTimeout int `json:"shutdown_timeout"`  // default: 30
    
    // Background service settings
    EnableBackground bool   `json:"enable_background"` // default: false
    PidFile         string `json:"pid_file"`          // default: "./mcp_mesh_dev.pid"
}

// Configuration precedence: CLI args > config file > env vars > defaults
func LoadConfiguration() (*CLIConfig, error) {
    // Start with default values
    config := createDefaultConfiguration()
    
    // 1. Load from environment variables (MCP_MESH_ prefix)
    loadFromEnvironment(config)
    
    // 2. Load from configuration file (~/.mcp_mesh/cli_config.json)
    if err := loadFromConfigFile(config); err != nil {
        return nil, fmt.Errorf("failed to load config file: %w", err)
    }
    
    // 3. Override with CLI arguments (handled by cobra automatically)
    // This happens in command handlers when flags are parsed
    
    return config, nil
}

func createDefaultConfiguration() *CLIConfig {
    return &CLIConfig{
        RegistryPort:        8080,
        RegistryHost:        "localhost",
        DbPath:             "./dev_registry.db",
        LogLevel:           "INFO",
        HealthCheckInterval: 30,
        AutoRestart:        true,
        WatchFiles:         true,
        DebugMode:          false,
        StartupTimeout:     30,
        ShutdownTimeout:    30,
        EnableBackground:   false,
        PidFile:            "./mcp_mesh_dev.pid",
    }
}

func loadFromEnvironment(config *CLIConfig) {
    // Registry settings
    if val := os.Getenv("MCP_MESH_REGISTRY_PORT"); val != "" {
        if port, err := strconv.Atoi(val); err == nil {
            config.RegistryPort = port
        }
    }
    
    if val := os.Getenv("MCP_MESH_REGISTRY_HOST"); val != "" {
        config.RegistryHost = val
    }
    
    // Database settings
    if val := os.Getenv("MCP_MESH_DB_PATH"); val != "" {
        config.DbPath = val
    }
    
    // Logging settings
    if val := os.Getenv("MCP_MESH_LOG_LEVEL"); val != "" {
        config.LogLevel = val
    }
    
    // Health monitoring
    if val := os.Getenv("MCP_MESH_HEALTH_CHECK_INTERVAL"); val != "" {
        if interval, err := strconv.Atoi(val); err == nil {
            config.HealthCheckInterval = interval
        }
    }
    
    // Development settings
    if val := os.Getenv("MCP_MESH_AUTO_RESTART"); val != "" {
        config.AutoRestart = parseBoolEnv(val)
    }
    
    if val := os.Getenv("MCP_MESH_WATCH_FILES"); val != "" {
        config.WatchFiles = parseBoolEnv(val)
    }
    
    if val := os.Getenv("MCP_MESH_DEBUG_MODE"); val != "" {
        config.DebugMode = parseBoolEnv(val)
    }
    
    // Timeout settings
    if val := os.Getenv("MCP_MESH_STARTUP_TIMEOUT"); val != "" {
        if timeout, err := strconv.Atoi(val); err == nil {
            config.StartupTimeout = timeout
        }
    }
    
    if val := os.Getenv("MCP_MESH_SHUTDOWN_TIMEOUT"); val != "" {
        if timeout, err := strconv.Atoi(val); err == nil {
            config.ShutdownTimeout = timeout
        }
    }
    
    // Background service settings
    if val := os.Getenv("MCP_MESH_ENABLE_BACKGROUND"); val != "" {
        config.EnableBackground = parseBoolEnv(val)
    }
    
    if val := os.Getenv("MCP_MESH_PID_FILE"); val != "" {
        config.PidFile = val
    }
}

func parseBoolEnv(val string) bool {
    switch strings.ToLower(val) {
    case "true", "1", "yes", "on":
        return true
    default:
        return false
    }
}

func loadFromConfigFile(config *CLIConfig) error {
    configPath := getConfigFilePath()
    
    // Check if config file exists
    if _, err := os.Stat(configPath); os.IsNotExist(err) {
        // Config file doesn't exist, use current values (from defaults + env)
        return nil
    }
    
    // Read config file
    data, err := ioutil.ReadFile(configPath)
    if err != nil {
        return fmt.Errorf("failed to read config file %s: %w", configPath, err)
    }
    
    // Parse JSON
    var fileConfig CLIConfig
    if err := json.Unmarshal(data, &fileConfig); err != nil {
        return fmt.Errorf("failed to parse config file %s: %w", configPath, err)
    }
    
    // Merge file config with current config (env vars + defaults)
    mergeConfigurations(config, &fileConfig)
    
    return nil
}

func mergeConfigurations(target *CLIConfig, source *CLIConfig) {
    // Only override non-zero values from file config
    if source.RegistryPort != 0 {
        target.RegistryPort = source.RegistryPort
    }
    if source.RegistryHost != "" {
        target.RegistryHost = source.RegistryHost
    }
    if source.DbPath != "" {
        target.DbPath = source.DbPath
    }
    if source.LogLevel != "" {
        target.LogLevel = source.LogLevel
    }
    if source.HealthCheckInterval != 0 {
        target.HealthCheckInterval = source.HealthCheckInterval
    }
    // Boolean fields need special handling since false is a valid value
    target.AutoRestart = source.AutoRestart
    target.WatchFiles = source.WatchFiles
    target.DebugMode = source.DebugMode
    target.EnableBackground = source.EnableBackground
    
    if source.StartupTimeout != 0 {
        target.StartupTimeout = source.StartupTimeout
    }
    if source.ShutdownTimeout != 0 {
        target.ShutdownTimeout = source.ShutdownTimeout
    }
    if source.PidFile != "" {
        target.PidFile = source.PidFile
    }
}

func getConfigFilePath() string {
    homeDir, err := os.UserHomeDir()
    if err != nil {
        // Fallback to current directory
        return "./cli_config.json"
    }
    
    // Ensure .mcp_mesh directory exists
    configDir := filepath.Join(homeDir, ".mcp_mesh")
    if err := os.MkdirAll(configDir, 0755); err != nil {
        // Fallback to current directory
        return "./cli_config.json"
    }
    
    return filepath.Join(configDir, "cli_config.json")
}

func saveConfiguration(config *CLIConfig) error {
    configPath := getConfigFilePath()
    
    // Ensure directory exists
    dir := filepath.Dir(configPath)
    if err := os.MkdirAll(dir, 0755); err != nil {
        return fmt.Errorf("failed to create config directory %s: %w", dir, err)
    }
    
    // Marshal configuration to JSON
    data, err := json.MarshalIndent(config, "", "  ")
    if err != nil {
        return fmt.Errorf("failed to marshal configuration: %w", err)
    }
    
    // Write to file
    if err := ioutil.WriteFile(configPath, data, 0644); err != nil {
        return fmt.Errorf("failed to write config file %s: %w", configPath, err)
    }
    
    return nil
}

// Apply CLI flags to configuration (called from command handlers)
func ApplyCliFlags(config *CLIConfig, cmd *cobra.Command) {
    // Registry settings
    if cmd.Flags().Changed("registry-port") {
        if val, err := cmd.Flags().GetInt("registry-port"); err == nil {
            config.RegistryPort = val
        }
    }
    
    if cmd.Flags().Changed("registry-host") {
        if val, err := cmd.Flags().GetString("registry-host"); err == nil {
            config.RegistryHost = val
        }
    }
    
    if cmd.Flags().Changed("db-path") {
        if val, err := cmd.Flags().GetString("db-path"); err == nil {
            config.DbPath = val
        }
    }
    
    if cmd.Flags().Changed("log-level") {
        if val, err := cmd.Flags().GetString("log-level"); err == nil {
            config.LogLevel = val
        }
    }
    
    // Continue for all CLI flags...
}
```

## Success Criteria
- [ ] **CRITICAL**: Configuration system with file, environment, and CLI precedence works identically
- [ ] **CRITICAL**: Configuration file loading and saving matches Python implementation exactly
- [ ] **CRITICAL**: Environment variable handling identical to Python version
- [ ] **CRITICAL**: Configuration directory creation and file permissions preserved
- [ ] **CRITICAL**: JSON parsing and error handling matches Python behavior
- [ ] **CRITICAL**: Default value initialization identical to Python CLI