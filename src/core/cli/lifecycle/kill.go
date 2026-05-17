package lifecycle

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// processAliveFn is overridable for tests so the kill helper can be exercised
// without launching real processes. Production code uses the syscall(0) probe
// in IsAlive below.
var processAliveFn = IsAlive

// isZombieFn is overridable for tests; production checks the OS process state
// via the platform-specific isZombie implementation (kill_zombie_linux.go,
// kill_zombie_darwin.go, kill_zombie_other.go).
var isZombieFn func(pid int) (bool, error) = isZombie

// IsAlive reports whether a PID is alive — signal 0 returns nil for any
// process the kernel still has an entry for. Zombies are reported alive by
// signal 0 alone; pollUntilDead pairs this with isZombie to treat zombies as
// effectively dead (the agent can't do any more work).
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

// IsAliveOrGroupAlive reports whether the given PID is alive OR any process
// in PID's process group is alive. Used when the "is there cleanup to do"
// decision should include orphan descendants of a dead parent.
//
// Tries kill(-pid, 0) first (group probe): success means at least one process
// in the group whose pgid equals pid still exists. ESRCH falls through to
// the single-PID IsAlive check, which catches processes that were not spawned
// with Setpgid (PID != PGID, so the group probe doesn't apply).
//
// Returns true conservatively on EPERM: cannot probe doesn't mean dead.
//
// NOTE: descendants that escaped the process group via setsid() or
// multiprocessing(daemon=False) are NOT visible to this probe and will not
// be reaped by the cleanup path. Documented limitation; see #1033.
func IsAliveOrGroupAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	// Group probe: kill(-pid, 0) returns nil iff at least one process is
	// in the process group whose pgid equals pid. Permission errors are
	// treated as "still there" — we cannot prove death.
	if err := syscall.Kill(-pid, syscall.Signal(0)); err == nil {
		return true
	} else if errors.Is(err, syscall.EPERM) {
		return true
	}
	// Fall through to the canonical single-PID check.
	return IsAlive(pid)
}

// groupAliveFn is overridable for tests; production uses IsAliveOrGroupAlive.
var groupAliveFn = IsAliveOrGroupAlive

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
//
// CRITICAL: a zombie-probe error (ps failed for a transient reason) is
// inconclusive — we MUST NOT interpret it as "dead". Doing so would let a
// transient EAGAIN under load cause us to remove the PID file of a still-live
// process. We keep polling on probe errors instead.
func pollUntilDead(pid int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !processAliveFn(pid) {
			return true
		}
		if z, err := isZombieFn(pid); err == nil && z {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !processAliveFn(pid) {
		return true
	}
	if z, err := isZombieFn(pid); err == nil && z {
		return true
	}
	return false
}

// pollUntilGroupDead is the group-aware variant of pollUntilDead. It polls
// groupAliveFn (kill(-pid, 0) + single-PID fallback) at 50ms ticks until either
// the entire process group is empty or the deadline passes. Returns true iff
// the group is confirmed empty.
//
// Used by the KillVerifyAndCleanup branch where the parent PID is already
// dead but descendants survive in the same pgid (issue #1033). pollUntilDead
// would return true immediately in that scenario because the parent is gone —
// we need to wait on the orphans instead.
//
// Same zombie semantics as pollUntilDead: a zombie counts as dead so an
// init-reaped orphan isn't a false negative. Probe errors stay inconclusive.
func pollUntilGroupDead(pid int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !groupAliveFn(pid) {
			return true
		}
		if z, err := isZombieFn(pid); err == nil && z {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !groupAliveFn(pid) {
		return true
	}
	if z, err := isZombieFn(pid); err == nil && z {
		return true
	}
	return false
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
		// Parent PID is dead. Check whether descendants survive in the same
		// process group — that's the #1033 case (crash mid-startup, uvicorn
		// worker or similar lingers).
		if !groupAliveFn(pid) {
			// Parent dead AND group empty — pure stale bookkeeping. Clean up.
			_ = os.Remove(pidPath)
			_ = os.Remove(groupPath)
			return false, nil
		}
		// Parent dead but group has surviving descendants — proceed to kill
		// the group as if normal stop. signalGroupOrPID's negative-PID send
		// catches everyone in the group. The "parent" SIGTERM to a dead PID
		// is a no-op (ESRCH); signalGroupOrPID does -pid first.
		// Poll on group death, not parent death, since the parent is already
		// gone and pollUntilDead would return true immediately.
		_ = signalGroupOrPID(pid, syscall.SIGTERM)
		if !pollUntilGroupDead(pid, timeout) {
			_ = signalGroupOrPID(pid, syscall.SIGKILL)
			if !pollUntilGroupDead(pid, 3*time.Second) {
				return false, fmt.Errorf("lifecycle: process group %d (%s) still alive after SIGKILL", pid, name)
			}
		}
		if err := os.Remove(pidPath); err != nil && !os.IsNotExist(err) {
			return true, fmt.Errorf("lifecycle: process group killed but failed to remove %s: %w", pidPath, err)
		}
		_ = os.Remove(groupPath)
		return true, nil
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
