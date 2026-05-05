package scaffold

import (
	"fmt"

	"github.com/spf13/cobra"
)

// supportedLLMVendors are the vendor shortcuts accepted by `meshctl scaffold llm-provider --vendor`.
var supportedLLMVendors = []string{"claude", "openai", "gemini", "litellm-fallback"}

// supportedLLMRuntimes are the language runtimes accepted by `--runtime`.
// They mirror NormalizeLanguage but are documented as runtime-oriented for the subcommand UX.
var supportedLLMRuntimes = []string{"python", "typescript", "java"}

// vendorToModel maps a vendor shortcut to a default LiteLLM model string.
// Used by `meshctl scaffold llm-provider`.
var vendorToModel = map[string]string{
	"claude":           "anthropic/claude-sonnet-4-5",
	"openai":           "openai/gpt-4o",
	"gemini":           "gemini/gemini-1.5-pro",
	"litellm-fallback": "openai/gpt-4o",
}

// vendorToProviderTags maps a vendor shortcut to the discovery tags applied to the
// generated `@mesh.llm_provider` so consumers can pin to it via `+claude`, `+openai`, etc.
var vendorToProviderTags = map[string][]string{
	"claude":           {"llm", "claude", "anthropic", "provider", "+claude"},
	"openai":           {"llm", "openai", "gpt", "provider", "+openai"},
	"gemini":           {"llm", "gemini", "google", "provider", "+gemini"},
	"litellm-fallback": {"llm", "provider", "+fallback"},
}

// vendorToConsumerTag is the single discovery tag a consumer should request to pin a provider.
var vendorToConsumerTag = map[string]string{
	"claude":           "+claude",
	"openai":           "+openai",
	"gemini":           "+gemini",
	"litellm-fallback": "+fallback",
}

// IsValidLLMVendor reports whether v is a recognised vendor shortcut.
func IsValidLLMVendor(v string) bool {
	for _, x := range supportedLLMVendors {
		if x == v {
			return true
		}
	}
	return false
}

// SupportedLLMVendors returns the vendor shortcuts accepted by the scaffold subcommand.
func SupportedLLMVendors() []string {
	return supportedLLMVendors
}

// VendorToModel returns the default model string for a vendor shortcut.
// Returns the zero value if the vendor is unknown.
func VendorToModel(v string) string {
	return vendorToModel[v]
}

// VendorToProviderTags returns the discovery tags applied to a generated provider.
func VendorToProviderTags(v string) []string {
	return vendorToProviderTags[v]
}

// VendorToConsumerTag returns the single tag a consumer should request to pin to this vendor.
func VendorToConsumerTag(v string) string {
	return vendorToConsumerTag[v]
}

// runtimeStartCommand returns the language-appropriate command to run a generated agent.
func runtimeStartCommand(runtime, name string) string {
	switch NormalizeLanguage(runtime) {
	case "typescript":
		return fmt.Sprintf("cd %s && npm install && npx tsx src/index.ts", name)
	case "java":
		return fmt.Sprintf("cd %s && mvn spring-boot:run", name)
	default:
		return fmt.Sprintf("cd %s && python main.py", name)
	}
}

// newScaffoldLLMProviderCommand builds the `meshctl scaffold llm-provider` subcommand.
//
// It generates a ready-to-run @mesh.llm_provider agent for a given vendor + runtime,
// then prints a follow-up message pointing the user at `meshctl scaffold llm` for
// the consumer side.
func newScaffoldLLMProviderCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "llm-provider",
		Short: "Generate an @mesh.llm_provider agent for a specific vendor",
		Long: `Generate an @mesh.llm_provider agent that exposes a vendor-specific LLM via mesh.

Other agents can consume this provider through @mesh.llm with mesh delegation,
no API key handling required on the consumer side.

Examples:
  # Claude provider in Python (default runtime)
  meshctl scaffold llm-provider --vendor claude --name my-claude

  # OpenAI provider in TypeScript
  meshctl scaffold llm-provider --vendor openai --runtime typescript --name gpt-provider

  # Gemini provider in Java
  meshctl scaffold llm-provider --vendor gemini --runtime java --name gemini-provider`,
		RunE: runScaffoldLLMProvider,
	}

	cmd.Flags().String("vendor", "claude",
		fmt.Sprintf("LLM vendor: %v", supportedLLMVendors))
	cmd.Flags().String("runtime", "python",
		fmt.Sprintf("Language runtime: %v", supportedLLMRuntimes))
	cmd.Flags().StringP("name", "n", "",
		"Agent name (default: <vendor>-provider)")
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	cmd.Flags().String("description", "", "Agent description")
	cmd.Flags().String("model", "",
		"Override LiteLLM model string (default derived from --vendor)")
	cmd.Flags().String("package", "",
		"Java package name (default: com.example.<agent-name>)")
	cmd.Flags().Bool("dry-run", false, "Preview generated files without creating them")

	return cmd
}

