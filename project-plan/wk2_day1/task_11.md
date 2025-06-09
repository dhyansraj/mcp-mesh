# Task 11: Configuration Management System (30 minutes)

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
**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI configuration management functionality.

**Reference Preservation**:
- Keep ALL Python CLI configuration code as reference during migration
- Test EVERY existing configuration command and subcommand
- Maintain IDENTICAL behavior for configuration management (`config` with all subcommands)
- Preserve ALL configuration validation and error handling

**Implementation Validation**:
- Each Go configuration command must pass Python CLI behavior tests
- Configuration outputs must match Python implementation exactly
- File handling must be identical to Python version

## Objective
Implement comprehensive configuration management system (`config` command with all subcommands) maintaining identical behavior to Python

## Reference
`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/config.py` directory

## Detailed Implementation

### 5.1: Implement comprehensive configuration management system
```go
func NewConfigCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "config",
        Short: "Manage CLI configuration",
        Long:  "Manage MCP Mesh CLI configuration with show, set, reset, path, and save operations",
    }
    
    cmd.AddCommand(NewConfigShowCommand())
    cmd.AddCommand(NewConfigSetCommand())
    cmd.AddCommand(NewConfigResetCommand())
    cmd.AddCommand(NewConfigPathCommand())
    cmd.AddCommand(NewConfigSaveCommand())
    
    return cmd
}

func NewConfigShowCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "show",
        Short: "Show current configuration",
        Long:  "Display the current MCP Mesh CLI configuration values",
        RunE:  configShow,
    }
    
    cmd.Flags().String("format", "yaml", "Output format (yaml/json)")
    
    return cmd
}

func NewConfigSetCommand() *cobra.Command {
    return &cobra.Command{
        Use:   "set [key] [value]",
        Short: "Set configuration value",
        Long:  "Set a specific configuration key to a new value",
        Args:  cobra.ExactArgs(2),
        RunE:  configSet,
    }
}

func NewConfigResetCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "reset",
        Short: "Reset configuration to defaults",
        Long:  "Reset all configuration values to their default settings",
        RunE:  configReset,
    }
    
    cmd.Flags().Bool("confirm", false, "Skip confirmation prompt")
    
    return cmd
}

func NewConfigPathCommand() *cobra.Command {
    return &cobra.Command{
        Use:   "path",
        Short: "Show configuration file path",
        Long:  "Display the path to the MCP Mesh CLI configuration file",
        RunE:  configPath,
    }
}

func NewConfigSaveCommand() *cobra.Command {
    return &cobra.Command{
        Use:   "save",
        Short: "Save current configuration as defaults",
        Long:  "Save the current configuration state as default values",
        RunE:  configSave,
    }
}

// Implementation functions
func configShow(cmd *cobra.Command, args []string) error {
    format, _ := cmd.Flags().GetString("format")
    
    config, err := LoadConfiguration()
    if err != nil {
        return fmt.Errorf("failed to load configuration: %w", err)
    }
    
    switch format {
    case "json":
        return outputConfigAsJSON(config)
    case "yaml":
        return outputConfigAsYAML(config)
    default:
        return fmt.Errorf("unsupported format: %s", format)
    }
}

func configSet(cmd *cobra.Command, args []string) error {
    key := args[0]
    value := args[1]
    
    // Validate key exists
    if !isValidConfigKey(key) {
        return fmt.Errorf("invalid configuration key: %s", key)
    }
    
    // Load current config
    config, err := LoadConfiguration()
    if err != nil {
        return fmt.Errorf("failed to load configuration: %w", err)
    }
    
    // Update the value
    if err := setConfigValue(config, key, value); err != nil {
        return fmt.Errorf("failed to set %s: %w", key, err)
    }
    
    // Save updated config
    if err := saveConfiguration(config); err != nil {
        return fmt.Errorf("failed to save configuration: %w", err)
    }
    
    fmt.Printf("Configuration updated: %s = %s\n", key, value)
    return nil
}

func configReset(cmd *cobra.Command, args []string) error {
    confirm, _ := cmd.Flags().GetBool("confirm")
    
    if !confirm {
        fmt.Print("This will reset all configuration to defaults. Continue? (y/N): ")
        var response string
        fmt.Scanln(&response)
        if response != "y" && response != "Y" {
            fmt.Println("Reset cancelled.")
            return nil
        }
    }
    
    // Create default configuration
    defaultConfig := createDefaultConfiguration()
    
    // Save default config
    if err := saveConfiguration(defaultConfig); err != nil {
        return fmt.Errorf("failed to save default configuration: %w", err)
    }
    
    fmt.Println("Configuration reset to defaults.")
    return nil
}

func configPath(cmd *cobra.Command, args []string) error {
    configPath := getConfigFilePath()
    fmt.Println(configPath)
    return nil
}

func configSave(cmd *cobra.Command, args []string) error {
    config, err := LoadConfiguration()
    if err != nil {
        return fmt.Errorf("failed to load current configuration: %w", err)
    }
    
    if err := saveConfiguration(config); err != nil {
        return fmt.Errorf("failed to save configuration: %w", err)
    }
    
    fmt.Println("Configuration saved as defaults.")
    return nil
}

// Helper functions
func isValidConfigKey(key string) bool {
    validKeys := map[string]bool{
        "registry_port":         true,
        "registry_host":         true,
        "db_path":              true,
        "log_level":            true,
        "health_check_interval": true,
        "auto_restart":         true,
        "watch_files":          true,
        "debug_mode":           true,
        "startup_timeout":      true,
        "shutdown_timeout":     true,
        "enable_background":    true,
        "pid_file":             true,
    }
    
    return validKeys[key]
}

func setConfigValue(config *CLIConfig, key, value string) error {
    switch key {
    case "registry_port":
        port, err := strconv.Atoi(value)
        if err != nil {
            return fmt.Errorf("invalid port number: %s", value)
        }
        config.RegistryPort = port
    case "registry_host":
        config.RegistryHost = value
    case "db_path":
        config.DbPath = value
    case "log_level":
        config.LogLevel = value
    case "health_check_interval":
        interval, err := strconv.Atoi(value)
        if err != nil {
            return fmt.Errorf("invalid interval: %s", value)
        }
        config.HealthCheckInterval = interval
    // Add more cases for other configuration fields...
    default:
        return fmt.Errorf("unknown configuration key: %s", key)
    }
    
    return nil
}

func outputConfigAsJSON(config *CLIConfig) error {
    data, err := json.MarshalIndent(config, "", "  ")
    if err != nil {
        return err
    }
    
    fmt.Println(string(data))
    return nil
}

func outputConfigAsYAML(config *CLIConfig) error {
    // Simple YAML-like output for configuration
    fmt.Printf("registry_port: %d\n", config.RegistryPort)
    fmt.Printf("registry_host: %s\n", config.RegistryHost)
    fmt.Printf("db_path: %s\n", config.DbPath)
    fmt.Printf("log_level: %s\n", config.LogLevel)
    fmt.Printf("health_check_interval: %d\n", config.HealthCheckInterval)
    fmt.Printf("auto_restart: %t\n", config.AutoRestart)
    fmt.Printf("watch_files: %t\n", config.WatchFiles)
    fmt.Printf("debug_mode: %t\n", config.DebugMode)
    fmt.Printf("startup_timeout: %d\n", config.StartupTimeout)
    fmt.Printf("shutdown_timeout: %d\n", config.ShutdownTimeout)
    fmt.Printf("enable_background: %t\n", config.EnableBackground)
    fmt.Printf("pid_file: %s\n", config.PidFile)
    
    return nil
}
```

## Success Criteria
- [ ] **CRITICAL**: Complete configuration management system (`config` with all subcommands)
- [ ] **CRITICAL**: All configuration subcommands work identically to Python CLI
- [ ] **CRITICAL**: Configuration validation and error handling matches Python
- [ ] **CRITICAL**: Output formats (JSON/YAML) match Python implementation
- [ ] **CRITICAL**: Configuration key validation identical to Python version
- [ ] **CRITICAL**: Help text and usage information matches Python CLI