package scaffold

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"github.com/spf13/cobra"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSupportedLLMVendors(t *testing.T) {
	v := SupportedLLMVendors()
	assert.Contains(t, v, "claude")
	assert.Contains(t, v, "openai")
	assert.Contains(t, v, "gemini")
	assert.Contains(t, v, "litellm-fallback")
}

func TestIsValidLLMVendor(t *testing.T) {
	assert.True(t, IsValidLLMVendor("claude"))
	assert.True(t, IsValidLLMVendor("openai"))
	assert.True(t, IsValidLLMVendor("gemini"))
	assert.True(t, IsValidLLMVendor("litellm-fallback"))
	assert.False(t, IsValidLLMVendor("anthropic"))
	assert.False(t, IsValidLLMVendor(""))
}

func TestVendorToModel(t *testing.T) {
	assert.Equal(t, "anthropic/claude-sonnet-4-5", VendorToModel("claude"))
	assert.Equal(t, "openai/gpt-4o", VendorToModel("openai"))
	assert.Equal(t, "gemini/gemini-1.5-pro", VendorToModel("gemini"))
	assert.NotEmpty(t, VendorToModel("litellm-fallback"))
	assert.Equal(t, "", VendorToModel("unknown"))
}

func TestVendorToProviderTags(t *testing.T) {
	for _, v := range []string{"claude", "openai", "gemini", "litellm-fallback"} {
		tags := VendorToProviderTags(v)
		require.NotEmpty(t, tags, "expected tags for %s", v)
		assert.Contains(t, tags, "llm")
	}
	assert.Contains(t, VendorToProviderTags("claude"), "+claude")
	assert.Contains(t, VendorToProviderTags("openai"), "+openai")
	assert.Contains(t, VendorToProviderTags("gemini"), "+gemini")
}

func TestVendorToConsumerTag(t *testing.T) {
	assert.Equal(t, "+claude", VendorToConsumerTag("claude"))
	assert.Equal(t, "+openai", VendorToConsumerTag("openai"))
	assert.Equal(t, "+gemini", VendorToConsumerTag("gemini"))
	assert.Equal(t, "+fallback", VendorToConsumerTag("litellm-fallback"))
}

func TestRuntimeStartCommand(t *testing.T) {
	assert.Contains(t, runtimeStartCommand("python", "agent"), "python main.py")
	assert.Contains(t, runtimeStartCommand("py", "agent"), "python main.py")
	assert.Contains(t, runtimeStartCommand("typescript", "agent"), "npx tsx")
	assert.Contains(t, runtimeStartCommand("ts", "agent"), "npx tsx")
	assert.Contains(t, runtimeStartCommand("java", "agent"), "mvn spring-boot:run")
}

func TestNewScaffoldLLMProviderCommand_Flags(t *testing.T) {
	cmd := newScaffoldLLMProviderCommand()
	assert.Equal(t, "llm-provider", cmd.Use)
	assert.NotNil(t, cmd.Flags().Lookup("vendor"))
	assert.NotNil(t, cmd.Flags().Lookup("runtime"))
	assert.NotNil(t, cmd.Flags().Lookup("name"))
	assert.NotNil(t, cmd.Flags().Lookup("model"))
	assert.NotNil(t, cmd.Flags().Lookup("dry-run"))

	vendor, _ := cmd.Flags().GetString("vendor")
	assert.Equal(t, "claude", vendor)
	runtime, _ := cmd.Flags().GetString("runtime")
	assert.Equal(t, "python", runtime)
}

func TestNewScaffoldLLMCommand_Flags(t *testing.T) {
	cmd := newScaffoldLLMCommand()
	assert.Equal(t, "llm", cmd.Use)
	assert.NotNil(t, cmd.Flags().Lookup("vendor"))
	assert.NotNil(t, cmd.Flags().Lookup("runtime"))
	assert.NotNil(t, cmd.Flags().Lookup("name"))
	assert.NotNil(t, cmd.Flags().Lookup("max-iterations"))
	assert.NotNil(t, cmd.Flags().Lookup("response-format"))
	assert.NotNil(t, cmd.Flags().Lookup("dry-run"))
}

func TestAttachLLMSubcommands(t *testing.T) {
	parent := &cobra.Command{Use: "scaffold"}
	AttachLLMSubcommands(parent)

	have := map[string]bool{}
	for _, c := range parent.Commands() {
		have[c.Use] = true
	}
	assert.True(t, have["llm-provider"], "expected llm-provider subcommand")
	assert.True(t, have["llm"], "expected llm subcommand")
}

