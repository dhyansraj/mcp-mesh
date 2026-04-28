package lifecycle

import (
	"os"
	"strings"
	"testing"
)

func TestNewGroupIDFormat(t *testing.T) {
	resetSeqForTests()
	g := NewGroupID()
	parts := strings.Split(g.String(), "-")
	if len(parts) != 3 {
		t.Fatalf("group id %q must have 3 segments, got %d", g, len(parts))
	}
	for i, p := range parts {
		if p == "" {
			t.Errorf("segment %d empty in %q", i, g)
		}
	}
}

func TestNewGroupIDUniqueness(t *testing.T) {
	resetSeqForTests()
	const N = 1000
	seen := make(map[string]struct{}, N)
	for i := 0; i < N; i++ {
		s := NewGroupID().String()
		if _, dup := seen[s]; dup {
			t.Fatalf("duplicate group id at iteration %d: %q", i, s)
		}
		seen[s] = struct{}{}
	}
}

func TestParseRoundTrip(t *testing.T) {
	resetSeqForTests()
	g := NewGroupID()
	g2, err := Parse(g.String())
	if err != nil {
		t.Fatalf("Parse(%q) failed: %v", g, err)
	}
	if g2 != g {
		t.Errorf("round-trip differs: in=%q out=%q", g, g2)
	}
}

func TestParseRejectsGarbage(t *testing.T) {
	bad := []string{
		"",
		"plain",
		"123",
		"a-b-c",       // non-numeric segments
		"123-abc",     // mixed
		"123-",        // empty trailing
		"-123",        // empty leading
		"1-2-3-4",     // too many segments
		"123-456",     // legacy 2-segment form (no longer accepted)
		"123-456/789", // path separator
		"123-456\x00", // NUL
	}
	for _, s := range bad {
		if _, err := Parse(s); err == nil {
			t.Errorf("Parse(%q) should have errored", s)
		}
	}
}

func TestLookupGroup(t *testing.T) {
	tmp := t.TempDir()
	defer WithRoot(tmp)()
	if err := os.MkdirAll(PIDsDir(), 0755); err != nil {
		t.Fatal(err)
	}

	// Missing -> ErrNoGroup.
	if _, err := LookupGroup("nope"); err != ErrNoGroup {
		t.Errorf("expected ErrNoGroup, got %v", err)
	}

	// Write a valid group file and look it up.
	g := NewGroupID()
	if err := os.WriteFile(GroupFile("foo"), []byte(g.String()+"\n"), 0644); err != nil {
		t.Fatal(err)
	}
	got, err := LookupGroup("foo")
	if err != nil {
		t.Fatalf("LookupGroup: %v", err)
	}
	if got != g {
		t.Errorf("LookupGroup = %q, want %q", got, g)
	}

	// Write a malformed group file and ensure parse error is surfaced.
	if err := os.WriteFile(GroupFile("bad"), []byte("garbage"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := LookupGroup("bad"); err == nil {
		t.Errorf("expected parse error for malformed group file")
	}
}
