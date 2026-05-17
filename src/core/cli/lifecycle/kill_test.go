package lifecycle

import (
	"fmt"
	"os"
	"os/exec"
	"sync"
	"syscall"
	"testing"
	"time"
)

// stubAlivePIDs is a test seam — when set, IsAlive lookups consult this map
// instead of running real syscall(0). Tests that need to control liveness
// independently of real processes use this. Production never touches it.
var stubAlivePIDs = struct {
	sync.Mutex
	pids map[int]bool
	use  bool
}{pids: make(map[int]bool)}

func useStubAlive(t *testing.T, alive map[int]bool) {
	t.Helper()
	stubAlivePIDs.Lock()
	prev := processAliveFn
	prevZombie := isZombieFn
	stubAlivePIDs.pids = alive
	stubAlivePIDs.use = true
	processAliveFn = func(pid int) bool {
		stubAlivePIDs.Lock()
		defer stubAlivePIDs.Unlock()
		return stubAlivePIDs.pids[pid]
	}
	// Tests that stub aliveness must also stub zombie detection — otherwise
	// the real isZombie would shell out to ps. Since these tests use fake
	// PIDs, the stub always reports "not a zombie, no error".
	isZombieFn = func(pid int) (bool, error) { return false, nil }
	stubAlivePIDs.Unlock()
	t.Cleanup(func() {
		stubAlivePIDs.Lock()
		processAliveFn = prev
		isZombieFn = prevZombie
		stubAlivePIDs.use = false
		stubAlivePIDs.pids = make(map[int]bool)
		stubAlivePIDs.Unlock()
	})
}

// stubGroupAlivePIDs mirrors stubAlivePIDs but for the group-aware probe.
// Tests can drive parent-alive vs group-alive independently to exercise the
// #1033 orphan-descendants branch in KillVerifyAndCleanup.
var stubGroupAlivePIDs = struct {
	sync.Mutex
	pids map[int]bool
	use  bool
}{pids: make(map[int]bool)}

func useStubGroupAlive(t *testing.T, alive map[int]bool) {
	t.Helper()
	stubGroupAlivePIDs.Lock()
	prev := groupAliveFn
	stubGroupAlivePIDs.pids = alive
	stubGroupAlivePIDs.use = true
	groupAliveFn = func(pid int) bool {
		stubGroupAlivePIDs.Lock()
		defer stubGroupAlivePIDs.Unlock()
		return stubGroupAlivePIDs.pids[pid]
	}
	stubGroupAlivePIDs.Unlock()
	t.Cleanup(func() {
		stubGroupAlivePIDs.Lock()
		groupAliveFn = prev
		stubGroupAlivePIDs.use = false
		stubGroupAlivePIDs.pids = make(map[int]bool)
		stubGroupAlivePIDs.Unlock()
	})
}

// setGroupAlive updates the stub map for an in-flight test (e.g., to flip
// the group from "still alive" to "dead" after SIGTERM is sent).
func setGroupAlive(pid int, alive bool) {
	stubGroupAlivePIDs.Lock()
	defer stubGroupAlivePIDs.Unlock()
	if alive {
		stubGroupAlivePIDs.pids[pid] = true
	} else {
		delete(stubGroupAlivePIDs.pids, pid)
	}
}

func TestKillVerifyMissingPIDFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	killed, err := KillVerifyAndCleanup("ghost", 100*time.Millisecond)
	if err != nil {
		t.Errorf("missing pid file should be no-op, got err=%v", err)
	}
	if killed {
		t.Error("should not report killed when no PID file")
	}
}

func TestKillVerifyDeadPIDCleansFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Write a PID file pointing at a dead PID. Use the stub so we don't depend
	// on the OS reporting a real PID as dead.
	useStubAlive(t, map[int]bool{}) // empty map = nothing alive
	// Group must also be empty so we hit the "pure stale bookkeeping" branch
	// rather than the #1033 orphan-group path.
	useStubGroupAlive(t, map[int]bool{})

	g := NewGroupID()
	_ = WriteAgent("zombie", 12345, g)

	killed, err := KillVerifyAndCleanup("zombie", 100*time.Millisecond)
	if err != nil {
		t.Errorf("dead PID cleanup should succeed: %v", err)
	}
	if killed {
		t.Error("should not report killed for already-dead PID")
	}
	if _, err := os.Stat(PIDFile("zombie")); !os.IsNotExist(err) {
		t.Errorf("expected pid file removed: %v", err)
	}
	if _, err := os.Stat(GroupFile("zombie")); !os.IsNotExist(err) {
		t.Errorf("expected group file removed: %v", err)
	}
}

