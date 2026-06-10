package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// newTestProcessManager builds a ProcessManager directly (bypassing the
// global singleton and config loading) with a temp state file.
func newTestProcessManager(t *testing.T) *ProcessManager {
	t.Helper()
	return &ProcessManager{
		processes:    make(map[string]*ProcessInfo),
		logger:       NewCLILogger("TEST"),
		stateFile:    filepath.Join(t.TempDir(), "processes.json"),
		shutdownChan: make(chan struct{}),
	}
}

func seedManagedProcess(pm *ProcessManager, name string, pid int) {
	pm.processes[name] = &ProcessInfo{
		PID:         pid,
		Name:        name,
		Command:     "test-cmd",
		StartTime:   time.Now(),
		Status:      "running",
		HealthCheck: "unknown",
		LastSeen:    time.Now(),
		ServiceType: "agent",
		Type:        "agent",
		Environment: map[string]string{"MCP_MESH_TEST": "1"},
		Metadata:    map[string]interface{}{"k": "v"},
	}
}

// TestProcessManagerGettersReturnIsolatedCopies verifies MED-3: mutations on
// the structs returned by GetProcess / GetAllProcesses must not leak into the
// manager's shared state.
func TestProcessManagerGettersReturnIsolatedCopies(t *testing.T) {
	pm := newTestProcessManager(t)
	seedManagedProcess(pm, "agent-a", os.Getpid())

	got, ok := pm.GetProcess("agent-a")
	if !ok {
		t.Fatal("GetProcess: agent-a not found")
	}
	got.Status = "mutated"
	got.HealthCheck = "mutated"
	got.Environment["MCP_MESH_TEST"] = "mutated"
	got.Metadata["k"] = "mutated"

	all := pm.GetAllProcesses()
	allCopy, ok := all["agent-a"]
	if !ok {
		t.Fatal("GetAllProcesses: agent-a not found")
	}
	allCopy.Status = "also-mutated"
	allCopy.Environment["MCP_MESH_TEST"] = "also-mutated"

	// Re-read: the manager's state must be unaffected by either mutation.
	fresh, ok := pm.GetProcess("agent-a")
	if !ok {
		t.Fatal("GetProcess (re-read): agent-a not found")
	}
	if fresh.Status == "mutated" || fresh.Status == "also-mutated" {
		t.Errorf("manager state Status leaked caller mutation: %q", fresh.Status)
	}
	if fresh.HealthCheck == "mutated" {
		t.Errorf("manager state HealthCheck leaked caller mutation: %q", fresh.HealthCheck)
	}
	if fresh.Environment["MCP_MESH_TEST"] != "1" {
		t.Errorf("manager state Environment leaked caller mutation: %q", fresh.Environment["MCP_MESH_TEST"])
	}
	if fresh.Metadata["k"] != "v" {
		t.Errorf("manager state Metadata leaked caller mutation: %v", fresh.Metadata["k"])
	}
}

// TestProcessManagerConcurrentGetters exercises concurrent GetAllProcesses +
// GetProcess callers (the signal_handler.go pattern) under the race detector.
// Pre-MED-3, GetAllProcesses mutated shared structs under RLock and returned
// aliased pointers — `go test -race` flagged exactly this interleave.
func TestProcessManagerConcurrentGetters(t *testing.T) {
	pm := newTestProcessManager(t)
	for i := 0; i < 5; i++ {
		// Mix of live (our own PID) and dead PIDs so updateProcessStatus
		// takes both branches.
		pid := os.Getpid()
		if i%2 == 1 {
			pid = 0x7ffffff - i // certainly not a live PID
		}
		seedManagedProcess(pm, fmt.Sprintf("agent-%d", i), pid)
	}

	const goroutines = 8
	const iterations = 200

	var wg sync.WaitGroup
	for g := 0; g < goroutines; g++ {
		wg.Add(1)
		go func(g int) {
			defer wg.Done()
			for i := 0; i < iterations; i++ {
				if i%2 == 0 {
					all := pm.GetAllProcesses()
					// Mutate the returned copies — must be race-free and
					// must not affect the manager.
					for _, info := range all {
						info.Status = "scribbled"
						info.LastSeen = time.Time{}
					}
				} else {
					if info, ok := pm.GetProcess(fmt.Sprintf("agent-%d", g%5)); ok {
						info.HealthCheck = "scribbled"
					}
				}
			}
		}(g)
	}
	wg.Wait()

	// Manager state must never contain the scribbles.
	for name, info := range pm.GetAllProcesses() {
		if info.Status == "scribbled" || info.HealthCheck == "scribbled" {
			t.Errorf("manager state for %s contains caller scribbles (status=%q health=%q)", name, info.Status, info.HealthCheck)
		}
	}
}
