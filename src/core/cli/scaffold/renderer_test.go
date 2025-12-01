package scaffold

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewTemplateRenderer(t *testing.T) {
	renderer := NewTemplateRenderer()

	assert.NotNil(t, renderer)
}

func TestTemplateRenderer_RenderString(t *testing.T) {
	renderer := NewTemplateRenderer()

	tests := []struct {
		name     string
		template string
		data     map[string]interface{}
		expected string
		wantErr  bool
	}{
		{
			name:     "simple variable substitution",
			template: "Hello, {{ .Name }}!",
			data:     map[string]interface{}{"Name": "World"},
			expected: "Hello, World!",
			wantErr:  false,
		},
		{
			name:     "multiple variables",
			template: "Agent: {{ .Name }}, Port: {{ .Port }}",
			data:     map[string]interface{}{"Name": "my-agent", "Port": 9000},
			expected: "Agent: my-agent, Port: 9000",
			wantErr:  false,
		},
		{
			name:     "nested data",
			template: "{{ .Agent.Name }} runs on {{ .Agent.Port }}",
			data: map[string]interface{}{
				"Agent": map[string]interface{}{
					"Name": "weather-agent",
					"Port": 9100,
				},
			},
			expected: "weather-agent runs on 9100",
			wantErr:  false,
		},
		{
			name:     "conditional",
			template: "{{ if .Description }}Desc: {{ .Description }}{{ else }}No description{{ end }}",
			data:     map[string]interface{}{"Description": "A test agent"},
			expected: "Desc: A test agent",
			wantErr:  false,
		},
		{
			name:     "conditional empty",
			template: "{{ if .Description }}Desc: {{ .Description }}{{ else }}No description{{ end }}",
			data:     map[string]interface{}{"Description": ""},
			expected: "No description",
			wantErr:  false,
		},
		{
			name:     "range over slice",
			template: "Tools: {{ range .Tools }}{{ . }} {{ end }}",
			data:     map[string]interface{}{"Tools": []string{"tool1", "tool2", "tool3"}},
			expected: "Tools: tool1 tool2 tool3 ",
			wantErr:  false,
		},
		{
			name:     "invalid template syntax",
			template: "{{ .Name",
			data:     map[string]interface{}{"Name": "test"},
			expected: "",
			wantErr:  true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := renderer.RenderString(tt.template, tt.data)
			if tt.wantErr {
				require.Error(t, err)
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expected, result)
			}
		})
	}
}

