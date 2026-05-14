package cli

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"
	"mcp-mesh/src/core/cli/scaffold"
)

// NewScaffoldCommand creates the scaffold command for generating MCP Mesh agents.
// It supports multiple modes (providers) for generation: static templates and LLM-based.
func NewScaffoldCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "scaffold",
		Short: "Generate new MCP Mesh agent from templates",
		Long: `Generate a new MCP Mesh agent using templates.

Subcommands (per agent type):
  basic         Plain @mesh.agent skeleton (no LLM, no A2A)
  llm           Consumer agent that uses an LLM via mesh delegation
  llm-provider  @mesh.llm_provider agent for a specific vendor
  a2a-consumer  Bridge an external A2A producer onto the mesh

Run 'meshctl scaffold <subcommand> --help' for per-subcommand flags.

Top-level (no subcommand) modes:
  Interactive wizard: Run with no flags (and a TTY) to enter the wizard
  Config file:        meshctl scaffold --config scaffold.yaml
  Compose generator:  meshctl scaffold --compose [--observability]
  List modes:         meshctl scaffold --list-modes

Examples:
  # Interactive mode (recommended for first-time users)
  meshctl scaffold

  # Generate basic tool agent
  meshctl scaffold basic --name my-agent

  # Generate LLM-powered agent (consumer)
  meshctl scaffold llm --name emotion-analyzer --vendor openai --response-format json

  # Generate LLM provider
  meshctl scaffold llm-provider --name claude-provider --vendor claude

  # Generate from config file
  meshctl scaffold --config scaffold.yaml

  # List available modes
  meshctl scaffold --list-modes

  # Generate docker-compose.yml for all agents in directory
  meshctl scaffold --compose

  # Generate docker-compose with observability stack (redis, tempo, grafana)
  meshctl scaffold --compose --observability

  # Generate standalone observability stack (redis, tempo, grafana)
  meshctl scaffold --observability

  # Generate docker-compose with custom project name
  meshctl scaffold --compose --project-name my-project

  # Preview generated code without creating files
  meshctl scaffold basic --name my-agent --dry-run

Documentation:
  For SDK reference and decorator documentation, see:
    meshctl man decorators    # @mesh.tool, @mesh.llm, @mesh.agent, etc.
    meshctl man llm           # LLM integration guide
    meshctl man deployment    # Docker and Kubernetes deployment
    meshctl man --list        # All available topics

Infrastructure:
  Docker Images:
    mcpmesh/registry:2.0.0-beta.3            - Registry service
    mcpmesh/python-runtime:2.0.0-beta.3      - Python agent runtime (has mcp-mesh SDK)
    mcpmesh/typescript-runtime:2.0.0-beta.3  - TypeScript agent runtime (has @mcpmesh/sdk)

  Helm Charts (for Kubernetes - OCI registry, no helm repo add needed):
    oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core   - Registry + PostgreSQL + observability
    oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-agent  - Deploy individual agents`,
		RunE: runScaffoldCommand,
	}

	// Deprecated alias: `--agent-type <X>` auto-routes to the equivalent
	// subcommand. Restored after PR #958 removed it outright — tsuite
	// integration tests still depend on the legacy form. Hidden so --help
	// only shows the canonical subcommand-based UX.
	cmd.Flags().String("agent-type", "",
		"DEPRECATED: use 'meshctl scaffold <subcommand>' instead (tool|llm-agent|llm-provider)")
	_ = cmd.Flags().MarkHidden("agent-type")

	// Common flags
	cmd.Flags().String("mode", "static", "Generation mode: static, llm")
	cmd.Flags().StringP("name", "n", "", "Agent name (required unless interactive or config)")
	cmd.Flags().StringP("lang", "l", "python", "Language: python, typescript, java (or py, ts, jv)")
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	cmd.Flags().String("description", "", "Agent description")
	cmd.Flags().Bool("list-modes", false, "List available scaffold modes")
	cmd.Flags().Bool("no-interactive", false, "Disable interactive mode (for scripting)")
	cmd.Flags().Bool("dry-run", false, "Preview generated code without creating files")
	cmd.Flags().String("package", "", "Java package name (default: com.example.<agent-name>)")

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

	// Attach `basic` subcommand (#957). Explicit replacement for the legacy
	// `--agent-type tool` form. Generates a plain @mesh.agent skeleton.
	scaffold.AttachBasicSubcommand(cmd)

	// Attach `llm-provider` and `llm` subcommands (#859).
	// These wrap the static template machinery with vendor + runtime shortcuts
	// and print follow-up messages cross-linking provider/consumer scaffolds.
	scaffold.AttachLLMSubcommands(cmd)

	// Attach `a2a-consumer` subcommand (#909). Fetches an external A2A
	// producer's /.well-known/agent.json and emits a runnable consumer
	// agent skeleton with one mesh capability per skill in the card.
	scaffold.AttachA2AConsumerSubcommand(cmd)

	return cmd
}

