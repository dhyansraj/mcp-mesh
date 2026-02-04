package handlers

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"mcp-mesh/src/core/cli/scaffold"
)

// PythonHandler implements LanguageHandler for Python agents
type PythonHandler struct{}

// Language returns the language identifier
func (h *PythonHandler) Language() string {
	return "python"
}

// CanHandle checks if the given path is a Python file
func (h *PythonHandler) CanHandle(path string) bool {
	return strings.HasSuffix(strings.ToLower(path), ".py")
}

// DetectInDirectory checks if the directory contains Python markers
func (h *PythonHandler) DetectInDirectory(dir string) bool {
	// Use shared LanguageMarkers map
	for _, marker := range LanguageMarkers["python"] {
		if fileExists(filepath.Join(dir, marker)) {
			return true
		}
	}
	// Also check for .py files
	entries, err := os.ReadDir(dir)
	if err == nil {
		for _, entry := range entries {
			if strings.HasSuffix(entry.Name(), ".py") {
				return true
			}
		}
	}
	return false
}

// GetTemplates returns Python agent templates
func (h *PythonHandler) GetTemplates() map[string]string {
	return map[string]string{
		"main.py":          pythonMainTemplate,
		"__init__.py":      pythonInitTemplate,
		"__main__.py":      pythonMainModuleTemplate,
		"requirements.txt": pythonRequirementsTemplate,
		"Dockerfile":       h.GenerateDockerfile(),
	}
}

// GenerateAgent generates Python agent files
func (h *PythonHandler) GenerateAgent(config ScaffoldConfig) error {
	// Create output directory
	if err := os.MkdirAll(config.OutputDir, 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	// Build template data from config
	data := map[string]interface{}{
		"Name":        config.Name,
		"Port":        config.Port,
		"Version":     config.Version,
		"Description": config.Description,
		"Capability":  config.Name, // Default capability to agent name
	}

	// Create renderer and render templates
	renderer := scaffold.NewTemplateRenderer()
	templates := h.GetTemplates()

	for filename, templateContent := range templates {
		filePath := filepath.Join(config.OutputDir, filename)
		if err := renderer.RenderToFile(templateContent, data, filePath); err != nil {
			return fmt.Errorf("failed to render %s: %w", filename, err)
		}
	}

	return nil
}

// GenerateDockerfile returns Python Dockerfile content
func (h *PythonHandler) GenerateDockerfile() string {
	return `# Dockerfile for MCP Mesh Python agent
FROM mcpmesh/python-runtime:0.8

WORKDIR /app

# Switch to root to copy files
USER root

# Copy requirements and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source code
COPY --chmod=755 . .
RUN chown -R mcp-mesh:mcp-mesh /app

# Switch back to non-root user
USER mcp-mesh

# Expose the agent port
EXPOSE 9000

# Run the agent
CMD ["python", "main.py"]
`
}

// GenerateHelmValues returns Python-specific Helm values
func (h *PythonHandler) GenerateHelmValues() map[string]interface{} {
	return map[string]interface{}{
		"runtime": "python",
		"image": map[string]interface{}{
			"repository": "mcpmesh/python-runtime",
			"tag":        "0.8",
		},
		"command": []string{"python", "main.py"},
	}
}

// ParseAgentFile extracts agent info from a Python file
func (h *PythonHandler) ParseAgentFile(path string) (*AgentInfo, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}

	info := &AgentInfo{}

	// Extract name from @mesh.agent(name="...")
	lines := strings.Split(string(content), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.Contains(line, "@mesh.agent") {
			// Simple extraction - look for name="value"
			if idx := strings.Index(line, `name="`); idx != -1 {
				start := idx + 6
				end := strings.Index(line[start:], `"`)
				if end != -1 {
					info.Name = line[start : start+end]
				}
			}
			// Look for http_port=
			if idx := strings.Index(line, "http_port="); idx != -1 {
				start := idx + 10
				end := start
				for end < len(line) && line[end] >= '0' && line[end] <= '9' {
					end++
				}
				if end > start {
					fmt.Sscanf(line[start:end], "%d", &info.Port)
				}
			}
		}
	}

	// Fall back to filename if name not found
	if info.Name == "" {
		info.Name = strings.TrimSuffix(filepath.Base(path), ".py")
	}

	return info, nil
}

// GetDockerImage returns the Python runtime Docker image
func (h *PythonHandler) GetDockerImage() string {
	return "mcpmesh/python-runtime:0.8"
}

// ValidatePrerequisites checks Python environment
func (h *PythonHandler) ValidatePrerequisites(dir string) error {
	// Check for .venv
	venvPath := filepath.Join(dir, ".venv")
	if !fileExists(venvPath) {
		return fmt.Errorf(".venv not found. Run: python3 -m venv .venv && source .venv/bin/activate")
	}

	// Check for mcp-mesh package (simplified check)
	// In production, would check pip list
	return nil
}

// GetStartCommand returns the command to start a Python agent
func (h *PythonHandler) GetStartCommand(file string) []string {
	// Walk upward from file directory to find .venv/bin/python
	// This handles nested sources where .venv is at project root
	currentDir := filepath.Dir(file)
	for {
		venvPython := filepath.Join(currentDir, ".venv", "bin", "python")
		if fileExists(venvPython) {
			return []string{venvPython, file}
		}

		// Move to parent directory
		parentDir := filepath.Dir(currentDir)
		// Stop if we've reached the filesystem root
		if parentDir == currentDir {
			break
		}
		currentDir = parentDir
	}

	// Fall back to system python
	return []string{"python3", file}
}

// GetEnvironment returns Python-specific environment variables
func (h *PythonHandler) GetEnvironment() map[string]string {
	return map[string]string{
		"PYTHONUNBUFFERED": "1",
	}
}

// Template constants
const pythonMainTemplate = `import mesh
from fastmcp import FastMCP

app = FastMCP("{{.Name}} Service")

@app.tool()
@mesh.tool(
    capability="{{.Capability}}",
    description="{{.Description}}",
    tags=["tools"],
)
async def example_tool(input: str) -> str:
    return f"Processed: {input}"

@mesh.agent(
    name="{{.Name}}",
    version="{{.Version}}",
    http_port={{.Port}},
    auto_run=True,
)
class Agent:
    pass
`

const pythonInitTemplate = `# {{.Name}} MCP Mesh Agent
`

const pythonMainModuleTemplate = `from .main import *
`

const pythonRequirementsTemplate = `mcp-mesh>=0.9.0-beta.2
`
