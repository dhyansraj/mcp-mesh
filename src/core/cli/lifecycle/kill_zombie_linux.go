//go:build linux

package lifecycle

import (
	"os"
	"strconv"
	"strings"
)

// isZombie reads /proc/<pid>/stat and reports whether the process is in zombie
// (Z) or dead-pending (X) state. Mirrors the implementation in
// src/core/cli/utils_linux.go so meshctl works on slim Linux images without
// procps installed.
//
// The stat format is:
//
//	pid (comm) state ppid pgrp ...
//
// where (comm) may contain spaces and parentheses, so we anchor on the LAST
// ")" and read the state character that follows.
//
// Returns (false, nil) when /proc/<pid>/stat is missing or unreadable — the
// caller's aliveness check is authoritative for that case. No I/O on the proc
// filesystem maps to the transient-fork failure mode the (bool, error)
// contract exists for, so this implementation never returns a non-nil error.
func isZombie(pid int) (bool, error) {
	if pid <= 0 {
		return false, nil
	}
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return false, nil
	}
	s := string(data)
	lastParen := strings.LastIndex(s, ")")
	if lastParen < 0 || lastParen+2 >= len(s) {
		return false, nil
	}
	rest := strings.TrimLeft(s[lastParen+1:], " ")
	if len(rest) == 0 {
		return false, nil
	}
	state := rest[0]
	return state == 'Z' || state == 'X', nil
}
