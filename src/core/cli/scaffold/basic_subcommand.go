package scaffold

import (
	"fmt"

	"github.com/spf13/cobra"
)

// newScaffoldBasicCommand builds `meshctl scaffold basic`.
//
// It is the explicit subcommand form of the previous
// `meshctl scaffold --agent-type tool` / default template invocation: it
// generates a plain @mesh.agent skeleton (no LLM, no A2A bridging) in the
// chosen runtime.
//
// Introduced in #957 (fix 1) alongside the removal of the legacy
// `--agent-type` flag form.
func newScaffoldBasicCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "basic",
		Short: "Generate a basic @mesh.agent skeleton",
		Long: `Generate a basic MCP Mesh agent (no LLM, no A2A bridging).

This is the explicit subcommand replacement for the old
'meshctl scaffold --agent-type tool' form.

Examples:
  # Default runtime (Python)
  meshctl scaffold basic --name my-agent

  # TypeScript
  meshctl scaffold basic --name my-agent --lang typescript

  # Java
  meshctl scaffold basic --name my-agent --lang java --port 8090

  # Preview without writing files
  meshctl scaffold basic --name my-agent --dry-run`,
		RunE: runScaffoldBasic,
	}

	cmd.Flags().StringP("name", "n", "",
		"Agent name (required)")
	cmd.Flags().StringP("lang", "l", "python",
		fmt.Sprintf("Language runtime: %v", supportedLanguages))
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	cmd.Flags().String("description", "", "Agent description")
	cmd.Flags().String("package", "",
		"Java package name (default: com.example.<agent-name>)")
	cmd.Flags().Bool("dry-run", false, "Preview generated files without creating them")
	// --no-interactive is registered for v1.4.1 script compatibility.
	// TODO: wire to actual prompt-suppression once interactive prompts are added.
	cmd.Flags().Bool("no-interactive", false, "Disable interactive prompts (for scripting)")

	return cmd
}

// runScaffoldBasic executes the `basic` subcommand.
func runScaffoldBasic(cmd *cobra.Command, _ []string) error {
	name, _ := cmd.Flags().GetString("name")
	lang, _ := cmd.Flags().GetString("lang")
	output, _ := cmd.Flags().GetString("output")
	port, _ := cmd.Flags().GetInt("port")
	description, _ := cmd.Flags().GetString("description")
	javaPackage, _ := cmd.Flags().GetString("package")
	dryRun, _ := cmd.Flags().GetBool("dry-run")

	if name == "" {
		return fmt.Errorf("--name is required")
	}

	language := NormalizeLanguage(lang)
	if !IsValidLanguage(language) {
		return fmt.Errorf("unsupported language: %s (supported: %v)", lang, supportedLanguages)
	}

	// Auto-increment port if --port wasn't explicitly set (issue #957 fix 2).
	port = AutoAssignScaffoldPort(cmd, port, output, name)

	ctx := &ScaffoldContext{
		Name:        name,
		Description: description,
		Language:    language,
		OutputDir:   output,
		Port:        port,
		AgentType:   "tool",
		Template:    "basic",
		JavaPackage: javaPackage,
		Cmd:         cmd,
		DryRun:      dryRun,
	}

	provider := NewStaticProvider()
	if err := provider.Validate(ctx); err != nil {
		return err
	}
	return provider.Execute(ctx)
}

// AttachBasicSubcommand registers `meshctl scaffold basic` onto the
// scaffold root command. Called from cli.NewScaffoldCommand.
func AttachBasicSubcommand(parent *cobra.Command) {
	parent.AddCommand(newScaffoldBasicCommand())
}
