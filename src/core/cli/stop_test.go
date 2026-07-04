package cli

import (
	"os"
	"os/exec"
	"strings"
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

// TestStopNamedAgents_AllUnknown verifies multi-name stop aggregates per-agent
// failures: every unknown name is reported, and a single non-nil error naming
// all failures (with the correct count) is returned so the command exits
// non-zero.
func TestStopNamedAgents_AllUnknown(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	err := stopNamedAgents([]string{"ghost-a", "ghost-b"}, time.Second, true, false, false)
	if err == nil {
		t.Fatal("expected aggregated error for two unknown agents")
	}
	msg := err.Error()
	if !strings.Contains(msg, "2 agent(s)") {
		t.Errorf("error should report a count of 2, got: %v", err)
	}
	for _, name := range []string{"ghost-a", "ghost-b"} {
		if !strings.Contains(msg, name) {
			t.Errorf("error should name %q, got: %v", name, err)
		}
	}
}

// TestStopNamedAgents_MixedKnownAndUnknown verifies that one un-stoppable agent
// never aborts the rest: a tracked-but-dead agent is cleaned up successfully
// (its PID file removed) while an unknown name fails, and the aggregated error
// counts only the real failure.
func TestStopNamedAgents_MixedKnownAndUnknown(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	// A tracked agent whose PID is already dead: spawn a short sleep, kill and
	// reap it so its PID is gone, then record it. stopSpecificAgent treats this
	// as stale bookkeeping and cleans it up (no error).
	dead := exec.Command("sleep", "30")
	dead.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := dead.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	deadPID := dead.Process.Pid
	_ = dead.Process.Kill()
	_ = dead.Wait()

	if err := lifecycle.WriteAgent("known-dead", deadPID, lifecycle.NewGroupID()); err != nil {
		t.Fatalf("WriteAgent: %v", err)
	}

	err := stopNamedAgents([]string{"known-dead", "ghost-x"}, time.Second, true, false, false)
	if err == nil {
		t.Fatal("expected an error because one name is unknown")
	}
	msg := err.Error()
	if !strings.Contains(msg, "1 agent(s)") {
		t.Errorf("error should report exactly 1 failure, got: %v", err)
	}
	if !strings.Contains(msg, "ghost-x") {
		t.Errorf("error should name the unknown agent, got: %v", err)
	}
	if strings.Contains(msg, "known-dead") {
		t.Errorf("the tracked dead agent should have stopped cleanly, got: %v", err)
	}
	if _, statErr := lifecycle.LookupAgent("known-dead"); statErr != nil {
		t.Errorf("LookupAgent after stop: %v", statErr)
	}
	if _, err := os.Stat(lifecycle.PIDFile("known-dead")); !os.IsNotExist(err) {
		t.Errorf("known-dead pid file should be removed after stop")
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
