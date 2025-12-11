package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"mcp-mesh/src/core/cli"
	"mcp-mesh/src/core/cli/man"
	"mcp-mesh/src/core/cli/scaffold"
)

// version is injected at build time via ldflags
var version = "dev"

var rootCmd = &cobra.Command{
	Use:   "meshctl",
	Short: "MCP Mesh Control CLI",
	Long: `Control CLI for MCP Mesh to start, stop, and manage MCP agents with mesh runtime capabilities.

This CLI provides commands to manage MCP agents with distributed mesh networking and service discovery.`,
}

func init() {
	// Set embedded templates for scaffold command
	scaffold.SetEmbeddedTemplates(EmbeddedTemplates)
}

func main() {
	// Set version from build-time injection
	rootCmd.Version = version

	// Add all subcommands
	rootCmd.AddCommand(cli.NewStartCommand())
	rootCmd.AddCommand(cli.NewListCommand())
	rootCmd.AddCommand(cli.NewCallCommand())
	rootCmd.AddCommand(cli.NewStatusCommand())
	rootCmd.AddCommand(cli.NewConfigCommand())
	rootCmd.AddCommand(cli.NewScaffoldCommand())
	rootCmd.AddCommand(man.NewManCommand())

	// Execute the root command
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
