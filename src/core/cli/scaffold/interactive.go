package scaffold

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/AlecAivazis/survey/v2"
)

// InteractiveConfig holds the configuration collected from interactive prompts
type InteractiveConfig struct {
	// Common fields
	AgentType   string
	Language    string
	Name        string
	Description string
	Port        int

	// Tool-specific (for basic tool agents)
	InitialToolName        string   // Name of the first tool to create
	InitialToolDescription string   // Description of the first tool
	Capabilities           []string
	Tags                   []string
	Dependencies           []string

	// LLM-agent specific
	LLMProviderSelector string   // "claude" or "openai"
	ProviderTags        []string // Tags for provider filtering
	MaxIterations       int
	SystemPrompt        string
	UsePromptFile       bool   // If true, create a prompt file
	ContextParam        string
	ResponseFormat      string // "text" or "json"

	// Tool filter for @mesh.llm (which tools the LLM can access)
	ToolFilter []map[string]interface{}
	FilterMode string // "all", "best_match", "*"

	// LLM-provider specific
	Model string // LiteLLM model string
}

// InteractiveResult holds the result of the interactive scaffold wizard
type InteractiveResult struct {
	Config    *InteractiveConfig // For new agent creation
	AgentName string             // Agent name
}

// RunInteractiveScaffold runs the interactive scaffold wizard
func RunInteractiveScaffold(outputDir string) (*InteractiveResult, error) {
	config := &InteractiveConfig{}
	result := &InteractiveResult{Config: config}

	// Step 1: Get agent name FIRST
	namePrompt := &survey.Input{
		Message: "Agent name (kebab-case, e.g., my-agent):",
	}
	if err := survey.AskOne(namePrompt, &config.Name, survey.WithValidator(survey.Required)); err != nil {
		return nil, fmt.Errorf("failed to get agent name: %w", err)
	}
	result.AgentName = config.Name

	// Step 2: Check if agent already exists
	agentDir := filepath.Join(outputDir, config.Name)
	mainPyPath := filepath.Join(agentDir, "main.py")
	tsIndexPath := filepath.Join(agentDir, "src", "index.ts")
	pomPath := filepath.Join(agentDir, "pom.xml")
	if fileExists(mainPyPath) || fileExists(tsIndexPath) || fileExists(pomPath) {
		return nil, fmt.Errorf("agent '%s' already exists at %s", config.Name, agentDir)
	}

	// Step 3: Agent doesn't exist - ask for agent type
	agentType := ""
	prompt := &survey.Select{
		Message: "What type of agent do you want to create?",
		Options: []string{
			"tool - Basic tool agent with capability registration",
			"llm-agent - LLM-powered agent with agentic loop",
			"llm-provider - Zero-code LLM provider (wraps LiteLLM)",
		},
		Default: "tool - Basic tool agent with capability registration",
	}
	if err := survey.AskOne(prompt, &agentType); err != nil {
		return nil, fmt.Errorf("failed to get agent type: %w", err)
	}
	config.AgentType = strings.Split(agentType, " - ")[0]

	// Step 3b: Select language
	langOption := ""
	langPrompt := &survey.Select{
		Message: "Which language/runtime?",
		Options: []string{
			"python - Python with FastMCP (default)",
			"typescript - TypeScript with @mcpmesh/sdk",
			"java - Java with Spring Boot",
		},
		Default: "python - Python with FastMCP (default)",
	}
	if err := survey.AskOne(langPrompt, &langOption); err != nil {
		return nil, fmt.Errorf("failed to get language: %w", err)
	}
	config.Language = strings.Split(langOption, " - ")[0]

	// Step 4: Get description
	descPrompt := &survey.Input{
		Message: "Agent description:",
		Default: fmt.Sprintf("MCP Mesh agent for %s", config.Name),
	}
	if err := survey.AskOne(descPrompt, &config.Description); err != nil {
		return nil, fmt.Errorf("failed to get description: %w", err)
	}

	// Step 4: Get port
	portStr := ""
	portPrompt := &survey.Input{
		Message: "HTTP port:",
		Default: "8080",
	}
	if err := survey.AskOne(portPrompt, &portStr); err != nil {
		return nil, fmt.Errorf("failed to get port: %w", err)
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return nil, fmt.Errorf("invalid port number: %w", err)
	}
	config.Port = port

	// Step 5: Agent-type-specific prompts
	switch config.AgentType {
	case "tool":
		if err := promptToolConfig(config); err != nil {
			return nil, err
		}
	case "llm-agent":
		if err := promptLLMAgentConfig(config); err != nil {
			return nil, err
		}
	case "llm-provider":
		if err := promptLLMProviderConfig(config); err != nil {
			return nil, err
		}
	}

	return result, nil
}

