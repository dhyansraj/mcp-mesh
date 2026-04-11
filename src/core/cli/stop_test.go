package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestStopWatcherParentIfEmptyKeepAlive exercises the keep-alive branch of
// stopWatcherParentIfEmpty: when some agents under a parent have been killed
// but others remain live, the function must:
//  1. leave the parent process alone (we verify this by using os.Getpid() as
//     the parent — if the function signalled it, the test would terminate),
//  2. prune stale watcher-parent tracking files whose agent is no longer live,
//  3. preserve watcher-parent tracking files for agents that are still live.
//
// The kill branch is NOT exercised here because unit tests can't safely kill
// processes; it is covered by integration tests.
func TestStopWatcherParentIfEmptyKeepAlive(t *testing.T) {
	pm := newTestPIDManager(t)
	parent := os.Getpid() // use our own PID — we're alive, keep-alive must win.
	livePID := os.Getpid()

	// Three agent names under the same parent, all writing live PIDs.
	names := []string{"dead-agent", "alive-one", "alive-two"}
	for _, n := range names {
		if err := pm.WriteWatchAgentPID(n, parent, livePID); err != nil {
			t.Fatalf("WriteWatchAgentPID(%s): %v", n, err)
		}
		if err := pm.WriteWatchParentPID(n, parent); err != nil {
			t.Fatalf("WriteWatchParentPID(%s): %v", n, err)
		}
	}

	// Simulate stopSpecificAgent having already removed dead-agent's agent file.
	// The corresponding watcher-parent file is still present (that's exactly the
	// stale-file scenario stopWatcherParentIfEmpty is supposed to clean up).
	if err := pm.RemoveWatchAgentPID("dead-agent", parent); err != nil {
		t.Fatalf("RemoveWatchAgentPID: %v", err)
	}

	// Action under test. quiet=true to suppress log noise.
	stopWatcherParentIfEmpty(pm, "dead-agent", parent, 1*time.Second, false, true)

	// 1. Test process (the "parent") is still alive — i.e., we did NOT signal ourselves.
	if !IsProcessAlive(parent) {
		t.Fatalf("test process PID %d is not alive — stopWatcherParentIfEmpty should not have killed it", parent)
	}

	// 2. The dead agent's watcher-parent file is removed.
	deadWPFile := pm.GetWatchParentPIDFile("dead-agent", parent)
	if _, err := os.Stat(deadWPFile); !os.IsNotExist(err) {
		t.Errorf("expected %s to be removed, stat err=%v", filepath.Base(deadWPFile), err)
	}

	// 3. Both alive agents' watcher-parent files are preserved.
	for _, n := range []string{"alive-one", "alive-two"} {
		wpFile := pm.GetWatchParentPIDFile(n, parent)
		if _, err := os.Stat(wpFile); err != nil {
			t.Errorf("expected %s to still exist, stat err=%v", filepath.Base(wpFile), err)
		}
	}

	// 4. Exactly 2 watcher-parent files remain.
	entries, err := os.ReadDir(pm.pidsDir)
	if err != nil {
		t.Fatalf("read pids dir: %v", err)
	}
	var wpCount int
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		if strings.HasSuffix(e.Name(), ".watcher-parent.pid") {
			wpCount++
		}
	}
	if wpCount != 2 {
		t.Errorf("expected 2 watcher-parent files remaining, got %d", wpCount)
	}
}

// TestStopWatcherParentIfEmptyDeadParentCleansFiles exercises the
// already-dead-parent branch: when the parent process has already exited,
// the function should still prune all watcher-parent tracking files belonging
// to it (after removing the stale <name>.<parent_pid>.pid files, the agent
// enumeration returns empty, and the "not alive" short-circuit runs the
// cleanup loop above the kill path).
//
// We construct this scenario by using a reaped PID as the parent PID and
// writing all files referencing it. Because there are no live agent files
// associated with the parent, FindWatchAgentsByParent returns empty and the
// function takes the "no live agents" path. Since IsProcessAlive(dead) is
// false, it returns early — and the prune loop above must have cleaned up
// the stale watcher-parent files.
func TestStopWatcherParentIfEmptyDeadParentCleansFiles(t *testing.T) {
	pm := newTestPIDManager(t)
	dead := reapedPID(t)

	// Two watcher-parent tracking files referring to the dead parent, but no
	// live agent files under it (simulating a crashed parent whose agents are
	// gone but left stale watcher-parent files behind).
	for _, n := range []string{"alpha", "beta"} {
		if err := pm.WriteWatchParentPID(n, dead); err != nil {
			t.Fatalf("WriteWatchParentPID(%s): %v", n, err)
		}
	}

	stopWatcherParentIfEmpty(pm, "alpha", dead, 1*time.Second, false, true)

	// Both stale watcher-parent files should have been pruned.
	for _, n := range []string{"alpha", "beta"} {
		wpFile := pm.GetWatchParentPIDFile(n, dead)
		if _, err := os.Stat(wpFile); !os.IsNotExist(err) {
			t.Errorf("expected %s to be pruned, stat err=%v", filepath.Base(wpFile), err)
		}
	}
}
