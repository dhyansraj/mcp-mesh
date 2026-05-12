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

// TestNextAvailablePort_EmptyDir verifies that scanning an empty directory
// returns DefaultScaffoldPort (8080) — the "no existing agents" baseline.
func TestNextAvailablePort_EmptyDir(t *testing.T) {
	tmpDir := t.TempDir()
	got := NextAvailablePort(tmpDir)
	assert.Equal(t, DefaultScaffoldPort, got)
}

// TestNextAvailablePort_MissingDir verifies that a non-existent directory
// falls back to DefaultScaffoldPort rather than returning an error.
func TestNextAvailablePort_MissingDir(t *testing.T) {
	got := NextAvailablePort("/nonexistent/path/does/not/exist")
	assert.Equal(t, DefaultScaffoldPort, got)
}

// TestNextAvailablePort_OneAgent verifies that one scaffolded agent on port
// 8080 yields a next port of 8081.
func TestNextAvailablePort_OneAgent(t *testing.T) {
	tmpDir := t.TempDir()
	writePyAgent(t, tmpDir, "py-greeter", 8080)

	got := NextAvailablePort(tmpDir)
	assert.Equal(t, 8081, got)
}

// TestNextAvailablePort_PicksMax verifies that the helper picks
// max(detected_ports)+1 rather than count-of-agents.
func TestNextAvailablePort_PicksMax(t *testing.T) {
	tmpDir := t.TempDir()
	writePyAgent(t, tmpDir, "py-greeter-1", 8080)
	writePyAgent(t, tmpDir, "py-greeter-2", 8082)
	writePyAgent(t, tmpDir, "py-greeter-3", 8081)

	got := NextAvailablePort(tmpDir)
	assert.Equal(t, 8083, got)
}

// TestNextAvailablePort_CustomPortsBelowDefault verifies that if all
// detected ports are below the default, we still return the default.
func TestNextAvailablePort_CustomPortsBelowDefault(t *testing.T) {
	tmpDir := t.TempDir()
	writePyAgent(t, tmpDir, "py-low", 3000)

	got := NextAvailablePort(tmpDir)
	assert.Equal(t, DefaultScaffoldPort, got)
}

// TestAutoAssignScaffoldPort_ExplicitOverride verifies that when the user
// explicitly passes --port, that value is used as-is regardless of what
// else is in the directory.
func TestAutoAssignScaffoldPort_ExplicitOverride(t *testing.T) {
	tmpDir := t.TempDir()
	writePyAgent(t, tmpDir, "py-greeter", 8080)

	cmd := &cobra.Command{Use: "scaffold"}
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	require.NoError(t, cmd.Flags().Set("port", "9999"))

	got := AutoAssignScaffoldPort(cmd, 9999, tmpDir, "explicit-agent")
	assert.Equal(t, 9999, got, "explicit --port should not be auto-overridden")
}

// TestAutoAssignScaffoldPort_NoFlagSet verifies that when --port was not
// explicitly set, the helper auto-picks the next free port and emits a log
// line on the command's writer.
func TestAutoAssignScaffoldPort_NoFlagSet(t *testing.T) {
	tmpDir := t.TempDir()
	writePyAgent(t, tmpDir, "py-greeter", 8080)

	cmd := &cobra.Command{Use: "scaffold"}
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	buf := &bytes.Buffer{}
	cmd.SetOut(buf)

	got := AutoAssignScaffoldPort(cmd, 8080, tmpDir, "py-greeter-2")
	assert.Equal(t, 8081, got)
	assert.Contains(t, buf.String(), "8080")
	assert.Contains(t, buf.String(), "8081")
	assert.Contains(t, buf.String(), "py-greeter-2")
}

// TestAutoAssignScaffoldPort_NoExistingAgents verifies that with no
// existing agents the helper returns DefaultScaffoldPort and emits no log
// line (since the value didn't change from the default).
func TestAutoAssignScaffoldPort_NoExistingAgents(t *testing.T) {
	tmpDir := t.TempDir()

	cmd := &cobra.Command{Use: "scaffold"}
	cmd.Flags().IntP("port", "p", 8080, "HTTP port for the agent")
	buf := &bytes.Buffer{}
	cmd.SetOut(buf)

	got := AutoAssignScaffoldPort(cmd, 8080, tmpDir, "first-agent")
	assert.Equal(t, DefaultScaffoldPort, got)
	assert.Empty(t, buf.String(), "no log line when port is the default")
}

// writePyAgent writes a minimal Python agent file (main.py with
// @mesh.agent decorator) inside outputDir/agentName so ScanForAgents picks
// it up.
func writePyAgent(t *testing.T, outputDir, name string, port int) {
	t.Helper()
	dir := filepath.Join(outputDir, name)
	require.NoError(t, os.MkdirAll(dir, 0755))
	content := "import mesh\n\n" +
		"@mesh.agent(\n" +
		"    name=\"" + name + "\",\n" +
		"    http_port=" + itoa(port) + ",\n" +
		")\n" +
		"class Foo: pass\n"
	require.NoError(t, os.WriteFile(filepath.Join(dir, "main.py"), []byte(content), 0644))
}

func itoa(i int) string {
	// Avoid importing strconv just for one call in a test helper.
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var buf [20]byte
	pos := len(buf)
	for i > 0 {
		pos--
		buf[pos] = byte('0' + i%10)
		i /= 10
	}
	if neg {
		pos--
		buf[pos] = '-'
	}
	return string(buf[pos:])
}
