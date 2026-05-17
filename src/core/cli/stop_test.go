package cli

import (
	"os"
	"os/exec"
	"syscall"
	"testing"
	"time"

	"mcp-mesh/src/core/cli/lifecycle"
)

// TestSuggestAgentNames exercises the fuzzy "Did you mean?" helper used by
// stopSpecificAgent when the requested name isn't tracked. Matching is
// substring-in-either-direction against running agent names.
func TestSuggestAgentNames(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	for _, name := range []string{"digest-api", "portfolio-worker", "market-data"} {
		if err := lifecycle.WriteAgent(name, os.Getpid(), lifecycle.NewGroupID()); err != nil {
			t.Fatalf("WriteAgent(%s): %v", name, err)
		}
	}

	tests := []struct {
		query string
		want  []string
	}{
		{"api", []string{"digest-api"}},
		{"digest", []string{"digest-api"}},
		{"market", []string{"market-data"}},
		{"mkt", nil},
		{"digest-api", []string{"digest-api"}},
		{"worker", []string{"portfolio-worker"}},
		{"", nil},
	}
	for _, tc := range tests {
		got := suggestAgentNames(tc.query)
		if !equalStringSlices(got, tc.want) {
			t.Errorf("suggestAgentNames(%q) = %v, want %v", tc.query, got, tc.want)
		}
	}
}

// TestSuggestAgentNamesCapped verifies that suggestAgentNames returns at most
// 3 results even when more agents match the query, and that the returned
// subset is deterministic (sorted alphabetically).
func TestSuggestAgentNamesCapped(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	names := []string{
		"zeta-agent", "beta-agent", "delta-agent",
		"alpha-agent", "gamma-agent",
	}
	for _, n := range names {
		if err := lifecycle.WriteAgent(n, os.Getpid(), lifecycle.NewGroupID()); err != nil {
			t.Fatalf("WriteAgent(%s): %v", n, err)
		}
	}

	got := suggestAgentNames("agent")
	if len(got) != 3 {
		t.Fatalf("suggestAgentNames(\"agent\") returned %d results, want exactly 3: %v", len(got), got)
	}
	want := []string{"alpha-agent", "beta-agent", "delta-agent"}
	if !equalStringSlices(got, want) {
		t.Errorf("suggestAgentNames(\"agent\") = %v, want %v (sorted and capped)", got, want)
	}
}

// TestKillProcessByPID_RefusesPID1 guards the symmetric pid==1 hole on the
// <agent>.watcher.pid path: killProcessByPID(1, ...) must never reach
// syscall.Kill(-1, ...), which is POSIX broadcast to every process the user
// can signal. Strategy mirrors TestSignalGroupOrPID_RefusesPID1: spawn a
// benign sleep we own, invoke killProcessByPID(1, ...), then confirm the
// sleep is still alive — proving no broadcast was issued.
func TestKillProcessByPID_RefusesPID1(t *testing.T) {
	cmd := exec.Command("sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	go func() { _ = cmd.Wait() }()
	t.Cleanup(func() { _ = cmd.Process.Kill() })

	sleepPID := cmd.Process.Pid

	// Must not panic, must return true (treated as no-op success).
	if !killProcessByPID(1, 100*time.Millisecond) {
		t.Error("killProcessByPID(1, ...) returned false — expected no-op true")
	}

	// Give any (incorrectly issued) broadcast signal a moment to land.
	time.Sleep(50 * time.Millisecond)

	if !lifecycle.IsAlive(sleepPID) {
		t.Errorf("benign sleep PID %d is dead — killProcessByPID(1, ...) appears to have broadcast", sleepPID)
	}
}

func equalStringSlices(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
