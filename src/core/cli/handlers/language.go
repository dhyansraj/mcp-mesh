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

// EntryPointCandidate defines a potential entry point file with its language
type EntryPointCandidate struct {
	RelativePath string // Path relative to the folder (e.g., "main.py", "src/index.ts")
	Language     string // "python" or "typescript"
}

// entryPointPriority defines the search order for auto-detecting entry points.
// Python main.py takes priority, then TypeScript in src/, then root TypeScript.
// Note: .tsx and .jsx are intentionally not supported (React-specific).
var entryPointPriority = []EntryPointCandidate{
	{"main.py", "python"},
	{"src/index.ts", "typescript"},
	{"src/index.js", "typescript"},
	{"index.ts", "typescript"},
	{"index.js", "typescript"},
}

// ResolveEntryPoint resolves a path (file or folder) to an executable entry point.
// Returns (resolvedPath, language, error).
//
// If path is a file: returns it as-is with detected language.
// If path is a folder: scans for entry points in priority order.
//
// Entry point priority (from issue #474):
//  1. main.py         → python
//  2. src/index.ts    → typescript
//  3. src/index.js    → typescript
//  4. index.ts        → typescript
//  5. index.js        → typescript
func ResolveEntryPoint(path string) (string, string, error) {
	// Get absolute path for consistent handling
	absPath, err := filepath.Abs(path)
	if err != nil {
		return "", "", fmt.Errorf("invalid path %q: %w", path, err)
	}

	info, err := os.Stat(absPath)
	if err != nil {
		if os.IsNotExist(err) {
			return "", "", fmt.Errorf("path does not exist: %s", path)
		}
		return "", "", fmt.Errorf("cannot access path %q: %w", path, err)
	}

	// If it's a file, detect language from extension and return
	if !info.IsDir() {
		handler := DetectLanguage(absPath)
		lang := handler.Language()

		// Validate file extension
		ext := strings.ToLower(filepath.Ext(absPath))
		switch ext {
		case ".py", ".ts", ".js":
			return absPath, lang, nil
		default:
			return "", "", fmt.Errorf("unsupported file type %q: use .py, .ts, or .js", ext)
		}
	}

	// It's a directory - scan for entry points in priority order
	var checkedPaths []string
	for _, candidate := range entryPointPriority {
		candidatePath := filepath.Join(absPath, candidate.RelativePath)
		if fileExists(candidatePath) {
			return candidatePath, candidate.Language, nil
		}
		checkedPaths = append(checkedPaths, candidate.RelativePath)
	}

	// No entry point found - provide helpful error
	return "", "", fmt.Errorf(
		"no entry point found in folder %q\n\nChecked (in order):\n  - %s\n\nCreate one of these files or specify the full path to your agent script",
		path,
		strings.Join(checkedPaths, "\n  - "),
	)
}
