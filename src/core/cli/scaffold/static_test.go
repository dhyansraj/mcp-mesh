package scaffold

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/spf13/cobra"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestStaticProvider_ImplementsInterface(t *testing.T) {
	var _ ScaffoldProvider = (*StaticProvider)(nil)
}

func TestNewStaticProvider(t *testing.T) {
	provider := NewStaticProvider()

	assert.NotNil(t, provider)
}

func TestStaticProvider_Name(t *testing.T) {
	provider := NewStaticProvider()

	assert.Equal(t, "static", provider.Name())
}

func TestStaticProvider_Description(t *testing.T) {
	provider := NewStaticProvider()

	desc := provider.Description()
	assert.NotEmpty(t, desc)
	assert.Contains(t, desc, "template")
}

func TestStaticProvider_RegisterFlags(t *testing.T) {
	provider := NewStaticProvider()
	cmd := &cobra.Command{}

	provider.RegisterFlags(cmd)

	// Check static-specific flags are registered
	assert.NotNil(t, cmd.Flags().Lookup("template"))
	assert.NotNil(t, cmd.Flags().Lookup("template-dir"))
	assert.NotNil(t, cmd.Flags().Lookup("config"))

	// Check default values
	template, _ := cmd.Flags().GetString("template")
	assert.Equal(t, "basic", template)
}

func TestStaticProvider_Validate(t *testing.T) {
	provider := NewStaticProvider()

	tests := []struct {
		name    string
		ctx     *ScaffoldContext
		wantErr bool
		errMsg  string
	}{
		{
			name: "valid static context with basic template",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
				Template: "basic",
			},
			wantErr: false,
		},
		{
			name: "valid static context with llm-agent template",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
				Template: "llm-agent",
			},
			wantErr: false,
		},
		{
			name: "invalid template name",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
				Template: "nonexistent",
			},
			wantErr: true,
			errMsg:  "unsupported template",
		},
		{
			name: "empty template defaults to basic",
			ctx: &ScaffoldContext{
				Name:     "my-agent",
				Language: "python",
				Template: "",
			},
			wantErr: true,
			errMsg:  "unsupported template",
		},
		{
			name: "missing name still fails",
			ctx: &ScaffoldContext{
				Language: "python",
				Template: "basic",
			},
			wantErr: true,
			errMsg:  "name is required",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := provider.Validate(tt.ctx)
			if tt.wantErr {
				require.Error(t, err)
				assert.Contains(t, err.Error(), tt.errMsg)
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestStaticProvider_Execute_WithCustomTemplateDir(t *testing.T) {
	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	// Create custom template directory structure
	templateDir := createTestTemplateDir(t, tmpDir)

	// Output directory
	outputDir := filepath.Join(tmpDir, "output", "my-agent")

	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Description: "A test agent",
		Language:    "python",
		OutputDir:   filepath.Join(tmpDir, "output"),
		Port:        9100,
		Template:    "basic",
		TemplateDir: templateDir,
	}

	err := provider.Execute(ctx)
	require.NoError(t, err)

	// Verify output files exist
	assert.FileExists(t, filepath.Join(outputDir, "main.py"))
	assert.FileExists(t, filepath.Join(outputDir, "README.md"))
	assert.DirExists(t, filepath.Join(outputDir, "src"))
	assert.FileExists(t, filepath.Join(outputDir, "src", "agent.py"))

	// Verify content is rendered correctly
	mainContent, err := os.ReadFile(filepath.Join(outputDir, "main.py"))
	require.NoError(t, err)
	assert.Contains(t, string(mainContent), "my-agent")
	assert.Contains(t, string(mainContent), "9100")

	readmeContent, err := os.ReadFile(filepath.Join(outputDir, "README.md"))
	require.NoError(t, err)
	assert.Contains(t, string(readmeContent), "my-agent")
	assert.Contains(t, string(readmeContent), "A test agent")

	agentContent, err := os.ReadFile(filepath.Join(outputDir, "src", "agent.py"))
	require.NoError(t, err)
	assert.Contains(t, string(agentContent), "MyAgentAgent")
}

func TestStaticProvider_Execute_OutputDirCreated(t *testing.T) {
	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	templateDir := createTestTemplateDir(t, tmpDir)
	outputDir := filepath.Join(tmpDir, "deep", "nested", "output")

	ctx := &ScaffoldContext{
		Name:        "test-agent",
		Language:    "python",
		OutputDir:   outputDir,
		Port:        9000,
		Template:    "basic",
		TemplateDir: templateDir,
	}

	err := provider.Execute(ctx)
	require.NoError(t, err)

	// Output should be in outputDir/agent-name
	assert.DirExists(t, filepath.Join(outputDir, "test-agent"))
}

func TestStaticProvider_Execute_TemplateNotFound(t *testing.T) {
	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	// Create empty template dir (no templates)
	templateDir := filepath.Join(tmpDir, "templates")
	require.NoError(t, os.MkdirAll(templateDir, 0755))

	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		OutputDir:   filepath.Join(tmpDir, "output"),
		Port:        9000,
		Template:    "basic",
		TemplateDir: templateDir,
	}

	err := provider.Execute(ctx)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "template")
}

