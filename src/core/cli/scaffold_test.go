package cli

import (
	"bytes"
	"os"
	"path/filepath"
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
	assert.NotNil(t, cmd.Flags().Lookup("name"))
	assert.NotNil(t, cmd.Flags().Lookup("lang"))
	assert.NotNil(t, cmd.Flags().Lookup("output"))
	assert.NotNil(t, cmd.Flags().Lookup("port"))
	assert.NotNil(t, cmd.Flags().Lookup("description"))
}

// TestScaffoldCommand_DroppedFlagsAbsent asserts the dropped `mode llm`
// generation engine flags are gone. These flags were never released as a
// working feature (issue #999).
func TestScaffoldCommand_DroppedFlagsAbsent(t *testing.T) {
	cmd := NewScaffoldCommand()

	for _, name := range []string{"mode", "list-modes", "from-doc", "prompt", "validate"} {
		assert.Nil(t, cmd.Flags().Lookup(name),
			"--%s should be removed (see #999)", name)
	}
}

func TestScaffoldCommand_HasStaticFlags(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Static provider flags
	assert.NotNil(t, cmd.Flags().Lookup("template"))
	assert.NotNil(t, cmd.Flags().Lookup("template-dir"))
	assert.NotNil(t, cmd.Flags().Lookup("config"))
}

// TestScaffoldCommand_HasAPISubcommand verifies the `api` subcommand
// is wired alongside basic, llm, llm-provider, a2a-consumer (issue
// #1005). Reintroduced after the --agent-type api removal in #958
// orphaned the python/typescript/java/api template trees.
func TestScaffoldCommand_HasAPISubcommand(t *testing.T) {
	cmd := NewScaffoldCommand()

	sub, _, err := cmd.Find([]string{"api"})
	require.NoError(t, err)
	require.NotNil(t, sub)
	assert.Equal(t, "api", sub.Name(),
		"`meshctl scaffold api` must be registered as a subcommand")

	// Same flag surface as basic + tags.
	for _, name := range []string{"name", "lang", "output", "port", "description", "package", "tags", "dry-run", "no-interactive"} {
		assert.NotNil(t, sub.Flags().Lookup(name),
			"`scaffold api` must register --%s", name)
	}
}

// TestScaffoldCommand_HasKeepListFlags asserts the flags that back the
// deprecated `--agent-type llm-agent` / `--agent-type llm-provider` shims
// are still registered after the `mode llm` cleanup (#999).
func TestScaffoldCommand_HasKeepListFlags(t *testing.T) {
	cmd := NewScaffoldCommand()

	for _, name := range []string{"llm-selector", "model", "provider", "tool-name", "tool-description"} {
		assert.NotNil(t, cmd.Flags().Lookup(name),
			"--%s must remain on scaffold (back-compat for --agent-type shim, see #999)", name)
	}

	// api-key flag should NOT exist (uses env vars instead)
	assert.Nil(t, cmd.Flags().Lookup("api-key"))
}

// TestScaffoldCommand_LegacyParentFlagsHidden covers #1575: the parent
// --help listed pre-subcommand flags (--llm-selector, a never-read
// --provider, --template, --tool-name, the LLM knobs) as if they were the
// canonical UX. They stay registered for back-compat but are hidden.
func TestScaffoldCommand_LegacyParentFlagsHidden(t *testing.T) {
	cmd := NewScaffoldCommand()
	for _, d := range deprecatedParentFlags {
		f := cmd.Flags().Lookup(d.flag)
		require.NotNil(t, f, "--%s must stay registered for back-compat", d.flag)
		assert.Equal(t, !d.visible, f.Hidden, "--%s hidden state", d.flag)
	}

	var help bytes.Buffer
	cmd.SetOut(&help)
	cmd.SetArgs([]string{"--help"})
	require.NoError(t, cmd.Execute())
	for _, name := range []string{"--llm-selector", "--provider", "--tool-name", "--max-iterations", "--model", "--system-prompt"} {
		assert.NotContains(t, help.String(), name)
	}
	for _, name := range []string{"--compose", "--observability", "--config", "--project-name"} {
		assert.Contains(t, help.String(), name)
	}
	// --template stays visible because it is how --template-dir picks a
	// template, and both help texts say so.
	assert.Contains(t, help.String(), "Template name under --template-dir")
	assert.Contains(t, help.String(), "(pick the template with --template)")
}

