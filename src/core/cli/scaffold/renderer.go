package scaffold

import (
	"bytes"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"text/template"
	"unicode"
)

// TemplateRenderer handles template rendering with gomplate-style functions.
type TemplateRenderer struct {
	funcMap template.FuncMap
}

// NewTemplateRenderer creates a new template renderer with helper functions.
func NewTemplateRenderer() *TemplateRenderer {
	return &TemplateRenderer{
		funcMap: template.FuncMap{
			"toUpper":      strings.ToUpper,
			"toLower":      strings.ToLower,
			"toSnakeCase":  toSnakeCase,
			"toCamelCase":  toCamelCase,
			"toPascalCase": toPascalCase,
			"toKebabCase":  toKebabCase,
			"default":      defaultValue,
			"indent":       indent,
			"trimSpace":    strings.TrimSpace,
			"replace":      strings.ReplaceAll,
			"contains":     strings.Contains,
			"hasPrefix":    strings.HasPrefix,
			"hasSuffix":    strings.HasSuffix,
			"join":         strings.Join,
			"split":        strings.Split,
			"toJSON":       toJSON,
		},
	}
}

// RenderString renders a template string with the given data.
func (r *TemplateRenderer) RenderString(templateStr string, data map[string]interface{}) (string, error) {
	tmpl, err := template.New("template").Funcs(r.funcMap).Parse(templateStr)
	if err != nil {
		return "", fmt.Errorf("failed to parse template: %w", err)
	}

	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return "", fmt.Errorf("failed to execute template: %w", err)
	}

	return buf.String(), nil
}

// RenderFile reads a template file and renders it with the given data.
func (r *TemplateRenderer) RenderFile(templatePath string, data map[string]interface{}) (string, error) {
	content, err := os.ReadFile(templatePath)
	if err != nil {
		return "", fmt.Errorf("failed to read template file %s: %w", templatePath, err)
	}

	return r.RenderString(string(content), data)
}

// RenderToFile renders a template and writes the output to a file.
func (r *TemplateRenderer) RenderToFile(templateStr string, data map[string]interface{}, outputPath string) error {
	result, err := r.RenderString(templateStr, data)
	if err != nil {
		return err
	}

	// Create parent directories if needed
	if err := os.MkdirAll(filepath.Dir(outputPath), 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	if err := os.WriteFile(outputPath, []byte(result), 0644); err != nil {
		return fmt.Errorf("failed to write output file %s: %w", outputPath, err)
	}

	return nil
}

// RenderDirectory renders all template files in a source directory to an output directory.
// Files with .tmpl extension are rendered and the extension is stripped.
// Files without .tmpl are copied as-is.
// Filenames can contain template expressions (e.g., {{.Name}}.py.tmpl).
func (r *TemplateRenderer) RenderDirectory(srcDir, outDir string, data map[string]interface{}) error {
	return filepath.WalkDir(srcDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		// Get relative path from source directory
		relPath, err := filepath.Rel(srcDir, path)
		if err != nil {
			return err
		}

		// Skip the root directory
		if relPath == "." {
			return nil
		}

		// Handle filename templating
		outputRelPath, err := r.RenderString(relPath, data)
		if err != nil {
			return fmt.Errorf("failed to render filename %s: %w", relPath, err)
		}

		// Build output path
		outputPath := filepath.Join(outDir, outputRelPath)

		if d.IsDir() {
			// Create directory
			return os.MkdirAll(outputPath, 0755)
		}

		// Handle files
		isTemplate := strings.HasSuffix(outputPath, ".tmpl")
		if isTemplate {
			// Strip .tmpl extension for output
			outputPath = strings.TrimSuffix(outputPath, ".tmpl")

			// Read and render template
			content, err := os.ReadFile(path)
			if err != nil {
				return fmt.Errorf("failed to read template %s: %w", path, err)
			}

			return r.RenderToFile(string(content), data, outputPath)
		}

		// Copy non-template files as-is
		return copyFile(path, outputPath)
	})
}

// RenderEmbeddedDirectory renders templates from an embedded filesystem to an output directory.
// This is used for built-in templates that are compiled into the binary.
// srcPath is the path within the embedded FS (e.g., "templates/python/basic").
func (r *TemplateRenderer) RenderEmbeddedDirectory(embeddedFS embed.FS, srcPath, outDir string, data map[string]interface{}) error {
	return fs.WalkDir(embeddedFS, srcPath, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		// Get relative path from source directory
		relPath, err := filepath.Rel(srcPath, path)
		if err != nil {
			return err
		}

		// Skip the root directory
		if relPath == "." {
			return nil
		}

		// Handle filename templating
		outputRelPath, err := r.RenderString(relPath, data)
		if err != nil {
			return fmt.Errorf("failed to render filename %s: %w", relPath, err)
		}

		// Build output path
		outputPath := filepath.Join(outDir, outputRelPath)

		if d.IsDir() {
			// Create directory
			return os.MkdirAll(outputPath, 0755)
		}

		// Handle files
		isTemplate := strings.HasSuffix(outputPath, ".tmpl")
		if isTemplate {
			// Strip .tmpl extension for output
			outputPath = strings.TrimSuffix(outputPath, ".tmpl")

			// Read from embedded FS and render template
			content, err := embeddedFS.ReadFile(path)
			if err != nil {
				return fmt.Errorf("failed to read embedded template %s: %w", path, err)
			}

			return r.RenderToFile(string(content), data, outputPath)
		}

		// Copy non-template files from embedded FS
		return copyEmbeddedFile(embeddedFS, path, outputPath)
	})
}

// copyEmbeddedFile copies a file from an embedded FS to the filesystem.
func copyEmbeddedFile(embeddedFS embed.FS, src, dst string) error {
	// Create parent directories
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}

	content, err := embeddedFS.ReadFile(src)
	if err != nil {
		return err
	}

	return os.WriteFile(dst, content, 0644)
}