func runScaffoldCommand(cmd *cobra.Command, args []string) error {
	// Deprecated --agent-type routing: if the legacy alias is set, dispatch
	// to the equivalent subcommand. The flag is registered as hidden so the
	// canonical UX is `meshctl scaffold <subcommand>`; this branch only
	// exists for back-compat with scripts and the tsuite integration suite.
	if agentType, _ := cmd.Flags().GetString("agent-type"); agentType != "" {
		return routeDeprecatedAgentType(cmd, agentType, args)
	}

	// Check if listing modes
	listModes, _ := cmd.Flags().GetBool("list-modes")
	if listModes {
		return listScaffoldModes(cmd)
	}

	// Check if generating docker-compose
	compose, _ := cmd.Flags().GetBool("compose")
	observability, _ := cmd.Flags().GetBool("observability")
	if compose {
		return runComposeGeneration(cmd)
	}

	// Standalone observability: --observability without --compose
	if observability {
		return runObservabilityGeneration(cmd)
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
		name, _ := cmd.Flags().GetString("name")
		noInteractive, _ := cmd.Flags().GetBool("no-interactive")

		if name == "" && !noInteractive && isInteractiveTerminal() {
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

// agentTypeToSubcommand maps the legacy --agent-type value to the
// canonical subcommand name introduced by PR #958.
var agentTypeToSubcommand = map[string]string{
	"tool":         "basic",
	"llm-agent":    "llm",
	"llm-provider": "llm-provider",
}

// routeDeprecatedAgentType dispatches a `meshctl scaffold --agent-type X`
// invocation to the equivalent subcommand. Prints a stderr deprecation
// warning, rebuilds args without --agent-type, then invokes the
// subcommand's full Execute path (so its own flag parsing + RunE fire
// exactly as if the user had typed `meshctl scaffold <sub>` directly).
func routeDeprecatedAgentType(cmd *cobra.Command, agentType string, _ []string) error {
	// `api` was removed from the supported set in PR #958. There is no
	// drop-in replacement subcommand — HTTP gateway scaffolding is now
	// covered by deployment docs, not a scaffold template.
	if agentType == "api" {
		cmd.SilenceUsage = true
		return fmt.Errorf(
			"the 'api' agent type was removed; HTTP gateways are now built differently. " +
				"See `meshctl man deployment`")
	}

	subName, ok := agentTypeToSubcommand[agentType]
	if !ok {
		cmd.SilenceUsage = true
		return fmt.Errorf(
			"unknown --agent-type value '%s'; use one of: tool, llm-agent, llm-provider, "+
				"or use 'meshctl scaffold <subcommand>'", agentType)
	}

	fmt.Fprintf(cmd.ErrOrStderr(),
		"Warning: --agent-type is deprecated; use 'meshctl scaffold %s' instead "+
			"(mapping --agent-type=%s to 'scaffold %s'). "+
			"See 'meshctl scaffold --help'.\n",
		subName, agentType, subName)

	sub, _, err := cmd.Find([]string{subName})
	if err != nil || sub == nil || sub == cmd {
		return fmt.Errorf("internal error: subcommand %q not found", subName)
	}

	// The user invoked the parent cmd, so all flag values live on the
	// parent's FlagSet. Subcommands have a narrower (and sometimes
	// renamed) FlagSet of their own. Copy values across so the subcommand
	// RunE sees what it expects. Then dispatch the subcommand RunE
	// directly — calling sub.Execute() would walk back through the root
	// and re-enter this parent RunE, recursing infinitely.
	copyParentFlagsToSub(cmd, sub)
	if sub.RunE != nil {
		return sub.RunE(sub, nil)
	}
	if sub.Run != nil {
		sub.Run(sub, nil)
		return nil
	}
	return fmt.Errorf("internal error: subcommand %q has no Run function", subName)
}

// copyParentFlagsToSub copies values from the parent scaffold cmd to the
// equivalent flags on the subcommand. Handles direct-name matches plus
// the historical rename `--llm-selector` (parent) → `--vendor` (sub).
// Only copies flags the user actually set (via Changed), so subcommand
// defaults remain in place for unspecified flags.
func copyParentFlagsToSub(parent, sub *cobra.Command) {
	// 1:1 name matches — copy every parent flag that exists on sub by
	// the same name, when the user changed it.
	parent.Flags().Visit(func(f *pflag.Flag) {
		subFlag := sub.Flags().Lookup(f.Name)
		if subFlag == nil {
			return
		}
		// Slice values: f.Value.String() returns the bracketed form
		// "[a,b]" which Set re-parses as a single literal element. Use
		// the SliceValue extension to round-trip correctly.
		if parentSlice, ok := f.Value.(pflag.SliceValue); ok {
			if subSlice, ok := subFlag.Value.(pflag.SliceValue); ok {
				_ = subSlice.Replace(parentSlice.GetSlice())
				return
			}
		}
		_ = sub.Flags().Set(f.Name, f.Value.String())
	})

	// Renamed alias: parent's --llm-selector corresponds to the
	// subcommand's --vendor flag on both `llm` and `llm-provider`.
	if parent.Flags().Changed("llm-selector") {
		if subFlag := sub.Flags().Lookup("vendor"); subFlag != nil {
			val, _ := parent.Flags().GetString("llm-selector")
			_ = sub.Flags().Set("vendor", val)
		}
	}
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

	ctx := scaffold.ContextFromInteractive(result.Config)

	// Override output dir if provided via CLI
	if output != "." {
		ctx.OutputDir = output
	}

	ctx.Cmd = cmd
	ctx.IsInteractive = true
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

	// Auto-increment port when the user did not pass --port explicitly: scan
	// the output directory for previously-scaffolded agents and pick
	// max(detected_ports)+1. This keeps two `meshctl scaffold` calls in the
	// same directory from colliding on 8080. See issue #957 (fix 2).
	port = scaffold.AutoAssignScaffoldPort(cmd, port, output, name)

	// agent-type was removed in #957 (fix 1); subcommands (basic, llm,
	// llm-provider, a2a-consumer) are the canonical way to pick an agent
	// type now. Top-level scaffold without a subcommand defaults to "tool"
	// (basic template) for backward compatibility with `meshctl scaffold
	// --name X --template Y` invocations and interactive mode.
	agentType := ""

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

	// Get tool flags (for new agent creation)
	toolName, _ := cmd.Flags().GetString("tool-name")
	toolDescription, _ := cmd.Flags().GetString("tool-description")
	dryRun, _ := cmd.Flags().GetBool("dry-run")
	javaPackage, _ := cmd.Flags().GetString("package")

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
		ToolName:            toolName,
		ToolDescription:     toolDescription,
		Cmd:                 cmd,
		DryRun:              dryRun,
		JavaPackage:         javaPackage,
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
		if !observability {
			return fmt.Errorf("no agents found in %s; create agents first with 'meshctl scaffold --name <agent-name>'", output)
		}
		cmd.Println("No agents found, generating registry + observability stack only...")
		cmd.Println()
	} else {
		cmd.Printf("Found %d agent(s):\n", len(agents))
		for _, agent := range agents {
			cmd.Printf("  - %s (port %d) in %s/\n", agent.Name, agent.Port, agent.Dir)
		}
		cmd.Println()
	}

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

// runObservabilityGeneration handles the --observability flag (without --compose)
// to generate a standalone docker-compose.observability.yml with only the observability stack
func runObservabilityGeneration(cmd *cobra.Command) error {
	output, _ := cmd.Flags().GetString("output")
	projectName, _ := cmd.Flags().GetString("project-name")

	config := &scaffold.ComposeConfig{
		Agents:        nil,
		Observability: true,
		ProjectName:   projectName,
		NetworkName:   "",
	}

	if err := scaffold.GenerateObservabilityCompose(config, output); err != nil {
		return fmt.Errorf("failed to generate observability compose: %w", err)
	}

	cmd.Println("Generated docker-compose.observability.yml with Redis, Tempo, and Grafana")
	cmd.Println()
	cmd.Println("Services included:")
	cmd.Println("  - redis (6379)")
	cmd.Println("  - tempo (3200, 4317)")
	cmd.Println("  - grafana (3000)")
	cmd.Println()
	cmd.Println("Start with:")
	if output != "." {
		cmd.Printf("  docker compose -f %s/docker-compose.observability.yml up -d\n", output)
	} else {
		cmd.Println("  docker compose -f docker-compose.observability.yml up -d")
	}

	return nil
}