// TestScaffoldCommand_LegacyParentFlagsWarn: every hidden legacy parent flag
// must announce its deprecation and name the canonical form when used.
func TestScaffoldCommand_LegacyParentFlagsWarn(t *testing.T) {
	cmd := NewScaffoldCommand()
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo", "--no-interactive", "--dry-run",
		"--llm-selector", "openai", "--provider", "openai", "--template", "llm-agent",
		"--tool-name", "t", "--tool-description", "d", "--max-iterations", "3",
		"--system-prompt", "p", "--response-format", "json", "--context-param", "c",
		"--filter", "x", "--filter-mode", "best_match", "--model", "openai/gpt-4o", "--tags", "a",
	})
	_ = cmd.Execute()

	stderr := errOut.String()
	for _, d := range deprecatedParentFlags {
		assert.Contains(t, stderr, "Warning: --"+d.flag+" on 'meshctl scaffold' is deprecated",
			"no deprecation warning for --%s; stderr:\n%s", d.flag, stderr)
		assert.Contains(t, stderr, "use "+d.use+" instead",
			"warning for --%s must name the canonical form; stderr:\n%s", d.flag, stderr)
	}
	assert.Contains(t, stderr, "--provider on 'meshctl scaffold' is deprecated and has no effect here")
}

// TestScaffoldCommand_TemplateWithTemplateDirIsNotDeprecated: with
// --template-dir, --template picks a subdirectory of the user's own template
// tree, which no subcommand can do, so it must not be called deprecated.
func TestScaffoldCommand_TemplateWithTemplateDirIsNotDeprecated(t *testing.T) {
	cmd := NewScaffoldCommand()
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo", "--no-interactive", "--dry-run",
		"--template-dir", t.TempDir(), "--template", "basic",
	})
	_ = cmd.Execute()
	assert.NotContains(t, errOut.String(), "--template on 'meshctl scaffold' is deprecated")
}

// TestScaffoldCommand_AgentTypeReportsRenamedAndDroppedFlags: through the
// --agent-type shim, --llm-selector is renamed to --vendor and flags the
// target subcommand lacks are dropped; both must be reported, not silent.
func TestScaffoldCommand_AgentTypeReportsRenamedAndDroppedFlags(t *testing.T) {
	cmd := NewScaffoldCommand()
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo", "--agent-type", "llm-agent", "--no-interactive", "--dry-run",
		"--llm-selector", "openai", "--model", "openai/gpt-4o", "--provider", "gemini",
	})
	_ = cmd.Execute()

	stderr := errOut.String()
	assert.Contains(t, stderr, "Warning: --llm-selector is deprecated; use --vendor instead.")
	assert.Contains(t, stderr, "Warning: --model is not supported by 'meshctl scaffold llm' and was ignored.")
	// Both vendor sources given: the message names --llm-selector, which is
	// where the shim's --vendor value came from, not a --vendor the user never typed.
	assert.Contains(t, stderr, "ignoring --provider because --llm-selector is also set")
	assert.NotContains(t, stderr, "because --vendor is also set")
}

// TestScaffoldCommand_AgentTypeProviderAloneWarnsOnSub: without
// --llm-selector, --provider is forwarded to the subcommand's alias, which
// warns for itself.
func TestScaffoldCommand_AgentTypeProviderAloneWarnsOnSub(t *testing.T) {
	cmd := NewScaffoldCommand()
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo", "--agent-type", "llm-agent", "--no-interactive", "--dry-run",
		"--provider", "gemini",
	})
	_ = cmd.Execute()
	assert.Contains(t, errOut.String(), "Warning: --provider is deprecated; use --vendor instead.")
}

// TestScaffoldCommand_AgentTypeReportsDroppedNonDeprecatedFlags: parent-only
// flags such as --template-dir and --config have no meaning on the target
// subcommand; the shim must say it ignored them.
func TestScaffoldCommand_AgentTypeReportsDroppedNonDeprecatedFlags(t *testing.T) {
	cmd := NewScaffoldCommand()
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "foo", "--agent-type", "tool", "--no-interactive", "--dry-run",
		"--template-dir", t.TempDir(), "--config", "x.yaml",
	})
	_ = cmd.Execute()
	stderr := errOut.String()
	assert.Contains(t, stderr, "Warning: --template-dir is not supported by 'meshctl scaffold basic' and was ignored.")
	assert.Contains(t, stderr, "Warning: --config is not supported by 'meshctl scaffold basic' and was ignored.")
	assert.NotContains(t, stderr, "--name is not supported")
	assert.NotContains(t, stderr, "--agent-type is not supported")
}

