package tracing

import (
	"fmt"
	"testing"
	"time"
)

// TestLoadAggregateBoundsFromEnv covers every branch of the #1424 knobs,
// including the disable values and the requirement that a BAD value falls back
// to the default rather than silently removing the bound.
func TestLoadAggregateBoundsFromEnv(t *testing.T) {
	cases := []struct {
		name         string
		retention    string
		maxEntries   string
		wantRetain   time.Duration
		wantMaxEntry int
	}{
		{"unset_uses_defaults", "", "", defaultAggregateRetention, defaultAggregateMaxEntries},
		{"retention_override", "1h", "", time.Hour, defaultAggregateMaxEntries},
		{"max_entries_override", "", "250", defaultAggregateRetention, 250},
		{"both_overridden", "30m", "7", 30 * time.Minute, 7},
		{"retention_zero_disables_age_prune", "0", "", 0, defaultAggregateMaxEntries},
		{"max_entries_zero_disables_cap", "", "0", defaultAggregateRetention, 0},
		{"both_zero_fully_unbounded", "0", "0", 0, 0},

		// Bad values must FALL BACK, never disable. A typo must not silently
		// unbound the map.
		{"retention_negative_falls_back", "-1h", "", defaultAggregateRetention, defaultAggregateMaxEntries},
		{"retention_garbage_falls_back", "not-a-duration", "", defaultAggregateRetention, defaultAggregateMaxEntries},
		{"max_entries_negative_falls_back", "", "-5", defaultAggregateRetention, defaultAggregateMaxEntries},
		{"max_entries_garbage_falls_back", "", "lots", defaultAggregateRetention, defaultAggregateMaxEntries},
		{"max_entries_float_falls_back", "", "1e4", defaultAggregateRetention, defaultAggregateMaxEntries},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("MCP_MESH_TELEMETRY_AGGREGATE_RETENTION", tc.retention)
			t.Setenv("MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES", tc.maxEntries)

			got := LoadAggregateBoundsFromEnv()
			if got.Retention != tc.wantRetain {
				t.Errorf("Retention = %s, want %s", got.Retention, tc.wantRetain)
			}
			if got.MaxEntries != tc.wantMaxEntry {
				t.Errorf("MaxEntries = %d, want %d", got.MaxEntries, tc.wantMaxEntry)
			}
		})
	}
}

// TestDefaultAggregateBoundsAreBounded is the regression guard for #1424: the
// out-of-the-box configuration must bound both dimensions. If someone changes
// a default to 0 this fails loudly.
func TestDefaultAggregateBoundsAreBounded(t *testing.T) {
	b := DefaultAggregateBounds()
	if b.Retention <= 0 {
		t.Errorf("default aggregate retention must be positive, got %s", b.Retention)
	}
	if b.MaxEntries <= 0 {
		t.Errorf("default aggregate max entries must be positive, got %d", b.MaxEntries)
	}
}

type stamped struct{ seen time.Time }

func stampedSeen(s *stamped) time.Time { return s.seen }

func TestPruneOlderThan(t *testing.T) {
	now := time.Now()
	m := map[string]*stamped{
		"fresh":    {seen: now},
		"recent":   {seen: now.Add(-30 * time.Second)},
		"stale":    {seen: now.Add(-2 * time.Hour)},
		"ancient":  {seen: now.Add(-48 * time.Hour)},
		"zerotime": {}, // never stamped — must be treated as infinitely old
	}

	removed := PruneOlderThan(m, stampedSeen, now.Add(-time.Hour))
	if removed != 3 {
		t.Fatalf("removed = %d, want 3", removed)
	}
	if len(m) != 2 {
		t.Fatalf("len(m) = %d, want 2", len(m))
	}
	for _, k := range []string{"fresh", "recent"} {
		if _, ok := m[k]; !ok {
			t.Errorf("key %q should have survived the prune", k)
		}
	}
}

// TestEnforceMaxEntriesBoundsGrowth drives the map far past its cap and proves
// the length never exceeds it — the actual bound, not just that the function
// is callable.
func TestEnforceMaxEntriesBoundsGrowth(t *testing.T) {
	const cap = 100
	base := time.Now()
	m := make(map[string]*stamped)

	maxSeen := 0
	for i := 0; i < 5000; i++ {
		m[fmt.Sprintf("key-%05d", i)] = &stamped{seen: base.Add(time.Duration(i) * time.Millisecond)}
		EnforceMaxEntries(m, stampedSeen, cap, StringKeyLess)
		if len(m) > maxSeen {
			maxSeen = len(m)
		}
		if len(m) > cap {
			t.Fatalf("after insert %d: len(m) = %d exceeds cap %d", i, len(m), cap)
		}
	}

	if maxSeen == 0 {
		t.Fatal("map never grew; test did not exercise the cap")
	}
	// The survivors must be the most recently seen keys, i.e. eviction is LRU
	// and not arbitrary — dropping a recently-active key would be the bad
	// failure mode for a dashboard.
	if _, ok := m["key-04999"]; !ok {
		t.Error("most recently inserted key was evicted; eviction is not least-recently-seen")
	}
	if _, ok := m["key-00000"]; ok {
		t.Error("oldest key survived 5000 inserts past a cap of 100")
	}
}

// TestEnforceMaxEntriesDisabled proves 0 really means "no ceiling" so the knob's
// disable value is honest.
func TestEnforceMaxEntriesDisabled(t *testing.T) {
	m := make(map[string]*stamped)
	for i := 0; i < 1000; i++ {
		m[fmt.Sprintf("k%d", i)] = &stamped{seen: time.Now()}
		if n := EnforceMaxEntries(m, stampedSeen, 0, StringKeyLess); n != 0 {
			t.Fatalf("cap of 0 evicted %d entries; it must be a no-op", n)
		}
	}
	if len(m) != 1000 {
		t.Fatalf("len(m) = %d, want 1000 with the cap disabled", len(m))
	}
}

// TestEnforceMaxEntriesTinyCap covers cap values small enough that the 10%
// batch rounds to zero.
func TestEnforceMaxEntriesTinyCap(t *testing.T) {
	for _, cap := range []int{1, 2, 3} {
		m := make(map[string]*stamped)
		base := time.Now()
		for i := 0; i < 50; i++ {
			m[fmt.Sprintf("k%02d", i)] = &stamped{seen: base.Add(time.Duration(i) * time.Millisecond)}
			EnforceMaxEntries(m, stampedSeen, cap, StringKeyLess)
			if len(m) > cap {
				t.Fatalf("cap=%d: len(m) = %d after insert %d", cap, len(m), i)
			}
		}
		if len(m) == 0 {
			t.Fatalf("cap=%d: map emptied entirely", cap)
		}
	}
}
