package scaffold

import (
	"bytes"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestNewScaffoldAPICommand_BasicShape verifies the subcommand is
// registered with the expected Use string and metadata.
func TestNewScaffoldAPICommand_BasicShape(t *testing.T) {
	cmd := newScaffoldAPICommand()
	assert.Equal(t, "api", cmd.Use)
	assert.NotEmpty(t, cmd.Short)
	assert.NotEmpty(t, cmd.Long)
	assert.NotNil(t, cmd.RunE)
}

// TestNewScaffoldAPICommand_Flags verifies the full flag surface
// matches the basic subcommand plus --tags. These are the flags
// scripts and tests in tsuite expect to be present.
func TestNewScaffoldAPICommand_Flags(t *testing.T) {
	cmd := newScaffoldAPICommand()
	for _, name := range []string{
		"name", "lang", "output", "port", "description",
		"package", "tags", "dry-run", "no-interactive",
	} {
		assert.NotNil(t, cmd.Flags().Lookup(name),
			"--%s must be registered", name)
	}
}

// TestNewScaffoldAPICommand_NoInteractiveFlag verifies the
// --no-interactive flag is present so 1.4.1-era scripts that pass it
// don't fail with "unknown flag".
func TestNewScaffoldAPICommand_NoInteractiveFlag(t *testing.T) {
	cmd := newScaffoldAPICommand()
	assert.NotNil(t, cmd.Flags().Lookup("no-interactive"))
}

// TestNewScaffoldAPICommand_DefaultLanguage confirms python is the
// default runtime, matching basic and the other scaffold subcommands.
func TestNewScaffoldAPICommand_DefaultLanguage(t *testing.T) {
	cmd := newScaffoldAPICommand()
	lang, err := cmd.Flags().GetString("lang")
	require.NoError(t, err)
	assert.Equal(t, "python", lang)
}

// TestNewScaffoldAPICommand_DefaultPort confirms the default port
// matches basic (8080), so port-collision auto-increment behaves
// identically across subcommands.
func TestNewScaffoldAPICommand_DefaultPort(t *testing.T) {
	cmd := newScaffoldAPICommand()
	port, err := cmd.Flags().GetInt("port")
	require.NoError(t, err)
	assert.Equal(t, 8080, port)
}

// TestRunScaffoldAPI_RequiresName verifies the --name flag is
// required. Mirrors basic's contract.
func TestRunScaffoldAPI_RequiresName(t *testing.T) {
	cmd := newScaffoldAPICommand()
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetErr(bytes.NewBufferString(""))
	cmd.SetArgs([]string{"--no-interactive"})

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "--name is required")
}

// TestRunScaffoldAPI_RejectsInvalidLanguage verifies unsupported
// languages produce a clear error before the template lookup runs.
func TestRunScaffoldAPI_RejectsInvalidLanguage(t *testing.T) {
	cmd := newScaffoldAPICommand()
	cmd.SetOut(bytes.NewBufferString(""))
	cmd.SetErr(bytes.NewBufferString(""))
	cmd.SetArgs([]string{
		"--name", "gw",
		"--lang", "cobol",
		"--no-interactive",
	})

	err := cmd.Execute()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported language")
}

// TestRunScaffoldAPI_DryRunPython exercises the dry-run path with
// filesystem-backed templates (the embedded FS is only set when the
// binary is built; unit tests rely on the cmd/meshctl/templates dir
// fallback wired into the static provider).
func TestRunScaffoldAPI_DryRunPython(t *testing.T) {
	out, err := runAPISubcommandDryRun(t, "python", "gw-py")
	require.NoError(t, err, "dry-run should succeed for python; got stderr/log output:\n%s", out)
	assertAPIDryRunMentions(t, out, "main.py")
	assertAPIDryRunMentions(t, out, "@mesh.route")
}

// TestRunScaffoldAPI_DryRunTypeScript exercises the dry-run path for
// the TypeScript Express template.
func TestRunScaffoldAPI_DryRunTypeScript(t *testing.T) {
	out, err := runAPISubcommandDryRun(t, "typescript", "gw-ts")
	require.NoError(t, err, "dry-run should succeed for typescript; got:\n%s", out)
	assertAPIDryRunMentions(t, out, "package.json")
}

// TestRunScaffoldAPI_DryRunJava exercises the dry-run path for the
// Java Spring Boot template.
func TestRunScaffoldAPI_DryRunJava(t *testing.T) {
	out, err := runAPISubcommandDryRun(t, "java", "gw-java")
	require.NoError(t, err, "dry-run should succeed for java; got:\n%s", out)
	assertAPIDryRunMentions(t, out, "pom.xml")
}

// runAPISubcommandDryRun wires the api subcommand to a captured
// buffer and points the static provider at the in-repo template tree
// via MESHCTL_TEMPLATE_DIR. Returns the captured stdout and execution
// error.
func runAPISubcommandDryRun(t *testing.T, lang, name string) (string, error) {
	t.Helper()

	// Point at in-repo cmd/meshctl/templates so the filesystem fallback
	// resolves when embedded templates aren't compiled in.
	t.Setenv("MESHCTL_TEMPLATE_DIR",
		getProjectRoot()+"/cmd/meshctl/templates")

	cmd := newScaffoldAPICommand()
	out := bytes.NewBufferString("")
	cmd.SetOut(out)
	cmd.SetErr(out)
	cmd.SetArgs([]string{
		"--name", name,
		"--lang", lang,
		"--no-interactive",
		"--dry-run",
	})

	err := cmd.Execute()
	return out.String(), err
}

// assertAPIDryRunMentions checks that the captured dry-run output
// includes the expected substring (a generated filename or template
// fragment), giving an actionable error message on failure.
func assertAPIDryRunMentions(t *testing.T, out, want string) {
	t.Helper()
	if !strings.Contains(out, want) {
		t.Errorf("dry-run output should mention %q; got:\n%s", want, out)
	}
}
