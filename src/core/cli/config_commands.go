package cli

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v2"
)

// NewConfigCommand creates the config command with subcommands
func NewConfigCommand() *cobra.Command {
	configCmd := &cobra.Command{
		Use:   "config",
		Short: "Manage MCP Mesh configuration",
		Long: `Manage MCP Mesh configuration settings.

The configuration is stored in ~/.mcp_mesh/cli_config.json and can be
managed through various subcommands.

Examples:
  meshctl config show              # Show current configuration
  meshctl config set registry_port 9090  # Set configuration value
  meshctl config reset             # Reset to defaults`,
	}

	// Add subcommands
	configCmd.AddCommand(newConfigShowCommand())
	configCmd.AddCommand(newConfigSetCommand())
	configCmd.AddCommand(newConfigResetCommand())
	configCmd.AddCommand(newConfigPathCommand())
	configCmd.AddCommand(newConfigSaveCommand())

	return configCmd
}

func newConfigShowCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "show",
		Short: "Show current configuration",
		Long: `Show the current configuration settings.

The configuration is loaded from environment variables, config file, and defaults.

Examples:
  meshctl config show              # Show in default format (YAML)
  meshctl config show --format json # Show in JSON format`,
		RunE: runConfigShowCommand,
	}

	cmd.Flags().String("format", "yaml", "Output format [yaml, json]")

	return cmd
}

func newConfigSetCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "set KEY VALUE",
		Short: "Set configuration value",
		Long: `Set a configuration value and save it to the config file.

Valid configuration keys:
  registry_port           - Registry service port (integer)
  registry_host           - Registry service host (string)
  db_path                 - Database file path (string)
  log_level               - Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  health_check_interval   - Health check interval in seconds (integer)
  debug_mode              - Debug mode flag (true, false)
  startup_timeout         - Startup timeout in seconds (integer)
  shutdown_timeout        - Shutdown timeout in seconds (integer)
  enable_background       - Background mode flag (true, false)
  pid_file                - PID file path (string)

Examples:
  meshctl config set registry_port 9090
  meshctl config set log_level DEBUG
  meshctl config set debug_mode true`,
		Args: cobra.ExactArgs(2),
		RunE: runConfigSetCommand,
	}

	return cmd
}

func newConfigResetCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "reset",
		Short: "Reset configuration to defaults",
		Long: `Reset the configuration to default values.

This will overwrite the current config file with default settings.
Environment variables will still override these defaults.

Examples:
  meshctl config reset`,
		RunE: runConfigResetCommand,
	}

	return cmd
}

func newConfigPathCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "path",
		Short: "Show configuration file path",
		Long: `Show the path to the configuration file.

Examples:
  meshctl config path`,
		RunE: runConfigPathCommand,
	}

	return cmd
}

func newConfigSaveCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "save",
		Short: "Save current configuration as defaults",
		Long: `Save the current effective configuration (including environment variables)
as the default configuration in the config file.

This is useful for persisting environment-based settings.

Examples:
  meshctl config save`,
		RunE: runConfigSaveCommand,
	}

	return cmd
}

func runConfigShowCommand(cmd *cobra.Command, args []string) error {
	// Load current configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Get format flag
	format, _ := cmd.Flags().GetString("format")

	switch strings.ToLower(format) {
	case "json":
		data, err := json.MarshalIndent(config, "", "  ")
		if err != nil {
			return fmt.Errorf("failed to marshal JSON: %w", err)
		}
		fmt.Println(string(data))

	case "yaml":
		data, err := yaml.Marshal(config)
		if err != nil {
			return fmt.Errorf("failed to marshal YAML: %w", err)
		}
		fmt.Print(string(data))

	default:
		return fmt.Errorf("invalid format: %s (must be 'json' or 'yaml')", format)
	}

	return nil
}

func runConfigSetCommand(cmd *cobra.Command, args []string) error {
	key := args[0]
	value := args[1]

	// Load current configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Set the value based on the key
	if err := setConfigValue(config, key, value); err != nil {
		return err
	}

	// Save the updated configuration
	if err := SaveConfig(config); err != nil {
		return fmt.Errorf("failed to save configuration: %w", err)
	}

	fmt.Printf("Configuration updated: %s = %s\n", key, value)
	return nil
}

func runConfigResetCommand(cmd *cobra.Command, args []string) error {
	// Create default configuration
	config := DefaultConfig()

	// Save it
	if err := SaveConfig(config); err != nil {
		return fmt.Errorf("failed to save default configuration: %w", err)
	}

	fmt.Println("Configuration reset to defaults")
	return nil
}

func runConfigPathCommand(cmd *cobra.Command, args []string) error {
	configPath := getConfigFilePath()
	fmt.Println(configPath)
	return nil
}

func runConfigSaveCommand(cmd *cobra.Command, args []string) error {
	// Load current effective configuration
	config, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("failed to load configuration: %w", err)
	}

	// Save it as the default
	if err := SaveConfig(config); err != nil {
		return fmt.Errorf("failed to save configuration: %w", err)
	}

	fmt.Println("Current configuration saved as defaults")
	return nil
}

func setConfigValue(config *CLIConfig, key, value string) error {
	switch key {
	case "registry_port":
		port, err := strconv.Atoi(value)
		if err != nil {
			return fmt.Errorf("invalid port number: %s", value)
		}
		if port < 1 || port > 65535 {
			return fmt.Errorf("port must be between 1 and 65535, got %d", port)
		}
		config.RegistryPort = port

	case "registry_host":
		if value == "" {
			return fmt.Errorf("registry host cannot be empty")
		}
		config.RegistryHost = value

	case "db_path":
		if value == "" {
			return fmt.Errorf("database path cannot be empty")
		}
		config.DBPath = value

	case "log_level":
		if !ValidateLogLevel(strings.ToUpper(value)) {
			return fmt.Errorf("invalid log level: %s (must be DEBUG, INFO, WARNING, ERROR, or CRITICAL)", value)
		}
		config.LogLevel = strings.ToUpper(value)

	case "health_check_interval":
		interval, err := strconv.Atoi(value)
		if err != nil {
			return fmt.Errorf("invalid health check interval: %s", value)
		}
		if interval < 1 {
			return fmt.Errorf("health check interval must be positive, got %d", interval)
		}
		config.HealthCheckInterval = interval

	case "debug_mode":
		config.DebugMode = strings.ToLower(value) == "true"

	case "startup_timeout":
		timeout, err := strconv.Atoi(value)
		if err != nil {
			return fmt.Errorf("invalid startup timeout: %s", value)
		}
		if timeout < 1 {
			return fmt.Errorf("startup timeout must be positive, got %d", timeout)
		}
		config.StartupTimeout = timeout

	case "shutdown_timeout":
		timeout, err := strconv.Atoi(value)
		if err != nil {
			return fmt.Errorf("invalid shutdown timeout: %s", value)
		}
		if timeout < 1 {
			return fmt.Errorf("shutdown timeout must be positive, got %d", timeout)
		}
		config.ShutdownTimeout = timeout

	case "enable_background":
		config.EnableBackground = strings.ToLower(value) == "true"

	case "pid_file":
		if value == "" {
			return fmt.Errorf("PID file path cannot be empty")
		}
		config.PIDFile = value

	default:
		return fmt.Errorf("unknown configuration key: %s", key)
	}

	return nil
}
