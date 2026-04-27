package lifecycle

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// processAliveFn is overridable for tests so the kill helper can be exercised
// without launching real processes. Production code uses the syscall(0) probe
// in IsAlive below.
var processAliveFn = IsAlive

// isZombieFn is overridable for tests; production checks the OS process state.
var isZombieFn = isZombie

// IsAlive reports whether a PID is alive — signal 0 returns nil for any
// process the kernel still has an entry for. Zombies are reported alive by
// signal 0 alone; for meshctl's purposes we treat zombies as effectively dead
// (the agent can't do any more work) and the cli package layer does the
// platform-specific zombie filter. lifecycle stays platform-agnostic.
func IsAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	return proc.Signal(syscall.Signal(0)) == nil
}

// isZombie reports whether the process is in zombie state. Zombies are
// kernel-tracked but functionally dead — kill -0 returns success on them but
// the process can never run again. We treat them as dead for the purpose of
// stop verification.
//
// Implementation: shell out to `ps -o stat= -p <pid>`. The "stat" column is
// portable enough across macOS and Linux: both report 'Z' for zombies. If ps
// itself errors (process disappeared between alive-check and stat-check),
// that's also "dead" for our purposes.
func isZombie(pid int) bool {
	if pid <= 0 {
		return false
	}
	out, err := exec.Command("ps", "-o", "stat=", "-p", strconv.Itoa(pid)).Output()
	if err != nil {
		// ps exits non-zero when the PID doesn't exist — treat as dead.
		return true
	}
	state := strings.TrimSpace(string(out))
	if state == "" {
		return true
	}
	// First character is the primary state. 'Z' = zombie (defunct).
	return state[0] == 'Z'
}

// readPIDFromFile reads and parses a PID file. Returns (0, nil) if missing.
func readPIDFromFile(path string) (int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return 0, nil
		}
		return 0, err
	}
	s := strings.TrimSpace(string(data))
	if s == "" {
		return 0, nil
	}
	pid, err := strconv.Atoi(s)
	if err != nil {
		return 0, fmt.Errorf("lifecycle: invalid PID in %s: %w", path, err)
	}
	return pid, nil
}

// pollUntilDead polls processAliveFn at 50ms ticks until either the process is
// dead or the deadline passes. Returns true iff confirmed dead.
//
// Zombie state counts as dead: after SIGKILL, a process becomes a zombie until
// its parent reaps it; kill(0) keeps reporting "alive" until then. For
// detached agents whose parent meshctl has already exited, the reaper is init,
// which can take longer than our timeout. Treating Z as dead avoids the
// false-negative "still alive after SIGKILL" error.
func pollUntilDead(pid int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !processAliveFn(pid) {
			return true
		}
		if isZombieFn(pid) {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !processAliveFn(pid) {
		return true
	}
	return isZombieFn(pid)
}

// signalGroupOrPID sends sig first to the process group (negative PID) and
// falls back to a single-process signal if that errors (process wasn't started
// with Setpgid). Returns the LAST error seen — caller should still verify
// death rather than trust the error code.
func signalGroupOrPID(pid int, sig syscall.Signal) error {
	if err := syscall.Kill(-pid, sig); err == nil {
		return nil
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	return proc.Signal(sig)
}

// KillVerifyAndCleanup orchestrates the full per-PID-file shutdown dance:
//
//  1. read <root>/pids/<name>.pid
//  2. if missing -> return (false, nil)
//  3. if process already dead -> remove PID file (and .group), return (false, nil)
//  4. SIGTERM (process group preferred), poll up to timeout
//  5. if still alive -> SIGKILL, poll up to 1s
//  6. on confirmed death -> remove PID file (and .group), return (true, nil)
//  7. on verify failure -> return error WITHOUT removing files (preserve state)
//
// killed=true means we actually sent a kill signal to a live process. The
// stale-file cleanup case returns (false, nil) so callers can distinguish
// "I had to act" from "nothing to do".
func KillVerifyAndCleanup(name string, timeout time.Duration) (killed bool, err error) {
	pidPath := PIDFile(name)
	groupPath := GroupFile(name)

	pid, err := readPIDFromFile(pidPath)
	if err != nil {
		return false, err
	}
	if pid == 0 {
		// PID file missing — nothing to do.
		return false, nil
	}

	if !processAliveFn(pid) {
		// Process already dead — clean up bookkeeping and report no kill.
		_ = os.Remove(pidPath)
		_ = os.Remove(groupPath)
		return false, nil
	}

	// Graceful: SIGTERM + poll.
	_ = signalGroupOrPID(pid, syscall.SIGTERM)
	if !pollUntilDead(pid, timeout) {
		// Force: SIGKILL + extended poll. Window is 3s so a parent that's slow
		// to reap (or has exited entirely, leaving init to reap) doesn't trip a
		// false-negative — pollUntilDead also treats zombies as dead, so the
		// only way to time out here is genuine refusal-to-die.
		_ = signalGroupOrPID(pid, syscall.SIGKILL)
		if !pollUntilDead(pid, 3*time.Second) {
			return false, fmt.Errorf("lifecycle: process %d (%s) still alive after SIGKILL", pid, name)
		}
	}

	if err := os.Remove(pidPath); err != nil && !os.IsNotExist(err) {
		return true, fmt.Errorf("lifecycle: process killed but failed to remove %s: %w", pidPath, err)
	}
	_ = os.Remove(groupPath) // best-effort; agent may not have a .group file (services don't)
	return true, nil
}
