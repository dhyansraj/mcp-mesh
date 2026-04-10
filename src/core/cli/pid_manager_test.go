package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// newTestPIDManager returns a PIDManager rooted at a fresh per-test temp directory.
func newTestPIDManager(t *testing.T) *PIDManager {
	t.Helper()
	pm, err := newPIDManagerWithDir(t.TempDir())
	if err != nil {
		t.Fatalf("newPIDManagerWithDir: %v", err)
	}
	return pm
}

// writePIDFile is a small helper that writes a file containing a PID string into
// a PIDManager's pids directory with the given filename.
func writePIDFile(t *testing.T, pm *PIDManager, filename string, pid int) {
	t.Helper()
	path := filepath.Join(pm.pidsDir, filename)
	if err := os.WriteFile(path, []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

// findByFile returns the PIDInfo whose PIDFile basename matches filename, or nil.
func findByFile(processes []PIDInfo, filename string) *PIDInfo {
	for i := range processes {
		if filepath.Base(processes[i].PIDFile) == filename {
			return &processes[i]
		}
	}
	return nil
}

// --- sanitizeName ---

func TestSanitizeName(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{"foo.py", "foo"},
		{"market-data-massive", "market-data-massive"},
		// filepath.Base strips directories, then .py is trimmed.
		{"agent/with/slashes.py", "slashes"},
		// filepath.Base("") returns ".", which becomes "_" after the rune map.
		// The name != "" fallback to "unknown" only fires for a truly empty string.
		{"", "_"},
		// Dots inside the base become underscores (after trimming .py).
		{"weird.name.py", "weird_name"},
		// Spaces and other specials are replaced with _.
		{"has spaces", "has_spaces"},
		{"a@b#c", "a_b_c"},
	}
	for _, tc := range cases {
		got := sanitizeName(tc.in)
		if got != tc.want {
			t.Errorf("sanitizeName(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

// TestSanitizeNameNoDotInvariant asserts the invariant the per-parent-PID
// filename scheme relies on: a sanitized name must never contain '.',
// otherwise the "<name>.<parent_pid>.pid" parser could be confused.
func TestSanitizeNameNoDotInvariant(t *testing.T) {
	inputs := []string{
		"foo.py",
		"weird.name.py",
		"a.b.c.d",
		"market-data-massive",
		"/abs/path/to/agent.py",
		"agent-v1.2.3.py",
		"",
		"unknown",
		"my_agent",
		"numbers123",
	}
	for _, in := range inputs {
		out := sanitizeName(in)
		if strings.Contains(out, ".") {
			t.Errorf("sanitizeName(%q) = %q contains '.' — violates filename invariant", in, out)
		}
	}
}

// --- ListRunningProcesses parser ---

func TestListRunningProcessesEmptyDirectory(t *testing.T) {
	pm := newTestPIDManager(t)
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 0 {
		t.Errorf("expected empty slice, got %d entries: %+v", len(processes), processes)
	}
}

func TestListRunningProcessesMissingDirectory(t *testing.T) {
	// Construct a PIDManager pointing at a dir that doesn't exist, bypassing
	// newPIDManagerWithDir (which mkdirs). We remove the dir after construction.
	pm := newTestPIDManager(t)
	if err := os.RemoveAll(pm.pidsDir); err != nil {
		t.Fatalf("rm tempdir: %v", err)
	}
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 0 {
		t.Errorf("expected empty slice for missing dir, got %d entries", len(processes))
	}
}

func TestListRunningProcessesRegistry(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "registry.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(processes))
	}
	p := processes[0]
	if p.Name != "registry" || p.Type != "registry" || p.ParentPID != 0 {
		t.Errorf("registry entry wrong: %+v", p)
	}
	if p.PID != os.Getpid() {
		t.Errorf("registry PID = %d, want %d", p.PID, os.Getpid())
	}
}

func TestListRunningProcessesUI(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "ui.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(processes))
	}
	p := processes[0]
	if p.Name != "ui" || p.Type != "ui" || p.ParentPID != 0 {
		t.Errorf("ui entry wrong: %+v", p)
	}
}

func TestListRunningProcessesFlatAgent(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "foo.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(processes))
	}
	p := processes[0]
	if p.Name != "foo" || p.Type != "agent" || p.ParentPID != 0 {
		t.Errorf("flat agent entry wrong: %+v", p)
	}
}

func TestListRunningProcessesWatchModeAgent(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "market-data-massive.12345.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(processes))
	}
	p := processes[0]
	if p.Name != "market-data-massive" || p.Type != "agent" || p.ParentPID != 12345 {
		t.Errorf("watch-mode agent wrong: %+v", p)
	}
}

func TestListRunningProcessesWatcherParent(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "market-data-massive.12345.watcher-parent.pid", 12345)

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(processes))
	}
	p := processes[0]
	if p.Name != "market-data-massive" || p.Type != "watcher-parent" || p.ParentPID != 12345 {
		t.Errorf("watcher-parent wrong: %+v", p)
	}
}