func TestTemplateRenderer_RenderString_HelperFunctions(t *testing.T) {
	renderer := NewTemplateRenderer()

	tests := []struct {
		name     string
		template string
		data     map[string]interface{}
		expected string
	}{
		{
			name:     "toUpper function",
			template: "{{ toUpper .Name }}",
			data:     map[string]interface{}{"Name": "my-agent"},
			expected: "MY-AGENT",
		},
		{
			name:     "toLower function",
			template: "{{ toLower .Name }}",
			data:     map[string]interface{}{"Name": "MY-AGENT"},
			expected: "my-agent",
		},
		{
			name:     "toSnakeCase function",
			template: "{{ toSnakeCase .Name }}",
			data:     map[string]interface{}{"Name": "my-agent"},
			expected: "my_agent",
		},
		{
			name:     "toCamelCase function",
			template: "{{ toCamelCase .Name }}",
			data:     map[string]interface{}{"Name": "my-agent"},
			expected: "myAgent",
		},
		{
			name:     "toPascalCase function",
			template: "{{ toPascalCase .Name }}",
			data:     map[string]interface{}{"Name": "my-agent"},
			expected: "MyAgent",
		},
		{
			name:     "toKebabCase function",
			template: "{{ toKebabCase .Name }}",
			data:     map[string]interface{}{"Name": "my_agent"},
			expected: "my-agent",
		},
		{
			name:     "default function with value",
			template: "{{ default \"unknown\" .Name }}",
			data:     map[string]interface{}{"Name": "my-agent"},
			expected: "my-agent",
		},
		{
			name:     "default function without value",
			template: "{{ default \"unknown\" .Name }}",
			data:     map[string]interface{}{"Name": ""},
			expected: "unknown",
		},
		{
			name:     "indent function",
			template: "{{ indent 4 .Code }}",
			data:     map[string]interface{}{"Code": "line1\nline2"},
			expected: "    line1\n    line2",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := renderer.RenderString(tt.template, tt.data)
			require.NoError(t, err)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestTemplateRenderer_RenderFile(t *testing.T) {
	renderer := NewTemplateRenderer()

	// Create temp directory with template file
	tmpDir := t.TempDir()
	templatePath := filepath.Join(tmpDir, "test.tmpl")
	err := os.WriteFile(templatePath, []byte("Agent: {{ .Name }}\nPort: {{ .Port }}"), 0644)
	require.NoError(t, err)

	data := map[string]interface{}{
		"Name": "my-agent",
		"Port": 9000,
	}

	result, err := renderer.RenderFile(templatePath, data)
	require.NoError(t, err)
	assert.Equal(t, "Agent: my-agent\nPort: 9000", result)
}

func TestTemplateRenderer_RenderFile_NotFound(t *testing.T) {
	renderer := NewTemplateRenderer()

	_, err := renderer.RenderFile("/nonexistent/file.tmpl", nil)
	require.Error(t, err)
}

func TestTemplateRenderer_RenderToFile(t *testing.T) {
	renderer := NewTemplateRenderer()
	tmpDir := t.TempDir()

	// Create template
	templateContent := "# {{ .Name }}\n\nDescription: {{ .Description }}"
	outputPath := filepath.Join(tmpDir, "output.md")

	data := map[string]interface{}{
		"Name":        "my-agent",
		"Description": "A test agent",
	}

	err := renderer.RenderToFile(templateContent, data, outputPath)
	require.NoError(t, err)

	// Verify output file
	content, err := os.ReadFile(outputPath)
	require.NoError(t, err)
	assert.Equal(t, "# my-agent\n\nDescription: A test agent", string(content))
}

func TestTemplateRenderer_RenderToFile_CreatesDirectories(t *testing.T) {
	renderer := NewTemplateRenderer()
	tmpDir := t.TempDir()

	// Output path with nested directories
	outputPath := filepath.Join(tmpDir, "nested", "dir", "output.txt")

	err := renderer.RenderToFile("Hello {{ .Name }}", map[string]interface{}{"Name": "World"}, outputPath)
	require.NoError(t, err)

	content, err := os.ReadFile(outputPath)
	require.NoError(t, err)
	assert.Equal(t, "Hello World", string(content))
}

func TestTemplateRenderer_RenderDirectory(t *testing.T) {
	renderer := NewTemplateRenderer()
	tmpDir := t.TempDir()

	// Create source template directory
	srcDir := filepath.Join(tmpDir, "templates")
	require.NoError(t, os.MkdirAll(srcDir, 0755))

	// Create template files
	require.NoError(t, os.WriteFile(
		filepath.Join(srcDir, "main.py.tmpl"),
		[]byte("# {{ .Name }}\nport = {{ .Port }}"),
		0644,
	))
	require.NoError(t, os.WriteFile(
		filepath.Join(srcDir, "README.md.tmpl"),
		[]byte("# {{ .Name }}\n{{ .Description }}"),
		0644,
	))

	// Create subdirectory with template
	require.NoError(t, os.MkdirAll(filepath.Join(srcDir, "src"), 0755))
	require.NoError(t, os.WriteFile(
		filepath.Join(srcDir, "src", "agent.py.tmpl"),
		[]byte("class {{ toPascalCase .Name }}Agent:\n    pass"),
		0644,
	))

	// Output directory
	outDir := filepath.Join(tmpDir, "output")

	data := map[string]interface{}{
		"Name":        "my-agent",
		"Port":        9000,
		"Description": "A test agent",
	}

	err := renderer.RenderDirectory(srcDir, outDir, data)
	require.NoError(t, err)

	// Verify output files (without .tmpl extension)
	mainContent, err := os.ReadFile(filepath.Join(outDir, "main.py"))
	require.NoError(t, err)
	assert.Equal(t, "# my-agent\nport = 9000", string(mainContent))

	readmeContent, err := os.ReadFile(filepath.Join(outDir, "README.md"))
	require.NoError(t, err)
	assert.Equal(t, "# my-agent\nA test agent", string(readmeContent))

	agentContent, err := os.ReadFile(filepath.Join(outDir, "src", "agent.py"))
	require.NoError(t, err)
	assert.Equal(t, "class MyAgentAgent:\n    pass", string(agentContent))
}

func TestTemplateRenderer_RenderDirectory_PreservesNonTemplates(t *testing.T) {
	renderer := NewTemplateRenderer()
	tmpDir := t.TempDir()

	// Create source directory
	srcDir := filepath.Join(tmpDir, "templates")
	require.NoError(t, os.MkdirAll(srcDir, 0755))

	// Create a template file and a non-template file
	require.NoError(t, os.WriteFile(
		filepath.Join(srcDir, "config.yaml.tmpl"),
		[]byte("name: {{ .Name }}"),
		0644,
	))
	require.NoError(t, os.WriteFile(
		filepath.Join(srcDir, "static.txt"),
		[]byte("This is static content"),
		0644,
	))

	outDir := filepath.Join(tmpDir, "output")

	err := renderer.RenderDirectory(srcDir, outDir, map[string]interface{}{"Name": "test"})
	require.NoError(t, err)

	// Template file should be rendered (without .tmpl)
	configContent, err := os.ReadFile(filepath.Join(outDir, "config.yaml"))
	require.NoError(t, err)
	assert.Equal(t, "name: test", string(configContent))

	// Static file should be copied as-is
	staticContent, err := os.ReadFile(filepath.Join(outDir, "static.txt"))
	require.NoError(t, err)
	assert.Equal(t, "This is static content", string(staticContent))
}

func TestTemplateRenderer_RenderDirectory_FilenameTemplating(t *testing.T) {
	renderer := NewTemplateRenderer()
	tmpDir := t.TempDir()

	// Create source directory
	srcDir := filepath.Join(tmpDir, "templates")
	require.NoError(t, os.MkdirAll(srcDir, 0755))

	// Create template file with templated filename
	require.NoError(t, os.WriteFile(
		filepath.Join(srcDir, "{{.Name}}.py.tmpl"),
		[]byte("# Agent: {{ .Name }}"),
		0644,
	))

	outDir := filepath.Join(tmpDir, "output")

	err := renderer.RenderDirectory(srcDir, outDir, map[string]interface{}{"Name": "weather-agent"})
	require.NoError(t, err)

	// File should be named after the agent
	content, err := os.ReadFile(filepath.Join(outDir, "weather-agent.py"))
	require.NoError(t, err)
	assert.Equal(t, "# Agent: weather-agent", string(content))
}

func TestTemplateData_FromContext(t *testing.T) {
	ctx := &ScaffoldContext{
		Name:        "my-agent",
		Description: "A test agent",
		Language:    "python",
		OutputDir:   "./output",
		Port:        9100,
		Template:    "basic",
	}

	data := TemplateDataFromContext(ctx)

	assert.Equal(t, "my-agent", data["Name"])
	assert.Equal(t, "A test agent", data["Description"])
	assert.Equal(t, "python", data["Language"])
	assert.Equal(t, 9100, data["Port"])
	assert.Equal(t, "basic", data["Template"])

	// Check computed fields
	assert.Equal(t, "my_agent", data["NameSnake"])
	assert.Equal(t, "myAgent", data["NameCamel"])
	assert.Equal(t, "MyAgent", data["NamePascal"])
	assert.Equal(t, "my-agent", data["NameKebab"])
}
