package scaffold

import (
	"embed"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/AlecAivazis/survey/v2"
	"github.com/spf13/cobra"
)

// embeddedTemplates holds the embedded template filesystem.
// This is set by the main package via SetEmbeddedTemplates.
var embeddedTemplates embed.FS
var embeddedTemplatesSet bool

// SetEmbeddedTemplates sets the embedded templates filesystem.
// This should be called from main.go before using the scaffold command.
func SetEmbeddedTemplates(fs embed.FS) {
	embeddedTemplates = fs
	embeddedTemplatesSet = true
}

// supportedTemplates defines the templates available for static generation
var supportedTemplates = []string{"basic", "llm-agent", "llm-provider"}

// agentTypeToTemplate maps agent types to their corresponding template names
var agentTypeToTemplate = map[string]string{
	"tool":         "basic",
	"llm-agent":    "llm-agent",
	"llm-provider": "llm-provider",
}

// StaticProvider implements ScaffoldProvider for template-based generation.
// It uses gomplate to render templates with user-provided configuration.
type StaticProvider struct{}

// NewStaticProvider creates a new static template provider
func NewStaticProvider() *StaticProvider {
	return &StaticProvider{}
}

// Name returns the provider's unique identifier
func (p *StaticProvider) Name() string {
	return "static"
}

// Description returns a human-readable description of the provider
func (p *StaticProvider) Description() string {
	return "Generate from templates using gomplate"
}

// RegisterFlags adds static-specific flags to the command
func (p *StaticProvider) RegisterFlags(cmd *cobra.Command) {
	cmd.Flags().StringP("template", "t", "basic", "Template: basic, llm-agent, llm-provider")
	cmd.Flags().String("template-dir", "", "Custom template directory")
	cmd.Flags().String("config", "", "Config file (YAML) for complex scaffolding")
	cmd.Flags().String("add-tool", "", "Add a new tool to existing agent (requires agent name)")
	cmd.Flags().String("tool-name", "", "Tool name (for new agent or --add-tool)")
	cmd.Flags().String("tool-description", "", "Tool description (for new agent or --add-tool)")
	cmd.Flags().String("tool-type", "", "Tool type for --add-tool: mesh.tool (basic capability) or mesh.llm (LLM-powered)")
}

// Validate checks if the provided context is valid for static generation
func (p *StaticProvider) Validate(ctx *ScaffoldContext) error {
	// First validate common fields
	if err := ctx.Validate(); err != nil {
		return err
	}

	// Map agent type to template if specified
	if ctx.AgentType != "" {
		if template, ok := agentTypeToTemplate[ctx.AgentType]; ok {
			ctx.Template = template
		}
	}

	// Validate template
	if !IsValidTemplate(ctx.Template) {
		return fmt.Errorf("unsupported template: %s (supported: %v)", ctx.Template, supportedTemplates)
	}

	return nil
}

// toolSnippetTemplate is the embedded template for adding a new @mesh.tool
const toolSnippetTemplate = `@app.tool()
@mesh.tool(
    capability="{{ .ToolName }}",
    description="{{ .ToolDescription }}",
    tags={{ if .Tags }}{{ toJSON .Tags }}{{ else }}["tools"]{{ end }},
)
async def {{ .ToolName }}() -> str:
    """
    {{ .ToolDescription }}.

    Returns:
        Result string.
    """
    # TODO: Implement tool logic
    return "Not implemented"
`

