package lifecycle

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSweepDropsDeadAgentPID(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{}) // nothing is alive
	useStubGroupAlive(t, map[int]bool{})
	g := NewGroupID()
	_ = WriteAgent("dead-agent", 12345, g)

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.DeadAgentPIDsCleaned == 0 {
		t.Errorf("expected DeadAgentPIDsCleaned > 0, got %+v", r)
	}
	if _, err := os.Stat(PIDFile("dead-agent")); !os.IsNotExist(err) {
		t.Errorf("pid file should be gone, stat err=%v", err)
	}
}

func TestSweepKeepsLiveAgentPID(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{777: true}) // 777 is alive
	useStubGroupAlive(t, map[int]bool{777: true})
	g := NewGroupID()
	_ = WriteAgent("alive-agent", 777, g)

	if _, err := Sweep(); err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if _, err := os.Stat(PIDFile("alive-agent")); err != nil {
		t.Errorf("live agent pid file should remain: %v", err)
	}
	if _, err := os.Stat(GroupFile("alive-agent")); err != nil {
		t.Errorf("live agent group file should remain: %v", err)
	}
}

func TestSweepRemovesOrphanGroupFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{})
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		t.Fatal(err)
	}
	g := NewGroupID()
	if err := os.WriteFile(GroupFile("orphan"), []byte(g.String()), 0644); err != nil {
		t.Fatal(err)
	}

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.StaleGroupFilesPruned == 0 {
		t.Errorf("expected StaleGroupFilesPruned > 0, got %+v", r)
	}
	if _, err := os.Stat(GroupFile("orphan")); !os.IsNotExist(err) {
		t.Errorf("orphan group file should be removed")
	}
}

func TestSweepDropsDeadDepsEntries(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{777: true}) // alive-agent's pid
	useStubGroupAlive(t, map[int]bool{777: true})
	g := NewGroupID()
	_ = WriteAgent("alive-agent", 777, g)
	_ = WriteAgent("dead-agent", 12345, g) // 12345 not in alive map

	// Wait — Sweep step 1 will remove dead-agent.pid. We need the deps file to
	// reference dead-agent BEFORE the sweep so we can verify step 3 removes the
	// stale entry. Build the deps file directly.
	if err := RegisterDep(ServiceRegistry, g, []string{"alive-agent", "dead-agent"}); err != nil {
		t.Fatal(err)
	}

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.StaleDepsEntries == 0 {
		t.Errorf("expected StaleDepsEntries > 0, got %+v", r)
	}

	// Deps file should now contain only alive-agent.
	got, _ := AgentsInGroup(ServiceRegistry, g)
	if len(got) != 1 || got[0] != "alive-agent" {
		t.Errorf("deps after sweep = %v, want [alive-agent]", got)
	}
}

func TestSweepRemovesEmptyDepsFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{}) // nothing alive
	useStubGroupAlive(t, map[int]bool{})
	g := NewGroupID()
	_ = WriteAgent("dead", 12345, g)
	_ = RegisterDep(ServiceRegistry, g, []string{"dead"})

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.EmptyDepsFilesRemoved == 0 {
		t.Errorf("expected EmptyDepsFilesRemoved > 0, got %+v", r)
	}
	if _, err := os.Stat(RegistryDepsFile(g)); !os.IsNotExist(err) {
		t.Errorf("empty deps file should be gone: %v", err)
	}
}

func TestSweepDoesNotKillProcesses(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// All PIDs alive — Sweep must not touch them.
	useStubAlive(t, map[int]bool{777: true, 888: true, 999: true})
	useStubGroupAlive(t, map[int]bool{777: true, 888: true, 999: true})
	g := NewGroupID()
	_ = WriteAgent("a", 777, g)
	_ = WriteService("registry", 888)
	_ = WriteService("ui", 999)
	_ = WriteWrapperPID(g, 777)

	if _, err := Sweep(); err != nil {
		t.Fatalf("Sweep: %v", err)
	}

	// All files still present.
	for _, p := range []string{PIDFile("a"), PIDFile("registry"), PIDFile("ui"), WrapperPIDFile(g)} {
		if _, err := os.Stat(p); err != nil {
			t.Errorf("file %s should still exist: %v", filepath.Base(p), err)
		}
	}
}

func TestSweepRemovesStaleWrapperPID(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{}) // nothing alive
	useStubGroupAlive(t, map[int]bool{})
	g := NewGroupID()
	_ = WriteWrapperPID(g, 12345)

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.StaleWrapperPIDs == 0 {
		t.Errorf("expected StaleWrapperPIDs > 0, got %+v", r)
	}
	if _, err := os.Stat(WrapperPIDFile(g)); !os.IsNotExist(err) {
		t.Errorf("stale wrapper pid should be gone")
	}
}

