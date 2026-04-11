//go:build linux

package cli

import (
	"os/exec"
	"testing"
	"time"
)

// TestIsProcessAliveFiltersZombies verifies that a zombie child (a process
// that has exited but not been reaped) is reported as not-alive by
// IsProcessAlive. This is the Linux-specific path that was missing prior
// to the tsuite regression fix for #748.
func TestIsProcessAliveFiltersZombies(t *testing.T) {
	// Spawn a short-lived subprocess that exits immediately. Do NOT call
	// Wait() on it, so it becomes a zombie until this test process reaps
	// it at the end of the test.
	cmd := exec.Command("sh", "-c", "exit 0")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start zombie candidate: %v", err)
	}
	pid := cmd.Process.Pid

	// Wait until the kernel has marked the process as exited (zombie) —
	// signal(0) still succeeds but /proc/<pid>/stat should show state Z.
	// Poll for up to 1 second.
	deadline := time.Now().Add(1 * time.Second)
	foundZombie := false
	for time.Now().Before(deadline) {
		if isProcessZombie(pid) {
			foundZombie = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !foundZombie {
		// If we can't reproduce the zombie state on this kernel (e.g.,
		// running under a reaper init like `tini` which reaps immediately),
		// skip.
		_ = cmd.Wait()
		t.Skip("could not reproduce zombie state — test kernel reaps too aggressively")
	}

	// IsProcessAlive should now return false for the zombie.
	if IsProcessAlive(pid) {
		t.Errorf("IsProcessAlive returned true for zombie PID %d, want false", pid)
	}

	// Reap the zombie so we don't leak it.
	_ = cmd.Wait()
}

// TestIsProcessZombieReturnsFalseForLiveProcess verifies that an ordinary
// running process (our own test process) is NOT reported as a zombie.
func TestIsProcessZombieReturnsFalseForLiveProcess(t *testing.T) {
	if isProcessZombie(1) {
		t.Errorf("isProcessZombie(1) = true, want false (init is not a zombie)")
	}
}

// TestIsProcessZombieReturnsFalseForMissingPID verifies that a PID with no
// /proc entry is not reported as a zombie. The caller's signal(0) check
// will catch the missing process as "not alive" first anyway.
func TestIsProcessZombieReturnsFalseForMissingPID(t *testing.T) {
	// PID 0 has no /proc/0 entry.
	if isProcessZombie(0) {
		t.Errorf("isProcessZombie(0) = true, want false")
	}
	// A very high PID that almost certainly doesn't exist.
	if isProcessZombie(2147483646) {
		t.Errorf("isProcessZombie(2147483646) = true, want false")
	}
}
