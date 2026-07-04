package lifecycle

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
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

// TestKillVerifyAndCleanup_GracefulBranch_WaitsForGroupDeath is the #1274
// regression: in the graceful branch (parent alive at entry) the wait MUST be
// group-scoped, not parent-scoped. Here the parent stays "alive" per the
// single-PID stub throughout, while the group flips dead shortly after SIGTERM
// — stop must observe the GROUP transition and clean up. Pre-fix the graceful
// branch polled pollUntilDead(parent), which never saw the parent die and
// would have timed out; this asserts the group probe drives the wait.
func TestKillVerifyAndCleanup_GracefulBranch_WaitsForGroupDeath(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 55555
	useStubAlive(t, map[int]bool{pid: true})      // parent alive -> graceful branch
	useStubGroupAlive(t, map[int]bool{pid: true}) // group alive initially

	// Flip the group dead shortly after SIGTERM so pollUntilGroupDead observes
	// the transition rather than timing out.
	go func() {
		time.Sleep(80 * time.Millisecond)
		setGroupAlive(pid, false)
	}()

	g := NewGroupID()
	_ = WriteAgent("graceful-group", pid, g)

	start := time.Now()
	killed, err := KillVerifyAndCleanup("graceful-group", 2*time.Second)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !killed {
		t.Error("killed should be true when the group was reaped in the graceful branch")
	}
	if elapsed := time.Since(start); elapsed < 60*time.Millisecond {
		t.Errorf("returned in %v — graceful branch did not wait on the group", elapsed)
	}
	if _, err := os.Stat(PIDFile("graceful-group")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed after group reap")
	}
	if _, err := os.Stat(GroupFile("graceful-group")); !os.IsNotExist(err) {
		t.Errorf("group file should be removed after group reap")
	}
}

// TestKillVerifyAndCleanup_GracefulBranch_GroupRefusesToDie verifies that in
// the graceful branch a group that survives both SIGTERM and SIGKILL causes an
// error naming the process GROUP and preserves the PID file for retry — the
// parent being "alive" per the single-PID stub must not short-circuit the
// group escalation.
func TestKillVerifyAndCleanup_GracefulBranch_GroupRefusesToDie(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 55556
	useStubAlive(t, map[int]bool{pid: true})      // parent alive -> graceful branch
	useStubGroupAlive(t, map[int]bool{pid: true}) // group never dies

	g := NewGroupID()
	_ = WriteAgent("graceful-undead", pid, g)

	_, err := KillVerifyAndCleanup("graceful-undead", 100*time.Millisecond)
	if err == nil {
		t.Fatal("expected error when the group can't be killed in the graceful branch")
	}
	if !strings.Contains(err.Error(), "process group") {
		t.Errorf("error should reference the process group, got: %v", err)
	}
	if _, statErr := os.Stat(PIDFile("graceful-undead")); statErr != nil {
		t.Errorf("PID file should be preserved on verify failure: %v", statErr)
	}
}

