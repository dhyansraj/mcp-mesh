package cli

import (
	"os"
	"testing"

	"mcp-mesh/src/core/cli/lifecycle"
)

// TestSuggestAgentNames exercises the fuzzy "Did you mean?" helper used by
// stopSpecificAgent when the requested name isn't tracked. Matching is
// substring-in-either-direction against running agent names.
func TestSuggestAgentNames(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	for _, name := range []string{"digest-api", "portfolio-worker", "market-data"} {
		if err := lifecycle.WriteAgent(name, os.Getpid(), lifecycle.NewGroupID()); err != nil {
			t.Fatalf("WriteAgent(%s): %v", name, err)
		}
	}

	tests := []struct {
		query string
		want  []string
	}{
		{"api", []string{"digest-api"}},
		{"digest", []string{"digest-api"}},
		{"market", []string{"market-data"}},
		{"mkt", nil},
		{"digest-api", []string{"digest-api"}},
		{"worker", []string{"portfolio-worker"}},
		{"", nil},
	}
	for _, tc := range tests {
		got := suggestAgentNames(tc.query)
		if !equalStringSlices(got, tc.want) {
			t.Errorf("suggestAgentNames(%q) = %v, want %v", tc.query, got, tc.want)
		}
	}
}

// TestSuggestAgentNamesCapped verifies that suggestAgentNames returns at most
// 3 results even when more agents match the query, and that the returned
// subset is deterministic (sorted alphabetically).
func TestSuggestAgentNamesCapped(t *testing.T) {
	tmp := t.TempDir()
	defer lifecycle.WithRoot(tmp)()

	names := []string{
		"zeta-agent", "beta-agent", "delta-agent",
		"alpha-agent", "gamma-agent",
	}
	for _, n := range names {
		if err := lifecycle.WriteAgent(n, os.Getpid(), lifecycle.NewGroupID()); err != nil {
			t.Fatalf("WriteAgent(%s): %v", n, err)
		}
	}

	got := suggestAgentNames("agent")
	if len(got) != 3 {
		t.Fatalf("suggestAgentNames(\"agent\") returned %d results, want exactly 3: %v", len(got), got)
	}
	want := []string{"alpha-agent", "beta-agent", "delta-agent"}
	if !equalStringSlices(got, want) {
		t.Errorf("suggestAgentNames(\"agent\") = %v, want %v (sorted and capped)", got, want)
	}
}

func equalStringSlices(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