// promptToolConfig prompts for tool-specific configuration
func promptToolConfig(config *InteractiveConfig) error {
	// Get initial tool name
	toolNamePrompt := &survey.Input{
		Message: "Tool name (snake_case, e.g., process_data):",
	}
	if err := survey.AskOne(toolNamePrompt, &config.InitialToolName, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("failed to get tool name: %w", err)
	}

	// Get initial tool description
	toolDescPrompt := &survey.Input{
		Message: "Tool description:",
		Default: fmt.Sprintf("A tool for %s", config.InitialToolName),
	}
	if err := survey.AskOne(toolDescPrompt, &config.InitialToolDescription); err != nil {
		return fmt.Errorf("failed to get tool description: %w", err)
	}

	// Get tags
	tagsStr := ""
	tagsPrompt := &survey.Input{
		Message: "Tags (comma-separated, e.g., tools,utility):",
		Default: "tools",
	}
	if err := survey.AskOne(tagsPrompt, &tagsStr); err != nil {
		return fmt.Errorf("failed to get tags: %w", err)
	}
	if tagsStr != "" {
		config.Tags = splitAndTrim(tagsStr)
	}

	return nil
}

// promptLLMAgentConfig prompts for LLM-agent-specific configuration
func promptLLMAgentConfig(config *InteractiveConfig) error {
	// Select LLM provider
	providerSelector := ""
	providerPrompt := &survey.Select{
		Message: "Which LLM provider should this agent use?",
		Options: []string{
			"claude - Anthropic Claude (recommended)",
			"openai - OpenAI GPT models",
		},
		Default: "claude - Anthropic Claude (recommended)",
	}
	if err := survey.AskOne(providerPrompt, &providerSelector); err != nil {
		return fmt.Errorf("failed to get LLM provider: %w", err)
	}
	config.LLMProviderSelector = strings.Split(providerSelector, " - ")[0]

	// Set provider tags based on selection
	switch config.LLMProviderSelector {
	case "claude":
		config.ProviderTags = []string{"llm", "+claude"}
	case "openai":
		config.ProviderTags = []string{"llm", "+gpt"}
	}

	// Tool filter configuration
	if err := promptToolFilter(config); err != nil {
		return err
	}

	// Get max iterations
	iterStr := ""
	iterPrompt := &survey.Input{
		Message: "Max agentic loop iterations (1 for single-shot):",
		Default: "1",
	}
	if err := survey.AskOne(iterPrompt, &iterStr); err != nil {
		return fmt.Errorf("failed to get max iterations: %w", err)
	}
	maxIter, err := strconv.Atoi(iterStr)
	if err != nil {
		return fmt.Errorf("invalid max iterations: %w", err)
	}
	config.MaxIterations = maxIter

	// Prompt file or inline
	useFile := false
	filePrompt := &survey.Confirm{
		Message: "Create separate prompt file? (recommended for complex prompts)",
		Default: true,
	}
	if err := survey.AskOne(filePrompt, &useFile); err != nil {
		return fmt.Errorf("failed to get prompt file preference: %w", err)
	}
	config.UsePromptFile = useFile

	if !useFile {
		// Get inline system prompt
		promptInput := &survey.Multiline{
			Message: "System prompt (press Enter twice to finish):",
		}
		if err := survey.AskOne(promptInput, &config.SystemPrompt); err != nil {
			return fmt.Errorf("failed to get system prompt: %w", err)
		}
	}

	// Get context parameter name
	ctxPrompt := &survey.Input{
		Message: "Context parameter name:",
		Default: "ctx",
	}
	if err := survey.AskOne(ctxPrompt, &config.ContextParam); err != nil {
		return fmt.Errorf("failed to get context param: %w", err)
	}

	// Get response format
	respFormat := ""
	formatPrompt := &survey.Select{
		Message: "Response format:",
		Options: []string{
			"text - Plain text response",
			"json - Structured JSON response (with Pydantic model)",
		},
		Default: "text - Plain text response",
	}
	if err := survey.AskOne(formatPrompt, &respFormat); err != nil {
		return fmt.Errorf("failed to get response format: %w", err)
	}
	config.ResponseFormat = strings.Split(respFormat, " - ")[0]

	// Get tags
	tagsStr := ""
	tagsPrompt := &survey.Input{
		Message: "Tags (comma-separated, e.g., llm,analysis):",
		Default: "llm",
	}
	if err := survey.AskOne(tagsPrompt, &tagsStr); err != nil {
		return fmt.Errorf("failed to get tags: %w", err)
	}
	if tagsStr != "" {
		config.Tags = splitAndTrim(tagsStr)
	}

	return nil
}

