package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

// readRawProcessesFile reads and parses processes.json directly, WITHOUT the
// liveness filtering GetRunningProcesses applies — the test PIDs are fake.
func readRawProcessesFile(t *testing.T) []ProcessInfo {
	t.Helper()
	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatalf("home dir: %v", err)
	}
	data, err := os.ReadFile(filepath.Join(home, ".mcp-mesh", "processes.json"))
	if err != nil {
		t.Fatalf("read processes.json: %v", err)
	}
	var procs []ProcessInfo
	if err := json.Unmarshal(data, &procs); err != nil {
		t.Fatalf("processes.json is not valid JSON (torn write?): %v", err)
	}
	return procs
}

// TestConcurrentProcessFileUpdates verifies MED-4: concurrent Add/Remove
// read-modify-write cycles on processes.json must not lose updates (each
// cycle is serialized by the flock) and must never produce a torn write
// (atomic temp+rename).
func TestConcurrentProcessFileUpdates(t *testing.T) {
	t.Setenv("HOME", t.TempDir())

	const n = 40
	basePID := 1_000_000 // fake PIDs; never touched by liveness checks here

	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			proc := ProcessInfo{
				PID:  basePID + i,
				Name: fmt.Sprintf("agent-%d", i),
				Type: "agent",
			}
			if err := AddRunningProcess(proc); err != nil {
				t.Errorf("AddRunningProcess(%d): %v", i, err)
			}
		}(i)
	}
	wg.Wait()

	procs := readRawProcessesFile(t)
	if len(procs) != n {
		t.Fatalf("after %d concurrent adds, file has %d entries — updates were lost", n, len(procs))
	}
	seen := make(map[int]bool, len(procs))
	for _, p := range procs {
		seen[p.PID] = true
	}
	for i := 0; i < n; i++ {
		if !seen[basePID+i] {
			t.Errorf("entry for PID %d missing after concurrent adds", basePID+i)
		}
	}

	// Concurrent removes of the first half (parallel-shutdown-kill pattern).
	for i := 0; i < n/2; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			if err := RemoveRunningProcess(basePID + i); err != nil {
				t.Errorf("RemoveRunningProcess(%d): %v", i, err)
			}
		}(i)
	}
	wg.Wait()

	procs = readRawProcessesFile(t)
	if len(procs) != n/2 {
		t.Fatalf("after %d concurrent removes, file has %d entries, want %d", n/2, len(procs), n/2)
	}
	for _, p := range procs {
		if p.PID < basePID+n/2 {
			t.Errorf("PID %d should have been removed", p.PID)
		}
	}
}

// TestGetRunningProcessesWarnsOnCorruptFile verifies that a torn/corrupt
// processes.json falls back to an empty list WITH a warning on stderr instead
// of silently pretending nothing was ever tracked.
func TestGetRunningProcessesWarnsOnCorruptFile(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	mcpDir := filepath.Join(home, ".mcp-mesh")
	if err := os.MkdirAll(mcpDir, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(mcpDir, "processes.json"), []byte("{\"truncated\": [1, 2"), 0644); err != nil {
		t.Fatal(err)
	}

	// Capture stderr around the call.
	oldStderr := os.Stderr
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stderr = w

	procs, gerr := GetRunningProcesses()

	w.Close()
	os.Stderr = oldStderr
	captured, _ := io.ReadAll(r)
	r.Close()

	if gerr != nil {
		t.Fatalf("GetRunningProcesses on corrupt file: %v", gerr)
	}
	if len(procs) != 0 {
		t.Errorf("expected empty list for corrupt file, got %d entries", len(procs))
	}
	if !strings.Contains(string(captured), "not valid JSON") {
		t.Errorf("expected parse-failure warning on stderr, got: %q", string(captured))
	}
}

// TestCorruptProcessFileSelfHealsOnce verifies that a corrupt processes.json
// is quarantined to processes.json.corrupt (overwriting any previous
// quarantine) and reset to an empty list on the first read, so the warning
// fires exactly once and subsequent reads are silent.
func TestCorruptProcessFileSelfHealsOnce(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)

	mcpDir := filepath.Join(home, ".mcp-mesh")
	if err := os.MkdirAll(mcpDir, 0755); err != nil {
		t.Fatal(err)
	}
	processFile := filepath.Join(mcpDir, "processes.json")
	corruptFile := processFile + ".corrupt"

	corruptContent := []byte("{\"truncated\": [1, 2")
	if err := os.WriteFile(processFile, corruptContent, 0644); err != nil {
		t.Fatal(err)
	}
	// A stale quarantine from a previous incident must be overwritten.
	if err := os.WriteFile(corruptFile, []byte("old quarantine"), 0644); err != nil {
		t.Fatal(err)
	}

	captureStderr := func(fn func()) string {
		t.Helper()
		oldStderr := os.Stderr
		r, w, err := os.Pipe()
		if err != nil {
			t.Fatal(err)
		}
		os.Stderr = w
		fn()
		w.Close()
		os.Stderr = oldStderr
		captured, _ := io.ReadAll(r)
		r.Close()
		return string(captured)
	}

	// First read: warns, quarantines, heals.
	first := captureStderr(func() {
		procs, err := GetRunningProcesses()
		if err != nil {
			t.Errorf("first GetRunningProcesses: %v", err)
		}
		if len(procs) != 0 {
			t.Errorf("expected empty list for corrupt file, got %d entries", len(procs))
		}
	})
	if !strings.Contains(first, "not valid JSON") {
		t.Errorf("expected parse-failure warning on first read, got: %q", first)
	}

	quarantined, err := os.ReadFile(corruptFile)
	if err != nil {
		t.Fatalf("read quarantine file: %v", err)
	}
	if string(quarantined) != string(corruptContent) {
		t.Errorf("quarantine file content = %q, want original corrupt content %q", quarantined, corruptContent)
	}

	healed, err := os.ReadFile(processFile)
	if err != nil {
		t.Fatalf("read healed processes.json: %v", err)
	}
	var procs []ProcessInfo
	if err := json.Unmarshal(healed, &procs); err != nil {
		t.Errorf("healed processes.json is not valid JSON: %v (content: %q)", err, healed)
	}
	if len(procs) != 0 {
		t.Errorf("healed processes.json should be an empty list, got %d entries", len(procs))
	}

	// Second read: silent.
	second := captureStderr(func() {
		procs, err := GetRunningProcesses()
		if err != nil {
			t.Errorf("second GetRunningProcesses: %v", err)
		}
		if len(procs) != 0 {
			t.Errorf("expected empty list on second read, got %d entries", len(procs))
		}
	})
	if second != "" {
		t.Errorf("expected no warning on second read, got: %q", second)
	}
}

// TestAddRunningProcessReplacesSamePID preserves the historical dedupe
// behavior: re-adding a PID replaces the existing entry instead of
// duplicating it.
func TestAddRunningProcessReplacesSamePID(t *testing.T) {
	t.Setenv("HOME", t.TempDir())

	if err := AddRunningProcess(ProcessInfo{PID: 1_000_001, Name: "old-name", Type: "agent"}); err != nil {
		t.Fatal(err)
	}
	if err := AddRunningProcess(ProcessInfo{PID: 1_000_001, Name: "new-name", Type: "agent"}); err != nil {
		t.Fatal(err)
	}

	procs := readRawProcessesFile(t)
	if len(procs) != 1 {
		t.Fatalf("expected 1 entry after re-add of same PID, got %d", len(procs))
	}
	if procs[0].Name != "new-name" {
		t.Errorf("expected re-add to replace entry, got name %q", procs[0].Name)
	}
}