// llmToolSnippetTemplate is the embedded template for adding a new @mesh.llm tool
const llmToolSnippetTemplate = `# ===== {{ toUpperSnakeCase .ToolName }} CONTEXT MODEL =====

class {{ toPascalCase .ToolName }}Context(BaseModel):
    """Context for {{ .ToolName }} LLM processing."""

    input_text: str = Field(..., description="Input text to process")
    # Add additional context fields as needed

{{ if eq .ResponseFormat "json" }}
# ===== {{ toUpperSnakeCase .ToolName }} RESPONSE MODEL =====

class {{ toPascalCase .ToolName }}Response(BaseModel):
    """Structured response from {{ .ToolName }}."""

    result: str = Field(..., description="Processing result")
    # Add additional response fields as needed
{{ end }}
# ===== {{ toUpperSnakeCase .ToolName }} LLM TOOL =====

@app.tool()
@mesh.llm(
    filter={{ if .ToolFilter }}{{ toJSON .ToolFilter }}{{ else }}None{{ end }},
    filter_mode="{{ default "all" .FilterMode }}",
    provider={"capability": "llm", "tags": {{ toJSON .ProviderTags }}},
    max_iterations={{ default 1 .MaxIterations }},
    system_prompt={{ if .SystemPromptIsFile }}"{{ .SystemPrompt }}"{{ else }}"""{{ default "You are an AI assistant. Process the input and provide a helpful response." .SystemPrompt }}"""{{ end }},
    context_param="{{ default "ctx" .ContextParam }}",
)
@mesh.tool(
    capability="{{ .ToolName }}",
    description="{{ default "LLM-powered tool" .ToolDescription }}",
    tags={{ if .Tags }}{{ toJSON .Tags }}{{ else }}["llm", "tools"]{{ end }},
)
def {{ toSnakeCase .ToolName }}(
    {{ default "ctx" .ContextParam }}: {{ toPascalCase .ToolName }}Context,
    llm: mesh.MeshLlmAgent = None,
){{ if eq .ResponseFormat "json" }} -> {{ toPascalCase .ToolName }}Response{{ else }} -> str{{ end }}:
    """
    {{ default "LLM-powered tool" .ToolDescription }}.

    Args:
        {{ default "ctx" .ContextParam }}: Context containing input data for processing
        llm: Injected LLM agent (provided by mesh)

    Returns:
        {{ if eq .ResponseFormat "json" }}Structured response with processing results{{ else }}Processing result as text{{ end }}
    """
    return llm("Process the input based on the context provided")
`

// DetectedAgentType represents the type of agent detected from existing code
type DetectedAgentType string

const (
	DetectedTool        DetectedAgentType = "tool"
	DetectedLLMAgent    DetectedAgentType = "llm-agent"
	DetectedLLMProvider DetectedAgentType = "llm-provider"
	DetectedUnknown     DetectedAgentType = "unknown"
)

// detectAgentType reads an existing agent file and determines the agent type
// by looking for characteristic decorators/functions.
// Supports both Python (.py) and TypeScript (.ts) files.
func detectAgentType(agentFilePath string) (DetectedAgentType, error) {
	content, err := os.ReadFile(agentFilePath)
	if err != nil {
		return DetectedUnknown, err
	}

	contentStr := string(content)

	// Python detection
	if strings.HasSuffix(agentFilePath, ".py") {
		// Check for @mesh.llm_provider first (most specific)
		if strings.Contains(contentStr, "@mesh.llm_provider") {
			return DetectedLLMProvider, nil
		}
		// Check for @mesh.llm decorator (indicates llm-agent or tool with llm tools)
		if strings.Contains(contentStr, "@mesh.llm(") {
			return DetectedLLMAgent, nil
		}
		// Check for @mesh.tool decorator (basic tool agent)
		if strings.Contains(contentStr, "@mesh.tool(") {
			return DetectedTool, nil
		}
		// Check for @mesh.agent (generic agent, treat as tool)
		if strings.Contains(contentStr, "@mesh.agent") {
			return DetectedTool, nil
		}
	}

	// TypeScript detection
	if strings.HasSuffix(agentFilePath, ".ts") || strings.HasSuffix(agentFilePath, ".js") {
		// Check for mesh.llmProvider first (most specific)
		if strings.Contains(contentStr, "mesh.llmProvider(") || strings.Contains(contentStr, "llmProvider(") {
			return DetectedLLMProvider, nil
		}
		// Check for mesh.llm function (indicates llm-agent)
		if strings.Contains(contentStr, "mesh.llm(") {
			return DetectedLLMAgent, nil
		}
		// Check for mesh.tool function (basic tool agent)
		if strings.Contains(contentStr, "mesh.tool(") {
			return DetectedTool, nil
		}
		// Check for mesh() call (generic agent, treat as tool)
		if strings.Contains(contentStr, "mesh(server") || strings.Contains(contentStr, "= mesh(") {
			return DetectedTool, nil
		}
	}

	return DetectedUnknown, nil
}