// promptToolFilter prompts for tool filter configuration
func promptToolFilter(config *InteractiveConfig) error {
	// Ask about tool access
	filterModeOption := ""
	filterModePrompt := &survey.Select{
		Message: "Which tools should this LLM agent have access to?",
		Options: []string{
			"* - All available tools in the mesh (wildcard)",
			"none - No tools (LLM-only, no tool calling)",
			"filtered - Specific tools by capability/tags",
		},
		Default: "none - No tools (LLM-only, no tool calling)",
	}
	if err := survey.AskOne(filterModePrompt, &filterModeOption); err != nil {
		return fmt.Errorf("failed to get filter mode: %w", err)
	}

	filterMode := strings.Split(filterModeOption, " - ")[0]

	switch filterMode {
	case "*":
		config.FilterMode = "*"
		config.ToolFilter = nil
	case "none":
		config.FilterMode = "all"
		config.ToolFilter = nil
	case "filtered":
		config.FilterMode = "all"
		if err := promptFilterDetails(config); err != nil {
			return err
		}
	}

	return nil
}

// promptFilterDetails prompts for detailed filter configuration
func promptFilterDetails(config *InteractiveConfig) error {
	// Ask for filter type
	filterType := ""
	filterTypePrompt := &survey.Select{
		Message: "How do you want to filter tools?",
		Options: []string{
			"capability - By specific capability name(s)",
			"tags - By tag matching",
			"both - By capability and tags together",
		},
		Default: "capability - By specific capability name(s)",
	}
	if err := survey.AskOne(filterTypePrompt, &filterType); err != nil {
		return fmt.Errorf("failed to get filter type: %w", err)
	}
	filterType = strings.Split(filterType, " - ")[0]

	switch filterType {
	case "capability":
		// Get capabilities
		capStr := ""
		capPrompt := &survey.Input{
			Message: "Capabilities to filter (comma-separated, e.g., date_service,info):",
		}
		if err := survey.AskOne(capPrompt, &capStr, survey.WithValidator(survey.Required)); err != nil {
			return fmt.Errorf("failed to get capabilities: %w", err)
		}
		caps := splitAndTrim(capStr)
		config.ToolFilter = make([]map[string]interface{}, len(caps))
		for i, cap := range caps {
			config.ToolFilter[i] = map[string]interface{}{"capability": cap}
		}

	case "tags":
		// Get tags
		tagStr := ""
		tagPrompt := &survey.Input{
			Message: "Tags to filter (comma-separated, e.g., executor,tools):",
		}
		if err := survey.AskOne(tagPrompt, &tagStr, survey.WithValidator(survey.Required)); err != nil {
			return fmt.Errorf("failed to get filter tags: %w", err)
		}
		config.ToolFilter = []map[string]interface{}{
			{"tags": splitAndTrim(tagStr)},
		}

	case "both":
		// Get capability
		capStr := ""
		capPrompt := &survey.Input{
			Message: "Capability name:",
		}
		if err := survey.AskOne(capPrompt, &capStr, survey.WithValidator(survey.Required)); err != nil {
			return fmt.Errorf("failed to get capability: %w", err)
		}
		// Get tags
		tagStr := ""
		tagPrompt := &survey.Input{
			Message: "Tags (comma-separated):",
		}
		if err := survey.AskOne(tagPrompt, &tagStr); err != nil {
			return fmt.Errorf("failed to get filter tags: %w", err)
		}
		filter := map[string]interface{}{"capability": capStr}
		if tagStr != "" {
			filter["tags"] = splitAndTrim(tagStr)
		}
		config.ToolFilter = []map[string]interface{}{filter}
	}

	// Ask about filter mode
	filterModeType := ""
	filterModePrompt := &survey.Select{
		Message: "Filter matching mode:",
		Options: []string{
			"all - Include all tools matching any filter",
			"best_match - One tool per capability (best match)",
		},
		Default: "all - Include all tools matching any filter",
	}
	if err := survey.AskOne(filterModePrompt, &filterModeType); err != nil {
		return fmt.Errorf("failed to get filter mode: %w", err)
	}
	config.FilterMode = strings.Split(filterModeType, " - ")[0]

	return nil
}

