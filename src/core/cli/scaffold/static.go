package scaffold

import (
	"embed"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

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
	cmd.Flags().String("tool-name", "", "Tool name for the agent")
	cmd.Flags().String("tool-description", "", "Tool description for the agent")
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

// getAgentEntryFile returns the entry file path for an agent based on language.
// Python uses main.py, TypeScript uses src/index.ts
func getAgentEntryFile(outputDir, language string) string {
	if language == "typescript" {
		return filepath.Join(outputDir, "src", "index.ts")
	}
	if language == "java" {
		return filepath.Join(outputDir, "pom.xml")
	}
	return filepath.Join(outputDir, "main.py")
}

// Execute performs the scaffold generation using templates.
func (p *StaticProvider) Execute(ctx *ScaffoldContext) error {
	// Create output directory: outputDir/agentName
	outputDir := filepath.Join(ctx.OutputDir, ctx.Name)

	// Handle dry-run mode - render and print without creating files
	if ctx.DryRun {
		return p.executeDryRun(ctx)
	}

	// Check if directory already exists (for safety - don't overwrite)
	entryFile := getAgentEntryFile(outputDir, ctx.Language)
	if FileExists(entryFile) {
		if ctx.Cmd != nil {
			ctx.Cmd.Printf("Agent '%s' already exists at %s\n", ctx.Name, outputDir)
		}
		return fmt.Errorf("agent already exists at %s", outputDir)
	}

	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	// Create template renderer
	renderer := NewTemplateRenderer()

	// Compute default Java package name if not specified
	if ctx.Language == "java" && ctx.JavaPackage == "" {
		sanitized := strings.ReplaceAll(strings.ReplaceAll(ctx.Name, "-", ""), "_", "")
		ctx.JavaPackage = "com.example." + strings.ToLower(sanitized)
	}

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
		} else if ctx.Language == "java" {
			ctx.Cmd.Printf("  cd %s && mvn spring-boot:run\n", ctx.Name)
			ctx.Cmd.Printf("  # or: meshctl start %s\n", ctx.Name)
		} else {
			ctx.Cmd.Printf("  meshctl start %s/main.py\n", ctx.Name)
		}
		ctx.Cmd.Printf("\n")
		ctx.Cmd.Printf("For Docker/K8s deployment, see: meshctl man deployment\n")
	}

	return nil
}

// executeDryRun renders templates and prints them to stdout without creating files.
func (p *StaticProvider) executeDryRun(ctx *ScaffoldContext) error {
	// Create template renderer
	renderer := NewTemplateRenderer()

	// Compute default Java package name if not specified
	if ctx.Language == "java" && ctx.JavaPackage == "" {
		sanitized := strings.ReplaceAll(strings.ReplaceAll(ctx.Name, "-", ""), "_", "")
		ctx.JavaPackage = "com.example." + strings.ToLower(sanitized)
	}

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