// getAgentEntryFile returns the entry file path for an agent based on language.
// Python uses main.py, TypeScript uses src/index.ts
func getAgentEntryFile(outputDir, language string) string {
	if language == "typescript" {
		return filepath.Join(outputDir, "src", "index.ts")
	}
	return filepath.Join(outputDir, "main.py")
}

// Execute performs the scaffold generation using templates.
func (p *StaticProvider) Execute(ctx *ScaffoldContext) error {
	// Create output directory: outputDir/agentName
	outputDir := filepath.Join(ctx.OutputDir, ctx.Name)

	// Check if this is add-tool mode
	if ctx.AddTool {
		return p.executeAddTool(ctx, outputDir)
	}

	// Handle dry-run mode - render and print without creating files
	if ctx.DryRun {
		return p.executeDryRun(ctx)
	}

	// Check if directory already exists (for safety - don't overwrite)
	// Check for both Python (main.py) and TypeScript (src/index.ts) entry files
	entryFile := getAgentEntryFile(outputDir, ctx.Language)
	if FileExists(entryFile) {
		// In interactive mode, ask if user wants to add a tool instead
		if ctx.IsInteractive {
			return p.handleExistingAgentInteractive(ctx, outputDir, entryFile)
		}

		// Non-interactive mode: return error
		if ctx.Cmd != nil {
			ctx.Cmd.Printf("Agent '%s' already exists at %s\n", ctx.Name, outputDir)
			ctx.Cmd.Printf("To add a new tool, use: meshctl scaffold --name %s --add-tool <tool-name>\n", ctx.Name)
		}
		return fmt.Errorf("agent already exists; use --add-tool to add tools to existing agent")
	}

	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	// Create template renderer
	renderer := NewTemplateRenderer()

	// Build template data
	data := TemplateDataFromContext(ctx)

	// Check if custom template directory is specified
	if ctx.TemplateDir != "" {
		// Use filesystem templates from custom directory
		templateSrcDir, err := p.getCustomTemplateDir(ctx)
		if err != nil {
			return err
		}
		if err := renderer.RenderDirectory(templateSrcDir, outputDir, data); err != nil {
			return fmt.Errorf("failed to render templates: %w", err)
		}
	} else if embeddedTemplatesSet {
		// Use embedded templates (default)
		embeddedPath := fmt.Sprintf("templates/%s/%s", ctx.Language, ctx.Template)
		if err := renderer.RenderEmbeddedDirectory(embeddedTemplates, embeddedPath, outputDir, data); err != nil {
			return fmt.Errorf("failed to render embedded templates: %w", err)
		}
	} else {
		// Fallback to filesystem templates (for development/testing)
		templateSrcDir, err := p.getBuiltinTemplateDir(ctx)
		if err != nil {
			return err
		}
		if err := renderer.RenderDirectory(templateSrcDir, outputDir, data); err != nil {
			return fmt.Errorf("failed to render templates: %w", err)
		}
	}

	// Print success message with generated files
	if ctx.Cmd != nil {
		ctx.Cmd.Printf("\n✅ Created agent '%s' in %s/\n\n", ctx.Name, outputDir)
		ctx.Cmd.Printf("Generated files:\n")
		printGeneratedFiles(ctx.Cmd, outputDir, ctx.Name)
		ctx.Cmd.Printf("\n")
		ctx.Cmd.Printf("Next steps:\n")
		if ctx.Language == "typescript" {
			ctx.Cmd.Printf("  cd %s && npm install\n", ctx.Name)
			ctx.Cmd.Printf("  meshctl start %s/src/index.ts\n", ctx.Name)
		} else {
			ctx.Cmd.Printf("  meshctl start %s/main.py\n", ctx.Name)
		}
		ctx.Cmd.Printf("\n")
		ctx.Cmd.Printf("For Docker/K8s deployment, see: meshctl man deployment\n")
	}

	return nil
}