// TestKillVerifyAndCleanup_GracefulBranch_ParentDiesChildLingers_RealProcess
// reproduces the field-measured #1274 symptom with real processes: a group
// leader (recorded PID, like an `mvn spring-boot:run` parent) that dies on
// SIGTERM while a child that IGNORES SIGTERM lingers in the same group. The
// discriminator is elapsed time: pre-fix the graceful branch polled the parent
// only and returned within milliseconds of the parent's death (leaking the
// child); post-fix it blocks for the whole SIGTERM window waiting on the
// group, then SIGKILLs the child. We assert the call blocked (did not return
// early) AND the group is fully drained afterward.
func TestKillVerifyAndCleanup_GracefulBranch_ParentDiesChildLingers_RealProcess(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Outer sh is the group leader (recorded PID). It backgrounds an inner sh
	// that ignores SIGTERM and sleeps, then the outer sh sleeps 5s so it is
	// still alive when KillVerifyAndCleanup enters the graceful branch. On the
	// group SIGTERM the outer sh dies (default action) while the inner sh
	// survives — exactly the parent-dies-first, child-lingers shape.
	cmd := exec.Command("sh", "-c", `sh -c "trap '' TERM; sleep 60" & sleep 5`)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Skipf("sh not available: %v", err)
	}
	pid := cmd.Process.Pid
	waitDone := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(waitDone)
	}()
	t.Cleanup(func() {
		_ = syscall.Kill(-pid, syscall.SIGKILL)
		<-waitDone
	})

	// Let the inner child fork into the group before we act.
	time.Sleep(250 * time.Millisecond)

	g := NewGroupID()
	if err := WriteAgent("linger", pid, g); err != nil {
		t.Fatal(err)
	}

	const termTimeout = 800 * time.Millisecond
	start := time.Now()
	killed, err := KillVerifyAndCleanup("linger", termTimeout)
	elapsed := time.Since(start)
	if err != nil {
		t.Fatalf("KillVerifyAndCleanup: %v", err)
	}
	if !killed {
		t.Error("expected killed=true")
	}
	// Pre-fix this returns in ~milliseconds (parent died on SIGTERM); the fix
	// makes it wait out the SIGTERM window on the TERM-ignoring child.
	if elapsed < termTimeout {
		t.Errorf("returned in %v (< SIGTERM window %v) — graceful branch did not wait on the lingering child",
			elapsed, termTimeout)
	}
	// The child was SIGKILLed; poll for the group to drain (init reaps the
	// orphan zombie asynchronously).
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !IsAliveOrGroupAlive(pid) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if IsAliveOrGroupAlive(pid) {
		t.Errorf("process group %d still alive after stop — lingering child was not killed", pid)
	}
	if _, err := os.Stat(PIDFile("linger")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed")
	}
}

// useStubGroupAllZombie overrides groupAllZombieFn for a test.
func useStubGroupAllZombie(t *testing.T, allZombie bool, err error) {
	t.Helper()
	prev := groupAllZombieFn
	groupAllZombieFn = func(pid int) (bool, error) { return allZombie, err }
	t.Cleanup(func() { groupAllZombieFn = prev })
}

// TestGroupAllZombie_RealZombie verifies the platform probe against a REAL
// unreaped zombie: a child in its own process group that has exited but whose
// parent (this test process) never Wait()s it. This mirrors the container
// case where a SIGKILLed orphan reparents to a non-reaping PID 1 — the zombie
// lingers in the process table, kill(-pgid, 0) still reports the group as
// "alive" (nil on Linux, EPERM on Darwin), yet groupAllZombie must recognize
// the group holds nothing live so the drain waits can make progress.
func TestGroupAllZombie_RealZombie(t *testing.T) {
	cmd := exec.Command("sh", "-c", "exit 0")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Skipf("sh not available: %v", err)
	}
	pid := cmd.Process.Pid
	t.Cleanup(func() { _ = cmd.Wait() }) // reap only in cleanup — hold the zombie

	// Let the child exit and settle into Z state.
	time.Sleep(150 * time.Millisecond)

	az, err := groupAllZombie(pid)
	if err != nil {
		t.Fatalf("groupAllZombie errored: %v", err)
	}
	if !az {
		t.Fatalf("groupAllZombie(%d) = false, want true (only member is a zombie)", pid)
	}

	// And the poll must treat it as dead promptly rather than timing out.
	if !pollUntilGroupDead(pid, 500*time.Millisecond) {
		t.Errorf("pollUntilGroupDead did not treat an all-zombie group as dead")
	}
}

