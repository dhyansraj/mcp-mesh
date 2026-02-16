package cli

import (
	"encoding/json"
	"fmt"
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

Configuration is loaded from defaults, environment variables, and CLI flags.

Examples:
  meshctl config show              # Show current configuration
  meshctl config path              # Show configuration file path`,
	}

	// Add subcommands
	configCmd.AddCommand(newConfigShowCommand())
	configCmd.AddCommand(newConfigPathCommand())

	return configCmd
}

func newConfigShowCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "show",
		Short: "Show current configuration",
		Long: `Show the current configuration settings.

The configuration is loaded from defaults, environment variables, and CLI flags.

Examples:
  meshctl config show              # Show in default format (YAML)
  meshctl config show --format json # Show in JSON format`,
		RunE: runConfigShowCommand,
	}

	cmd.Flags().String("format", "yaml", "Output format [yaml, json]")

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

func runConfigPathCommand(cmd *cobra.Command, args []string) error {
	configPath := getConfigFilePath()
	fmt.Println(configPath)
	return nil
}
