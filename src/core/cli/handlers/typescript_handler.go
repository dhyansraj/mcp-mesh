package handlers

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"mcp-mesh/src/core/cli/scaffold"
)

// TypeScriptHandler implements LanguageHandler for TypeScript/JavaScript agents
type TypeScriptHandler struct{}

// Language returns the language identifier
func (h *TypeScriptHandler) Language() string {
	return "typescript"
}

// CanHandle checks if the given path is a TypeScript or JavaScript file
func (h *TypeScriptHandler) CanHandle(path string) bool {
	lowerPath := strings.ToLower(path)
	return strings.HasSuffix(lowerPath, ".ts") || strings.HasSuffix(lowerPath, ".js")
}

// DetectInDirectory checks if the directory contains TypeScript/JavaScript markers
func (h *TypeScriptHandler) DetectInDirectory(dir string) bool {
	// Use shared LanguageMarkers map
	for _, marker := range LanguageMarkers["typescript"] {
		if fileExists(filepath.Join(dir, marker)) {
			return true
		}
	}
	// Also check for .ts or .js files
	entries, err := os.ReadDir(dir)
	if err == nil {
		for _, entry := range entries {
			name := entry.Name()
			if strings.HasSuffix(name, ".ts") || strings.HasSuffix(name, ".js") {
				return true
			}
		}
	}
	return false
}

// GetTemplates returns TypeScript agent templates
func (h *TypeScriptHandler) GetTemplates() map[string]string {
	return map[string]string{
		"src/index.ts":   typescriptMainTemplate,
		"package.json":   typescriptPackageTemplate,
		"tsconfig.json":  typescriptConfigTemplate,
		"Dockerfile":     h.GenerateDockerfile(),
		".dockerignore":  typescriptDockerIgnoreTemplate,
	}
}

// GenerateAgent generates TypeScript agent files
func (h *TypeScriptHandler) GenerateAgent(config ScaffoldConfig) error {
	// Create output directory and src subdirectory
	srcDir := filepath.Join(config.OutputDir, "src")
	if err := os.MkdirAll(srcDir, 0755); err != nil {
		return fmt.Errorf("failed to create src directory: %w", err)
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
		// RenderToFile creates parent directories automatically
		if err := renderer.RenderToFile(templateContent, data, filePath); err != nil {
			return fmt.Errorf("failed to render %s: %w", filename, err)
		}
	}

	return nil
}

// GenerateDockerfile returns TypeScript Dockerfile content
func (h *TypeScriptHandler) GenerateDockerfile() string {
	return `# Dockerfile for MCP Mesh TypeScript agent
FROM mcpmesh/typescript-runtime:0.8

WORKDIR /app

# Switch to root to copy files
USER root

# Copy package files and install dependencies
COPY package*.json ./
RUN npm ci --omit=dev

# Copy agent source code
COPY --chmod=755 . .
RUN chown -R mcp-mesh:mcp-mesh /app

# Switch back to non-root user
USER mcp-mesh

# Expose the agent port
EXPOSE 9000

# Run the agent (tsx for .ts files)
CMD ["npx", "tsx", "src/index.ts"]
`
}

// GenerateHelmValues returns TypeScript-specific Helm values
func (h *TypeScriptHandler) GenerateHelmValues() map[string]interface{} {
	return map[string]interface{}{
		"runtime": "typescript",
		"image": map[string]interface{}{
			"repository": "mcpmesh/typescript-runtime",
			"tag":        "0.8",
		},
		"command": []string{"npx", "tsx", "src/index.ts"},
	}
}

// ParseAgentFile extracts agent info from a TypeScript file
func (h *TypeScriptHandler) ParseAgentFile(path string) (*AgentInfo, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}

	info := &AgentInfo{}
	contentStr := string(content)

	// Extract name from mesh(server, { name: "..." })
	nameRe := regexp.MustCompile(`mesh\s*\([^,]+,\s*\{[^}]*name\s*:\s*["']([^"']+)["']`)
	if matches := nameRe.FindStringSubmatch(contentStr); len(matches) > 1 {
		info.Name = matches[1]
	}

	// Extract port from mesh(server, { port: ... })
	portRe := regexp.MustCompile(`mesh\s*\([^,]+,\s*\{[^}]*port\s*:\s*(\d+)`)
	if matches := portRe.FindStringSubmatch(contentStr); len(matches) > 1 {
		fmt.Sscanf(matches[1], "%d", &info.Port)
	}

	// Fall back to filename if name not found
	if info.Name == "" {
		baseName := filepath.Base(path)
		info.Name = strings.TrimSuffix(strings.TrimSuffix(baseName, ".ts"), ".js")
		if info.Name == "index" {
			// Use parent directory name
			info.Name = filepath.Base(filepath.Dir(path))
		}
	}

	return info, nil
}