func TestSweepCleansTmpDepsLeftover(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	if err := os.MkdirAll(RegistryDepsDir(), 0755); err != nil {
		t.Fatal(err)
	}
	leftover := filepath.Join(RegistryDepsDir(), "1234-5678-9.tmp")
	if err := os.WriteFile(leftover, []byte("garbage"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := Sweep(); err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if _, err := os.Stat(leftover); !os.IsNotExist(err) {
		t.Errorf("leftover .tmp should be removed")
	}
}

// TestSweep_AgentPID_KeepsWhenGroupAlive guards the #1033 fix: the agent .pid
// sweep MUST keep the file when the parent PID is dead but the process group
// has surviving descendants (orphans), so `meshctl stop` can still find the
// bookkeeping and reap them.
func TestSweep_AgentPID_KeepsWhenGroupAlive(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Parent dead, group alive — the orphan case.
	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{55555: true})
	g := NewGroupID()
	_ = WriteAgent("orphan-agent", 55555, g)

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.DeadAgentPIDsCleaned != 0 {
		t.Errorf("DeadAgentPIDsCleaned should be 0 when group is alive; got %+v", r)
	}
	if _, err := os.Stat(PIDFile("orphan-agent")); err != nil {
		t.Errorf("pid file must be preserved when group is alive: %v", err)
	}
	if _, err := os.Stat(GroupFile("orphan-agent")); err != nil {
		t.Errorf("group file must be preserved when group is alive: %v", err)
	}
}

// TestSweep_AgentPID_RemovesWhenGroupDead preserves the original behavior when
// both parent AND group are dead — the .pid file is cleaned.
func TestSweep_AgentPID_RemovesWhenGroupDead(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{})
	g := NewGroupID()
	_ = WriteAgent("gone", 12345, g)

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.DeadAgentPIDsCleaned == 0 {
		t.Errorf("expected DeadAgentPIDsCleaned > 0, got %+v", r)
	}
	if _, err := os.Stat(PIDFile("gone")); !os.IsNotExist(err) {
		t.Errorf("pid file should be removed when both parent and group dead")
	}
}

// TestSweep_DepsWalk_KeepsEntryWhenGroupAlive guards refcount-sync with the
// agent .pid sweep above: if the .pid is kept (group alive), the deps entry
// must also be kept so registry/UI refcount doesn't underreport.
func TestSweep_DepsWalk_KeepsEntryWhenGroupAlive(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Parent dead, group alive for orphan-agent; nothing in alive map for
	// processAliveFn so the deps walk would (in the OLD behavior) prune it.
	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{66666: true})
	g := NewGroupID()
	_ = WriteAgent("orphan-agent", 66666, g)
	if err := RegisterDep(ServiceRegistry, g, []string{"orphan-agent"}); err != nil {
		t.Fatal(err)
	}

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.StaleDepsEntries != 0 {
		t.Errorf("StaleDepsEntries should be 0 when group is alive; got %+v", r)
	}
	got, _ := AgentsInGroup(ServiceRegistry, g)
	if len(got) != 1 || got[0] != "orphan-agent" {
		t.Errorf("deps after sweep = %v, want [orphan-agent]", got)
	}
}

// TestSweep_WrapperMarker_RemovesWhenSinglePIDDead is a REGRESSION GUARD:
// wrapper markers MUST remain on single-PID processAliveFn semantics. If they
// switched to group-aware, the wrapper's own forked child (which is in the
// same pgid) would keep the marker file alive forever — wrappers exit when
// the agent backgrounds, but the agent stays in the same pgid.
func TestSweep_WrapperMarker_RemovesWhenSinglePIDDead(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const wrapperPID = 77777
	// Wrapper PID is dead. Group probe would say "alive" (forked agent still
	// in group), but Sweep MUST use the single-PID probe here.
	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{wrapperPID: true})

	g := NewGroupID()
	if err := WriteWrapperPID(g, wrapperPID); err != nil {
		t.Fatal(err)
	}

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.StaleWrapperPIDs == 0 {
		t.Errorf("wrapper marker should be cleaned when single-PID is dead even if group has descendants; got %+v", r)
	}
	if _, err := os.Stat(WrapperPIDFile(g)); !os.IsNotExist(err) {
		t.Errorf("wrapper marker should be removed")
	}
}

// TestSweep_WatcherMarker_RemovesWhenSinglePIDDead is the corresponding
// regression guard for watcher markers. Watchers live in the controlling
// meshctl process; their semantics REQUIRE single-PID — switching to group
// would cause the watcher .pid to linger forever.
func TestSweep_WatcherMarker_RemovesWhenSinglePIDDead(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	const watcherPID = 88888
	useStubAlive(t, map[int]bool{})
	useStubGroupAlive(t, map[int]bool{watcherPID: true})

	if err := WriteWatcher("watched-agent", watcherPID); err != nil {
		t.Fatal(err)
	}

	r, err := Sweep()
	if err != nil {
		t.Fatalf("Sweep: %v", err)
	}
	if r.StaleWatcherPIDs == 0 {
		t.Errorf("watcher marker should be cleaned when single-PID is dead even if group reports alive; got %+v", r)
	}
	if _, err := os.Stat(WatcherPIDFile("watched-agent")); !os.IsNotExist(err) {
		t.Errorf("watcher marker should be removed")
	}
}