// handleExistingAgentInteractive handles the case when agent already exists in interactive mode
func (p *StaticProvider) handleExistingAgentInteractive(ctx *ScaffoldContext, outputDir, entryFilePath string) error {
	if ctx.Cmd != nil {
		ctx.Cmd.Println()
		ctx.Cmd.Printf("⚠️  Agent '%s' already exists at %s\n", ctx.Name, outputDir)
		ctx.Cmd.Println()
	}

	// Detect agent type
	detectedType, err := detectAgentType(entryFilePath)
	if err != nil {
		return fmt.Errorf("failed to detect agent type: %w", err)
	}

	// If it's an llm-provider, we can't add tools
	if detectedType == DetectedLLMProvider {
		if ctx.Cmd != nil {
			ctx.Cmd.Println("This is an LLM provider agent which cannot have additional tools.")
		}
		return fmt.Errorf("cannot add tools to llm-provider agents")
	}

	// Ask if user wants to add a tool instead
	addTool := false
	confirmPrompt := &survey.Confirm{
		Message: "Would you like to add a new tool to this existing agent?",
		Default: true,
	}
	if err := survey.AskOne(confirmPrompt, &addTool); err != nil {
		return fmt.Errorf("prompt failed: %w", err)
	}

	if !addTool {
		return fmt.Errorf("agent already exists; operation cancelled")
	}

	// Get tool name
	toolName := ""
	namePrompt := &survey.Input{
		Message: "Tool name (snake_case, e.g., analyze_text):",
	}
	if err := survey.AskOne(namePrompt, &toolName, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("failed to get tool name: %w", err)
	}

	// Run the add-tool interactive wizard
	addToolConfig, err := RunAddToolInteractive(toolName)
	if err != nil {
		return fmt.Errorf("add-tool wizard failed: %w", err)
	}

	// Update context with add-tool configuration
	ctx.AddTool = true
	ctx.ToolName = addToolConfig.ToolName
	ctx.ToolDescription = addToolConfig.ToolDescription
	ctx.ToolType = addToolConfig.ToolType
	ctx.Tags = addToolConfig.Tags

	if addToolConfig.ToolType == "mesh.llm" {
		ctx.LLMProviderSelector = addToolConfig.LLMProviderSelector
		ctx.ProviderTags = addToolConfig.ProviderTags
		ctx.MaxIterations = addToolConfig.MaxIterations
		ctx.ContextParam = addToolConfig.ContextParam
		ctx.ResponseFormat = addToolConfig.ResponseFormat
		ctx.ToolFilter = addToolConfig.ToolFilter
		ctx.FilterMode = addToolConfig.FilterMode

		if addToolConfig.UsePromptFile {
			ctx.SystemPrompt = fmt.Sprintf("file://prompts/%s.jinja2", addToolConfig.ToolName)
			ctx.CreatePromptFile = true
		} else {
			ctx.SystemPrompt = addToolConfig.SystemPrompt
		}
	}

	// Execute add-tool
	return p.executeAddTool(ctx, outputDir)
}

