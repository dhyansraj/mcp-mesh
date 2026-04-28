// Package lifecycle owns meshctl's on-disk process bookkeeping: PID files,
// service-dependency reference counts ("deps"), GC of stale entries, and the
// kill-and-verify primitive used by `meshctl stop`.
//
// Directory layout (rooted at MCP_MESH_HOME, default ~/.mcp-mesh/):
//
//	pids/
//	  <agent>.pid               # one per agent process
//	  <agent>.group             # group-id that owns the agent (text)
//	  registry.pid              # registry service
//	  ui.pid                    # UI service
//	  wrapper-<group>.pid       # transient marker for forked-detach wrappers
//	registry/deps/<group>       # one file per group, lines = agent names depending on registry
//	registry/start.lock         # flock for serializing concurrent registry starts
//	ui/deps/<group>             # one file per group, lines = agent names depending on UI
//	ui/start.lock               # flock for serializing concurrent UI starts
//	lifecycle.lock              # global flock for deps register/unregister
//
// Replaces the old per-parent-PID watch namespacing (<name>.<ppid>.pid):
// group-id supersedes that concept entirely.
package lifecycle

import (
	"os"
	"path/filepath"
	"sync"
)

const envHome = "MCP_MESH_HOME"

// rootOverride supports test fixtures via WithRoot. Production paths read the
// env var and fall back to ~/.mcp-mesh/. Guarded by mu so tests can swap it
// concurrently with reads (rare but the linter is happier this way).
var (
	mu           sync.RWMutex
	rootOverride string
)

// Root returns the lifecycle home directory. Resolution order:
//  1. explicit override set via WithRoot (test-only)
//  2. MCP_MESH_HOME env var
//  3. ~/.mcp-mesh/
//
// Falls back to "/.mcp-mesh" if the home dir cannot be resolved (extremely
// unlikely on a developer workstation, but we don't want to panic from a path
// helper).
func Root() string {
	mu.RLock()
	override := rootOverride
	mu.RUnlock()
	if override != "" {
		return override
	}
	if v := os.Getenv(envHome); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return "/.mcp-mesh"
	}
	return filepath.Join(home, ".mcp-mesh")
}

// WithRoot swaps the root for the duration of the returned restore closure.
// Test-only — never call from production code paths. Not safe to nest.
func WithRoot(path string) func() {
	mu.Lock()
	prev := rootOverride
	rootOverride = path
	mu.Unlock()
	return func() {
		mu.Lock()
		rootOverride = prev
		mu.Unlock()
	}
}

// PIDsDir returns <root>/pids/.
func PIDsDir() string { return filepath.Join(Root(), "pids") }

// RegistryDepsDir returns <root>/registry/deps/.
func RegistryDepsDir() string { return filepath.Join(Root(), "registry", "deps") }

// UIDepsDir returns <root>/ui/deps/.
func UIDepsDir() string { return filepath.Join(Root(), "ui", "deps") }

// PIDFile returns <root>/pids/<name>.pid. Caller is responsible for sanitizing
// name; lifecycle package treats the input as opaque.
func PIDFile(name string) string {
	return filepath.Join(PIDsDir(), name+".pid")
}

// GroupFile returns <root>/pids/<agent>.group — the group-id that owns this
// agent's PID file. Used by stop to find the registry/UI deps file to update.
func GroupFile(agent string) string {
	return filepath.Join(PIDsDir(), agent+".group")
}

// RegistryDepsFile returns <root>/registry/deps/<group> — the list of agents
// from a single group that depend on the registry being alive.
func RegistryDepsFile(group GroupID) string {
	return filepath.Join(RegistryDepsDir(), group.String())
}

// UIDepsFile returns <root>/ui/deps/<group>.
func UIDepsFile(group GroupID) string {
	return filepath.Join(UIDepsDir(), group.String())
}

// LockFile returns the global flock used to serialize deps register/unregister
// operations across meshctl invocations.
func LockFile() string { return filepath.Join(Root(), "lifecycle.lock") }

// RegistryStartLock returns the flock that serializes concurrent
// `meshctl start` invocations racing to start the registry.
func RegistryStartLock() string { return filepath.Join(Root(), "registry", "start.lock") }

// UIStartLock returns the flock that serializes concurrent UI starts.
func UIStartLock() string { return filepath.Join(Root(), "ui", "start.lock") }

// WrapperPIDFile returns <root>/pids/wrapper-<group>.pid — a transient marker
// written by forkToBackground so GC can clean up if the wrapper dies before
// its child writes any real PID files.
func WrapperPIDFile(group GroupID) string {
	return filepath.Join(PIDsDir(), "wrapper-"+group.String()+".pid")
}

// WatcherPIDFile returns <root>/pids/<agent>.watcher.pid — the PID of the
// meshctl process that owns the watch-mode watcher for this agent. Stop reads
// this to kill the watcher BEFORE the agent so the watcher can't respawn the
// agent on a stale file system event between the agent's death and stop's exit.
func WatcherPIDFile(agent string) string {
	return filepath.Join(PIDsDir(), agent+".watcher.pid")
}

// EnsureDirs creates all lifecycle directories. Safe to call repeatedly.
func EnsureDirs() error {
	dirs := []string{PIDsDir(), RegistryDepsDir(), UIDepsDir(),
		filepath.Dir(RegistryStartLock()), filepath.Dir(UIStartLock())}
	for _, d := range dirs {
		if err := os.MkdirAll(d, 0755); err != nil {
			return err
		}
	}
	return nil
}