func TestRunScaffoldLLMProvider_InvalidVendor(t *testing.T) {
	cmd := newScaffoldLLMProviderCommand()
	require.NoError(t, cmd.Flags().Set("vendor", "bogus"))
	require.NoError(t, cmd.Flags().Set("runtime", "python"))

	err := runScaffoldLLMProvider(cmd, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported vendor")
}

func TestRunScaffoldLLMProvider_InvalidRuntime(t *testing.T) {
	cmd := newScaffoldLLMProviderCommand()
	require.NoError(t, cmd.Flags().Set("vendor", "claude"))
	require.NoError(t, cmd.Flags().Set("runtime", "rust"))

	err := runScaffoldLLMProvider(cmd, nil)
	require.Error(t, err)
}

func TestRunScaffoldLLMConsumer_InvalidVendor(t *testing.T) {
	cmd := newScaffoldLLMCommand()
	require.NoError(t, cmd.Flags().Set("vendor", "bogus"))
	require.NoError(t, cmd.Flags().Set("runtime", "python"))

	err := runScaffoldLLMConsumer(cmd, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported vendor")
}

// TestRunScaffoldLLMProvider_DryRun_Python verifies a dry-run for the provider
// renders a valid file mentioning the chosen vendor model and provider tag.
// It uses on-disk templates (no embedded FS) by chdir'ing into the repo root.
func TestRunScaffoldLLMProvider_DryRun_Python(t *testing.T) {
	repoRoot := findRepoRoot(t)
	t.Chdir(repoRoot)

	cmd := newScaffoldLLMProviderCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	require.NoError(t, cmd.Flags().Set("vendor", "claude"))
	require.NoError(t, cmd.Flags().Set("runtime", "python"))
	require.NoError(t, cmd.Flags().Set("name", "my-claude"))
	require.NoError(t, cmd.Flags().Set("dry-run", "true"))

	require.NoError(t, runScaffoldLLMProvider(cmd, nil))

	output := out.String()
	assert.Contains(t, output, "Dry-run")
	assert.Contains(t, output, "anthropic/claude-sonnet-4-5")
	assert.Contains(t, output, "+claude")
}

func TestRunScaffoldLLMConsumer_DryRun_Python(t *testing.T) {
	repoRoot := findRepoRoot(t)
	t.Chdir(repoRoot)

	cmd := newScaffoldLLMCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	require.NoError(t, cmd.Flags().Set("vendor", "openai"))
	require.NoError(t, cmd.Flags().Set("runtime", "python"))
	require.NoError(t, cmd.Flags().Set("name", "my-consumer"))
	require.NoError(t, cmd.Flags().Set("dry-run", "true"))

	require.NoError(t, runScaffoldLLMConsumer(cmd, nil))

	output := out.String()
	assert.Contains(t, output, "Dry-run")
	// The consumer should pin its provider via the openai tag.
	assert.Contains(t, output, "+openai")
}

// TestRunScaffoldLLMProvider_PrintsFollowupMessage verifies that the cross-link
// to `meshctl scaffold llm` is printed after a successful (non-dry-run) generation.
func TestRunScaffoldLLMProvider_PrintsFollowupMessage(t *testing.T) {
	repoRoot := findRepoRoot(t)
	t.Chdir(repoRoot)

	tmp := t.TempDir()
	cmd := newScaffoldLLMProviderCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	require.NoError(t, cmd.Flags().Set("vendor", "claude"))
	require.NoError(t, cmd.Flags().Set("runtime", "python"))
	require.NoError(t, cmd.Flags().Set("name", "claude-prov-test"))
	require.NoError(t, cmd.Flags().Set("output", tmp))

	require.NoError(t, runScaffoldLLMProvider(cmd, nil))

	output := out.String()
	assert.Contains(t, output, "Provider agent created")
	assert.Contains(t, output, "meshctl scaffold llm --runtime python --vendor claude")
	assert.Contains(t, output, "+claude")

	// Sanity-check that a main.py was actually written.
	assert.FileExists(t, filepath.Join(tmp, "claude-prov-test", "main.py"))
}

func TestRunScaffoldLLMConsumer_PrintsFollowupMessage(t *testing.T) {
	repoRoot := findRepoRoot(t)
	t.Chdir(repoRoot)

	tmp := t.TempDir()
	cmd := newScaffoldLLMCommand()
	var out bytes.Buffer
	cmd.SetOut(&out)
	cmd.SetErr(&out)
	require.NoError(t, cmd.Flags().Set("vendor", "gemini"))
	require.NoError(t, cmd.Flags().Set("runtime", "python"))
	require.NoError(t, cmd.Flags().Set("name", "gemini-cons-test"))
	require.NoError(t, cmd.Flags().Set("output", tmp))

	require.NoError(t, runScaffoldLLMConsumer(cmd, nil))

	output := out.String()
	assert.Contains(t, output, "Consumer agent created")
	assert.Contains(t, output, "meshctl scaffold llm-provider --vendor gemini --runtime python")
}

// findRepoRoot walks up from the test working directory until it finds a go.mod,
// so tests can locate the on-disk templates under cmd/meshctl/templates.
func findRepoRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	require.NoError(t, err)
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find go.mod walking up from test cwd")
		}
		dir = parent
	}
}