// newScaffoldLLMCommand builds the `meshctl scaffold llm` subcommand.
//
// It generates a consumer agent that uses @mesh.llm with mesh-delegated provider
// resolution (no string-provider option), and prints a follow-up message pointing
// the user at `meshctl scaffold llm-provider` for the provider side.
func newScaffoldLLMCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "llm",
		Short: "Generate a consumer agent that uses an LLM via mesh delegation",
		Long: `Generate an LLM-consuming agent (@mesh.llm) that resolves its provider
through mesh delegation. The consumer does not embed an API key or vendor SDK -
it only declares which provider tag it needs.

Pair with 'meshctl scaffold llm-provider' to generate the matching provider agent.

Examples:
  # Default: pin to a Claude provider
  meshctl scaffold llm --runtime python --name my-consumer

  # Pin to an OpenAI provider
  meshctl scaffold llm --runtime typescript --vendor openai --name analyzer

  # Pin to a Gemini provider in Java
  meshctl scaffold llm --runtime java --vendor gemini --name reasoner`,
		RunE: runScaffoldLLMConsumer,
	}

	cmd.Flags().String("vendor", "claude",
		fmt.Sprintf("Pin consumer to a provider tag: %v", supportedLLMVendors))
	cmd.Flags().String("runtime", "python",
		fmt.Sprintf("Language runtime: %v", supportedLLMRuntimes))
	cmd.Flags().StringP("name", "n", "",
		"Agent name (default: llm-consumer)")
	cmd.Flags().StringP("output", "o", ".", "Output directory")
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	cmd.Flags().String("description", "", "Agent description")
	cmd.Flags().Int("max-iterations", 1, "Max agentic loop iterations")
	cmd.Flags().String("system-prompt", "", "System prompt (inline or file:// path)")
	cmd.Flags().String("response-format", "text", "Response format: text, json")
	cmd.Flags().String("package", "",
		"Java package name (default: com.example.<agent-name>)")
	cmd.Flags().Bool("dry-run", false, "Preview generated files without creating them")

	return cmd
}

// runScaffoldLLMProvider executes the llm-provider subcommand.
func runScaffoldLLMProvider(cmd *cobra.Command, _ []string) error {
	vendor, _ := cmd.Flags().GetString("vendor")
	runtime, _ := cmd.Flags().GetString("runtime")
	name, _ := cmd.Flags().GetString("name")
	output, _ := cmd.Flags().GetString("output")
	port, _ := cmd.Flags().GetInt("port")
	description, _ := cmd.Flags().GetString("description")
	model, _ := cmd.Flags().GetString("model")
	javaPackage, _ := cmd.Flags().GetString("package")
	dryRun, _ := cmd.Flags().GetBool("dry-run")

	if !IsValidLLMVendor(vendor) {
		return fmt.Errorf("unsupported vendor: %s (supported: %v)", vendor, supportedLLMVendors)
	}

	language := NormalizeLanguage(runtime)
	if !IsValidLanguage(language) {
		return fmt.Errorf("unsupported runtime: %s (supported: %v)", runtime, supportedLLMRuntimes)
	}

	if name == "" {
		name = vendor + "-provider"
	}
	if model == "" {
		model = VendorToModel(vendor)
	}
	if description == "" {
		description = fmt.Sprintf("LLM provider for %s (%s)", vendor, model)
	}

	ctx := &ScaffoldContext{
		Name:        name,
		Description: description,
		Language:    language,
		OutputDir:   output,
		Port:        port,
		AgentType:   "llm-provider",
		Template:    "llm-provider",
		Model:       model,
		Tags:        VendorToProviderTags(vendor),
		JavaPackage: javaPackage,
		Cmd:         cmd,
		DryRun:      dryRun,
	}

	provider := NewStaticProvider()
	if err := provider.Validate(ctx); err != nil {
		return err
	}
	if err := provider.Execute(ctx); err != nil {
		return err
	}

	if !dryRun {
		printLLMProviderFollowup(cmd, name, vendor, runtime)
	}
	return nil
}

