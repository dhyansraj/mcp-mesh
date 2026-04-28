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