func TestListRunningProcessesAgentNameEdgeCases(t *testing.T) {
	pm := newTestPIDManager(t)
	// Digits in the name — parser must not greedy-consume them as parent_pid.
	writePIDFile(t, pm, "agent123.99999.pid", os.Getpid())
	// Underscore in the name.
	writePIDFile(t, pm, "my_agent.77777.pid", os.Getpid())
	// Dashes in the name.
	writePIDFile(t, pm, "market-data-v2.55555.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}

	cases := []struct {
		file     string
		wantName string
		wantPPID int
		wantType string
	}{
		{"agent123.99999.pid", "agent123", 99999, "agent"},
		{"my_agent.77777.pid", "my_agent", 77777, "agent"},
		{"market-data-v2.55555.pid", "market-data-v2", 55555, "agent"},
	}
	for _, tc := range cases {
		p := findByFile(processes, tc.file)
		if p == nil {
			t.Errorf("%s: not parsed", tc.file)
			continue
		}
		if p.Name != tc.wantName || p.ParentPID != tc.wantPPID || p.Type != tc.wantType {
			t.Errorf("%s: got name=%q ppid=%d type=%q, want name=%q ppid=%d type=%q",
				tc.file, p.Name, p.ParentPID, p.Type, tc.wantName, tc.wantPPID, tc.wantType)
		}
	}
}

func TestListRunningProcessesLegacyWatcherParentIgnored(t *testing.T) {
	pm := newTestPIDManager(t)
	// Legacy format (underscore separator) written by pre-namespacing meshctl versions.
	writePIDFile(t, pm, "market-data-massive_watcher-parent.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 0 {
		t.Errorf("legacy watcher-parent file should be silently ignored, got: %+v", processes)
	}
}

func TestListRunningProcessesNonPIDFilesIgnored(t *testing.T) {
	pm := newTestPIDManager(t)
	// Non-.pid files should be ignored.
	for _, f := range []string{".DS_Store", "README.md", "random.txt", "stale.log"} {
		if err := os.WriteFile(filepath.Join(pm.pidsDir, f), []byte("garbage"), 0644); err != nil {
			t.Fatalf("write %s: %v", f, err)
		}
	}
	// A subdirectory should be ignored.
	if err := os.MkdirAll(filepath.Join(pm.pidsDir, "subdir"), 0755); err != nil {
		t.Fatalf("mkdir subdir: %v", err)
	}
	// One valid file to make sure the scan actually runs.
	writePIDFile(t, pm, "foo.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry, got %d: %+v", len(processes), processes)
	}
	if processes[0].Name != "foo" {
		t.Errorf("unexpected entry: %+v", processes[0])
	}
}

func TestListRunningProcessesInvalidPIDContent(t *testing.T) {
	pm := newTestPIDManager(t)
	// Non-numeric content.
	if err := os.WriteFile(filepath.Join(pm.pidsDir, "bad.pid"), []byte("not-a-number"), 0644); err != nil {
		t.Fatalf("write bad.pid: %v", err)
	}
	// One valid file alongside.
	writePIDFile(t, pm, "good.pid", os.Getpid())

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses returned error: %v", err)
	}
	if len(processes) != 1 {
		t.Fatalf("expected 1 entry (bad file skipped), got %d: %+v", len(processes), processes)
	}
	if processes[0].Name != "good" {
		t.Errorf("unexpected entry: %+v", processes[0])
	}
}