// TestKillVerifyAndCleanup_ParentDeadGroupDead_CleansFilesOnly verifies the
// pure stale-bookkeeping branch: both single-PID and group probes return dead,
// so no signal is sent and the PID/group files are cleaned.
func TestKillVerifyAndCleanup_ParentDeadGroupDead_CleansFilesOnly(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{})

	g := NewGroupID()
	_ = WriteAgent("stale", 22222, g)

	killed, err := KillVerifyAndCleanup("stale", 100*time.Millisecond)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if killed {
		t.Error("killed should be false when parent and group are both dead")
	}
	if _, err := os.Stat(PIDFile("stale")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed")
	}
	if _, err := os.Stat(GroupFile("stale")); !os.IsNotExist(err) {
		t.Errorf("group file should be removed")
	}
}

// TestKillVerifyAndCleanup_ParentDeadGroupAlive_SignalsGroup verifies the
// #1033 orphan-descendants branch: parent is dead but group has surviving
// processes. We expect SIGTERM to the group, then cleanup once the group dies.
func TestKillVerifyAndCleanup_ParentDeadGroupAlive_SignalsGroup(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 33333
	useStubAlive(t, map[int]bool{}) // parent already dead
	useStubGroupAlive(t, map[int]bool{pid: true})

	// Flip the group to "dead" after a short delay so pollUntilGroupDead
	// observes the transition rather than timing out.
	go func() {
		time.Sleep(80 * time.Millisecond)
		setGroupAlive(pid, false)
	}()

	g := NewGroupID()
	_ = WriteAgent("orphan", pid, g)

	killed, err := KillVerifyAndCleanup("orphan", 2*time.Second)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !killed {
		t.Error("killed should be true when orphan group was reaped")
	}
	if _, err := os.Stat(PIDFile("orphan")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed after group reap")
	}
	if _, err := os.Stat(GroupFile("orphan")); !os.IsNotExist(err) {
		t.Errorf("group file should be removed after group reap")
	}
}

// TestKillVerifyAndCleanup_ParentDeadGroupRefusesToDie verifies that when the
// orphan group survives SIGTERM and SIGKILL the function errors and does NOT
// remove the PID file — the user must be able to retry.
func TestKillVerifyAndCleanup_ParentDeadGroupRefusesToDie(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 44444
	useStubAlive(t, map[int]bool{}) // parent dead
	// Group stays alive throughout — no goroutine flips it.
	useStubGroupAlive(t, map[int]bool{pid: true})

	g := NewGroupID()
	_ = WriteAgent("undead-group", pid, g)

	_, err := KillVerifyAndCleanup("undead-group", 100*time.Millisecond)
	if err == nil {
		t.Fatal("expected error when group can't be killed")
	}
	if _, statErr := os.Stat(PIDFile("undead-group")); statErr != nil {
		t.Errorf("PID file should be preserved on verify failure: %v", statErr)
	}
}

// TestPollUntilGroupDead_TreatsZombieAsDead guards the zombie-as-dead invariant
// in the group-aware poll loop — init-reaped orphans must not be a false
// negative.
func TestPollUntilGroupDead_TreatsZombieAsDead(t *testing.T) {
	prevGroup, prevZombie := groupAliveFn, isZombieFn
	groupAliveFn = func(pid int) bool { return true } // never empty
	isZombieFn = func(pid int) (bool, error) { return true, nil }
	t.Cleanup(func() {
		groupAliveFn = prevGroup
		isZombieFn = prevZombie
	})

	if !pollUntilGroupDead(12345, 100*time.Millisecond) {
		t.Error("pollUntilGroupDead must treat zombie as dead even when group probe stays alive")
	}
}

// TestIsAliveOrGroupAlive_RealFork spawns a child with Setpgid, kills the
// parent (leaving the child as an orphan in the same pgid), and verifies the
// group probe correctly differentiates the orphan-alive case from group-dead.
//
// Darwin-friendly: relies only on POSIX kill(2) semantics that match Linux.
func TestIsAliveOrGroupAlive_RealFork(t *testing.T) {
	// Spawn the parent and the child via a single bash so the child inherits
	// the parent's pgid. We use a shell that backgrounds a sleep, then the
	// shell itself dies — the orphan sleep stays in the original pgid.
	parent := exec.Command("bash", "-c", "sleep 10 & sleep 10")
	parent.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := parent.Start(); err != nil {
		t.Fatalf("spawn parent: %v", err)
	}
	parentPID := parent.Process.Pid
	t.Cleanup(func() {
		_ = syscall.Kill(-parentPID, syscall.SIGKILL)
		_ = parent.Wait()
	})

	// Give the shell time to fork its background sleep into the pgid.
	time.Sleep(150 * time.Millisecond)

	// Kill ONLY the parent (the bash shell). The background sleep stays alive
	// in the same pgid as an orphan.
	if err := parent.Process.Signal(syscall.SIGKILL); err != nil {
		t.Fatalf("signal parent: %v", err)
	}
	go func() { _ = parent.Wait() }()

	// Wait for the parent to be reaped from the process table.
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if !IsAlive(parentPID) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if IsAlive(parentPID) {
		t.Fatal("parent did not die")
	}

	// Parent is dead. Group still has the orphan sleep — group probe should
	// return true.
	if !IsAliveOrGroupAlive(parentPID) {
		t.Errorf("IsAliveOrGroupAlive(%d): expected true (orphan in group), got false", parentPID)
	}
	if IsAlive(parentPID) {
		t.Errorf("IsAlive(%d): expected false (parent dead), got true", parentPID)
	}

	// Kill the whole group.
	if err := syscall.Kill(-parentPID, syscall.SIGKILL); err != nil {
		t.Fatalf("kill group: %v", err)
	}

	// Wait for the group to drain.
	deadline = time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if !IsAliveOrGroupAlive(parentPID) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if IsAliveOrGroupAlive(parentPID) {
		t.Errorf("IsAliveOrGroupAlive(%d): expected false after group SIGKILL", parentPID)
	}
}

