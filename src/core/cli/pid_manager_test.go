package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
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
	// FindWatchAgentsByParent(0) must return no matches. The method's semantic
	// is "agents under a watch-mode parent"; parent 0 is not a valid watch-mode
	// parent, even though flat entries internally carry ParentPID == 0. The
	// guard at the top of the method short-circuits parentPID <= 0 to prevent
	// flat entries from being mistakenly surfaced as watch-mode agents.
	writePIDFile(t, pm, "flat.pid", os.Getpid())

	matches, err := pm.FindWatchAgentsByParent(0)
	if err != nil {
		t.Fatalf("FindWatchAgentsByParent(0): %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches for parent 0, got %d: %+v", len(matches), matches)
	}

	// Also verify the guard handles negative PIDs.
	matches, err = pm.FindWatchAgentsByParent(-1)
	if err != nil {
		t.Fatalf("FindWatchAgentsByParent(-1): %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches for parent -1, got %d: %+v", len(matches), matches)
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

// --- Dead PID helper (F1) ---

// reapedPID returns a PID that was just reaped and is (with very high probability)
// no longer alive. Used to test the `p.Running` filter in enumeration helpers.
// PID reuse in the microseconds after Wait returns is extraordinarily unlikely,
// but we still poll IsProcessAlive briefly to confirm the kernel has actually
// reflected the exit before the caller uses the value.
func reapedPID(t *testing.T) int {
	t.Helper()
	cmd := exec.Command("sh", "-c", "exit 0")
	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start throwaway process: %v", err)
	}
	pid := cmd.Process.Pid
	_ = cmd.Wait() // reap
	deadline := time.Now().Add(200 * time.Millisecond)
	for time.Now().Before(deadline) {
		if !IsProcessAlive(pid) {
			return pid
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("reaped PID %d still reports as alive after 200ms", pid)
	return 0
}

// --- Dead-PID filter tests (F1) ---

func TestFindWatchAgentsByNameFiltersDeadAgent(t *testing.T) {
	pm := newTestPIDManager(t)
	dead := reapedPID(t)
	// Write a watch-mode entry referring to the dead PID under parent 111.
	writePIDFile(t, pm, "ghost.111.pid", dead)

	matches, err := pm.FindWatchAgentsByName("ghost")
	if err != nil {
		t.Fatalf("FindWatchAgentsByName: %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches (agent dead), got %d: %+v", len(matches), matches)
	}
}

func TestFindWatchAgentsByParentFiltersDeadAgent(t *testing.T) {
	pm := newTestPIDManager(t)
	dead := reapedPID(t)
	writePIDFile(t, pm, "ghost.222.pid", dead)
	// Mix in a live agent under the same parent so we can verify the filter is
	// selective (alive pass through, dead filtered out).
	writePIDFile(t, pm, "alive.222.pid", os.Getpid())

	matches, err := pm.FindWatchAgentsByParent(222)
	if err != nil {
		t.Fatalf("FindWatchAgentsByParent: %v", err)
	}
	if len(matches) != 1 {
		t.Fatalf("expected 1 match (only the live agent), got %d: %+v", len(matches), matches)
	}
	if matches[0].Name != "alive" {
		t.Errorf("expected alive agent, got %+v", matches[0])
	}
}

// --- FindWatchParentsByPID tests (F3) ---

func TestFindWatchParentsByPID(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	// Two watcher-parent entries under parent 111, one under 222.
	writePIDFile(t, pm, "alpha.111.watcher-parent.pid", 111)
	writePIDFile(t, pm, "beta.111.watcher-parent.pid", 111)
	writePIDFile(t, pm, "gamma.222.watcher-parent.pid", 222)
	// Plus some watch-mode agent entries under the same parents (must NOT be returned).
	writePIDFile(t, pm, "alpha.111.pid", pid)
	writePIDFile(t, pm, "gamma.222.pid", pid)

	matches, err := pm.FindWatchParentsByPID(111)
	if err != nil {
		t.Fatalf("FindWatchParentsByPID(111): %v", err)
	}
	if len(matches) != 2 {
		t.Fatalf("expected 2 watcher-parent entries under 111, got %d: %+v", len(matches), matches)
	}
	names := []string{}
	for _, m := range matches {
		if m.Type != "watcher-parent" {
			t.Errorf("non-watcher-parent returned: %+v", m)
		}
		if m.ParentPID != 111 {
			t.Errorf("wrong ParentPID: %+v", m)
		}
		names = append(names, m.Name)
	}
	sort.Strings(names)
	if names[0] != "alpha" || names[1] != "beta" {
		t.Errorf("expected [alpha beta], got %v", names)
	}
}

func TestFindWatchParentsByPIDNoMatch(t *testing.T) {
	pm := newTestPIDManager(t)
	writePIDFile(t, pm, "alpha.111.watcher-parent.pid", 111)

	matches, err := pm.FindWatchParentsByPID(999)
	if err != nil {
		t.Fatalf("FindWatchParentsByPID: %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches, got %d: %+v", len(matches), matches)
	}
}

func TestFindWatchParentsByPIDZero(t *testing.T) {
	pm := newTestPIDManager(t)
	// Even if we had a watcher-parent entry with ParentPID 0 (which is not a
	// legitimate shape), the guard should short-circuit and return nothing.
	writePIDFile(t, pm, "alpha.111.watcher-parent.pid", 111)

	matches, err := pm.FindWatchParentsByPID(0)
	if err != nil {
		t.Fatalf("FindWatchParentsByPID(0): %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches for parent 0, got %d: %+v", len(matches), matches)
	}
	matches, err = pm.FindWatchParentsByPID(-1)
	if err != nil {
		t.Fatalf("FindWatchParentsByPID(-1): %v", err)
	}
	if len(matches) != 0 {
		t.Errorf("expected 0 matches for parent -1, got %d", len(matches))
	}
}

// TestFindWatchParentsByPIDReturnsDeadParent pins the intentional non-filtering
// behavior: unlike FindWatchAgentsByParent (which excludes dead PIDs),
// FindWatchParentsByPID returns tracking file metadata regardless of whether the
// parent is alive, because it is used to clean up stale files after a parent has
// already exited.
func TestFindWatchParentsByPIDReturnsDeadParent(t *testing.T) {
	pm := newTestPIDManager(t)
	dead := reapedPID(t)
	// Use the dead PID both as the parent PID in the filename AND as the file
	// contents so ListRunningProcesses reads the same dead PID.
	filename := fmt.Sprintf("alpha.%d.watcher-parent.pid", dead)
	writePIDFile(t, pm, filename, dead)

	matches, err := pm.FindWatchParentsByPID(dead)
	if err != nil {
		t.Fatalf("FindWatchParentsByPID: %v", err)
	}
	if len(matches) != 1 {
		t.Fatalf("expected 1 match (dead parent still returned for cleanup), got %d: %+v",
			len(matches), matches)
	}
	if matches[0].Running {
		// Expected: p.Running reports false for a dead PID, but the helper
		// still surfaces the entry.
	}
	if matches[0].Name != "alpha" || matches[0].ParentPID != dead {
		t.Errorf("unexpected entry: %+v", matches[0])
	}
}

// --- Parser malformed-filename edge cases (F2) ---

// TestListRunningProcessesMalformedFilenames documents and pins the parser's
// behavior for edge-case filenames. The goal is to prevent accidental resurfacing
// of malformed entries as "flat agents with dotted names", which would be
// un-recreatable by any code path (sanitizeName strips dots).
func TestListRunningProcessesMalformedFilenames(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	// Case A: empty base — ".pid" — skipped.
	if err := os.WriteFile(filepath.Join(pm.pidsDir, ".pid"), []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		t.Fatalf("write .pid: %v", err)
	}
	// Case B: double dot — "foo..pid" — base "foo.", trailing segment empty,
	// Atoi fails, dotted-unparseable → skipped (not flat fallback).
	writePIDFile(t, pm, "foo..pid", pid)
	// Case C: non-numeric trailing segment — "foo.bar.pid" — base "foo.bar",
	// trailing "bar" not a number, dotted-unparseable → skipped.
	writePIDFile(t, pm, "foo.bar.pid", pid)
	// Case D: zero parent — "foo.0.pid" — base "foo.0", parsed parent 0 which
	// is not a valid watch-mode parent → skipped (not flat fallback).
	writePIDFile(t, pm, "foo.0.pid", pid)
	// Case E: negative parent — "foo.-1.pid" — Atoi returns -1, <= 0 → skipped.
	writePIDFile(t, pm, "foo.-1.pid", pid)
	// Case F: purely numeric name — "123.pid" — no dot → flat agent "123".
	writePIDFile(t, pm, "123.pid", pid)
	// Case G: valid watch-mode alongside the malformed ones, as a sanity check
	// that the parser still processes the good files.
	writePIDFile(t, pm, "ok-agent.999.pid", pid)

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}

	// Expected survivors: "123.pid" (flat, name "123") and "ok-agent.999.pid"
	// (watch-mode, parent 999). All dotted-but-unparseable files are skipped.
	if len(processes) != 2 {
		t.Fatalf("expected 2 entries, got %d: %+v", len(processes), processes)
	}

	if p := findByFile(processes, "123.pid"); p == nil || p.Name != "123" || p.Type != "agent" || p.ParentPID != 0 {
		t.Errorf("123.pid entry wrong or missing: %+v", p)
	}
	if p := findByFile(processes, "ok-agent.999.pid"); p == nil || p.Name != "ok-agent" || p.Type != "agent" || p.ParentPID != 999 {
		t.Errorf("ok-agent.999.pid entry wrong or missing: %+v", p)
	}

	// Explicitly assert the skipped files are NOT present.
	for _, skipped := range []string{".pid", "foo..pid", "foo.bar.pid", "foo.0.pid", "foo.-1.pid"} {
		if p := findByFile(processes, skipped); p != nil {
			t.Errorf("expected %s to be skipped, got entry: %+v", skipped, p)
		}
	}
}

// TestListRunningProcessesMalformedWatcherParent pins parser behavior for
// watcher-parent files whose parent PID segment is malformed.
func TestListRunningProcessesMalformedWatcherParent(t *testing.T) {
	pm := newTestPIDManager(t)
	pid := os.Getpid()

	// "foo.watcher-parent.pid" — missing parent PID segment → rest = "foo",
	// LastIndex returns -1 → skipped.
	writePIDFile(t, pm, "foo.watcher-parent.pid", pid)
	// "foo.0.watcher-parent.pid" — parent PID is 0 → skipped.
	writePIDFile(t, pm, "foo.0.watcher-parent.pid", pid)
	// "foo.bar.watcher-parent.pid" — non-numeric parent PID → skipped.
	writePIDFile(t, pm, "foo.bar.watcher-parent.pid", pid)
	// Sanity check: one valid watcher-parent file.
	writePIDFile(t, pm, "good.42.watcher-parent.pid", 42)

	processes, err := pm.ListRunningProcesses()
	if err != nil {
		t.Fatalf("ListRunningProcesses: %v", err)
	}

	if len(processes) != 1 {
		t.Fatalf("expected 1 valid entry, got %d: %+v", len(processes), processes)
	}
	if p := findByFile(processes, "good.42.watcher-parent.pid"); p == nil || p.Type != "watcher-parent" || p.ParentPID != 42 {
		t.Errorf("good watcher-parent entry wrong or missing: %+v", p)
	}
}
