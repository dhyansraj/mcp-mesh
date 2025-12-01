package cli

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"mcp-mesh/src/core/cli/scaffold"
)

// NewScaffoldCommand creates the scaffold command for generating MCP Mesh agents.
// It supports multiple modes (providers) for generation: static templates and LLM-based.
func NewScaffoldCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "scaffold",
		Short: "Generate new MCP Mesh agent from template or LLM",
		Long: `Generate a new MCP Mesh agent using templates or LLM-based generation.

Supports three input modes:
  1. Interactive: Run without --name to enter interactive wizard
  2. CLI flags: Specify all options via command line
  3. Config file: Use --config to load from YAML file

Agent types:
  - tool: Basic tool agent with @mesh.tool decorator
  - llm-agent: LLM-powered agent with @mesh.llm decorator
  - llm-provider: Zero-code LLM provider with @mesh.llm_provider decorator

Examples:
  # Interactive mode (recommended for first-time users)
  meshctl scaffold

  # Generate basic tool agent
  meshctl scaffold --name my-agent --agent-type tool

  # Generate LLM-powered agent
  meshctl scaffold --name emotion-analyzer --agent-type llm-agent \
    --llm-selector openai --response-format json

  # Generate LLM provider
  meshctl scaffold --name claude-provider --agent-type llm-provider \
    --model anthropic/claude-sonnet-4-5

  # Generate from config file
  meshctl scaffold --config scaffold.yaml

  # List available modes
  meshctl scaffold --list-modes`,
		RunE: runScaffoldCommand,
	}

	// Common flags
	cmd.Flags().String("mode", "static", "Generation mode: static, llm")
	cmd.Flags().StringP("name", "n", "", "Agent name (required unless interactive or config)")
	cmd.Flags().StringP("lang", "l", "python", "Language: python (typescript, rust coming soon)")
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 9000, "HTTP port for the agent")
	cmd.Flags().String("description", "", "Agent description")
	cmd.Flags().Bool("list-modes", false, "List available scaffold modes")
	cmd.Flags().Bool("no-interactive", false, "Disable interactive mode (for scripting)")

	// Agent type flag
	cmd.Flags().String("agent-type", "", "Agent type: tool, llm-agent, llm-provider")

	// LLM-agent specific flags
	cmd.Flags().String("llm-selector", "claude", "LLM provider selector: claude, openai")
	cmd.Flags().Int("max-iterations", 1, "Max agentic loop iterations")
	cmd.Flags().String("system-prompt", "", "System prompt (inline or file:// path)")
	cmd.Flags().String("context-param", "ctx", "Context parameter name")
	cmd.Flags().String("response-format", "text", "Response format: text, json")

	// Tool filter flags for @mesh.llm
	cmd.Flags().String("filter", "", "Tool filter (JSON format, e.g., '{\"capability\":\"x\"}' or '[{\"tags\":[\"a\"]}]')")
	cmd.Flags().String("filter-mode", "all", "Filter mode: all, best_match, * (wildcard)")

	// LLM-provider specific flags
	cmd.Flags().String("model", "", "LiteLLM model (e.g., anthropic/claude-sonnet-4-5)")
	cmd.Flags().StringSlice("tags", nil, "Tags for discovery (comma-separated)")

	// Register provider-specific flags
	for _, name := range scaffold.DefaultRegistry.List() {
		provider, _ := scaffold.DefaultRegistry.Get(name)
		provider.RegisterFlags(cmd)
	}

	return cmd
}