// GetDockerImage returns the TypeScript runtime Docker image
func (h *TypeScriptHandler) GetDockerImage() string {
	return "mcpmesh/typescript-runtime:0.8"
}

// ValidatePrerequisites checks TypeScript environment
func (h *TypeScriptHandler) ValidatePrerequisites(dir string) error {
	// Check for node_modules
	nodeModules := filepath.Join(dir, "node_modules")
	if !fileExists(nodeModules) {
		return fmt.Errorf("node_modules not found. Run: npm install")
	}

	// Check for @mcpmesh/sdk in package.json
	pkgJson := filepath.Join(dir, "package.json")
	if !fileExists(pkgJson) {
		return nil // No package.json to check
	}

	content, err := os.ReadFile(pkgJson)
	if err != nil {
		return nil // Can't read, skip check
	}

	var pkg map[string]interface{}
	if err := json.Unmarshal(content, &pkg); err != nil {
		return nil // Invalid JSON, skip check
	}

	if !h.hasMeshSDK(pkg) {
		return fmt.Errorf("@mcpmesh/sdk not found in package.json. Run: npm install @mcpmesh/sdk")
	}

	return nil
}

// hasMeshSDK checks if @mcpmesh/sdk is in dependencies or devDependencies
func (h *TypeScriptHandler) hasMeshSDK(pkg map[string]interface{}) bool {
	for _, depType := range []string{"dependencies", "devDependencies"} {
		if deps, ok := pkg[depType].(map[string]interface{}); ok {
			if _, hasSdk := deps["@mcpmesh/sdk"]; hasSdk {
				return true
			}
		}
	}
	return false
}

// GetStartCommand returns the command to start a TypeScript/JavaScript agent
func (h *TypeScriptHandler) GetStartCommand(file string) []string {
	lowerFile := strings.ToLower(file)
	if strings.HasSuffix(lowerFile, ".ts") {
		// Use tsx for TypeScript files (fast TypeScript execution)
		return []string{"npx", "tsx", file}
	}
	// Use node for JavaScript files
	return []string{"node", file}
}

// GetEnvironment returns TypeScript-specific environment variables
func (h *TypeScriptHandler) GetEnvironment() map[string]string {
	return map[string]string{
		"NODE_ENV": "production",
	}
}

// Template constants
const typescriptMainTemplate = `import { FastMCP } from "fastmcp";
import { mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "{{.Name}}", version: "{{.Version}}" });

const agent = mesh(server, {
  name: "{{.Name}}",
  port: {{.Port}},
});

agent.addTool({
  name: "example",
  capability: "{{.Capability}}",
  description: "{{.Description}}",
  tags: ["tools"],
  parameters: z.object({
    input: z.string().describe("Input to process"),
  }),
  execute: async ({ input }) => {
    return "Processed: " + input;
  },
});

// No server.start() needed - SDK auto-starts!
`

const typescriptPackageTemplate = `{
  "name": "{{.Name}}",
  "version": "{{.Version}}",
  "type": "module",
  "scripts": {
    "start": "tsx src/index.ts",
    "build": "tsc",
    "dev": "tsx watch src/index.ts"
  },
  "dependencies": {
    "@mcpmesh/sdk": "^0.9.0-beta.1",
    "fastmcp": "^3.26.0",
    "zod": "^3.23.0"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "tsx": "^4.7.0",
    "typescript": "^5.4.0"
  }
}
`

const typescriptConfigTemplate = `{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "outDir": "dist"
  },
  "include": ["src/**/*"]
}
`

const typescriptDockerIgnoreTemplate = `node_modules
dist
.git
.env
*.log
`
