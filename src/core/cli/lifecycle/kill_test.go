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