func TestListRunningProcessesMixedDirectory(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	// Registry + UI + flat agent + two watch-mode agents under different parents + two watcher-parent entries
	writePIDFile(t, pm, "registry.pid", pid)
	writePIDFile(t, pm, "ui.pid", pid)
	writePIDFile(t, pm, "flat-agent.pid", pid)
	writePIDFile(t, pm, "market-data.111.pid", pid)
	writePIDFile(t, pm, "market-data.222.pid", pid)
	writePIDFile(t, pm, "market-data.111.watcher-parent.pid", 111)
	writePIDFile(t, pm, "market-data.222.watcher-parent.pid", 222)
	// Junk entries
	writePIDFile(t, pm, "legacy_watcher-parent.pid", pid) // legacy, should be skipped
	if err := os.WriteFile(filepath.Join(pm.pidsDir, "README.md"), []byte("x"), 0644); err != nil {
		t.Fatalf("write README: %v", err)
	}

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}
	// Expect: registry, ui, flat-agent, market-data.111, market-data.222,
	//         market-data.111.watcher-parent, market-data.222.watcher-parent = 7 entries.
	if len(processes) != 7 {
		t.Fatalf("expected 7 entries, got %d: %+v", len(processes), processes)
	}

	// Spot-check a couple of specific entries.
	if p := findByFile(processes, "registry.pid"); p == nil || p.Type != "registry" {
		t.Errorf("registry entry missing or wrong: %+v", p)
	}
	if p := findByFile(processes, "market-data.111.pid"); p == nil || p.Type != "agent" || p.ParentPID != 111 {
		t.Errorf("market-data.111 entry wrong: %+v", p)
	}
	if p := findByFile(processes, "market-data.222.watcher-parent.pid"); p == nil || p.Type != "watcher-parent" || p.ParentPID != 222 {
		t.Errorf("market-data.222 watcher-parent entry wrong: %+v", p)
	}
}

// --- FindWatchAgentsByName / FindWatchAgentsByParent ---

func TestFindWatchAgentsByName(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	// Same agent name under two different parent PIDs.
	writePIDFile(t, pm, "market-data.111.pid", pid)
	writePIDFile(t, pm, "market-data.222.pid", pid)
	// A flat entry for the same name — FindWatchAgentsByName should NOT return it.
	writePIDFile(t, pm, "market-data.pid", pid)
	// A different-named watch-mode entry — should not appear.
	writePIDFile(t, pm, "other.333.pid", pid)

	matches, err := pm.FindWatchAgentsByName("market-data")
	if err != nil {
		t.Fatalf("FindWatchAgentsByName: %v", err)
	}
	if len(matches) != 2 {
		t.Fatalf("expected 2 watch-mode matches for 'market-data', got %d: %+v", len(matches), matches)
	}

	// Extract parent PIDs as a set and verify.
	gotParents := []int{}
	for _, m := range matches {
		if m.Type != "agent" {
			t.Errorf("match has wrong type: %+v", m)
		}
		if m.Name != "market-data" {
			t.Errorf("match has wrong name: %+v", m)
		}
		gotParents = append(gotParents, m.ParentPID)
	}
	sort.Ints(gotParents)
	if gotParents[0] != 111 || gotParents[1] != 222 {
		t.Errorf("expected parents [111 222], got %v", gotParents)
	}
}

func TestFindWatchAgentsByNameNoMatch(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "other.111.pid", os.Getpid())

	matches, err := pm.FindWatchAgentsByName("nonexistent")
	if err != nil {
		t.Fatalf("FindWatchAgentsByName: %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches, got %d", len(matches))
	}
}

func TestFindWatchAgentsByNameFlatOnly(t *testing.T) {
	pm := newTestPIDManager(t)
	// Only a flat entry exists for this name.
	writePIDFile(t, pm, "flat-agent.pid", os.Getpid())

	matches, err := pm.FindWatchAgentsByName("flat-agent")
	if err != nil {
		t.Fatalf("FindWatchAgentsByName: %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("flat entries must not be returned by FindWatchAgentsByName, got %d: %+v",
			len(matches), matches)
	}
}

func TestFindWatchAgentsByParent(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	writePIDFile(t, pm, "agent-a.111.pid", pid)
	writePIDFile(t, pm, "agent-b.111.pid", pid)
	writePIDFile(t, pm, "agent-c.222.pid", pid)
	writePIDFile(t, pm, "flat.pid", pid) // ParentPID=0, must not match parent 111

	matches, err := pm.FindWatchAgentsByParent(111)
	if err != nil {
		t.Fatalf("FindWatchAgentsByParent: %v", err)
	}
	if len(matches) != 2 {
		t.Fatalf("expected 2 matches under parent 111, got %d: %+v", len(matches), matches)
	}
	names := []string{}
	for _, m := range matches {
		names = append(names, m.Name)
	}
	sort.Strings(names)
	if names[0] != "agent-a" || names[1] != "agent-b" {
		t.Errorf("expected [agent-a agent-b], got %v", names)
	}
}

