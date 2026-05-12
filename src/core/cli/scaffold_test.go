package cli

import (
	"bytes"
	"strings"
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

// TestScaffoldCommand_AgentTypeAliasHidden verifies the deprecated
// --agent-type flag is restored but hidden from --help output.
func TestScaffoldCommand_AgentTypeAliasHidden(t *testing.T) {
	cmd := NewScaffoldCommand()

	f := cmd.Flags().Lookup("agent-type")
	require.NotNil(t, f, "--agent-type alias must be registered for back-compat")
	assert.True(t, f.Hidden, "--agent-type should be hidden from --help")
}

// TestScaffoldCommand_AgentTypeRoutesToBasic verifies the deprecated
// `--agent-type tool` form routes to the `basic` subcommand and emits
// the deprecation warning to stderr.
func TestScaffoldCommand_AgentTypeRoutesToBasic(t *testing.T) {
	cmd := NewScaffoldCommand()
	out := bytes.NewBufferString("")
	errOut := bytes.NewBufferString("")
	cmd.SetOut(out)
	cmd.SetErr(errOut)
	cmd.SetArgs([]string{
		"--name", "foo",
		"--agent-type", "tool",
		"--no-interactive",
		"--dry-run",
	})

	// Execution may fail downstream (template/asset lookups depend on the
	// binary's embedded template dir which is not present in unit tests);
	// the contract we are testing is the routing + deprecation warning.
	_ = cmd.Execute()

	stderr := errOut.String()
	assert.Contains(t, stderr, "--agent-type is deprecated",
		"expected deprecation warning on stderr, got:\n%s", stderr)
	assert.Contains(t, stderr, "scaffold basic",
		"expected mapping mention in deprecation warning, got:\n%s", stderr)
}

// TestScaffoldCommand_AgentTypeLLMAgentRoutesToLLM verifies that the
// `llm-agent` value maps to the `llm` subcommand, and that the legacy
// parent `--llm-selector` value translates onto the subcommand's
// `--vendor` flag.
func TestScaffoldCommand_AgentTypeLLMAgentRoutesToLLM(t *testing.T) {
	cmd := NewScaffoldCommand()
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo",
		"--agent-type", "llm-agent",
		"--llm-selector", "claude",
		"--response-format", "json",
		"--no-interactive",
		"--dry-run",
	})

	_ = cmd.Execute()

	stderr := errOut.String()
	assert.Contains(t, stderr, "scaffold llm",
		"expected llm-agent to map to 'scaffold llm', got stderr:\n%s", stderr)
}

// TestScaffoldCommand_AgentTypeAPIErrors verifies the removed `api`
// value produces a clear error referencing the deployment man page.
func TestScaffoldCommand_AgentTypeAPIErrors(t *testing.T) {
	cmd := NewScaffoldCommand()
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetErr(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo",
		"--agent-type", "api",
		"--no-interactive",
	})

	err := cmd.Execute()
	require.Error(t, err)
	msg := err.Error()
	assert.Contains(t, msg, "'api' agent type was removed",
		"expected explicit removal message, got: %s", msg)
	assert.True(t,
		strings.Contains(msg, "meshctl man deployment") ||
			strings.Contains(msg, "man deployment"),
		"expected pointer to deployment docs, got: %s", msg)
}

// TestScaffoldCommand_AgentTypeUnknownErrors verifies that an unknown
// --agent-type value errors with a helpful list of valid values.
func TestScaffoldCommand_AgentTypeUnknownErrors(t *testing.T) {
	cmd := NewScaffoldCommand()
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetErr(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo",
		"--agent-type", "bogus",
		"--no-interactive",
	})

	err := cmd.Execute()
	require.Error(t, err)
	msg := err.Error()
	assert.Contains(t, msg, "unknown --agent-type value")
	assert.Contains(t, msg, "bogus")
	assert.Contains(t, msg, "tool")
	assert.Contains(t, msg, "llm-agent")
	assert.Contains(t, msg, "llm-provider")
}

// TestCopyParentFlagsToSub_LLMSelectorTranslatesToVendor verifies the
// legacy parent `--llm-selector` flag value lands on the subcommand's
// `--vendor` flag (cross-name alias).
func TestCopyParentFlagsToSub_LLMSelectorTranslatesToVendor(t *testing.T) {
	parent := NewScaffoldCommand()
	require.NoError(t, parent.Flags().Set("llm-selector", "openai"))

	sub, _, err := parent.Find([]string{"llm"})
	require.NoError(t, err)
	require.NotNil(t, sub)

	copyParentFlagsToSub(parent, sub)

	got, err := sub.Flags().GetString("vendor")
	require.NoError(t, err)
	assert.Equal(t, "openai", got)
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
