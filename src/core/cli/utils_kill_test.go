package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// pollProcessDead polls IsProcessAlive until the PID is dead (zombies count
// as dead) or the deadline passes. Returns true iff confirmed dead.
func pollProcessDead(pid int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !IsProcessAlive(pid) {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	return !IsProcessAlive(pid)
}

// TestKillProcessAlreadyDead verifies the fast path: a dead PID returns nil
// immediately without signaling.
func TestKillProcessAlreadyDead(t *testing.T) {
	// Spawn and fully reap a short-lived process so the PID is dead.
	cmd := exec.Command("true")
	if err := cmd.Run(); err != nil {
		t.Fatalf("run true: %v", err)
	}
	pid := cmd.Process.Pid

	start := time.Now()
	if err := KillProcess(pid, 5*time.Second); err != nil {
		t.Errorf("KillProcess on dead PID: %v", err)
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Errorf("KillProcess on dead PID took %v, expected immediate return", elapsed)
	}
}

// TestKillProcessKillsProcessGroup verifies KillProcess signals the whole
// process group (bug class #1033): a child that spawned a grandchild in the
// same pgid must take the grandchild down with it.
func TestKillProcessKillsProcessGroup(t *testing.T) {
	t.Parallel()

	gpidFile := filepath.Join(t.TempDir(), "gpid")
	// bash backgrounds a long sleep (the grandchild, same pgid), records its
	// PID, then blocks in wait.
	cmd := exec.Command("bash", "-c", fmt.Sprintf("sleep 300 & echo $! > %q; wait", gpidFile))
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn bash: %v", err)
	}
	childPID := cmd.Process.Pid

	// Reap from a goroutine and synchronize on it after the kill so the
	// child's zombie is gone before we assert death (#1176 reap race).
	waitDone := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(waitDone)
	}()
	t.Cleanup(func() { _ = syscall.Kill(-childPID, syscall.SIGKILL) })

	// Wait for the grandchild PID to be recorded.
	var gpid int
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if data, err := os.ReadFile(gpidFile); err == nil {
			if v, err := strconv.Atoi(strings.TrimSpace(string(data))); err == nil && v > 0 {
				gpid = v
				break
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	if gpid == 0 {
		t.Fatal("grandchild PID was never recorded")
	}
	if !IsProcessAlive(gpid) {
		t.Fatalf("grandchild %d should be alive before kill", gpid)
	}

	if err := KillProcess(childPID, 3*time.Second); err != nil {
		t.Fatalf("KillProcess: %v", err)
	}

	// Synchronize the child's reap, then assert both child and grandchild died.
	select {
	case <-waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("child was not reaped after KillProcess")
	}
	if IsProcessAlive(childPID) {
		t.Errorf("child %d still alive after KillProcess", childPID)
	}
	// Grandchild is reparented to init after the child dies; poll until init
	// reaps it (zombie counts as dead via IsProcessAlive's zombie filter).
	if !pollProcessDead(gpid, 3*time.Second) {
		t.Errorf("grandchild %d still alive after KillProcess — process group was not signaled", gpid)
	}
}

// TestKillProcessHonorsTimeoutBeyondFiveSeconds guards against the legacy 5s
// hard cap: a process whose graceful shutdown takes ~6s must be allowed to
// finish when the caller passes a 9s timeout (e.g., --shutdown-timeout 9),
// instead of being SIGKILLed at the 5s mark.
//
// The trap handler sleeps 6s and then writes a marker file before exiting; a
// SIGKILL at 5s would prevent the marker from ever appearing.
func TestKillProcessHonorsTimeoutBeyondFiveSeconds(t *testing.T) {
	t.Parallel()

	marker := filepath.Join(t.TempDir(), "graceful-exit")
	script := fmt.Sprintf("trap 'sleep 6; touch %q; exit 0' TERM; while :; do sleep 0.2; done", marker)
	cmd := exec.Command("bash", "-c", script)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn bash: %v", err)
	}
	pid := cmd.Process.Pid

	waitDone := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(waitDone)
	}()
	t.Cleanup(func() { _ = syscall.Kill(-pid, syscall.SIGKILL) })

	// Give bash a moment to install the trap.
	time.Sleep(200 * time.Millisecond)

	start := time.Now()
	if err := KillProcess(pid, 9*time.Second); err != nil {
		t.Fatalf("KillProcess: %v", err)
	}
	elapsed := time.Since(start)

	select {
	case <-waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("process was not reaped after KillProcess")
	}

	if elapsed < 5500*time.Millisecond {
		t.Errorf("KillProcess returned after %v — graceful phase appears capped below the caller's timeout", elapsed)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Errorf("graceful-exit marker missing (%v) — process was SIGKILLed before its ~6s graceful shutdown finished", err)
	}
}