func TestFindWatchAgentsByParentZero(t *testing.T) {
	pm := newTestPIDManager(t)
	// Flat entries have ParentPID=0; FindWatchAgentsByParent(0) should return
	// nothing (the method only finds watch-mode entries, which have parent>0 in
	// practice, and a flat entry's ParentPID==0 matches the filter but then the
	// "watch-mode agent" semantics aren't meaningful — current behavior returns
	// them because the implementation filters on parent PID equality).
	writePIDFile(t, pm, "flat.pid", os.Getpid())

	matches, err := pm.FindWatchAgentsByParent(0)
	if err != nil {
		t.Fatalf("FindWatchAgentsByParent: %v", err)
	}
	// Current behavior: the filter p.ParentPID == parentPID matches flat entries
	// when parentPID == 0. Assert what the code actually does so future changes
	// are flagged.
	if len(matches) != 1 {
		t.Errorf("expected 1 match (flat entry, ParentPID=0), got %d: %+v", len(matches), matches)
	}
}

// --- Write / Read / Remove round-trips ---

func TestWriteReadRemoveFlat(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	if err := pm.WritePID("foo", pid); err != nil {
		t.Fatalf("WritePID: %v", err)
	}
	got, err := pm.ReadPID("foo")
	if err != nil {
		t.Fatalf("ReadPID: %v", err)
	}
	if got != pid {
		t.Errorf("ReadPID = %d, want %d", got, pid)
	}
	expectedPath := filepath.Join(pm.pidsDir, "foo.pid")
	if _, err := os.Stat(expectedPath); err != nil {
		t.Errorf("expected file %s to exist: %v", expectedPath, err)
	}

	if err := pm.RemovePID("foo"); err != nil {
		t.Fatalf("RemovePID: %v", err)
	}
	if _, err := os.Stat(expectedPath); !os.IsNotExist(err) {
		t.Errorf("expected file %s to be gone, got err=%v", expectedPath, err)
	}
}

func TestWriteReadRemoveWatchAgent(t *testing.T) {
	pm := newTestPIDManager(t)
	const parent = 1234
	const agent = 5678

	if err := pm.WriteWatchAgentPID("foo", parent, agent); err != nil {
		t.Fatalf("WriteWatchAgentPID: %v", err)
	}
	expectedPath := filepath.Join(pm.pidsDir, "foo.1234.pid")
	if pm.GetWatchAgentPIDFile("foo", parent) != expectedPath {
		t.Errorf("GetWatchAgentPIDFile = %q, want %q",
			pm.GetWatchAgentPIDFile("foo", parent), expectedPath)
	}

	data, err := os.ReadFile(expectedPath)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if strings.TrimSpace(string(data)) != "5678" {
		t.Errorf("file content = %q, want %q", string(data), "5678")
	}

	if err := pm.RemoveWatchAgentPID("foo", parent); err != nil {
		t.Fatalf("RemoveWatchAgentPID: %v", err)
	}
	if _, err := os.Stat(expectedPath); !os.IsNotExist(err) {
		t.Errorf("expected file %s to be gone, got err=%v", expectedPath, err)
	}
}

func TestWriteReadRemoveWatchParent(t *testing.T) {
	pm := newTestPIDManager(t)
	const parent = 1234

	if err := pm.WriteWatchParentPID("foo", parent); err != nil {
		t.Fatalf("WriteWatchParentPID: %v", err)
	}
	expectedPath := filepath.Join(pm.pidsDir, "foo.1234.watcher-parent.pid")
	if pm.GetWatchParentPIDFile("foo", parent) != expectedPath {
		t.Errorf("GetWatchParentPIDFile = %q, want %q",
			pm.GetWatchParentPIDFile("foo", parent), expectedPath)
	}

	data, err := os.ReadFile(expectedPath)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if strings.TrimSpace(string(data)) != "1234" {
		t.Errorf("file content = %q, want %q", string(data), "1234")
	}

	if err := pm.RemoveWatchParentPID("foo", parent); err != nil {
		t.Fatalf("RemoveWatchParentPID: %v", err)
	}
	if _, err := os.Stat(expectedPath); !os.IsNotExist(err) {
		t.Errorf("expected file %s to be gone, got err=%v", expectedPath, err)
	}
}