func TestKillVerifyLiveProcessKilled(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Spawn a real `sleep` so SIGTERM actually does something.
	// Reap from a goroutine so the kernel can drop the PID entry — otherwise
	// signal(0) keeps reporting alive on the zombie.
	cmd := exec.Command("sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	go func() { _ = cmd.Wait() }()
	t.Cleanup(func() { _ = cmd.Process.Kill() })

	g := NewGroupID()
	if err := WriteAgent("sleeper", cmd.Process.Pid, g); err != nil {
		t.Fatal(err)
	}

	killed, err := KillVerifyAndCleanup("sleeper", 3*time.Second)
	if err != nil {
		t.Fatalf("KillVerifyAndCleanup: %v", err)
	}
	if !killed {
		t.Error("expected killed=true for live process")
	}
	if _, err := os.Stat(PIDFile("sleeper")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed")
	}
	if IsAlive(cmd.Process.Pid) {
		t.Error("process should be dead")
	}
}

// TestKillVerifyKILLFallback uses the stub to simulate a process that ignores
// SIGTERM but dies on SIGKILL. We simulate this by tracking signals via the
// stub and only flipping "alive" to false after a SIGKILL would have arrived.
func TestKillVerifyKILLFallback(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Use a bash script that traps SIGTERM and ignores it for 5 seconds.
	// We'll then KillVerifyAndCleanup with a short timeout so the SIGKILL path
	// is exercised.
	cmd := exec.Command("bash", "-c", "trap '' TERM; sleep 30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Skipf("bash not available: %v", err)
	}
	go func() { _ = cmd.Wait() }()
	t.Cleanup(func() { _ = cmd.Process.Kill() })

	g := NewGroupID()
	if err := WriteAgent("stubborn", cmd.Process.Pid, g); err != nil {
		t.Fatal(err)
	}

	// Short SIGTERM timeout so we fall through to SIGKILL.
	killed, err := KillVerifyAndCleanup("stubborn", 500*time.Millisecond)
	if err != nil {
		t.Fatalf("KillVerifyAndCleanup KILL fallback: %v", err)
	}
	if !killed {
		t.Error("expected killed=true")
	}
	if IsAlive(cmd.Process.Pid) {
		t.Error("process should be dead after KILL fallback")
	}
}

// TestKillVerifyFailureLeavesFile uses the stub to simulate a process that
// can never be killed (always alive). Verifies the PID file is NOT removed
// so the user can retry.
func TestKillVerifyFailureLeavesFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Stub: PID 99999 is always alive. Real signals to that PID will fail with
	// ESRCH (which the kill helper ignores) but the alive check stays true,
	// so the function should error and NOT remove the PID file.
	useStubAlive(t, map[int]bool{99999: true})

	g := NewGroupID()
	_ = WriteAgent("undead", 99999, g)

	_, err := KillVerifyAndCleanup("undead", 100*time.Millisecond)
	if err == nil {
		t.Fatal("expected error when process can't be killed")
	}
	if _, statErr := os.Stat(PIDFile("undead")); statErr != nil {
		t.Errorf("PID file should be preserved on verify failure: %v", statErr)
	}
}

// TestPollUntilDeadIgnoresZombieProbeError guards the invariant that a
// transient ps failure (EAGAIN under load, RLIMIT_NPROC, etc.) must NEVER
// be interpreted as "process is dead". Pre-fix, isZombie returned bool only
// and any ps error was treated as dead — that flipped death detection to
// true while the process was still alive, orphaning the agent.
func TestPollUntilDeadIgnoresZombieProbeError(t *testing.T) {
	// Process is alive; zombie probe always fails with a transient error.
	prevAlive, prevZombie := processAliveFn, isZombieFn
	processAliveFn = func(pid int) bool { return true }
	isZombieFn = func(pid int) (bool, error) {
		return false, fmt.Errorf("simulated transient ps failure")
	}
	t.Cleanup(func() {
		processAliveFn = prevAlive
		isZombieFn = prevZombie
	})

	if pollUntilDead(12345, 100*time.Millisecond) {
		t.Error("pollUntilDead must return false when process is alive and zombie probe errored — probe failure is inconclusive, not a death signal")
	}
}
