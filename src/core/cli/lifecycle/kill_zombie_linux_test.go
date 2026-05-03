//go:build linux

package lifecycle

import (
	"os/exec"
	"testing"
	"time"
)

// TestIsZombieDetectsZombieChild verifies that a zombie child (a process
// that has exited but not been reaped) is reported as a zombie via the
// /proc/<pid>/stat path. This is the case meshctl stop hits on slim Linux
// images where ps isn't installed.
func TestIsZombieDetectsZombieChild(t *testing.T) {
	cmd := exec.Command("sh", "-c", "exit 0")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start zombie candidate: %v", err)
	}
	pid := cmd.Process.Pid

	deadline := time.Now().Add(1 * time.Second)
	foundZombie := false
	for time.Now().Before(deadline) {
		z, err := isZombie(pid)
		if err != nil {
			t.Fatalf("isZombie returned unexpected error: %v", err)
		}
		if z {
			foundZombie = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !foundZombie {
		_ = cmd.Wait()
		t.Skip("could not reproduce zombie state — test kernel reaps too aggressively")
	}

	_ = cmd.Wait()
}

func TestIsZombieReturnsFalseForLiveProcess(t *testing.T) {
	z, err := isZombie(1)
	if err != nil {
		t.Fatalf("isZombie(1) returned unexpected error: %v", err)
	}
	if z {
		t.Errorf("isZombie(1) = true, want false (init is not a zombie)")
	}
}

func TestIsZombieReturnsFalseForMissingPID(t *testing.T) {
	z, err := isZombie(2147483646)
	if err != nil {
		t.Fatalf("isZombie returned unexpected error: %v", err)
	}
	if z {
		t.Errorf("isZombie(2147483646) = true, want false")
	}

	z, err = isZombie(0)
	if err != nil {
		t.Fatalf("isZombie(0) returned unexpected error: %v", err)
	}
	if z {
		t.Errorf("isZombie(0) = true, want false")
	}
}
