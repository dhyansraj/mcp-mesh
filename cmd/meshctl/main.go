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

Build polyglot agent networks in Python, Java, and TypeScript.

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
	rootCmd.AddCommand(cli.NewLogsCommand()) // Issue #362
	rootCmd.AddCommand(cli.NewListCommand())
	rootCmd.AddCommand(cli.NewCallCommand())
	rootCmd.AddCommand(cli.NewStatusCommand())
	rootCmd.AddCommand(cli.NewConfigCommand())
	rootCmd.AddCommand(cli.NewScaffoldCommand())
	rootCmd.AddCommand(cli.NewTraceCommand())  // Issue #310
	rootCmd.AddCommand(cli.NewAuditCommand())  // Issue #836
	rootCmd.AddCommand(cli.NewSchemaCommand()) // Issue #547
	rootCmd.AddCommand(cli.NewEntityCommand())
	rootCmd.AddCommand(man.NewManCommand())

	// Suppress the usage block on runtime/business errors. Flag-parse
	// errors still show usage because cobra prints it directly before
	// returning the error (SilenceUsage only affects RunE returns).
	// We also silence cobra's automatic error print so we can format it
	// ourselves below. See issue #957 (fix 4).
	applySilenceFlags(rootCmd)

	// Execute the root command
	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}

// applySilenceFlags walks the command tree and sets SilenceErrors on every
// node so main() can format errors uniformly. SilenceUsage is left at the
// cobra default (false) so flag-parse errors still print the usage block —
// that's the one case where the usage dump is genuinely useful.
//
// To stop usage from showing on RunE/business errors, every long-running
// command in this codebase that returns errors from RunE should also set
// cmd.SilenceUsage = true on itself when the error is a runtime/business
// error. The simpler path used here: set SilenceUsage in each command's
// PersistentPreRunE so RunE errors never carry usage. Because cobra resets
// SilenceUsage between subcommand calls, we apply it via Pre-run rather
// than via the static field.
//
// See issue #957 (fix 4).
func applySilenceFlags(cmd *cobra.Command) {
	cmd.SilenceErrors = true

	// Chain a PersistentPreRunE that sets SilenceUsage at runtime, AFTER
	// flag parsing has succeeded. This way:
	//   - flag-parse errors happen BEFORE this runs -> SilenceUsage stays
	//     false -> cobra prints usage (the desired UX for "you used the
	//     flag wrong").
	//   - RunE/business errors happen AFTER this runs -> SilenceUsage is
	//     true -> cobra suppresses usage (the desired UX for runtime
	//     errors like "agent not found").
	existing := cmd.PersistentPreRunE
	cmd.PersistentPreRunE = func(c *cobra.Command, args []string) error {
		c.SilenceUsage = true
		if existing != nil {
			return existing(c, args)
		}
		return nil
	}

	for _, c := range cmd.Commands() {
		applySilenceFlags(c)
	}
}