// TestGroupAllZombie_LiveGroupNotAllZombie verifies the probe does NOT report a
// group with a live member as all-zombie (guards against prematurely declaring
// a still-running agent dead).
func TestGroupAllZombie_LiveGroupNotAllZombie(t *testing.T) {
	cmd := exec.Command("sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	pid := cmd.Process.Pid
	go func() { _ = cmd.Wait() }()
	t.Cleanup(func() { _ = cmd.Process.Kill() })

	az, err := groupAllZombie(pid)
	if err != nil {
		t.Fatalf("groupAllZombie errored: %v", err)
	}
	if az {
		t.Errorf("groupAllZombie(%d) = true for a live group, want false", pid)
	}
}

// TestKillVerifyAndCleanup_GroupOnlyZombies_CleansUp is the tc29_watch_mixed
// container regression at the unit level: the parent PID is gone and the group
// probe still reports "alive" (an unreaped zombie child), but groupAllZombie
// confirms nothing live remains. KillVerifyAndCleanup must therefore SUCCEED
// (remove the bookkeeping) instead of hanging the full timeout and erroring —
// which is what caused the watch-reload path to skip the restart.
func TestKillVerifyAndCleanup_GroupOnlyZombies_CleansUp(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const pid = 55557
	useStubAlive(t, map[int]bool{})               // parent already reaped/gone
	useStubGroupAlive(t, map[int]bool{pid: true}) // group probe: zombie present -> "alive"
	useStubGroupAllZombie(t, true, nil)           // ...but every member is a zombie

	g := NewGroupID()
	_ = WriteAgent("zombie-group", pid, g)

	start := time.Now()
	killed, err := KillVerifyAndCleanup("zombie-group", 3*time.Second)
	if err != nil {
		t.Fatalf("unexpected error (should treat all-zombie group as drained): %v", err)
	}
	if !killed {
		t.Error("expected killed=true for an all-zombie orphan group")
	}
	if elapsed := time.Since(start); elapsed > 1*time.Second {
		t.Errorf("took %v — should not hang the full timeout on a zombie group", elapsed)
	}
	if _, err := os.Stat(PIDFile("zombie-group")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed")
	}
}

// TestGroupConfirmedDead_ZombieLeaderLiveChild_NotDead is the PR #1275 review
// guard: a zombie group LEADER must not by itself confirm the group dead while
// a LIVE child remains. Pre-fix groupConfirmedDead short-circuited on the
// tracked PID's zombie state, which would mask a live TERM-ignoring child and
// abort the SIGKILL escalation.
func TestGroupConfirmedDead_ZombieLeaderLiveChild_NotDead(t *testing.T) {
	prevGroup, prevZombie, prevAllZ := groupAliveFn, isZombieFn, groupAllZombieFn
	groupAliveFn = func(pid int) bool { return true }                    // child keeps group non-empty
	isZombieFn = func(pid int) (bool, error) { return true, nil }        // LEADER is a zombie
	groupAllZombieFn = func(pid int) (bool, error) { return false, nil } // ...but a live child exists
	t.Cleanup(func() {
		groupAliveFn = prevGroup
		isZombieFn = prevZombie
		groupAllZombieFn = prevAllZ
	})

	if groupConfirmedDead(12345) {
		t.Error("groupConfirmedDead must be false: zombie leader + live child is NOT a dead group")
	}
	if pollUntilGroupDead(12345, 100*time.Millisecond) {
		t.Error("pollUntilGroupDead must not confirm death while a live child remains — escalation must proceed")
	}
}

// TestKillVerifyAndCleanup_ZombieLeaderLiveChild_Escalates is the real-process
// version: the group leader (recorded PID) exits and becomes a zombie held by
// this test process (a non-reaping parent, mirroring a container PID 1), while
// a child that ignores SIGTERM lingers in the same group holding "the port".
// KillVerifyAndCleanup must NOT short-circuit on the zombie leader — it must
// wait out the SIGTERM window and SIGKILL the child. Discriminator: elapsed
// time >= the SIGTERM window (pre-fix returned in ~ms via the leader-zombie
// shortcut), plus the group ends up with no live member.
func TestKillVerifyAndCleanup_ZombieLeaderLiveChild_Escalates(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Outer sh = group leader (recorded PID): it backgrounds a SIGTERM-ignoring
	// child in the same group, then exits -> becomes a zombie (we never Wait it
	// until cleanup). The child stays alive and ignores SIGTERM.
	cmd := exec.Command("sh", "-c", `sh -c "trap '' TERM; sleep 60" & exit 0`)
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Skipf("sh not available: %v", err)
	}
	pid := cmd.Process.Pid
	t.Cleanup(func() {
		_ = syscall.Kill(-pid, syscall.SIGKILL)
		_ = cmd.Wait()
	})

	// Let the leader exit into Z state and the child settle in the group.
	time.Sleep(250 * time.Millisecond)

	g := NewGroupID()
	if err := WriteAgent("zleader", pid, g); err != nil {
		t.Fatal(err)
	}

	const termTimeout = 800 * time.Millisecond
	start := time.Now()
	killed, err := KillVerifyAndCleanup("zleader", termTimeout)
	elapsed := time.Since(start)
	if err != nil {
		t.Fatalf("KillVerifyAndCleanup: %v", err)
	}
	if !killed {
		t.Error("expected killed=true")
	}
	if elapsed < termTimeout {
		t.Errorf("returned in %v (< SIGTERM window %v) — leader-zombie shortcut masked the live child", elapsed, termTimeout)
	}
	// The child must be dead: no live (non-zombie) member left in the group.
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if az, err := groupAllZombie(pid); err == nil && az {
			break
		}
		if !IsAliveOrGroupAlive(pid) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if az, _ := groupAllZombie(pid); IsAliveOrGroupAlive(pid) && !az {
		t.Errorf("a live child survived in group %d — escalation did not kill it", pid)
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

// TestPollUntilGroupDead_TreatsAllZombieGroupAsDead guards the zombie-as-dead
// invariant in the group-aware poll loop: when the group probe still reports
// "alive" (an unreaped orphan zombie keeps kill(-pgid, 0) from returning ESRCH)
// but EVERY remaining member is a zombie, the group counts as dead. The signal
// is groupAllZombieFn, NOT the tracked PID's own zombie state — a zombie leader
// with a live child must still be treated as alive (see
// TestGroupConfirmedDead_ZombieLeaderLiveChild_NotDead).
func TestPollUntilGroupDead_TreatsAllZombieGroupAsDead(t *testing.T) {
	prevGroup, prevAllZ := groupAliveFn, groupAllZombieFn
	groupAliveFn = func(pid int) bool { return true } // zombie present -> probe never empty
	groupAllZombieFn = func(pid int) (bool, error) { return true, nil }
	t.Cleanup(func() {
		groupAliveFn = prevGroup
		groupAllZombieFn = prevAllZ
	})

	if !pollUntilGroupDead(12345, 100*time.Millisecond) {
		t.Error("pollUntilGroupDead must treat an all-zombie group as dead even when the group probe stays alive")
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
		// Kill the orphan group descendants. Parent was already reaped
		// inline above (exec.Cmd.Wait may only be called once).
		_ = syscall.Kill(-parentPID, syscall.SIGKILL)
	})

	// Give the shell time to fork its background sleep into the pgid.
	time.Sleep(150 * time.Millisecond)

	// Kill ONLY the parent (the bash shell). The background sleep stays alive
	// in the same pgid as an orphan.
	if err := parent.Process.Signal(syscall.SIGKILL); err != nil {
		t.Fatalf("signal parent: %v", err)
	}
	// Reap the parent inline. Wait() blocks until the kernel finishes
	// teardown so the PID is no longer in the process table when we check
	// IsAlive below. Single Wait() — t.Cleanup must NOT call Wait() again
	// since exec.Cmd.Wait() is callable exactly once (race detector flags
	// concurrent or repeated calls).
	_ = parent.Wait()

	if IsAlive(parentPID) {
		t.Fatal("parent did not die after SIGKILL + Wait")
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
	deadline := time.Now().Add(2 * time.Second)
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
	// signal(0) keeps reporting alive on the zombie. Synchronize on the reap
	// before asserting IsAlive: KillVerifyAndCleanup treats zombies as dead,
	// but IsAlive reports zombies as alive, so without the sync the assert
	// races the reaper goroutine (#1176).
	cmd := exec.Command("sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	waitDone := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(waitDone)
	}()
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
	select {
	case <-waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("sleep was not reaped after KillVerifyAndCleanup")
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
	// Reap-synchronized: IsAlive reports zombies as alive, so the assert
	// below must wait for the reaper goroutine (#1176).
	waitDone := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(waitDone)
	}()
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
	select {
	case <-waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("process was not reaped after KILL fallback")
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
	// ESRCH (which the kill helper ignores) but the alive check stays true.
	// The graceful branch enters because the parent probe reports alive, and it
	// then polls the GROUP — so the group must also be stubbed alive for the
	// "can never be killed" simulation to hold through the SIGKILL escalation.
	useStubAlive(t, map[int]bool{99999: true})
	useStubGroupAlive(t, map[int]bool{99999: true})

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

// TestKillPIDVerify_LiveProcessKilled spawns a real sleep and confirms
// KillPIDVerify reports death after SIGTERM.
//
// Reap-synchronized (#1176): KillPIDVerify's poll treats zombies as dead and
// returns within microseconds of SIGTERM, but IsAlive (signal-0 probe) reports
// zombies as ALIVE — so the assert must wait for the reaper goroutine to run,
// otherwise it races the scheduler.
func TestKillPIDVerify_LiveProcessKilled(t *testing.T) {
	cmd := exec.Command("sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	waitDone := make(chan struct{})
	go func() {
		_ = cmd.Wait()
		close(waitDone)
	}()
	t.Cleanup(func() { _ = cmd.Process.Kill() })

	if !KillPIDVerify(cmd.Process.Pid, 3*time.Second) {
		t.Error("expected KillPIDVerify to confirm death")
	}
	select {
	case <-waitDone:
	case <-time.After(3 * time.Second):
		t.Fatal("sleep was not reaped after KillPIDVerify")
	}
	if IsAlive(cmd.Process.Pid) {
		t.Error("process should be dead")
	}
}

// TestKillPIDVerify_RefusesPID1 confirms the broadcast guard: PID <= 1 returns
// true without signaling anything.
func TestKillPIDVerify_RefusesPID1(t *testing.T) {
	if !KillPIDVerify(1, 100*time.Millisecond) {
		t.Error("expected KillPIDVerify(1) to return true without signaling")
	}
	if !KillPIDVerify(0, 100*time.Millisecond) {
		t.Error("expected KillPIDVerify(0) to return true without signaling")
	}
}

// TestKillPIDVerify_TreatsZombieAsDead confirms KillPIDVerify inherits
// pollUntilDead's zombie-as-dead semantics via the stub hooks.
func TestKillPIDVerify_TreatsZombieAsDead(t *testing.T) {
	prevAlive, prevZombie := processAliveFn, isZombieFn
	processAliveFn = func(pid int) bool { return true } // never dead by signal 0
	isZombieFn = func(pid int) (bool, error) { return true, nil }
	t.Cleanup(func() {
		processAliveFn = prevAlive
		isZombieFn = prevZombie
	})

	if !KillPIDVerify(99999, 100*time.Millisecond) {
		t.Error("expected KillPIDVerify to treat a zombie PID as dead")
	}
}

// TestIsAliveOrGroupAlive_RefusesPID1 guards against accidental broadcast
// signals: a corrupted .pid file containing 1 must never be reported as
// "alive" via the group probe, since kill(-1, ...) is POSIX broadcast to
// every process the caller can signal — the orphan-group branch in
// KillVerifyAndCleanup would then issue a session-wide SIGKILL.
func TestIsAliveOrGroupAlive_RefusesPID1(t *testing.T) {
	// PID 1 (init) is always alive on POSIX. The function must still return
	// false because the group probe at -1 is too dangerous to issue.
	if IsAliveOrGroupAlive(1) {
		t.Error("IsAliveOrGroupAlive(1) must return false — kill(-1,...) would broadcast")
	}
}

// TestSignalGroupOrPID_RefusesPID1 verifies the same guard at the signal-send
// site: even if a pid==1 leaked past the probe layer somehow (caller bug,
// future code path, etc.), signalGroupOrPID itself refuses rather than
// translating to kill(-1, ...).
//
// Verification strategy: spawn a benign sleep, attempt signalGroupOrPID(1, ...)
// for SIGTERM, and confirm (a) an error is returned and (b) the sleep is
// still alive — proving no broadcast was issued.
func TestSignalGroupOrPID_RefusesPID1(t *testing.T) {
	cmd := exec.Command("sleep", "30")
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		t.Fatalf("spawn sleep: %v", err)
	}
	go func() { _ = cmd.Wait() }()
	t.Cleanup(func() { _ = cmd.Process.Kill() })

	sleepPID := cmd.Process.Pid

	err := signalGroupOrPID(1, syscall.SIGTERM)
	if err == nil {
		t.Fatal("signalGroupOrPID(1, SIGTERM) must return an error — would broadcast")
	}

	// Give any (incorrectly issued) signal a moment to land before we probe.
	time.Sleep(50 * time.Millisecond)

	if !IsAlive(sleepPID) {
		t.Errorf("benign sleep PID %d is dead — signalGroupOrPID(1, ...) appears to have broadcast", sleepPID)
	}

	// Also verify pid==0 and pid<0 are refused symmetrically.
	if err := signalGroupOrPID(0, syscall.SIGTERM); err == nil {
		t.Error("signalGroupOrPID(0, SIGTERM) must return an error")
	}
	if err := signalGroupOrPID(-5, syscall.SIGTERM); err == nil {
		t.Error("signalGroupOrPID(-5, SIGTERM) must return an error")
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
