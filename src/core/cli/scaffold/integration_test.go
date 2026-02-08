package scaffold

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// getProjectRoot returns the project root directory
func getProjectRoot() string {
	_, filename, _, _ := runtime.Caller(0)
	// Go up from src/core/cli/scaffold to project root
	return filepath.Join(filepath.Dir(filename), "..", "..", "..", "..")
}

func TestIntegration_ScaffoldWithBuiltinTemplates(t *testing.T) {
	// Skip if templates don't exist
	projectRoot := getProjectRoot()
	templateDir := filepath.Join(projectRoot, "templates")
	if _, err := os.Stat(templateDir); os.IsNotExist(err) {
		t.Skip("Built-in templates not found, skipping integration test")
	}

	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	// Only Python is supported currently
	tests := []struct {
		name     string
		language string
		template string
		files    []string // Expected files to be created
	}{
		{
			name:     "python basic template",
			language: "python",
			template: "basic",
			files: []string{
				"__init__.py",
				"__main__.py",
				"main.py",
				"README.md",
				"requirements.txt",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			outputDir := filepath.Join(tmpDir, tt.language)
			agentName := "test-" + tt.language + "-agent"

			ctx := &ScaffoldContext{
				Name:        agentName,
				Description: "Integration test agent",
				Language:    tt.language,
				OutputDir:   outputDir,
				Port:        9100,
				Template:    tt.template,
				TemplateDir: templateDir,
			}

			err := provider.Execute(ctx)
			require.NoError(t, err)

			// Verify expected files exist
			agentDir := filepath.Join(outputDir, agentName)
			for _, file := range tt.files {
				filePath := filepath.Join(agentDir, file)
				assert.FileExists(t, filePath, "Expected file %s to exist", file)
			}

			// Verify content contains agent name
			readmePath := filepath.Join(agentDir, "README.md")
			content, err := os.ReadFile(readmePath)
			require.NoError(t, err)
			assert.Contains(t, string(content), agentName)
			assert.Contains(t, string(content), "9100")
		})
	}
}

func TestIntegration_ScaffoldPythonAgentContent(t *testing.T) {
	projectRoot := getProjectRoot()
	templateDir := filepath.Join(projectRoot, "templates")
	if _, err := os.Stat(templateDir); os.IsNotExist(err) {
		t.Skip("Built-in templates not found, skipping integration test")
	}

	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	ctx := &ScaffoldContext{
		Name:        "weather-service",
		Description: "A weather data service agent",
		Language:    "python",
		OutputDir:   tmpDir,
		Port:        9200,
		Template:    "basic",
		TemplateDir: templateDir,
	}

	err := provider.Execute(ctx)
	require.NoError(t, err)

	agentDir := filepath.Join(tmpDir, "weather-service")

	// Check main.py content
	mainContent, err := os.ReadFile(filepath.Join(agentDir, "main.py"))
	require.NoError(t, err)
	assert.Contains(t, string(mainContent), "weather-service")
	assert.Contains(t, string(mainContent), "WeatherServiceAgent")
	assert.Contains(t, string(mainContent), "9200")
	assert.Contains(t, string(mainContent), "@mesh.agent")
	assert.Contains(t, string(mainContent), "@mesh.tool")
	assert.Contains(t, string(mainContent), "@app.tool")
	assert.Contains(t, string(mainContent), "FastMCP")
	assert.Contains(t, string(mainContent), "A weather data service agent")

	// Check __init__.py content
	initContent, err := os.ReadFile(filepath.Join(agentDir, "__init__.py"))
	require.NoError(t, err)
	assert.Contains(t, string(initContent), "WeatherService")

	// Check README.md content
	readmeContent, err := os.ReadFile(filepath.Join(agentDir, "README.md"))
	require.NoError(t, err)
	assert.Contains(t, string(readmeContent), "weather-service")
	assert.Contains(t, string(readmeContent), "mesh run main.py")
}

func TestIntegration_ScaffoldWithMESHCTL_TEMPLATE_DIR(t *testing.T) {
	projectRoot := getProjectRoot()
	templateDir := filepath.Join(projectRoot, "templates")
	if _, err := os.Stat(templateDir); os.IsNotExist(err) {
		t.Skip("Built-in templates not found, skipping integration test")
	}

	// Set environment variable
	t.Setenv("MESHCTL_TEMPLATE_DIR", templateDir)

	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	ctx := &ScaffoldContext{
		Name:      "env-test-agent",
		Language:  "python",
		OutputDir: tmpDir,
		Port:      8080,
		Template:  "basic",
		// No TemplateDir - should use env var
	}

	err := provider.Execute(ctx)
	require.NoError(t, err)

	// Verify output exists
	assert.DirExists(t, filepath.Join(tmpDir, "env-test-agent"))
	assert.FileExists(t, filepath.Join(tmpDir, "env-test-agent", "main.py"))
	assert.FileExists(t, filepath.Join(tmpDir, "env-test-agent", "__init__.py"))
	assert.FileExists(t, filepath.Join(tmpDir, "env-test-agent", "__main__.py"))
}
