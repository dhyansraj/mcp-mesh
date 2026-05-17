package lifecycle

import (
	"testing"
)

// TestIsAgentRunning_LiveParent: parent PID alive AND group alive → running.
func TestIsAgentRunning_LiveParent(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 11111
	useStubAlive(t, map[int]bool{pid: true})
	useStubGroupAlive(t, map[int]bool{pid: true})

	g := NewGroupID()
	if err := WriteAgent("live", pid, g); err != nil {
		t.Fatalf("WriteAgent: %v", err)
	}

	running, gotPID, err := IsAgentRunning("live")
	if err != nil {
		t.Fatalf("IsAgentRunning: %v", err)
	}
	if !running {
		t.Error("expected running=true for live parent")
	}
	if gotPID != pid {
		t.Errorf("pid = %d, want %d", gotPID, pid)
	}
}

// TestIsAgentRunning_OrphanDescendants: parent dead, group has orphan
// descendants → running (issue #1033). Uses groupAliveFn via the test seam to
// confirm the call path routes through it (W1).
func TestIsAgentRunning_OrphanDescendants(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 22222
	useStubAlive(t, map[int]bool{}) // parent dead
	useStubGroupAlive(t, map[int]bool{pid: true})

	g := NewGroupID()
	if err := WriteAgent("orphan", pid, g); err != nil {
		t.Fatalf("WriteAgent: %v", err)
	}

	running, gotPID, err := IsAgentRunning("orphan")
	if err != nil {
		t.Fatalf("IsAgentRunning: %v", err)
	}
	if !running {
		t.Error("expected running=true when parent dead but group alive")
	}
	if gotPID != pid {
		t.Errorf("pid = %d, want %d", gotPID, pid)
	}
}

// TestIsAgentRunning_AllDead: both single-PID and group probes return dead →
// not running, PID returned so callers can clean stale state.
func TestIsAgentRunning_AllDead(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 33333
	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{})

	g := NewGroupID()
	if err := WriteAgent("gone", pid, g); err != nil {
		t.Fatalf("WriteAgent: %v", err)
	}

	running, gotPID, err := IsAgentRunning("gone")
	if err != nil {
		t.Fatalf("IsAgentRunning: %v", err)
	}
	if running {
		t.Error("expected running=false when both probes return dead")
	}
	if gotPID != pid {
		t.Errorf("pid = %d, want %d (caller needs PID for cleanup)", gotPID, pid)
	}
}

// TestIsAgentRunning_MissingPIDFile: no .pid file → not running, pid=0.
func TestIsAgentRunning_MissingPIDFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{})

	running, gotPID, err := IsAgentRunning("nonexistent")
	if err != nil {
		t.Fatalf("IsAgentRunning: %v", err)
	}
	if running {
		t.Error("expected running=false when no PID file")
	}
	if gotPID != 0 {
		t.Errorf("pid = %d, want 0", gotPID)
	}
}
