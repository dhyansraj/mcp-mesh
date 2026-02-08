package cli

import (
	"bytes"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewScaffoldCommand(t *testing.T) {
	cmd := NewScaffoldCommand()

	assert.Equal(t, "scaffold", cmd.Use)
	assert.NotEmpty(t, cmd.Short)
	assert.NotEmpty(t, cmd.Long)
}

func TestScaffoldCommand_HasCommonFlags(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Common flags
	assert.NotNil(t, cmd.Flags().Lookup("mode"))
	assert.NotNil(t, cmd.Flags().Lookup("name"))
	assert.NotNil(t, cmd.Flags().Lookup("lang"))
	assert.NotNil(t, cmd.Flags().Lookup("output"))
	assert.NotNil(t, cmd.Flags().Lookup("port"))
	assert.NotNil(t, cmd.Flags().Lookup("description"))
	assert.NotNil(t, cmd.Flags().Lookup("list-modes"))
}

func TestScaffoldCommand_HasStaticFlags(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Static provider flags
	assert.NotNil(t, cmd.Flags().Lookup("template"))
	assert.NotNil(t, cmd.Flags().Lookup("template-dir"))
	assert.NotNil(t, cmd.Flags().Lookup("config"))
}

func TestScaffoldCommand_HasLLMFlags(t *testing.T) {
	cmd := NewScaffoldCommand()

	// LLM provider flags
	assert.NotNil(t, cmd.Flags().Lookup("from-doc"))
	assert.NotNil(t, cmd.Flags().Lookup("prompt"))
	assert.NotNil(t, cmd.Flags().Lookup("provider"))
	assert.NotNil(t, cmd.Flags().Lookup("validate"))

	// api-key flag should NOT exist (uses env vars instead)
	assert.Nil(t, cmd.Flags().Lookup("api-key"))
}

func TestScaffoldCommand_DefaultMode(t *testing.T) {
	cmd := NewScaffoldCommand()

	mode, err := cmd.Flags().GetString("mode")
	require.NoError(t, err)
	assert.Equal(t, "static", mode)
}

func TestScaffoldCommand_DefaultLanguage(t *testing.T) {
	cmd := NewScaffoldCommand()

	lang, err := cmd.Flags().GetString("lang")
	require.NoError(t, err)
	assert.Equal(t, "python", lang)
}

func TestScaffoldCommand_DefaultPort(t *testing.T) {
	cmd := NewScaffoldCommand()

	port, err := cmd.Flags().GetInt("port")
	require.NoError(t, err)
	assert.Equal(t, 8080, port)
}

func TestScaffoldCommand_DefaultOutput(t *testing.T) {
	cmd := NewScaffoldCommand()

	output, err := cmd.Flags().GetString("output")
	require.NoError(t, err)
	assert.Equal(t, ".", output)
}

func TestScaffoldCommand_ListModes(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Execute with --list-modes flag
	cmd.SetArgs([]string{"--list-modes"})
	out := bytes.NewBufferString("")
	cmd.SetOut(out)

	err := cmd.Execute()
	require.NoError(t, err)

	output := out.String()
	assert.Contains(t, output, "static")
	assert.Contains(t, output, "llm")
	assert.Contains(t, output, "Available scaffold modes")
}

func TestScaffoldCommand_MissingName(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Execute without name (use --no-interactive to skip interactive wizard)
	cmd.SetArgs([]string{"--mode", "static", "--no-interactive"})
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "name is required")
}

func TestScaffoldCommand_InvalidMode(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Execute with invalid mode
	cmd.SetArgs([]string{"--mode", "invalid", "--name", "test-agent"})
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not found")
}

func TestScaffoldCommand_StaticModeNoTemplates(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Execute static mode without templates directory available
	cmd.SetArgs([]string{
		"--mode", "static",
		"--name", "test-agent",
		"--lang", "python",
		"--template", "basic",
	})

	err := cmd.Execute()
	require.Error(t, err)
	// Should fail because no template directory is found
	assert.Contains(t, err.Error(), "template")
}

func TestScaffoldCommand_LLMModeNotImplemented(t *testing.T) {
	// Set API key env var for test
	t.Setenv("ANTHROPIC_API_KEY", "test-key")

	cmd := NewScaffoldCommand()

	// Execute LLM mode (stub)
	cmd.SetArgs([]string{
		"--mode", "llm",
		"--name", "test-agent",
		"--prompt", "Create a weather agent",
	})

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "not implemented")
}

func TestScaffoldCommand_LLMModeValidation(t *testing.T) {
	// Set API key env var for test
	t.Setenv("ANTHROPIC_API_KEY", "test-key")

	cmd := NewScaffoldCommand()

	// Execute LLM mode without prompt or from-doc
	cmd.SetArgs([]string{
		"--mode", "llm",
		"--name", "test-agent",
	})

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "either --from-doc or --prompt required")
}

func TestScaffoldCommand_InvalidLanguage(t *testing.T) {
	cmd := NewScaffoldCommand()

	cmd.SetArgs([]string{
		"--mode", "static",
		"--name", "test-agent",
		"--lang", "cobol",
	})

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported language")
}

func TestScaffoldCommand_InvalidTemplate(t *testing.T) {
	cmd := NewScaffoldCommand()

	cmd.SetArgs([]string{
		"--mode", "static",
		"--name", "test-agent",
		"--template", "nonexistent",
	})

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported template")
}

func TestScaffoldCommand_ShortFlags(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Test short flags exist
	assert.NotNil(t, cmd.Flags().ShorthandLookup("n")) // --name
	assert.NotNil(t, cmd.Flags().ShorthandLookup("l")) // --lang
	assert.NotNil(t, cmd.Flags().ShorthandLookup("o")) // --output
	assert.NotNil(t, cmd.Flags().ShorthandLookup("t")) // --template
	assert.NotNil(t, cmd.Flags().ShorthandLookup("p")) // --port
}