// runScaffoldLLMConsumer executes the llm subcommand (consumer agent).
func runScaffoldLLMConsumer(cmd *cobra.Command, _ []string) error {
	vendor, _ := cmd.Flags().GetString("vendor")
	runtime, _ := cmd.Flags().GetString("runtime")
	name, _ := cmd.Flags().GetString("name")
	output, _ := cmd.Flags().GetString("output")
	port, _ := cmd.Flags().GetInt("port")
	description, _ := cmd.Flags().GetString("description")
	maxIter, _ := cmd.Flags().GetInt("max-iterations")
	systemPrompt, _ := cmd.Flags().GetString("system-prompt")
	responseFormat, _ := cmd.Flags().GetString("response-format")
	javaPackage, _ := cmd.Flags().GetString("package")
	dryRun, _ := cmd.Flags().GetBool("dry-run")

	if !IsValidLLMVendor(vendor) {
		return fmt.Errorf("unsupported vendor: %s (supported: %v)", vendor, supportedLLMVendors)
	}

	language := NormalizeLanguage(runtime)
	if !IsValidLanguage(language) {
		return fmt.Errorf("unsupported runtime: %s (supported: %v)", runtime, supportedLLMRuntimes)
	}

	if name == "" {
		name = "llm-consumer"
	}

	// Mesh-delegated provider: pin to the vendor's consumer tag.
	providerTags := []string{"llm", VendorToConsumerTag(vendor)}

	ctx := &ScaffoldContext{
		Name:                name,
		Description:         description,
		Language:            language,
		OutputDir:           output,
		Port:                port,
		AgentType:           "llm-agent",
		Template:            "llm-agent",
		LLMProviderSelector: vendor,
		ProviderTags:        providerTags,
		MaxIterations:       maxIter,
		SystemPrompt:        systemPrompt,
		ContextParam:        "ctx",
		ResponseFormat:      responseFormat,
		FilterMode:          "all",
		JavaPackage:         javaPackage,
		Cmd:                 cmd,
		DryRun:              dryRun,
	}

	provider := NewStaticProvider()
	if err := provider.Validate(ctx); err != nil {
		return err
	}
	if err := provider.Execute(ctx); err != nil {
		return err
	}

	if !dryRun {
		printLLMConsumerFollowup(cmd, name, vendor, runtime)
	}
	return nil
}

// printLLMProviderFollowup prints the provider-side follow-up after generation.
func printLLMProviderFollowup(cmd *cobra.Command, name, vendor, runtime string) {
	consumerTag := VendorToConsumerTag(vendor)
	cmd.Printf("\n──────────────────────────────────────────────────────────────\n")
	cmd.Printf("Provider agent created: ./%s/\n\n", name)
	cmd.Printf("To consume this provider from another agent, use:\n\n")
	cmd.Printf("  meshctl scaffold llm --runtime %s --vendor %s\n\n", NormalizeLanguage(runtime), vendor)
	cmd.Printf("Then in your consumer agent's @mesh.llm decorator:\n\n")
	cmd.Printf("  @mesh.llm(provider={\"capability\": \"llm\", \"tags\": [\"%s\"]})\n", consumerTag)
	cmd.Printf("  def my_agent(messages): ...\n\n")
	cmd.Printf("Run the provider:\n")
	cmd.Printf("  %s\n", runtimeStartCommand(runtime, name))
	cmd.Printf("──────────────────────────────────────────────────────────────\n")
}

// printLLMConsumerFollowup prints the consumer-side follow-up after generation.
func printLLMConsumerFollowup(cmd *cobra.Command, name, vendor, runtime string) {
	cmd.Printf("\n──────────────────────────────────────────────────────────────\n")
	cmd.Printf("Consumer agent created: ./%s/\n\n", name)
	cmd.Printf("To run this, you'll need an LLM provider agent reachable via mesh:\n\n")
	cmd.Printf("  meshctl scaffold llm-provider --vendor %s --runtime %s\n\n", vendor, NormalizeLanguage(runtime))
	cmd.Printf("Then start both agents and meshctl will resolve the provider for you.\n")
	cmd.Printf("──────────────────────────────────────────────────────────────\n")
}

// AttachLLMSubcommands registers the llm-provider and llm subcommands onto the
// scaffold root command. Called from cli.NewScaffoldCommand.
func AttachLLMSubcommands(parent *cobra.Command) {
	parent.AddCommand(newScaffoldLLMProviderCommand())
	parent.AddCommand(newScaffoldLLMCommand())
}
