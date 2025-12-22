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
  meshctl scaffold --list-modes

  # Generate docker-compose.yml for all agents in directory
  meshctl scaffold --compose

  # Generate docker-compose with observability stack (redis, tempo, grafana)
  meshctl scaffold --compose --observability

  # Generate docker-compose with custom project name
  meshctl scaffold --compose --project-name my-project

  # Preview generated code without creating files
  meshctl scaffold --name my-agent --agent-type tool --dry-run

Documentation:
  For SDK reference and decorator documentation, see:
    meshctl man decorators    # @mesh.tool, @mesh.llm, @mesh.agent, etc.
    meshctl man llm           # LLM integration guide
    meshctl man deployment    # Docker and Kubernetes deployment
    meshctl man --list        # All available topics

Infrastructure:
  Docker Images:
    mcpmesh/registry:0.7        - Registry service
    mcpmesh/python-runtime:0.7  - Python agent runtime (has mcp-mesh SDK)

  Helm Charts (for Kubernetes - OCI registry, no helm repo add needed):
    oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core   - Registry + PostgreSQL + observability
    oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent  - Deploy individual agents`,
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
	cmd.Flags().Bool("dry-run", false, "Preview generated code without creating files")

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

	// Docker-compose generation flags
	cmd.Flags().Bool("compose", false, "Generate docker-compose.yml for all agents in directory")
	cmd.Flags().Bool("observability", false, "Include observability stack (redis, tempo, grafana) in docker-compose")
	cmd.Flags().String("project-name", "", "Docker compose project name (default: directory name)")
	cmd.Flags().Bool("force", false, "Force regenerate all agent configurations (overwrites existing agent services)")

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

	// Check if generating docker-compose
	compose, _ := cmd.Flags().GetBool("compose")
	if compose {
		return runComposeGeneration(cmd)
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
		// Check for add-tool mode
		addTool, _ := cmd.Flags().GetString("add-tool")
		name, _ := cmd.Flags().GetString("name")
		noInteractive, _ := cmd.Flags().GetBool("no-interactive")
		toolType, _ := cmd.Flags().GetString("tool-type")

		if addTool != "" {
			// Add-tool mode: require agent name
			if name == "" {
				return fmt.Errorf("--name is required when using --add-tool; specify the agent to add the tool to")
			}

			// Run interactive mode for add-tool if tool-type is not specified
			if toolType == "" && !noInteractive && isInteractiveTerminal() {
				ctx, err = runAddToolInteractiveMode(cmd, name, addTool)
				if err != nil {
					return err
				}
			} else {
				// Use CLI flags for add-tool
				ctx, err = loadFromFlags(cmd)
				if err != nil {
					return err
				}
			}
		} else if name == "" && !noInteractive && isInteractiveTerminal() {
			// Run interactive mode for creating new agents
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

	// Get output dir for checking existing agents
	output, _ := cmd.Flags().GetString("output")

	result, err := scaffold.RunInteractiveScaffold(output)
	if err != nil {
		return nil, fmt.Errorf("interactive scaffold failed: %w", err)
	}

	var ctx *scaffold.ScaffoldContext

	if result.IsAddTool {
		// User wants to add a tool to existing agent
		ctx = scaffold.ContextFromAddToolInteractive(result.AddToolConfig, result.AgentName)
	} else {
		// Creating a new agent
		ctx = scaffold.ContextFromInteractive(result.Config)
	}

	// Override output dir if provided via CLI
	if output != "." {
		ctx.OutputDir = output
	}

	ctx.Cmd = cmd
	ctx.IsInteractive = true
	return ctx, nil
}

// runAddToolInteractiveMode runs the interactive wizard for adding a tool
func runAddToolInteractiveMode(cmd *cobra.Command, agentName, toolName string) (*scaffold.ScaffoldContext, error) {
	cmd.Println("Add Tool to MCP Mesh Agent")
	cmd.Println("==========================")
	cmd.Printf("Agent: %s\n", agentName)
	cmd.Printf("Tool: %s\n", toolName)
	cmd.Println()

	addToolConfig, err := scaffold.RunAddToolInteractive(toolName)
	if err != nil {
		return nil, fmt.Errorf("interactive add-tool failed: %w", err)
	}

	ctx := scaffold.ContextFromAddToolInteractive(addToolConfig, agentName)

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

	// Get tool flags (for new agent or add-tool mode)
	addTool, _ := cmd.Flags().GetString("add-tool")
	toolName, _ := cmd.Flags().GetString("tool-name")
	toolDescription, _ := cmd.Flags().GetString("tool-description")
	toolType, _ := cmd.Flags().GetString("tool-type")
	dryRun, _ := cmd.Flags().GetBool("dry-run")

	// If --add-tool is provided, it specifies the tool name
	// Otherwise use --tool-name for new agent creation
	if addTool != "" {
		toolName = addTool
	}

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
		AddTool:             addTool != "",
		ToolName:            toolName,
		ToolDescription:     toolDescription,
		ToolType:            toolType,
		Cmd:                 cmd,
		DryRun:              dryRun,
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

// runComposeGeneration handles the --compose flag to generate docker-compose.yml
func runComposeGeneration(cmd *cobra.Command) error {
	output, _ := cmd.Flags().GetString("output")
	observability, _ := cmd.Flags().GetBool("observability")
	projectName, _ := cmd.Flags().GetString("project-name")
	force, _ := cmd.Flags().GetBool("force")

	cmd.Println("Scanning for agents...")

	// Scan for agents in the output directory
	agents, err := scaffold.ScanForAgents(output)
	if err != nil {
		return fmt.Errorf("failed to scan for agents: %w", err)
	}

	if len(agents) == 0 {
		return fmt.Errorf("no agents found in %s; create agents first with 'meshctl scaffold --name <agent-name>'", output)
	}

	cmd.Printf("Found %d agent(s):\n", len(agents))
	for _, agent := range agents {
		cmd.Printf("  - %s (port %d) in %s/\n", agent.Name, agent.Port, agent.Dir)
	}
	cmd.Println()

	// Build compose configuration
	config := &scaffold.ComposeConfig{
		Agents:        agents,
		Observability: observability,
		ProjectName:   projectName,
		NetworkName:   "",
		Force:         force,
	}

	// Generate docker-compose.yml
	result, err := scaffold.GenerateDockerCompose(config, output)
	if err != nil {
		return fmt.Errorf("failed to generate docker-compose.yml: %w", err)
	}

	// Display results based on what happened
	if result.WasMerged {
		if len(result.AddedAgents) > 0 {
			cmd.Printf("Updated docker-compose.yml in %s\n", output)
			cmd.Println()
			cmd.Println("New agents added:")
			for _, name := range result.AddedAgents {
				for _, agent := range agents {
					if agent.Name == name {
						cmd.Printf("  - %s (%d)\n", agent.Name, agent.Port)
						break
					}
				}
			}
		} else {
			cmd.Printf("docker-compose.yml in %s is already up to date\n", output)
		}
		if len(result.SkippedAgents) > 0 {
			cmd.Println()
			cmd.Println("Existing agents preserved (use --force to regenerate):")
			for _, name := range result.SkippedAgents {
				cmd.Printf("  - %s\n", name)
			}
		}
	} else {
		cmd.Printf("Successfully generated docker-compose.yml in %s\n", output)
		cmd.Println()
		cmd.Println("Services included:")
		cmd.Println("  - postgres (5432)")
		cmd.Println("  - registry (8000)")
		if observability {
			cmd.Println("  - redis (6379)")
			cmd.Println("  - tempo (3200, 4317)")
			cmd.Println("  - grafana (3000)")
		}
		for _, agent := range agents {
			cmd.Printf("  - %s (%d)\n", agent.Name, agent.Port)
		}
	}
	cmd.Println()
	cmd.Println("To start all services:")
	cmd.Println("  docker compose up -d")

	return nil
}
