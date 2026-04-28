package lifecycle

import (
	"os"
	"strings"
	"testing"
)

func TestWriteAgentOrderAndContent(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	if err := WriteAgent("foo", 4242, g); err != nil {
		t.Fatalf("WriteAgent: %v", err)
	}

	// .pid contains the PID.
	pidData, err := os.ReadFile(PIDFile("foo"))
	if err != nil {
		t.Fatalf("read pid: %v", err)
	}
	if strings.TrimSpace(string(pidData)) != "4242" {
		t.Errorf("pid file = %q, want 4242", string(pidData))
	}

	// .group contains the group-id.
	groupData, err := os.ReadFile(GroupFile("foo"))
	if err != nil {
		t.Fatalf("read group: %v", err)
	}
	if strings.TrimSpace(string(groupData)) != g.String() {
		t.Errorf("group file = %q, want %q", string(groupData), g)
	}

	// No tmp file left behind.
	if _, err := os.Stat(PIDFile("foo") + ".tmp"); !os.IsNotExist(err) {
		t.Errorf("tmp file should be gone, stat err=%v", err)
	}
}

func TestRemoveAgentIdempotent(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	_ = WriteAgent("foo", 1, g)
	if err := RemoveAgent("foo"); err != nil {
		t.Fatalf("RemoveAgent: %v", err)
	}
	// Both gone.
	if _, err := os.Stat(PIDFile("foo")); !os.IsNotExist(err) {
		t.Errorf("pid not removed: %v", err)
	}
	if _, err := os.Stat(GroupFile("foo")); !os.IsNotExist(err) {
		t.Errorf("group not removed: %v", err)
	}
	// Second call must not error.
	if err := RemoveAgent("foo"); err != nil {
		t.Errorf("RemoveAgent idempotent: %v", err)
	}
}

func TestWriteServiceNoGroupFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	if err := WriteService("registry", 9999); err != nil {
		t.Fatalf("WriteService: %v", err)
	}
	if _, err := os.Stat(GroupFile("registry")); !os.IsNotExist(err) {
		t.Errorf("services should not have a .group file, got %v", err)
	}
	if err := RemoveService("registry"); err != nil {
		t.Fatalf("RemoveService: %v", err)
	}
	if _, err := os.Stat(PIDFile("registry")); !os.IsNotExist(err) {
		t.Errorf("registry pid should be gone")
	}
}

func TestCrashBetweenWritesLeavesOnlyGroupFile(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	// Simulate WriteAgent crashing after the .group write but before the .pid
	// rename: write the group file directly and confirm the orphan is harmless.
	g := NewGroupID()
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(GroupFile("orphan"), []byte(g.String()), 0644); err != nil {
		t.Fatal(err)
	}
	// No .pid file yet — Sweep() (in gc_test.go) covers cleanup. Here we just
	// verify that the .group file alone exists in the right place.
	if _, err := os.Stat(GroupFile("orphan")); err != nil {
		t.Errorf("orphan group file: %v", err)
	}
	if _, err := os.Stat(PIDFile("orphan")); !os.IsNotExist(err) {
		t.Errorf("pid should not exist")
	}
}

func TestWrapperPIDLifecycle(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()

	g := NewGroupID()
	if err := WriteWrapperPID(g, 1234); err != nil {
		t.Fatalf("WriteWrapperPID: %v", err)
	}
	data, err := os.ReadFile(WrapperPIDFile(g))
	if err != nil {
		t.Fatalf("read wrapper pid: %v", err)
	}
	if strings.TrimSpace(string(data)) != "1234" {
		t.Errorf("got %q want 1234", string(data))
	}
	if err := RemoveWrapperPID(g); err != nil {
		t.Fatalf("RemoveWrapperPID: %v", err)
	}
	if _, err := os.Stat(WrapperPIDFile(g)); !os.IsNotExist(err) {
		t.Errorf("wrapper pid should be gone")
	}
}
