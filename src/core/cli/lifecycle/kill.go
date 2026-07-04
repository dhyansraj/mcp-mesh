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
// the single-PID check, which catches processes that were not spawned with
// Setpgid (PID != PGID, so the group probe doesn't apply).
//
// Returns true conservatively on EPERM at either probe site: "cannot probe"
// is not the same as "dead". The single-PID fallback inlines the syscall +
// EPERM handling rather than calling IsAlive — IsAlive collapses EPERM to
// false (its callers depend on that narrower predicate), but the group-aware
// contract here promises EPERM-as-alive on both probes.
//
// NOTE: descendants that escaped the process group via setsid() or
// multiprocessing(daemon=False) are NOT visible to this probe and will not
// be reaped by the cleanup path. Documented limitation; see #1033.
func IsAliveOrGroupAlive(pid int) bool {
	if pid <= 1 {
		// pid <= 0: invalid. pid == 1: kill(-1, ...) is POSIX broadcast —
		// treating a PID file containing 1 as "alive" via the group probe
		// would let the orphan-group branch in KillVerifyAndCleanup issue
		// a broadcast SIGKILL. Refuse to probe.
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
	// Single-PID fallback — alive if signal-0 succeeds, OR errors with EPERM.
	// Inlined (rather than delegating to IsAlive) so EPERM-as-alive symmetry
	// with the group probe above is preserved.
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	if err := proc.Signal(syscall.Signal(0)); err == nil {
		return true
	} else if errors.Is(err, syscall.EPERM) {
		return true
	}
	return false
}

// groupAliveFn is overridable for tests; production uses IsAliveOrGroupAlive.
var groupAliveFn = IsAliveOrGroupAlive

// groupAllZombieFn is overridable for tests; production uses groupAllZombie
// (platform-specific). Reports whether every remaining member of the process
// group is a zombie — see the platform files for the container/non-reaping-init
// rationale.
var groupAllZombieFn = groupAllZombie

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
// Same zombie semantics as pollUntilDead: a zombie at the (originally
// tracked) PID counts as dead so an init-reaped orphan isn't a false
// negative. The PID-reuse race window is microseconds and matches
// pollUntilDead's pre-existing exposure. Probe errors stay inconclusive.
func pollUntilGroupDead(pid int, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if groupConfirmedDead(pid) {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	return groupConfirmedDead(pid)
}

// groupConfirmedDead is the shared "is this process group effectively gone"
// predicate used by pollUntilGroupDead. The group counts as dead when ANY of:
//
//  1. the group probe reports empty (kill(-pid, 0) -> ESRCH); or
//  2. the originally tracked PID is itself a zombie (init-reaped orphan case
//     that pollUntilDead already handled); or
//  3. every REMAINING member of the group is a zombie — a SIGKILLed child in a
//     container whose PID 1 does not reap keeps kill(-pid, 0) reporting the
//     group "alive" indefinitely even though the zombie holds no port or FDs.
//     Without this, the group-drain waits would hang the full timeout and the
//     watch-reload path would then skip the restart (issue surfaced by
//     tc29_watch_mixed). Probe errors stay inconclusive — never treated as dead.
func groupConfirmedDead(pid int) bool {
	if !groupAliveFn(pid) {
		return true
	}
	if z, err := isZombieFn(pid); err == nil && z {
		return true
	}
	if az, err := groupAllZombieFn(pid); err == nil && az {
		return true
	}
	return false
}

// signalGroupOrPID sends sig first to the process group (negative PID) and
// falls back to a single-process signal if that errors (process wasn't started
// with Setpgid). Returns the LAST error seen — caller should still verify
// death rather than trust the error code.
func signalGroupOrPID(pid int, sig syscall.Signal) error {
	if pid <= 1 {
		// Defensive: a corrupted PID file containing 1 (or 0/negative) must
		// never trigger kill(-1, ...), which is a POSIX broadcast to every
		// process the caller can signal. Refuse rather than translate.
		return fmt.Errorf("lifecycle: refusing to signal pid %d (would broadcast)", pid)
	}
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
//  4. SIGTERM (process group preferred), poll until the whole group is dead
//  5. if the group is still alive -> SIGKILL the group, poll up to 3s
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

	// Graceful: SIGTERM to the whole process group, then wait for the ENTIRE
	// group to die — not just the parent. For multi-process agents (e.g. a
	// Maven `mvn spring-boot:run` parent whose child JVM holds the port) the
	// parent can exit while the child lingers bound to the port and still
	// heartbeating. Polling parent-only (pollUntilDead) would report "stopped"
	// the instant the parent exits and remove the PID files while the child
	// survives; a child that slow-walks or ignores SIGTERM would then never be
	// force-killed. Mirror the orphan branch above: poll the group and escalate
	// SIGKILL to the group at the timeout so stop blocks until the port is
	// actually released.
	_ = signalGroupOrPID(pid, syscall.SIGTERM)
	if !pollUntilGroupDead(pid, timeout) {
		// Force: SIGKILL the whole group + extended poll. Window is 3s so a
		// parent that's slow to reap (or has exited entirely, leaving init to
		// reap) doesn't trip a false-negative — pollUntilGroupDead also treats
		// zombies as dead, so the only way to time out here is a group member
		// genuinely refusing to die.
		_ = signalGroupOrPID(pid, syscall.SIGKILL)
		if !pollUntilGroupDead(pid, 3*time.Second) {
			return false, fmt.Errorf("lifecycle: process group %d (%s) still alive after SIGKILL", pid, name)
		}
	}

	if err := os.Remove(pidPath); err != nil && !os.IsNotExist(err) {
		return true, fmt.Errorf("lifecycle: process killed but failed to remove %s: %w", pidPath, err)
	}
	_ = os.Remove(groupPath) // best-effort; agent may not have a .group file (services don't)
	return true, nil
}

// KillPIDVerify runs TERM -> poll -> KILL -> poll against a bare PID (no
// PID-file bookkeeping), reusing signalGroupOrPID + pollUntilDead so callers
// inherit the zombie-aware death check and the PID<=1 broadcast guard. Returns
// true on confirmed death.
func KillPIDVerify(pid int, timeout time.Duration) bool {
	if pid <= 1 {
		return true
	}
	_ = signalGroupOrPID(pid, syscall.SIGTERM)
	if pollUntilDead(pid, timeout) {
		return true
	}
	_ = signalGroupOrPID(pid, syscall.SIGKILL)
	return pollUntilDead(pid, 3*time.Second)
}

// KillGroupVerify is the group-aware sibling of KillPIDVerify: TERM the process
// group, wait for the WHOLE group to drain, escalate to SIGKILL on timeout, and
// wait again. It routes through pollUntilGroupDead so callers inherit the
// zombie-aware group-drain check — an all-zombie group (e.g. a SIGKILLed child
// orphaned to a non-reaping container PID 1) counts as drained rather than
// hanging the timeout. Returns true on confirmed group death.
//
// Used by the watch-mode paths (terminateAgent, the restart fallback) that hold
// a bare PID with no <name>.pid bookkeeping. The 3s post-SIGKILL window matches
// KillVerifyAndCleanup.
func KillGroupVerify(pid int, timeout time.Duration) bool {
	if pid <= 1 {
		return true
	}
	_ = signalGroupOrPID(pid, syscall.SIGTERM)
	if pollUntilGroupDead(pid, timeout) {
		return true
	}
	_ = signalGroupOrPID(pid, syscall.SIGKILL)
	return pollUntilGroupDead(pid, 3*time.Second)
}
