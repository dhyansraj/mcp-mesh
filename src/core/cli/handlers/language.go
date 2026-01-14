// Package handlers provides language-specific operations for meshctl commands.
// It implements a unified handler pattern for Python and TypeScript agents.
package handlers

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// LanguageMarkers defines directory markers for detecting language.
// Shared across DetectLanguage() and handler DetectInDirectory() methods.
var LanguageMarkers = map[string][]string{
	"python":     {"pyproject.toml", "requirements.txt", ".venv", "setup.py"},
	"typescript": {"package.json", "tsconfig.json", "node_modules"},
}

// ScaffoldConfig contains configuration for generating agent files
type ScaffoldConfig struct {
	Name        string
	AgentType   string
	Port        int
	Version     string
	Description string
	OutputDir   string
}

// AgentInfo contains parsed information from an agent file
type AgentInfo struct {
	Name         string
	Port         int
	Version      string
	Capabilities []string
}

// LanguageHandler defines the interface for language-specific operations.
// Implementations provide Python and TypeScript specific behavior.
type LanguageHandler interface {
	// Detection
	Language() string                  // Returns "python" or "typescript"
	CanHandle(path string) bool        // Check if file/dir is this language
	DetectInDirectory(dir string) bool // Check if dir contains this language

	// Scaffold
	GetTemplates() map[string]string            // Template files
	GenerateAgent(config ScaffoldConfig) error  // Generate agent files
	GenerateDockerfile() string                 // Dockerfile content
	GenerateHelmValues() map[string]interface{} // Helm values

	// Compose
	ParseAgentFile(path string) (*AgentInfo, error) // Extract name, port, caps
	GetDockerImage() string                         // Runtime image name

	// Start
	ValidatePrerequisites(dir string) error // Check .venv or node_modules
	GetStartCommand(file string) []string   // Command to start agent
	GetEnvironment() map[string]string      // Required env vars
}

// NormalizeLanguage converts shorthand to canonical form.
// Returns "python" for "py", "python", "Python", etc.
// Returns "typescript" for "ts", "typescript", "TypeScript", etc.
// Returns empty string normalized to "python" (default).
// Unknown languages are returned as-is (lowercase).
func NormalizeLanguage(lang string) string {
	switch strings.ToLower(strings.TrimSpace(lang)) {
	case "python", "py", "":
		return "python"
	case "typescript", "ts":
		return "typescript"
	default:
		return strings.ToLower(lang) // Return as-is for validation to handle
	}
}

// GetHandlerByLanguage returns handler for explicit --lang flag.
// Returns error for unsupported languages.
func GetHandlerByLanguage(lang string) (LanguageHandler, error) {
	normalized := NormalizeLanguage(lang)
	switch normalized {
	case "python":
		return &PythonHandler{}, nil
	case "typescript":
		return &TypeScriptHandler{}, nil
	default:
		return nil, fmt.Errorf("unsupported language: %s (use: python, py, typescript, ts)", lang)
	}
}

// DetectLanguage auto-detects language from file/directory.
// Used when --lang flag is not specified.
// Returns PythonHandler as default for backwards compatibility.
func DetectLanguage(path string) LanguageHandler {
	// 1. File extension check
	lowerPath := strings.ToLower(path)
	if strings.HasSuffix(lowerPath, ".py") {
		return &PythonHandler{}
	}
	if strings.HasSuffix(lowerPath, ".ts") || strings.HasSuffix(lowerPath, ".js") {
		return &TypeScriptHandler{}
	}

	// 2. Directory detection - check for language markers (using shared map)
	info, err := os.Stat(path)
	if err == nil && info.IsDir() {
		// Python markers
		for _, marker := range LanguageMarkers["python"] {
			if fileExists(filepath.Join(path, marker)) {
				return &PythonHandler{}
			}
		}

		// TypeScript/JavaScript markers
		for _, marker := range LanguageMarkers["typescript"] {
			if fileExists(filepath.Join(path, marker)) {
				return &TypeScriptHandler{}
			}
		}
	}

	// 3. Default to Python for backwards compatibility
	return &PythonHandler{}
}

// GetAllHandlers returns all registered language handlers
func GetAllHandlers() []LanguageHandler {
	return []LanguageHandler{
		&PythonHandler{},
		&TypeScriptHandler{},
	}
}

// fileExists checks if a file or directory exists
func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
