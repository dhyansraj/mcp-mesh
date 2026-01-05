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
	Short: "MCP Mesh - Framework for building MCP agents",
	Long: `MCP Mesh - Framework for building MCP agents with automatic service discovery and dependency injection.

Scaffold agents from templates, run them locally or in containers. Agents discover each other
and inject dependencies automatically—no central orchestrator or manual wiring needed.`,
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
	rootCmd.AddCommand(cli.NewStopCommand()) // Issue #364
	rootCmd.AddCommand(cli.NewListCommand())
	rootCmd.AddCommand(cli.NewCallCommand())
	rootCmd.AddCommand(cli.NewStatusCommand())
	rootCmd.AddCommand(cli.NewConfigCommand())
	rootCmd.AddCommand(cli.NewScaffoldCommand())
	rootCmd.AddCommand(cli.NewTraceCommand()) // Issue #310
	rootCmd.AddCommand(man.NewManCommand())

	// Execute the root command
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