// executeAddTool handles adding a new tool to an existing agent
func (p *StaticProvider) executeAddTool(ctx *ScaffoldContext, outputDir string) error {
	mainPyPath := filepath.Join(outputDir, "main.py")

	// Check if main.py exists
	if !FileExists(mainPyPath) {
		return fmt.Errorf("agent '%s' not found at %s; create it first with: meshctl scaffold %s", ctx.Name, outputDir, ctx.Name)
	}

	// Detect agent type from existing code
	detectedType, err := detectAgentType(mainPyPath)
	if err != nil {
		return fmt.Errorf("failed to detect agent type: %w", err)
	}

	// Reject adding tools to llm-provider agents
	if detectedType == DetectedLLMProvider {
		return fmt.Errorf("cannot add tools to llm-provider agents; LLM providers only expose the @mesh.llm_provider capability")
	}

	// Create template renderer
	renderer := NewTemplateRenderer()

	// Build template data for the tool using full context
	data := TemplateDataFromContext(ctx)

	// Set defaults
	if ctx.ToolDescription == "" {
		data["ToolDescription"] = fmt.Sprintf("A tool called %s", ctx.ToolName)
	}

	// Determine which template to use based on tool type
	var snippetTemplate string
	var toolTypeDisplay string

	var promptFilePath string

	switch ctx.ToolType {
	case "mesh.llm":
		snippetTemplate = llmToolSnippetTemplate
		toolTypeDisplay = "mesh.llm (LLM-powered)"

		// Ensure ProviderTags has a default if not set
		if ctx.ProviderTags == nil || len(ctx.ProviderTags) == 0 {
			switch ctx.LLMProviderSelector {
			case "openai":
				data["ProviderTags"] = []string{"llm", "+gpt"}
			default: // claude
				data["ProviderTags"] = []string{"llm", "+claude"}
			}
		}

		// Create prompt file if requested
		if ctx.CreatePromptFile {
			promptsDir := filepath.Join(outputDir, "prompts")
			if err := os.MkdirAll(promptsDir, 0755); err != nil {
				return fmt.Errorf("failed to create prompts directory: %w", err)
			}

			promptFilePath = filepath.Join(promptsDir, ctx.ToolName+".jinja2")
			promptContent := fmt.Sprintf(`You are an AI assistant for %s.

%s

Analyze the provided context and respond appropriately.

{# Available context variables: #}
{# {{ ctx.input_text }} - The input text to process #}
`, ctx.ToolName, ctx.ToolDescription)

			if err := os.WriteFile(promptFilePath, []byte(promptContent), 0644); err != nil {
				return fmt.Errorf("failed to create prompt file: %w", err)
			}
		}
	default: // "mesh.tool" or empty
		snippetTemplate = toolSnippetTemplate
		toolTypeDisplay = "mesh.tool (basic capability)"
	}

	// Append the tool to main.py
	appended, err := renderer.AppendToolToFile(mainPyPath, snippetTemplate, data)
	if err != nil {
		return fmt.Errorf("failed to add tool: %w", err)
	}

	if !appended {
		return fmt.Errorf("could not find insertion point in %s; ensure the file has '# ===== AGENT CONFIGURATION =====' marker", mainPyPath)
	}

	// Print success message
	if ctx.Cmd != nil {
		ctx.Cmd.Printf("Successfully added %s tool '%s' to agent '%s'\n", toolTypeDisplay, ctx.ToolName, ctx.Name)
		ctx.Cmd.Printf("  File: %s\n", mainPyPath)
		if ctx.ToolType == "mesh.llm" {
			ctx.Cmd.Printf("  Tool Type: LLM-powered (@mesh.llm + @mesh.tool)\n")
			ctx.Cmd.Printf("  LLM Provider: %s\n", ctx.LLMProviderSelector)
			ctx.Cmd.Printf("  Response Format: %s\n", ctx.ResponseFormat)
			if promptFilePath != "" {
				ctx.Cmd.Printf("  Prompt File: %s\n", promptFilePath)
			}
			ctx.Cmd.Println()
			ctx.Cmd.Printf("  NOTE: Ensure these imports are present in your main.py:\n")
			ctx.Cmd.Printf("    from pydantic import BaseModel, Field\n")
			ctx.Cmd.Println()
			if promptFilePath != "" {
				ctx.Cmd.Printf("  Don't forget to customize the prompt file and context model!\n")
			} else {
				ctx.Cmd.Printf("  Don't forget to customize the context model and system prompt!\n")
			}
		} else {
			ctx.Cmd.Printf("  Tool Type: Basic capability (@mesh.tool)\n")
			ctx.Cmd.Printf("  Don't forget to implement the tool logic!\n")
		}
	}

	return nil
}