func runScaffoldCommand(cmd *cobra.Command, args []string) error {
	// Check if listing modes
	listModes, _ := cmd.Flags().GetBool("list-modes")
	if listModes {
		return listScaffoldModes(cmd)
	}

	var ctx *scaffold.ScaffoldContext
	var err error

	// Check for config file first
	configFile, _ := cmd.Flags().GetString("config")
	if configFile != "" {
		ctx, err = loadScaffoldFromConfigFile(cmd, configFile)
		if err != nil {
			return err
		}
	} else {
		// Check if we should run interactive mode
		name, _ := cmd.Flags().GetString("name")
		noInteractive, _ := cmd.Flags().GetBool("no-interactive")
		if name == "" && !noInteractive && isInteractiveTerminal() {
			ctx, err = runInteractiveMode(cmd)
			if err != nil {
				return err
			}
		} else {
			// Use CLI flags
			ctx, err = loadFromFlags(cmd)
			if err != nil {
				return err
			}
		}
	}

	// Get the provider mode
	mode, _ := cmd.Flags().GetString("mode")

	// Get the provider
	provider, err := scaffold.DefaultRegistry.Get(mode)
	if err != nil {
		return fmt.Errorf("unknown mode %q: %w", mode, err)
	}

	// Validate
	if err := provider.Validate(ctx); err != nil {
		return err
	}

	// Execute
	return provider.Execute(ctx)
}

// loadScaffoldFromConfigFile loads scaffold configuration from a YAML file
func loadScaffoldFromConfigFile(cmd *cobra.Command, configPath string) (*scaffold.ScaffoldContext, error) {
	config, err := scaffold.LoadConfig(configPath)
	if err != nil {
		return nil, err
	}

	if err := config.Validate(); err != nil {
		return nil, err
	}

	ctx := scaffold.ContextFromConfig(config)

	// Override with CLI flags if provided
	output, _ := cmd.Flags().GetString("output")
	if output != "." {
		ctx.OutputDir = output
	}

	ctx.Cmd = cmd
	return ctx, nil
}

// runInteractiveMode runs the interactive scaffold wizard
func runInteractiveMode(cmd *cobra.Command) (*scaffold.ScaffoldContext, error) {
	cmd.Println("Welcome to MCP Mesh Scaffold Wizard")
	cmd.Println("====================================")
	cmd.Println()

	interactiveConfig, err := scaffold.RunInteractiveScaffold()
	if err != nil {
		return nil, fmt.Errorf("interactive scaffold failed: %w", err)
	}

	ctx := scaffold.ContextFromInteractive(interactiveConfig)

	// Override output dir if provided via CLI
	output, _ := cmd.Flags().GetString("output")
	if output != "." {
		ctx.OutputDir = output
	}

	ctx.Cmd = cmd
	return ctx, nil
}

