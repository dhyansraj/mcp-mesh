package lifecycle

import (
	"os"
	"path/filepath"
	"strings"
)

// Report summarizes a GC sweep so callers (start/stop entry points) can log
// the work that was done. Counters are zero on a no-op sweep.
type Report struct {
	DeadAgentPIDsCleaned  int // <agent>.pid files whose PID was dead
	StaleGroupFilesPruned int // <agent>.group files with no matching .pid
	StaleWrapperPIDs      int // wrapper-<group>.pid files whose wrapper PID was dead
	StaleWatcherPIDs      int // <agent>.watcher.pid files whose watcher PID was dead
	StaleDepsEntries      int // agent names removed from deps files
	EmptyDepsFilesRemoved int // deps files removed because they ended up empty
}

// Sweep scans pids/, registry/deps/, ui/deps/ and drops stale entries.
//
// CRITICAL: GC NEVER kills processes. It only cleans up bookkeeping that
// references dead PIDs. Stop is the only operation that kills.
//
// Order matters:
//  1. Drop dead agent .pid files (and their .group files).
//  2. Drop stale wrapper-<group>.pid files.
//  3. Walk deps files, drop entries whose <agent>.pid is missing or dead,
//     remove empty deps files.
//  4. Drop orphan .group files that have no matching .pid (after step 1).
func Sweep() (Report, error) {
	var r Report

	// Step 1 + 2: scan pids/ for dead agent PIDs and stale wrapper markers.
	entries, err := pidsDirEntries()
	if err != nil {
		return r, err
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		// Wrapper markers: wrapper-<group>.pid
		if strings.HasPrefix(name, "wrapper-") && strings.HasSuffix(name, ".pid") {
			path := pidsDirJoin(name)
			pid, _ := readPIDFromFile(path)
			if pid == 0 || !processAliveFn(pid) {
				if os.Remove(path) == nil {
					r.StaleWrapperPIDs++
				}
			}
			continue
		}
		// Watcher markers: <agent>.watcher.pid — handled BEFORE the generic
		// .pid check because they end in .pid too and would otherwise be
		// misinterpreted as agent PID files.
		if strings.HasSuffix(name, ".watcher.pid") {
			path := pidsDirJoin(name)
			pid, _ := readPIDFromFile(path)
			if pid == 0 || !processAliveFn(pid) {
				if os.Remove(path) == nil {
					r.StaleWatcherPIDs++
				}
			}
			continue
		}
		// Agent/service PID files: <name>.pid
		if !strings.HasSuffix(name, ".pid") {
			continue
		}
		base := strings.TrimSuffix(name, ".pid")
		// Service PID files (registry, ui) are NOT skipped: when the recorded
		// process is dead we sweep the file the same as any agent PID file, so
		// stale service state from a crash doesn't haunt the user. Live
		// services are left alone; stop is the only path that signals them.
		path := pidsDirJoin(name)
		pid, _ := readPIDFromFile(path)
		if pid > 0 && processAliveFn(pid) {
			continue // alive — leave alone
		}
		// Reaching here means pid==0 OR pid is dead — the cleanup branch is
		// unconditional. (Previously this re-tested processAliveFn, which was
		// always true given the continue above, and called the syscall twice
		// for every dead PID.)
		if os.Remove(path) == nil {
			r.DeadAgentPIDsCleaned++
		}
		// Best-effort prune of matching .group file (agents only — services
		// don't have one, so the os.Remove will simply no-op).
		_ = os.Remove(filepath.Join(PIDsDir(), base+".group"))
	}

	// Step 3: walk deps files for both services. The walk + rewrite must hold
	// the lifecycle lock — RegisterDep/UnregisterDep also hold it, and without
	// the lock here a concurrent meshctl invocation could rewrite a deps file
	// between our read and our writeDepsAtomic, losing its update. Sweep is
	// infrequent and the lock is short-lived so this is safe.
	if err := withLifecycleLock(func() error {
		for _, svc := range []string{ServiceRegistry, ServiceUI} {
			dir := depsDirFor(svc)
			depEntries, err := os.ReadDir(dir)
			if err != nil {
				if os.IsNotExist(err) {
					continue
				}
				return err
			}
			for _, de := range depEntries {
				if de.IsDir() {
					continue
				}
				n := de.Name()
				if strings.HasSuffix(n, ".tmp") {
					// Leftover from interrupted writeDepsAtomic — safe to drop.
					_ = os.Remove(filepath.Join(dir, n))
					continue
				}
				path := filepath.Join(dir, n)
				agents, err := readDeps(path)
				if err != nil {
					continue
				}
				var alive []string
				for _, a := range agents {
					// Sentinels (names beginning with "_", e.g. "_ui_only_" written
					// by `meshctl start --ui` standalone) have no PID file by design
					// — they exist solely to keep the deps file non-empty so refcount
					// reports the service as in-use. Never reap them as "dead PID";
					// only `meshctl stop` (no args) clears them, via PruneSentinelDeps.
					if strings.HasPrefix(a, "_") {
						alive = append(alive, a)
						continue
					}
					pidPath := PIDFile(a)
					pid, _ := readPIDFromFile(pidPath)
					if pid > 0 && processAliveFn(pid) {
						alive = append(alive, a)
					} else {
						r.StaleDepsEntries++
					}
				}
				if len(alive) == 0 {
					if os.Remove(path) == nil {
						r.EmptyDepsFilesRemoved++
					}
					continue
				}
				if len(alive) != len(agents) {
					_ = writeDepsAtomic(path, alive)
				}
			}
		}
		return nil
	}); err != nil {
		return r, err
	}

	// Step 4: orphan .group files (no matching .pid). Done after step 1 so a
	// just-pruned .pid that left its .group behind also gets cleaned.
	entries2, err := pidsDirEntries()
	if err != nil {
		return r, err
	}
	for _, e := range entries2 {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if !strings.HasSuffix(name, ".group") {
			continue
		}
		base := strings.TrimSuffix(name, ".group")
		pidPath := PIDFile(base)
		if _, err := os.Stat(pidPath); os.IsNotExist(err) {
			if os.Remove(pidsDirJoin(name)) == nil {
				r.StaleGroupFilesPruned++
			}
		}
	}

	return r, nil
}