// executeDryRun renders templates and prints them to stdout without creating files.
func (p *StaticProvider) executeDryRun(ctx *ScaffoldContext) error {
	// Create template renderer
	renderer := NewTemplateRenderer()

	// Build template data
	data := TemplateDataFromContext(ctx)

	// Use a temporary directory to render files
	tempDir, err := os.MkdirTemp("", "meshctl-dryrun-*")
	if err != nil {
		return fmt.Errorf("failed to create temp directory: %w", err)
	}
	defer os.RemoveAll(tempDir)

	// Render templates to temp directory
	if ctx.TemplateDir != "" {
		templateSrcDir, err := p.getCustomTemplateDir(ctx)
		if err != nil {
			return err
		}
		if err := renderer.RenderDirectory(templateSrcDir, tempDir, data); err != nil {
			return fmt.Errorf("failed to render templates: %w", err)
		}
	} else if embeddedTemplatesSet {
		embeddedPath := fmt.Sprintf("templates/%s/%s", ctx.Language, ctx.Template)
		if err := renderer.RenderEmbeddedDirectory(embeddedTemplates, embeddedPath, tempDir, data); err != nil {
			return fmt.Errorf("failed to render embedded templates: %w", err)
		}
	} else {
		templateSrcDir, err := p.getBuiltinTemplateDir(ctx)
		if err != nil {
			return err
		}
		if err := renderer.RenderDirectory(templateSrcDir, tempDir, data); err != nil {
			return fmt.Errorf("failed to render templates: %w", err)
		}
	}

	// Print header
	if ctx.Cmd != nil {
		ctx.Cmd.Println("# Dry-run: Preview of generated files")
		ctx.Cmd.Printf("# Agent: %s\n", ctx.Name)
		ctx.Cmd.Printf("# Type: %s\n", ctx.AgentType)
		ctx.Cmd.Printf("# Template: %s/%s\n", ctx.Language, ctx.Template)
		ctx.Cmd.Println("#")
		ctx.Cmd.Println("# Files would be created in:", filepath.Join(ctx.OutputDir, ctx.Name))
		ctx.Cmd.Println()
	}

	// Walk the temp directory and print files
	return filepath.Walk(tempDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}

		relPath, err := filepath.Rel(tempDir, path)
		if err != nil {
			return err
		}

		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}

		if ctx.Cmd != nil {
			ctx.Cmd.Printf("# ═══════════════════════════════════════════════════════════════\n")
			ctx.Cmd.Printf("# File: %s/%s\n", ctx.Name, relPath)
			ctx.Cmd.Printf("# ═══════════════════════════════════════════════════════════════\n")
			ctx.Cmd.Println(string(content))
			ctx.Cmd.Println()
		}

		return nil
	})
}

// getCustomTemplateDir returns the template path from a custom template directory.
func (p *StaticProvider) getCustomTemplateDir(ctx *ScaffoldContext) (string, error) {
	templatePath := filepath.Join(ctx.TemplateDir, ctx.Language, ctx.Template)
	if _, err := os.Stat(templatePath); err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Errorf("template '%s' for language '%s' not found in %s", ctx.Template, ctx.Language, ctx.TemplateDir)
		}
		return "", fmt.Errorf("failed to access template directory: %w", err)
	}
	return templatePath, nil
}

