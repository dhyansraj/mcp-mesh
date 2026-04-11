//go:build linux

package cli

import (
	"os"
	"strconv"
	"strings"
)

// isProcessZombie returns true if the given PID is a zombie (state Z) or
// dead-pending (state X) on Linux. Reads /proc/<pid>/stat and parses the
// state field.
//
// The stat format is:
//
//	pid (comm) state ppid pgrp ...
//
// where (comm) may contain spaces and parentheses. To parse robustly, we
// find the LAST ")" in the line and read the character after the following
// space — that's the state field.
//
// Returns false on any error (file missing, permission denied, parse
// failure) — the caller will fall back to the signal(0) answer. A missing
// file is the common case when the kernel has already fully reaped the
// process, in which case signal(0) will also return ESRCH and the caller
// already treats that as "not alive".
func isProcessZombie(pid int) bool {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return false
	}
	s := string(data)
	// Find the last ")" to skip past the comm field which can contain
	// arbitrary characters including parens and spaces.
	lastParen := strings.LastIndex(s, ")")
	if lastParen < 0 || lastParen+2 >= len(s) {
		return false
	}
	// After the ")", there's a space, then the single-character state.
	rest := strings.TrimLeft(s[lastParen+1:], " ")
	if len(rest) == 0 {
		return false
	}
	state := rest[0]
	return state == 'Z' || state == 'X'
}
