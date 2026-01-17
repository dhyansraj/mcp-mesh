package man

import (
	"fmt"

	"github.com/spf13/cobra"
)

// NewManCommand creates the man command for meshctl.
func NewManCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "man [topic]",
		Short: "Show MCP Mesh manual pages",
		Long: `Show comprehensive MCP Mesh manual pages.

Use this command to learn about MCP Mesh concepts, decorators,
configuration, and best practices. Manual pages are embedded in the
binary and work offline.

The --raw flag outputs plain markdown, which is useful for:
- LLM assistants that need to understand MCP Mesh concepts
- Piping to other tools (grep, less, etc.)
- Copying to documentation

The --typescript flag shows TypeScript examples for topics that have
TypeScript variants (decorators, deployment, llm, testing, etc.).

Examples:
  meshctl man                       # Show architecture overview
  meshctl man decorators            # Learn about mesh decorators (Python)
  meshctl man decorators -t         # TypeScript decorator examples
  meshctl man deployment --typescript  # TypeScript deployment guide
  meshctl man llm -t                # TypeScript LLM integration
  meshctl man --list                # List all available topics
  meshctl man --raw decorators      # Raw markdown output (LLM-friendly)
  meshctl man --search "health"     # Search across all topics

Code Generation:
  To generate agent code from templates, use:
    meshctl scaffold              # Interactive wizard
    meshctl scaffold --dry-run    # Preview generated code
    meshctl scaffold --help       # All scaffold options`,
		RunE:              runManCommand,
		Args:              cobra.MaximumNArgs(1),
		ValidArgsFunction: completeManTopics,
	}

	cmd.Flags().BoolP("list", "l", false, "List all available topics")
	cmd.Flags().BoolP("raw", "r", false, "Output raw markdown (LLM-friendly)")
	cmd.Flags().StringP("search", "s", "", "Search across all topics")
	cmd.Flags().BoolP("typescript", "t", false, "Show TypeScript examples (for topics with TypeScript variants)")

	return cmd
}

// runManCommand executes the man command.
func runManCommand(cmd *cobra.Command, args []string) error {
	raw, _ := cmd.Flags().GetBool("raw")
	list, _ := cmd.Flags().GetBool("list")
	search, _ := cmd.Flags().GetString("search")
	typescript, _ := cmd.Flags().GetBool("typescript")

	renderer := NewRenderer(raw)

	// Handle --list flag
	if list {
		guides := ListGuides()
		fmt.Print(renderer.RenderList(guides))
		return nil
	}

	// Handle --search flag
	if search != "" {
		results, err := SearchGuides(search)
		if err != nil {
			return fmt.Errorf("search failed: %w", err)
		}
		fmt.Print(renderer.RenderSearchResults(search, results))
		return nil
	}

	// Get topic (default to "overview")
	topic := "overview"
	if len(args) > 0 {
		topic = args[0]
	}

	// Get and render guide (with optional TypeScript variant)
	guide, content, err := GetGuideWithVariant(topic, typescript)
	if err != nil {
		// Show suggestions for similar topics
		suggestions := SuggestSimilarTopics(topic)
		fmt.Print(renderer.RenderSuggestions(topic, suggestions))
		return nil
	}

	fmt.Print(renderer.Render(guide, content))
	return nil
}

// completeManTopics provides shell completion for man topics.
func completeManTopics(cmd *cobra.Command, args []string, toComplete string) ([]string, cobra.ShellCompDirective) {
	if len(args) != 0 {
		return nil, cobra.ShellCompDirectiveNoFileComp
	}

	var completions []string
	guides := ListGuides()
	for _, guide := range guides {
		completions = append(completions, guide.Name+"\t"+guide.Description)
		for _, alias := range guide.Aliases {
			completions = append(completions, alias+"\t"+guide.Description)
		}
	}

	return completions, cobra.ShellCompDirectiveNoFileComp
}