// getBuiltinTemplateDir returns the path to built-in templates from filesystem.
// This is a fallback for development/testing when embedded templates are not available.
// It searches in the following order:
// 1. MESHCTL_TEMPLATE_DIR environment variable
// 2. ./templates directory (relative to current working directory)
// 3. ./cmd/meshctl/templates directory (for development)
// 4. ~/.config/meshctl/templates
func (p *StaticProvider) getBuiltinTemplateDir(ctx *ScaffoldContext) (string, error) {
	// Check environment variable
	if envDir := os.Getenv("MESHCTL_TEMPLATE_DIR"); envDir != "" {
		templatePath := filepath.Join(envDir, ctx.Language, ctx.Template)
		if _, err := os.Stat(templatePath); err == nil {
			return templatePath, nil
		}
	}

	// Check relative to current directory
	if cwd, err := os.Getwd(); err == nil {
		// Check ./templates (legacy location)
		localDir := filepath.Join(cwd, "templates", ctx.Language, ctx.Template)
		if _, err := os.Stat(localDir); err == nil {
			return localDir, nil
		}
		// Check ./cmd/meshctl/templates (new location)
		cmdDir := filepath.Join(cwd, "cmd", "meshctl", "templates", ctx.Language, ctx.Template)
		if _, err := os.Stat(cmdDir); err == nil {
			return cmdDir, nil
		}
	}

	// Check user config directory
	if homeDir, err := os.UserHomeDir(); err == nil {
		configDir := filepath.Join(homeDir, ".config", "meshctl", "templates", ctx.Language, ctx.Template)
		if _, err := os.Stat(configDir); err == nil {
			return configDir, nil
		}
	}

	return "", fmt.Errorf("no template directory found; templates should be embedded in binary, or set MESHCTL_TEMPLATE_DIR or use --template-dir flag")
}

// SupportedTemplates returns the list of available templates
func SupportedTemplates() []string {
	return supportedTemplates
}

// IsValidTemplate checks if a template name is supported
func IsValidTemplate(template string) bool {
	for _, t := range supportedTemplates {
		if t == template {
			return true
		}
	}
	return false
}

// printGeneratedFiles walks the output directory and prints a tree of generated files
func printGeneratedFiles(cmd *cobra.Command, outputDir, agentName string) {
	cmd.Printf("  %s/\n", agentName)

	var files []string
	var dirs []string

	// Walk directory to collect files and subdirectories
	filepath.Walk(outputDir, func(path string, info os.FileInfo, err error) error {
		if err != nil || path == outputDir {
			return nil
		}

		relPath, _ := filepath.Rel(outputDir, path)

		if info.IsDir() {
			dirs = append(dirs, relPath)
		} else {
			files = append(files, relPath)
		}
		return nil
	})

	// Sort for consistent output
	sort.Strings(files)
	sort.Strings(dirs)

	// Print directories first (with their files)
	printedDirs := make(map[string]bool)
	for i, file := range files {
		dir := filepath.Dir(file)
		isLast := i == len(files)-1
		prefix := "├──"
		if isLast {
			prefix = "└──"
		}

		// If file is in a subdirectory, print the directory first
		if dir != "." && !printedDirs[dir] {
			cmd.Printf("  ├── %s/\n", dir)
			printedDirs[dir] = true
		}

		// Print file with appropriate indentation
		if dir != "." {
			subPrefix := "│   ├──"
			if isLast || (i < len(files)-1 && filepath.Dir(files[i+1]) != dir) {
				subPrefix = "│   └──"
			}
			cmd.Printf("  %s %s\n", subPrefix, filepath.Base(file))
		} else {
			cmd.Printf("  %s %s\n", prefix, file)
		}
	}
}

func init() {
	DefaultRegistry.Register(NewStaticProvider())
}