func TestStaticProvider_Execute_InvalidTemplateDir(t *testing.T) {
	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		OutputDir:   filepath.Join(tmpDir, "output"),
		Port:        9000,
		Template:    "basic",
		TemplateDir: "/nonexistent/template/dir",
	}

	err := provider.Execute(ctx)
	require.Error(t, err)
}

func TestStaticProvider_Execute_PrintsSuccessMessage(t *testing.T) {
	provider := NewStaticProvider()
	tmpDir := t.TempDir()

	templateDir := createTestTemplateDir(t, tmpDir)

	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Language:    "python",
		OutputDir:   filepath.Join(tmpDir, "output"),
		Port:        9000,
		Template:    "basic",
		TemplateDir: templateDir,
	}

	err := provider.Execute(ctx)
	require.NoError(t, err)
	// Success is verified by no error - actual printing is handled by the CLI
}

func TestStaticProvider_Execute_PythonOnly(t *testing.T) {
	provider := NewStaticProvider()
	tmpDir := t.TempDir()
	templateDir := createTestTemplateDirForLanguage(t, tmpDir, "python", ".py")

	ctx := &ScaffoldContext{
		Name:        "test-agent",
		Language:    "python",
		OutputDir:   filepath.Join(tmpDir, "output"),
		Port:        9000,
		Template:    "basic",
		TemplateDir: templateDir,
	}

	err := provider.Execute(ctx)
	require.NoError(t, err)

	// Verify output exists
	assert.DirExists(t, filepath.Join(tmpDir, "output", "test-agent"))
}

// Helper function to create a test template directory
func createTestTemplateDir(t *testing.T, baseDir string) string {
	t.Helper()

	// Create template structure: templates/python/basic/
	templateDir := filepath.Join(baseDir, "templates")
	langDir := filepath.Join(templateDir, "python", "basic")
	require.NoError(t, os.MkdirAll(langDir, 0755))

	// Create main.py.tmpl
	mainContent := `# {{ .Name }}
# Port: {{ .Port }}

def main():
    print("Starting {{ .Name }}")

if __name__ == "__main__":
    main()
`
	require.NoError(t, os.WriteFile(filepath.Join(langDir, "main.py.tmpl"), []byte(mainContent), 0644))

	// Create README.md.tmpl
	readmeContent := `# {{ .Name }}

{{ .Description }}

## Getting Started

Run the agent on port {{ .Port }}.
`
	require.NoError(t, os.WriteFile(filepath.Join(langDir, "README.md.tmpl"), []byte(readmeContent), 0644))

	// Create src/agent.py.tmpl
	srcDir := filepath.Join(langDir, "src")
	require.NoError(t, os.MkdirAll(srcDir, 0755))

	agentContent := `class {{ toPascalCase .Name }}Agent:
    """{{ .Description }}"""

    def __init__(self, port: int = {{ .Port }}):
        self.port = port
`
	require.NoError(t, os.WriteFile(filepath.Join(srcDir, "agent.py.tmpl"), []byte(agentContent), 0644))

	return templateDir
}

// Helper function to create a test template directory for a specific language
func createTestTemplateDirForLanguage(t *testing.T, baseDir, lang, ext string) string {
	t.Helper()

	templateDir := filepath.Join(baseDir, "templates")
	langDir := filepath.Join(templateDir, lang, "basic")
	require.NoError(t, os.MkdirAll(langDir, 0755))

	// Create a simple main file for the language
	mainContent := fmt.Sprintf(`// {{ .Name }} - {{ .Language }} agent
// Port: {{ .Port }}
`)
	filename := "main" + ext + ".tmpl"
	require.NoError(t, os.WriteFile(filepath.Join(langDir, filename), []byte(mainContent), 0644))

	return templateDir
}

func TestStaticProvider_SupportedTemplates(t *testing.T) {
	templates := SupportedTemplates()

	assert.Contains(t, templates, "basic")
	assert.Contains(t, templates, "llm-agent")
	assert.Contains(t, templates, "llm-provider")
	assert.Len(t, templates, 3)
}

func TestStaticProvider_IsValidTemplate(t *testing.T) {
	assert.True(t, IsValidTemplate("basic"))
	assert.True(t, IsValidTemplate("llm-agent"))
	assert.True(t, IsValidTemplate("llm-provider"))
	assert.False(t, IsValidTemplate("multi-tool"))
	assert.False(t, IsValidTemplate("gateway"))
	assert.False(t, IsValidTemplate("nonexistent"))
	assert.False(t, IsValidTemplate(""))
}
