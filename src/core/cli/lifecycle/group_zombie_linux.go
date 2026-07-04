//go:build linux

package lifecycle

import (
	"os"
	"strconv"
	"strings"
)

// groupAllZombie reports whether process group pgid is non-empty and EVERY
// member is a zombie (Z) or dead-pending (X).
//
// Why this exists: a zombie has already exited and released all of its
// resources — ports, sockets, file descriptors — and only occupies a
// process-table slot awaiting a reaper. In a container whose PID 1 does not
// reap orphans (a bare shell/test-harness entrypoint), a grandchild that
// outlived its parent is reparented to that non-reaping PID 1 and its zombie
// can linger indefinitely. kill(-pgid, 0) keeps reporting such a group as
// "alive", which would hang the group-drain waits in kill.go forever. Treating
// an all-zombie group as dead lets stop/reload make progress: the port is
// already free, so there is nothing left to wait for.
//
// Returns:
//   - (true, nil)  at least one member was found and ALL members are zombies
//   - (false, nil) a live (non-zombie) member exists, or the group is empty
//   - (false, err) the /proc scan itself failed — inconclusive; the caller
//     MUST NOT treat this as "dead"
//
// Reads /proc/<pid>/stat directly (no procps dependency) mirroring isZombie.
// The stat line is `pid (comm) state ppid pgrp ...`; (comm) may contain spaces
// and parens, so we anchor on the LAST ')' and read the space-separated fields
// that follow: field 0 = state, field 2 = pgrp.
func groupAllZombie(pgid int) (bool, error) {
	if pgid <= 1 {
		return false, nil
	}
	entries, err := os.ReadDir("/proc")
	if err != nil {
		return false, err
	}
	found := false
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		if _, err := strconv.Atoi(e.Name()); err != nil {
			continue // not a PID directory
		}
		data, err := os.ReadFile("/proc/" + e.Name() + "/stat")
		if err != nil {
			continue // process vanished mid-scan — skip, not fatal
		}
		s := string(data)
		lastParen := strings.LastIndex(s, ")")
		if lastParen < 0 || lastParen+2 >= len(s) {
			continue
		}
		fields := strings.Fields(s[lastParen+1:])
		if len(fields) < 3 {
			continue
		}
		pg, err := strconv.Atoi(fields[2])
		if err != nil || pg != pgid {
			continue
		}
		found = true
		if state := fields[0]; state != "Z" && state != "X" {
			return false, nil // a live member exists — group not drained
		}
	}
	return found, nil
}
