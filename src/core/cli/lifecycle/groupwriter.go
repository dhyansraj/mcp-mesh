package lifecycle

import (
	"fmt"
	"os"
	"path/filepath"
)

// WriteAgent writes the agent's bookkeeping to disk:
//   - <agent>.group  (text: group-id) — written FIRST so that a crash between
//     the two writes leaves an unowned .group file (harmless; GC sweeps it).
//     The reverse order would leave a .pid with no owner — stop would have to
//     guess which deps file to update.
//   - <agent>.pid    (text: PID, atomically via tmp+rename)
func WriteAgent(name string, pid int, group GroupID) error {
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		return fmt.Errorf("lifecycle: mkdir pids: %w", err)
	}
	groupPath := GroupFile(name)
	if err := os.WriteFile(groupPath, []byte(group.String()), 0644); err != nil {
		return fmt.Errorf("lifecycle: write group file %s: %w", groupPath, err)
	}
	pidPath := PIDFile(name)
	tmp := pidPath + ".tmp"
	if err := os.WriteFile(tmp, []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		return fmt.Errorf("lifecycle: write pid tmp %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, pidPath); err != nil {
		// Clean up tmp on failure to avoid orphans cluttering the dir.
		_ = os.Remove(tmp)
		return fmt.Errorf("lifecycle: rename pid file %s: %w", pidPath, err)
	}
	return nil
}

// RemoveAgent removes the .pid, .group, and .watcher.pid files. Missing files
// are not errors — the call is idempotent. Watcher pid is included so a clean
// agent removal also drops any orphan watcher tracking.
func RemoveAgent(name string) error {
	if err := os.Remove(PIDFile(name)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("lifecycle: remove pid %s: %w", name, err)
	}
	if err := os.Remove(GroupFile(name)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("lifecycle: remove group %s: %w", name, err)
	}
	if err := os.Remove(WatcherPIDFile(name)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("lifecycle: remove watcher pid %s: %w", name, err)
	}
	return nil
}

// WriteService writes a service PID file (registry, ui, etc.) — no .group
// file because services aren't owned by a single group; ownership is tracked
// via the deps directories. Atomic via tmp+rename.
func WriteService(service string, pid int) error {
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		return fmt.Errorf("lifecycle: mkdir pids: %w", err)
	}
	pidPath := PIDFile(service)
	tmp := pidPath + ".tmp"
	if err := os.WriteFile(tmp, []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		return fmt.Errorf("lifecycle: write service pid tmp: %w", err)
	}
	if err := os.Rename(tmp, pidPath); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("lifecycle: rename service pid: %w", err)
	}
	return nil
}

// RemoveService removes a service PID file. Idempotent.
func RemoveService(service string) error {
	if err := os.Remove(PIDFile(service)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("lifecycle: remove service %s: %w", service, err)
	}
	return nil
}

// WriteWrapperPID writes the transient wrapper-<group>.pid marker used by GC.
func WriteWrapperPID(group GroupID, pid int) error {
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		return fmt.Errorf("lifecycle: mkdir pids: %w", err)
	}
	path := WrapperPIDFile(group)
	return os.WriteFile(path, []byte(fmt.Sprintf("%d", pid)), 0644)
}

// RemoveWrapperPID removes a wrapper-<group>.pid marker. Idempotent.
func RemoveWrapperPID(group GroupID) error {
	if err := os.Remove(WrapperPIDFile(group)); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// WriteWatcher records that the given meshctl process owns the watch-mode
// watcher for an agent. Atomic via tmp+rename so a crash between mkdir and
// rename never leaves a partially-written file. Caller is the meshctl process
// that holds the watcher goroutine; pid is os.Getpid() of that process.
func WriteWatcher(agent string, pid int) error {
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		return fmt.Errorf("lifecycle: mkdir pids: %w", err)
	}
	path := WatcherPIDFile(agent)
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		return fmt.Errorf("lifecycle: write watcher pid tmp: %w", err)
	}
	if err := os.Rename(tmp, path); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("lifecycle: rename watcher pid: %w", err)
	}
	return nil
}

// ReadWatcherPID returns the PID of the meshctl process owning the watch-mode
// watcher for the given agent, or (0, nil) if no watcher.pid file exists.
func ReadWatcherPID(agent string) (int, error) {
	return readPIDFromFile(WatcherPIDFile(agent))
}

// RemoveWatcher removes <agent>.watcher.pid. Idempotent — missing file is
// not an error.
func RemoveWatcher(agent string) error {
	if err := os.Remove(WatcherPIDFile(agent)); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("lifecycle: remove watcher pid %s: %w", agent, err)
	}
	return nil
}

// PIDsDirEntries lists all files under PIDsDir() (no recursion). Used by GC.
func pidsDirEntries() ([]os.DirEntry, error) {
	entries, err := os.ReadDir(PIDsDir())
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	return entries, nil
}

// pidsDirJoin joins a filename onto the pids directory path.
func pidsDirJoin(name string) string { return filepath.Join(PIDsDir(), name) }