// copyFile copies a file from src to dst.
func copyFile(src, dst string) error {
	// Create parent directories
	if err := os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
		return err
	}

	srcFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer srcFile.Close()

	dstFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer dstFile.Close()

	_, err = io.Copy(dstFile, srcFile)
	return err
}

// TemplateDataFromContext converts a ScaffoldContext to a template data map.
func TemplateDataFromContext(ctx *ScaffoldContext) map[string]interface{} {
	data := map[string]interface{}{
		// Common fields
		"Name":        ctx.Name,
		"Description": ctx.Description,
		"Language":    ctx.Language,
		"OutputDir":   ctx.OutputDir,
		"Port":        ctx.Port,
		"Template":    ctx.Template,
		"TemplateDir": ctx.TemplateDir,
		"ConfigFile":  ctx.ConfigFile,
		"AgentType":   ctx.AgentType,

		// Computed name variants
		"NameSnake":  toSnakeCase(ctx.Name),
		"NameCamel":  toCamelCase(ctx.Name),
		"NamePascal": toPascalCase(ctx.Name),
		"NameKebab":  toKebabCase(ctx.Name),

		// Tool-specific
		"Capabilities": ctx.Capabilities,
		"Tags":         ctx.Tags,
		"Dependencies": ctx.Dependencies,

		// LLM-agent specific
		"LLMProviderSelector": ctx.LLMProviderSelector,
		"ProviderTags":        ctx.ProviderTags,
		"MaxIterations":       ctx.MaxIterations,
		"SystemPrompt":        ctx.SystemPrompt,
		"ContextParam":        ctx.ContextParam,
		"ResponseFormat":      ctx.ResponseFormat,

		// Tool filter for @mesh.llm
		"ToolFilter": ctx.ToolFilter,
		"FilterMode": ctx.FilterMode,

		// LLM-provider specific
		"Model": ctx.Model,

		// Helper computed values
		"SystemPromptIsFile":   strings.HasPrefix(ctx.SystemPrompt, "file://"),
		"SystemPromptInline":   !strings.HasPrefix(ctx.SystemPrompt, "file://") && ctx.SystemPrompt != "",
		"SystemPromptFilePath": strings.TrimPrefix(ctx.SystemPrompt, "file://"),
	}

	return data
}

// Helper functions for template rendering

// toSnakeCase converts a string to snake_case.
func toSnakeCase(s string) string {
	// Replace hyphens and spaces with underscores
	s = strings.ReplaceAll(s, "-", "_")
	s = strings.ReplaceAll(s, " ", "_")

	// Handle camelCase by inserting underscores before uppercase letters
	var result strings.Builder
	for i, r := range s {
		if i > 0 && unicode.IsUpper(r) && !unicode.IsUpper(rune(s[i-1])) {
			result.WriteRune('_')
		}
		result.WriteRune(unicode.ToLower(r))
	}

	return result.String()
}

// toCamelCase converts a string to camelCase.
func toCamelCase(s string) string {
	words := splitWords(s)
	if len(words) == 0 {
		return ""
	}

	var result strings.Builder
	for i, word := range words {
		if i == 0 {
			result.WriteString(strings.ToLower(word))
		} else {
			result.WriteString(capitalize(word))
		}
	}

	return result.String()
}

// toPascalCase converts a string to PascalCase.
func toPascalCase(s string) string {
	words := splitWords(s)
	var result strings.Builder
	for _, word := range words {
		result.WriteString(capitalize(word))
	}
	return result.String()
}

// toKebabCase converts a string to kebab-case.
func toKebabCase(s string) string {
	// Replace underscores and spaces with hyphens
	s = strings.ReplaceAll(s, "_", "-")
	s = strings.ReplaceAll(s, " ", "-")

	// Handle camelCase by inserting hyphens before uppercase letters
	var result strings.Builder
	for i, r := range s {
		if i > 0 && unicode.IsUpper(r) && !unicode.IsUpper(rune(s[i-1])) {
			result.WriteRune('-')
		}
		result.WriteRune(unicode.ToLower(r))
	}

	return result.String()
}

// splitWords splits a string into words by common separators and camelCase boundaries.
func splitWords(s string) []string {
	// First, insert a separator before uppercase letters that follow lowercase letters (camelCase)
	var result strings.Builder
	for i, r := range s {
		if i > 0 && unicode.IsUpper(r) {
			prev := rune(s[i-1])
			if unicode.IsLower(prev) {
				result.WriteRune('_')
			}
		}
		result.WriteRune(r)
	}

	// Split on common separators
	re := regexp.MustCompile(`[-_\s]+`)
	parts := re.Split(result.String(), -1)

	var words []string
	for _, part := range parts {
		if part != "" {
			words = append(words, part)
		}
	}
	return words
}

// capitalize capitalizes the first letter of a string.
func capitalize(s string) string {
	if s == "" {
		return ""
	}
	return strings.ToUpper(s[:1]) + strings.ToLower(s[1:])
}

// defaultValue returns the value if non-empty, otherwise returns the default.
func defaultValue(defaultVal, value interface{}) interface{} {
	if value == nil {
		return defaultVal
	}

	// Check for empty string
	if str, ok := value.(string); ok && str == "" {
		return defaultVal
	}

	return value
}

// indent adds indentation to each line of a string.
func indent(spaces int, s string) string {
	padding := strings.Repeat(" ", spaces)
	lines := strings.Split(s, "\n")
	for i, line := range lines {
		lines[i] = padding + line
	}
	return strings.Join(lines, "\n")
}

// toJSON converts a value to a JSON string.
func toJSON(v interface{}) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "[]"
	}
	return string(b)
}