// promptLLMProviderConfig prompts for LLM-provider-specific configuration
func promptLLMProviderConfig(config *InteractiveConfig) error {
	// Select model
	model := ""
	modelPrompt := &survey.Select{
		Message: "Which LLM model should this provider expose?",
		Options: []string{
			"anthropic/claude-sonnet-4-5 - Claude Sonnet 4.5 (latest)",
			"anthropic/claude-3-5-sonnet-20241022 - Claude 3.5 Sonnet",
			"anthropic/claude-3-5-haiku-20241022 - Claude 3.5 Haiku (fast)",
			"openai/gpt-4o - GPT-4o (recommended)",
			"openai/gpt-4o-mini - GPT-4o Mini (fast, cheap)",
			"openai/gpt-4-turbo - GPT-4 Turbo",
			"custom - Enter custom model string",
		},
		Default: "anthropic/claude-sonnet-4-5 - Claude Sonnet 4.5 (latest)",
	}
	if err := survey.AskOne(modelPrompt, &model); err != nil {
		return fmt.Errorf("failed to get model: %w", err)
	}

	if strings.HasPrefix(model, "custom") {
		// Get custom model string
		customPrompt := &survey.Input{
			Message: "Enter LiteLLM model string (e.g., anthropic/claude-3-opus):",
		}
		if err := survey.AskOne(customPrompt, &config.Model, survey.WithValidator(survey.Required)); err != nil {
			return fmt.Errorf("failed to get custom model: %w", err)
		}
	} else {
		config.Model = strings.Split(model, " - ")[0]
	}

	// Set tags based on model
	if strings.Contains(config.Model, "anthropic") {
		config.Tags = []string{"llm", "claude", "anthropic", "provider"}
	} else if strings.Contains(config.Model, "openai") {
		config.Tags = []string{"llm", "openai", "gpt", "provider"}
	} else {
		config.Tags = []string{"llm", "provider"}
	}

	// Allow adding custom tags
	addTags := false
	addTagsPrompt := &survey.Confirm{
		Message: "Add additional tags?",
		Default: false,
	}
	if err := survey.AskOne(addTagsPrompt, &addTags); err != nil {
		return fmt.Errorf("failed to get tags preference: %w", err)
	}

	if addTags {
		tagsStr := ""
		tagsPrompt := &survey.Input{
			Message: "Additional tags (comma-separated):",
		}
		if err := survey.AskOne(tagsPrompt, &tagsStr); err != nil {
			return fmt.Errorf("failed to get tags: %w", err)
		}
		if tagsStr != "" {
			config.Tags = append(config.Tags, splitAndTrim(tagsStr)...)
		}
	}

	return nil
}

// splitAndTrim splits a comma-separated string and trims whitespace
func splitAndTrim(s string) []string {
	parts := strings.Split(s, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		trimmed := strings.TrimSpace(p)
		if trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}

// fileExists checks if a file exists (local helper for interactive)
func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// ContextFromInteractive creates a ScaffoldContext from InteractiveConfig
func ContextFromInteractive(ic *InteractiveConfig) *ScaffoldContext {
	ctx := NewScaffoldContext()
	ctx.Name = ic.Name
	ctx.Description = ic.Description
	ctx.Port = ic.Port
	ctx.AgentType = ic.AgentType
	if ic.Language != "" {
		ctx.Language = ic.Language
	}
	ctx.Tags = ic.Tags
	ctx.Capabilities = ic.Capabilities
	ctx.Dependencies = ic.Dependencies

	// LLM-agent specific
	ctx.LLMProviderSelector = ic.LLMProviderSelector
	ctx.ProviderTags = ic.ProviderTags
	ctx.MaxIterations = ic.MaxIterations
	ctx.ContextParam = ic.ContextParam
	ctx.ResponseFormat = ic.ResponseFormat

	// Tool filter for @mesh.llm
	ctx.ToolFilter = ic.ToolFilter
	ctx.FilterMode = ic.FilterMode

	// Handle system prompt
	if ic.UsePromptFile {
		ctx.SystemPrompt = fmt.Sprintf("file://prompts/%s.jinja2", ic.Name)
	} else {
		ctx.SystemPrompt = ic.SystemPrompt
	}

	// LLM-provider specific
	ctx.Model = ic.Model

	// Map agent type to template and set type-specific fields
	switch ic.AgentType {
	case "tool":
		ctx.Template = "basic"
		// Set initial tool name/description for basic template
		ctx.ToolName = ic.InitialToolName
		ctx.ToolDescription = ic.InitialToolDescription
	case "llm-agent":
		ctx.Template = "llm-agent"
	case "llm-provider":
		ctx.Template = "llm-provider"
	}

	return ctx
}
