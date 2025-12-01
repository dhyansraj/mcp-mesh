package scaffold

import (
	"embed"
	"fmt"
	"os"
	"path/filepath"

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
var supportedTemplates = []string{"basic", "llm-agent", "llm-provider", "multi-tool", "gateway"}

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
	cmd.Flags().StringP("template", "t", "basic", "Template: basic, llm-agent, multi-tool, gateway")
	cmd.Flags().String("template-dir", "", "Custom template directory")
	cmd.Flags().String("config", "", "Config file (YAML) for complex scaffolding")
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

// Execute performs the scaffold generation using templates.
func (p *StaticProvider) Execute(ctx *ScaffoldContext) error {
	// Create output directory: outputDir/agentName
	outputDir := filepath.Join(ctx.OutputDir, ctx.Name)
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

	// Print success message
	if ctx.Cmd != nil {
		ctx.Cmd.Printf("Successfully created agent '%s' in %s\n", ctx.Name, outputDir)
		ctx.Cmd.Printf("  Language: %s\n", ctx.Language)
		if ctx.AgentType != "" {
			ctx.Cmd.Printf("  Agent Type: %s\n", ctx.AgentType)
		}
		ctx.Cmd.Printf("  Template: %s\n", ctx.Template)
		ctx.Cmd.Printf("  Port: %d\n", ctx.Port)
		if ctx.Model != "" {
			ctx.Cmd.Printf("  Model: %s\n", ctx.Model)
		}
	}

	return nil
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

// init registers the static provider with the default registry
func init() {
	DefaultRegistry.Register(NewStaticProvider())
}
