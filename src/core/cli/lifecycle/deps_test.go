package lifecycle

import (
	"os"
	"sort"
	"sync"
	"testing"
)

func TestRegisterAddsAgents(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	if err := RegisterDep(ServiceRegistry, g, []string{"a1", "a2"}); err != nil {
		t.Fatalf("RegisterDep: %v", err)
	}
	got, err := AgentsInGroup(ServiceRegistry, g)
	if err != nil {
		t.Fatalf("AgentsInGroup: %v", err)
	}
	want := []string{"a1", "a2"}
	if !equalSorted(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func TestRegisterIdempotentDuplicates(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	if err := RegisterDep(ServiceRegistry, g, []string{"a1", "a1", "a2"}); err != nil {
		t.Fatalf("RegisterDep: %v", err)
	}
	if err := RegisterDep(ServiceRegistry, g, []string{"a2", "a3"}); err != nil {
		t.Fatalf("RegisterDep again: %v", err)
	}
	got, _ := AgentsInGroup(ServiceRegistry, g)
	want := []string{"a1", "a2", "a3"}
	if !equalSorted(got, want) {
		t.Errorf("got %v, want %v", got, want)
	}
}

func TestUnregisterRemovesAndDeletesEmpty(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	_ = RegisterDep(ServiceRegistry, g, []string{"a1", "a2"})
	if err := UnregisterDep(ServiceRegistry, g, []string{"a1"}); err != nil {
		t.Fatalf("UnregisterDep: %v", err)
	}
	got, _ := AgentsInGroup(ServiceRegistry, g)
	if !equalSorted(got, []string{"a2"}) {
		t.Errorf("after partial unregister, got %v want [a2]", got)
	}

	// Removing the last agent should delete the file.
	if err := UnregisterDep(ServiceRegistry, g, []string{"a2"}); err != nil {
		t.Fatalf("UnregisterDep last: %v", err)
	}
	if _, err := os.Stat(RegistryDepsFile(g)); !os.IsNotExist(err) {
		t.Errorf("expected deps file removed, stat err=%v", err)
	}
}

func TestUnregisterMissingFileNoError(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()
	g := NewGroupID()
	if err := UnregisterDep(ServiceRegistry, g, []string{"x"}); err != nil {
		t.Errorf("UnregisterDep on missing file should be no-op, got %v", err)
	}
}

func TestDepsForServiceListsNonEmpty(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g1 := NewGroupID()
	g2 := NewGroupID()
	_ = RegisterDep(ServiceRegistry, g1, []string{"a"})
	_ = RegisterDep(ServiceRegistry, g2, []string{"b"})

	groups, err := DepsForService(ServiceRegistry)
	if err != nil {
		t.Fatalf("DepsForService: %v", err)
	}
	if len(groups) != 2 {
		t.Errorf("expected 2 groups, got %d: %v", len(groups), groups)
	}

	// Empty deps file (manually created) should NOT be reported.
	emptyG := NewGroupID()
	if err := os.WriteFile(RegistryDepsFile(emptyG), nil, 0644); err != nil {
		t.Fatal(err)
	}
	groups2, _ := DepsForService(ServiceRegistry)
	if len(groups2) != 2 {
		t.Errorf("empty deps file should not be reported, got groups=%v", groups2)
	}
}

func TestIsServiceRefcountZero(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	zero, err := IsServiceRefcountZero(ServiceRegistry)
	if err != nil {
		t.Fatalf("IsServiceRefcountZero: %v", err)
	}
	if !zero {
		t.Error("expected refcount=0 with no deps files")
	}

	g := NewGroupID()
	_ = RegisterDep(ServiceRegistry, g, []string{"agent1"})
	zero, _ = IsServiceRefcountZero(ServiceRegistry)
	if zero {
		t.Error("expected refcount>0 after register")
	}

	_ = UnregisterDep(ServiceRegistry, g, []string{"agent1"})
	zero, _ = IsServiceRefcountZero(ServiceRegistry)
	if !zero {
		t.Error("expected refcount=0 after unregister")
	}
}

// TestConcurrentRegisterFlock pounds on RegisterDep from many goroutines and
// verifies the merged set has no lost updates. Without flock+atomic write
// this would intermittently lose entries.
func TestConcurrentRegisterFlock(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	const N = 50
	var wg sync.WaitGroup
	wg.Add(N)
	for i := 0; i < N; i++ {
		go func(i int) {
			defer wg.Done()
			name := []string{"agentA", "agentB"}
			_ = RegisterDep(ServiceRegistry, g, name)
			_ = RegisterDep(ServiceRegistry, g, []string{"agentC"})
		}(i)
	}
	wg.Wait()
	got, _ := AgentsInGroup(ServiceRegistry, g)
	want := []string{"agentA", "agentB", "agentC"}
	if !equalSorted(got, want) {
		t.Errorf("after concurrent register, got %v want %v", got, want)
	}
}

func TestUnknownServicePanics(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()
	g := NewGroupID()

	// depsDirFor panics on unknown service — programmer error since callers
	// pass package constants. Both routes (RegisterDep, DepsForService) flow
	// through it; verify they panic rather than silently returning.
	assertPanics(t, "RegisterDep(bogus)", func() {
		_ = RegisterDep("bogus", g, []string{"x"})
	})
	assertPanics(t, "DepsForService(bogus)", func() {
		_, _ = DepsForService("bogus")
	})
}

func assertPanics(t *testing.T, label string, fn func()) {
	t.Helper()
	defer func() {
		if r := recover(); r == nil {
			t.Errorf("%s: expected panic, got none", label)
		}
	}()
	fn()
}

func equalSorted(a, b []string) bool {
	aa := append([]string{}, a...)
	bb := append([]string{}, b...)
	sort.Strings(aa)
	sort.Strings(bb)
	if len(aa) != len(bb) {
		return false
	}
	for i := range aa {
		if aa[i] != bb[i] {
			return false
		}
	}
	return true
}
