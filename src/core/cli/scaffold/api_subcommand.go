package scaffold

import (
	"fmt"

	"github.com/spf13/cobra"
)

// newScaffoldAPICommand builds `meshctl scaffold api`.
//
// It scaffolds a non-mesh HTTP API server (FastAPI / Express / Spring
// Boot) that consumes mesh capabilities via dependency injection:
//   - Python: @mesh.route on FastAPI handlers
//   - TypeScript: Express middleware that wires McpMeshTool proxies
//   - Java: Spring Boot starter that injects mesh capabilities
//
// Different from the `basic` subcommand, which produces a mesh-native
// MCP agent. This subcommand produces an HTTP gateway/API server whose
// routes call into the mesh.
//
// The --agent-type api form was removed in PR #958 during the
// subcommand migration; this subcommand restores the capability via the
// canonical subcommand UX (issue #1005).
func newScaffoldAPICommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "api",
		Short: "Generate an HTTP gateway agent (FastAPI / Express / Spring Boot) that consumes mesh capabilities",
		Long: `Generate a non-mesh HTTP API server that consumes mesh capabilities via
dependency injection.

Unlike 'meshctl scaffold basic' (which generates a mesh-native MCP
agent), this subcommand emits an HTTP gateway whose routes resolve
mesh capabilities at request time:

  - Python:     FastAPI app with @mesh.route handlers
  - TypeScript: Express app with mesh middleware
  - Java:       Spring Boot app with mesh starter

The generated app registers as a consumer (Type: API) on the mesh
control plane; it does not implement the MCP protocol itself.

Examples:
  # Python FastAPI gateway with @mesh.route
  meshctl scaffold api --name gateway --lang python

  # TypeScript Express gateway
  meshctl scaffold api --name gateway --lang typescript

  # Java Spring Boot gateway
  meshctl scaffold api --name gateway --lang java

  # Preview without writing files
  meshctl scaffold api --name gateway --dry-run`,
		RunE: runScaffoldAPI,
	}

	cmd.Flags().StringP("name", "n", "",
		"Agent name (required)")
	cmd.Flags().StringP("lang", "l", "python",
		fmt.Sprintf("Language runtime: %v", supportedLanguages))
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the API gateway")
	cmd.Flags().String("description", "", "Agent description")
	cmd.Flags().String("package", "",
		"Java package name (default: com.example.<agent-name>)")
	cmd.Flags().StringSlice("tags", nil, "Tags for discovery (comma-separated)")
	cmd.Flags().Bool("dry-run", false, "Preview generated files without creating them")
	// --no-interactive is registered for v1.4.1 script compatibility.
	// TODO: wire to actual prompt-suppression once interactive prompts are added.
	cmd.Flags().Bool("no-interactive", false, "Disable interactive prompts (for scripting)")

	return cmd
}

// runScaffoldAPI executes the `api` subcommand.
func runScaffoldAPI(cmd *cobra.Command, _ []string) error {
	name, _ := cmd.Flags().GetString("name")
	lang, _ := cmd.Flags().GetString("lang")
	output, _ := cmd.Flags().GetString("output")
	port, _ := cmd.Flags().GetInt("port")
	description, _ := cmd.Flags().GetString("description")
	javaPackage, _ := cmd.Flags().GetString("package")
	tags, _ := cmd.Flags().GetStringSlice("tags")
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
		AgentType:   "api",
		Template:    "api",
		Tags:        tags,
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

// AttachAPISubcommand registers `meshctl scaffold api` onto the
// scaffold root command. Called from cli.NewScaffoldCommand.
//
// Reintroduced in #1005 after the --agent-type api form was removed in
// #958 without a subcommand replacement. The 3 template trees
// (python/api, typescript/api, java/api) were left orphaned in the
// repo; this hooks them back up via the canonical subcommand UX.
func AttachAPISubcommand(parent *cobra.Command) {
	parent.AddCommand(newScaffoldAPICommand())
}
