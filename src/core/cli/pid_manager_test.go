package cli

import (
	"strings"
	"testing"
)

// --- sanitizeName ---
//
// sanitizeName remains in pid_manager.go for any non-lifecycle callers (e.g.,
// log file naming) that need a filesystem-safe name. The watch-mode
// "<name>.<parent_pid>.pid" parser is gone, so the dot-stripping invariant
// is no longer load-bearing — but keeping the function predictable.

func TestSanitizeName(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{"foo.py", "foo"},
		{"market-data-massive", "market-data-massive"},
		{"agent/with/slashes.py", "slashes"},
		{"", "_"},
		{"weird.name.py", "weird_name"},
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

func TestSanitizeNameNoControlChars(t *testing.T) {
	inputs := []string{
		"foo.py",
		"weird.name.py",
		"a.b.c.d",
		"market-data-massive",
		"/abs/path/to/agent.py",
		"agent-v1.2.3.py",
		"unknown",
		"my_agent",
		"numbers123",
	}
	for _, in := range inputs {
		out := sanitizeName(in)
		if strings.ContainsAny(out, "/\\\x00") {
			t.Errorf("sanitizeName(%q) = %q contains path/control characters", in, out)
		}
	}
}
