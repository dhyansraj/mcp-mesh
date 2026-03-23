package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"mcp-mesh/src/core/cli/handlers"
)

// isAgentFile returns true if the path is a valid agent file (.py, .ts, .js, .yaml, .yml, .jar, .java)
// or a directory containing known language markers (pom.xml, main.py, package.json, etc.)
func isAgentFile(path string) bool {
	ext := filepath.Ext(path)
	switch ext {
	case ".py", ".ts", ".js", ".yaml", ".yml", ".jar", ".java":
		return true
	}

	info, err := os.Stat(path)
	if err == nil && info.IsDir() {
		for _, markers := range handlers.LanguageMarkers {
			for _, marker := range markers {
				if _, err := os.Stat(filepath.Join(path, marker)); err == nil {
					return true
				}
			}
		}
	}

	return false
}

// isJavaProject checks if the given path is a Java agent (JAR file or Maven project)
func isJavaProject(agentPath string) bool {
	if strings.HasSuffix(strings.ToLower(agentPath), ".jar") {
		return true
	}
	info, err := os.Stat(agentPath)
	if err != nil {
		return false
	}
	dir := agentPath
	if !info.IsDir() {
		dir = filepath.Dir(agentPath)
	}
	// Check for pom.xml in the directory or parent directories
	javaHandler := &handlers.JavaHandler{}
	_, err = javaHandler.FindProjectRoot(dir)
	return err == nil
}

// isPythonProject checks if the given path is a Python agent
func isPythonProject(agentPath string) bool {
	lowerPath := strings.ToLower(agentPath)
	if strings.HasSuffix(lowerPath, ".py") || strings.HasSuffix(lowerPath, ".yaml") || strings.HasSuffix(lowerPath, ".yml") {
		// Check if it's detected as Python by the language handler
		handler := handlers.DetectLanguage(agentPath)
		return handler.Language() == langPython
	}
	info, err := os.Stat(agentPath)
	if err != nil {
		return false
	}
	if info.IsDir() {
		handler := handlers.DetectLanguage(agentPath)
		return handler.Language() == langPython
	}
	return false
}

// resolveAllAgentPaths resolves folder paths to entry point files.
// Supports both folder names (auto-detect entry point) and full file paths.
// Returns resolved file paths or error if any path cannot be resolved.
//
// Examples:
//
//	["my-agent"]                    -> ["/abs/path/my-agent/main.py"]
//	["my-agent/src/index.ts"]       -> ["/abs/path/my-agent/src/index.ts"]
//	["agent1", "agent2/main.py"]    -> ["/abs/path/agent1/main.py", "/abs/path/agent2/main.py"]
func resolveAllAgentPaths(args []string) ([]string, error) {
	resolved := make([]string, 0, len(args))

	for _, arg := range args {
		resolvedPath, _, err := handlers.ResolveEntryPoint(arg)
		if err != nil {
			return nil, fmt.Errorf("failed to resolve %q: %w", arg, err)
		}
		resolved = append(resolved, resolvedPath)
	}

	return resolved, nil
}