// TestScaffoldCommand_ComposeDryRunWritesNothing: --compose --dry-run prints
// the YAML to stdout and leaves the directory untouched.
func TestScaffoldCommand_ComposeDryRunWritesNothing(t *testing.T) {
	dir := t.TempDir()
	require.NoError(t, os.MkdirAll(filepath.Join(dir, "a1"), 0755))
	require.NoError(t, os.WriteFile(filepath.Join(dir, "a1", "main.py"),
		[]byte("import mesh\n@mesh.agent(name=\"a1\", http_port=9501)\nclass A: pass\n"), 0644))

	cmd := NewScaffoldCommand()
	out := bytes.NewBufferString("")
	cmd.SetOut(out)
	cmd.SetErr(bytes.NewBufferString(""))
	cmd.SetArgs([]string{"--compose", "--observability", "--dry-run", "-o", dir})
	require.NoError(t, cmd.Execute())

	assert.Contains(t, out.String(), "a1:")
	assert.Contains(t, out.String(), `"9501:9501"`)
	assert.NoFileExists(t, filepath.Join(dir, "docker-compose.yml"))
	assert.NoFileExists(t, filepath.Join(dir, "tempo.yaml"))
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

func TestScaffoldCommand_MissingName(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Execute without name (use --no-interactive to skip interactive wizard)
	cmd.SetArgs([]string{"--no-interactive"})
	errOut := bytes.NewBufferString("")
	cmd.SetErr(errOut)

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "name is required")
}

func TestScaffoldCommand_StaticModeNoTemplates(t *testing.T) {
	cmd := NewScaffoldCommand()

	// Execute without templates directory available
	cmd.SetArgs([]string{
		"--name", "test-agent",
		"--lang", "python",
		"--template", "basic",
	})

	err := cmd.Execute()
	require.Error(t, err)
	// Should fail because no template directory is found
	assert.Contains(t, err.Error(), "template")
}

func TestScaffoldCommand_InvalidLanguage(t *testing.T) {
	cmd := NewScaffoldCommand()

	cmd.SetArgs([]string{
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

// TestScaffoldCommand_AgentTypeAPIErrors verifies the legacy
// `--agent-type api` form errors with a pointer to the new
// `meshctl scaffold api` subcommand. The subcommand was reintroduced
// in #1005 but the legacy --agent-type flag is being retired
// holistically, so api is intentionally not shimmed.
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
	assert.Contains(t, msg, "'--agent-type api' form was removed",
		"expected explicit removal message, got: %s", msg)
	assert.Contains(t, msg, "meshctl scaffold api",
		"expected pointer to the new subcommand, got: %s", msg)
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

// TestCopyParentFlagsToSub_FilterPropagatesToLLMSub asserts the parent's
// `--filter` (and friends) value lands on the `llm` subcommand's same-named
// flag after copyParentFlagsToSub runs. This is the wiring that backs the
// deprecated `meshctl scaffold --agent-type llm-agent --filter ...` form —
// if the sub doesn't register `--filter`, the value silently disappears.
// See review feedback on PR for issue #956.
func TestCopyParentFlagsToSub_FilterPropagatesToLLMSub(t *testing.T) {
	parent := NewScaffoldCommand()
	require.NoError(t, parent.Flags().Set("filter", `{"capability":"x"}`))
	require.NoError(t, parent.Flags().Set("filter-mode", "best_match"))
	require.NoError(t, parent.Flags().Set("context-param", "myctx"))
	require.NoError(t, parent.Flags().Set("tags", "alpha,beta"))

	for _, subName := range []string{"llm", "llm-provider"} {
		t.Run(subName, func(t *testing.T) {
			sub, _, err := parent.Find([]string{subName})
			require.NoError(t, err)
			require.NotNil(t, sub)

			// Both flags must exist on the sub for the copy loop to write to them.
			require.NotNil(t, sub.Flags().Lookup("filter"),
				"sub '%s' must register --filter so the legacy --agent-type form doesn't drop it", subName)
			require.NotNil(t, sub.Flags().Lookup("filter-mode"),
				"sub '%s' must register --filter-mode", subName)
			require.NotNil(t, sub.Flags().Lookup("context-param"),
				"sub '%s' must register --context-param", subName)
			require.NotNil(t, sub.Flags().Lookup("tags"),
				"sub '%s' must register --tags", subName)

			copyParentFlagsToSub(parent, sub)

			assert.Equal(t, `{"capability":"x"}`,
				sub.Flags().Lookup("filter").Value.String(),
				"sub '%s' --filter must mirror parent value", subName)
			assert.Equal(t, "best_match",
				sub.Flags().Lookup("filter-mode").Value.String(),
				"sub '%s' --filter-mode must mirror parent value", subName)
			assert.Equal(t, "myctx",
				sub.Flags().Lookup("context-param").Value.String(),
				"sub '%s' --context-param must mirror parent value", subName)
			assert.Equal(t, "[alpha,beta]",
				sub.Flags().Lookup("tags").Value.String(),
				"sub '%s' --tags must mirror parent value", subName)
		})
	}
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
