package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"mcp-mesh/src/core/cli"
)

var rootCmd = &cobra.Command{
	Use:   "mcp-mesh-dev",
	Short: "MCP Mesh Development CLI - Go implementation",
	Long: `Development CLI for MCP Mesh with identical functionality to Python version.

This CLI provides commands to start, stop, and manage MCP agents with mesh runtime capabilities.
It maintains 100% compatibility with the original Python CLI while providing improved performance.`,
	Version: "1.0.0-alpha",
}

func main() {
	// Add all subcommands
	rootCmd.AddCommand(cli.NewStartCommand())
	rootCmd.AddCommand(cli.NewListCommand())
	rootCmd.AddCommand(cli.NewStopCommand())
	rootCmd.AddCommand(cli.NewStatusCommand())
	rootCmd.AddCommand(cli.NewLogsCommand())
	rootCmd.AddCommand(cli.NewRestartCommand())
	rootCmd.AddCommand(cli.NewConfigCommand())

	// Add new process management commands
	rootCmd.AddCommand(cli.NewMonitorCommand())
	rootCmd.AddCommand(cli.NewStatsCommand())
	rootCmd.AddCommand(cli.NewLogAggregatorCommand())

	// Add workflow testing command
	rootCmd.AddCommand(cli.NewWorkflowTestCommand())

	// Execute the root command
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
