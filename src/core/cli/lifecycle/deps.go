package lifecycle

import (
	"bufio"
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
)

// Service identifies which shared resource a deps file belongs to. Strings
// chosen to match the on-disk subdirectory name (registry/deps, ui/deps).
const (
	ServiceRegistry = "registry"
	ServiceUI       = "ui"
)

// depsDirFor returns the absolute path to the deps directory for a service.
// Panics on unknown service — callers pass package-level constants
// (ServiceRegistry, ServiceUI), so an unknown value is always a programmer
// error, never a runtime condition we can recover from.
func depsDirFor(service string) string {
	switch service {
	case ServiceRegistry:
		return RegistryDepsDir()
	case ServiceUI:
		return UIDepsDir()
	default:
		panic("lifecycle: unknown service: " + service)
	}
}

// depsFileFor returns the absolute path to the deps file for a (service, group).
func depsFileFor(service string, group GroupID) string {
	return filepath.Join(depsDirFor(service), group.String())
}

// withLifecycleLock acquires the global flock at LockFile() for the duration
// of fn. Used to serialize all deps register/unregister calls so concurrent
// `meshctl start` invocations don't lose entries to a race.
//
// Creates the lockfile if missing (and its parent directory). The lock is
// released by closing the underlying file descriptor — Linux/macOS treat that
// as an unlock automatically.
func withLifecycleLock(fn func() error) error {
	if err := os.MkdirAll(filepath.Dir(LockFile()), 0755); err != nil {
		return fmt.Errorf("lifecycle: create lock dir: %w", err)
	}
	f, err := os.OpenFile(LockFile(), os.O_CREATE|os.O_RDWR, 0644)
	if err != nil {
		return fmt.Errorf("lifecycle: open lockfile: %w", err)
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return fmt.Errorf("lifecycle: flock: %w", err)
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	return fn()
}

// readDeps reads the deps file at path and returns the agents listed in it
// (one per line). Returns an empty slice if the file is missing.
func readDeps(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()
	var out []string
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		out = append(out, line)
	}
	return out, sc.Err()
}

// writeDepsAtomic writes the deps file via tmp+rename so an interrupted write
// never leaves a half-written file. Sorts and deduplicates entries first.
//
// If the deduplicated set is empty, the existing file (if any) is removed
// rather than rewritten as a zero-byte file. Empty files would confuse
// IsServiceRefcountZero (which keys off file existence in DepsForService) and
// every caller already wants the file gone in that case.
func writeDepsAtomic(path string, agents []string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	dedup := dedupSort(agents)
	if len(dedup) == 0 {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
			return err
		}
		return nil
	}
	var buf bytes.Buffer
	for _, a := range dedup {
		buf.WriteString(a)
		buf.WriteByte('\n')
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, buf.Bytes(), 0644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func dedupSort(in []string) []string {
	if len(in) == 0 {
		return nil
	}
	seen := make(map[string]struct{}, len(in))
	out := make([]string, 0, len(in))
	for _, s := range in {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		if _, ok := seen[s]; ok {
			continue
		}
		seen[s] = struct{}{}
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

// RegisterDep adds the given agents to the deps file for (service, group),
// creating the file if missing. Idempotent on duplicates. Holds the global
// lifecycle lock for the duration.
func RegisterDep(service string, group GroupID, agents []string) error {
	if len(agents) == 0 {
		return nil
	}
	path := depsFileFor(service, group)
	return withLifecycleLock(func() error {
		existing, err := readDeps(path)
		if err != nil {
			return fmt.Errorf("lifecycle: read deps %s: %w", path, err)
		}
		merged := append(existing, agents...)
		return writeDepsAtomic(path, merged)
	})
}

// UnregisterDep removes the given agents from the deps file for (service,
// group). If the file ends up empty after removal, it is deleted entirely so
// IsServiceRefcountZero can rely on file-existence as the signal. Missing file
// is a no-op (idempotent).
func UnregisterDep(service string, group GroupID, agents []string) error {
	if len(agents) == 0 {
		return nil
	}
	path := depsFileFor(service, group)
	return withLifecycleLock(func() error {
		existing, err := readDeps(path)
		if err != nil {
			return fmt.Errorf("lifecycle: read deps %s: %w", path, err)
		}
		if len(existing) == 0 {
			// File missing or already empty — try to remove the empty file too.
			os.Remove(path)
			return nil
		}
		drop := make(map[string]struct{}, len(agents))
		for _, a := range agents {
			drop[a] = struct{}{}
		}
		var remaining []string
		for _, a := range existing {
			if _, gone := drop[a]; gone {
				continue
			}
			remaining = append(remaining, a)
		}
		if len(remaining) == 0 {
			return os.Remove(path)
		}
		return writeDepsAtomic(path, remaining)
	})
}

// DepsForService returns the group-ids that have non-empty deps files under
// the service. Used by stop --registry/--ui to print the WARN line listing
// dependent groups before forcing the kill.
func DepsForService(service string) ([]GroupID, error) {
	dir := depsDirFor(service)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var out []GroupID
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		// Skip .tmp files left by an interrupted write.
		if strings.HasSuffix(e.Name(), ".tmp") {
			continue
		}
		g, err := Parse(e.Name())
		if err != nil {
			continue
		}
		// Only count files with at least one entry — empty files indicate the
		// group is gone and GC just hasn't pruned them yet.
		path := filepath.Join(dir, e.Name())
		agents, err := readDeps(path)
		if err != nil || len(agents) == 0 {
			continue
		}
		out = append(out, g)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out, nil
}

// AgentsInGroup returns the agents listed in the deps file for (service,
// group). Empty slice if the file is missing or empty.
func AgentsInGroup(service string, group GroupID) ([]string, error) {
	return readDeps(depsFileFor(service, group))
}

// IsServiceRefcountZero reports whether no group has any agents listed for the
// service — i.e., the service can be safely stopped.
func IsServiceRefcountZero(service string) (bool, error) {
	groups, err := DepsForService(service)
	if err != nil {
		return false, err
	}
	return len(groups) == 0, nil
}

// PruneSentinelDeps removes all sentinel entries (names starting with "_",
// e.g. "_ui_only_") from every deps file under the service. If a deps file
// becomes empty as a result, it is deleted so IsServiceRefcountZero reports
// truly zero.
//
// Used by `meshctl stop` (no args) so a standalone --ui session does not
// keep the UI alive past a "stop everything" command. Sentinels exist to
// protect the per-agent stop path (where killing an unrelated agent must
// not bring down a separately-started UI), but a no-args stop is the
// universal shutdown and must not be blocked by them.
func PruneSentinelDeps(service string) error {
	dir := depsDirFor(service)
	return withLifecycleLock(func() error {
		entries, err := os.ReadDir(dir)
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		for _, e := range entries {
			if e.IsDir() || strings.HasSuffix(e.Name(), ".tmp") {
				continue
			}
			path := filepath.Join(dir, e.Name())
			agents, err := readDeps(path)
			if err != nil {
				continue
			}
			var kept []string
			for _, a := range agents {
				if strings.HasPrefix(a, "_") {
					continue
				}
				kept = append(kept, a)
			}
			if len(kept) == len(agents) {
				continue
			}
			if len(kept) == 0 {
				_ = os.Remove(path)
				continue
			}
			_ = writeDepsAtomic(path, kept)
		}
		return nil
	})
}