// loadFromFlags loads scaffold configuration from CLI flags
func loadFromFlags(cmd *cobra.Command) (*scaffold.ScaffoldContext, error) {
	var err error

	// Get common flags
	name, _ := cmd.Flags().GetString("name")
	lang, _ := cmd.Flags().GetString("lang")
	output, _ := cmd.Flags().GetString("output")
	port, _ := cmd.Flags().GetInt("port")
	description, _ := cmd.Flags().GetString("description")

	// Get agent type
	agentType, _ := cmd.Flags().GetString("agent-type")

	// Get static provider flags
	template, _ := cmd.Flags().GetString("template")
	templateDir, _ := cmd.Flags().GetString("template-dir")
	configFile, _ := cmd.Flags().GetString("config")

	// Get LLM scaffold mode flags
	fromDoc, _ := cmd.Flags().GetString("from-doc")
	prompt, _ := cmd.Flags().GetString("prompt")
	llmProvider, _ := cmd.Flags().GetString("provider")
	validateCode, _ := cmd.Flags().GetBool("validate")

	// Get LLM-agent specific flags
	llmSelector, _ := cmd.Flags().GetString("llm-selector")
	maxIterations, _ := cmd.Flags().GetInt("max-iterations")
	systemPrompt, _ := cmd.Flags().GetString("system-prompt")
	contextParam, _ := cmd.Flags().GetString("context-param")
	responseFormat, _ := cmd.Flags().GetString("response-format")

	// Get tool filter flags
	filterStr, _ := cmd.Flags().GetString("filter")
	filterMode, _ := cmd.Flags().GetString("filter-mode")

	// Parse filter JSON
	var toolFilter []map[string]interface{}
	if filterStr != "" {
		toolFilter, err = parseToolFilter(filterStr)
		if err != nil {
			return nil, fmt.Errorf("invalid filter: %w", err)
		}
	}

	// Get LLM-provider specific flags
	model, _ := cmd.Flags().GetString("model")
	tags, _ := cmd.Flags().GetStringSlice("tags")

	// Set default provider tags based on selector
	var providerTags []string
	switch llmSelector {
	case "claude":
		providerTags = []string{"llm", "+claude"}
	case "openai":
		providerTags = []string{"llm", "+gpt"}
	}

	// Build context
	ctx := &scaffold.ScaffoldContext{
		Name:                name,
		Description:         description,
		Language:            lang,
		OutputDir:           output,
		Port:                port,
		AgentType:           agentType,
		Template:            template,
		TemplateDir:         templateDir,
		ConfigFile:          configFile,
		Tags:                tags,
		LLMProviderSelector: llmSelector,
		ProviderTags:        providerTags,
		MaxIterations:       maxIterations,
		SystemPrompt:        systemPrompt,
		ContextParam:        contextParam,
		ResponseFormat:      responseFormat,
		ToolFilter:          toolFilter,
		FilterMode:          filterMode,
		Model:               model,
		FromDoc:             fromDoc,
		Prompt:              prompt,
		LLMProvider:         llmProvider,
		ValidateCode:        validateCode,
		Cmd:                 cmd,
	}

	return ctx, nil
}

// parseToolFilter parses a filter string (JSON) into a slice of filter maps.
// Supports formats:
//   - Single object: {"capability": "x", "tags": ["a"]}
//   - Array: [{"capability": "x"}, {"tags": ["y"]}]
//   - Simple string: "capability_name" (converted to {"capability": "capability_name"})
func parseToolFilter(filterStr string) ([]map[string]interface{}, error) {
	filterStr = trimString(filterStr)
	if filterStr == "" {
		return nil, nil
	}

	// Try parsing as array first
	if filterStr[0] == '[' {
		var filters []map[string]interface{}
		if err := json.Unmarshal([]byte(filterStr), &filters); err != nil {
			return nil, fmt.Errorf("invalid filter array: %w", err)
		}
		return filters, nil
	}

	// Try parsing as single object
	if filterStr[0] == '{' {
		var filter map[string]interface{}
		if err := json.Unmarshal([]byte(filterStr), &filter); err != nil {
			return nil, fmt.Errorf("invalid filter object: %w", err)
		}
		return []map[string]interface{}{filter}, nil
	}

	// Treat as simple capability name
	return []map[string]interface{}{
		{"capability": filterStr},
	}, nil
}

// trimString removes leading/trailing whitespace
func trimString(s string) string {
	start := 0
	end := len(s)
	for start < end && (s[start] == ' ' || s[start] == '\t' || s[start] == '\n' || s[start] == '\r') {
		start++
	}
	for end > start && (s[end-1] == ' ' || s[end-1] == '\t' || s[end-1] == '\n' || s[end-1] == '\r') {
		end--
	}
	return s[start:end]
}

// isInteractiveTerminal checks if the current terminal supports interactive input
func isInteractiveTerminal() bool {
	// Check if stdin is a terminal
	fi, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return (fi.Mode() & os.ModeCharDevice) != 0
}

func listScaffoldModes(cmd *cobra.Command) error {
	cmd.Println("Available scaffold modes:")
	cmd.Println()

	for _, name := range scaffold.DefaultRegistry.List() {
		provider, _ := scaffold.DefaultRegistry.Get(name)
		cmd.Printf("  %-10s %s\n", name, provider.Description())
	}

	return nil
}
