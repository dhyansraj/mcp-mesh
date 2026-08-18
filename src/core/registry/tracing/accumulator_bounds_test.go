package tracing

import (
	"fmt"
	"io"
	"log"
	"testing"
	"time"
)

// feedEdgeTrace drives one two-agent trace through the accumulator's real
// entry points (ProcessTraceEvent + FinalizeAllActive), producing exactly one
// edge key. This is the live path — no direct map writes.
func feedEdgeTrace(ta *TraceAccumulator, traceID, source, target string) {
	_ = ta.ProcessTraceEvent(makeEndEvent(traceID, "root-"+traceID, "", source, 10, true))
	_ = ta.ProcessTraceEvent(makeEndEvent(traceID, "child-"+traceID, "root-"+traceID, target, 5, true))
	ta.FinalizeAllActive()
}

// edgeKeyFor names the key feedEdgeTrace produces. makeEndEvent stamps every
// span's operation as "test_op", and the callee's operation is the key's
// function component (#1531).
func edgeKeyFor(source, target string) edgeKey {
	return edgeKey{Source: source, Target: target, Function: "test_op"}
}

// TestEdgeStatsUnboundedWithoutBounds is the "before" half of the #1424
// contrast: with both bounds off (the pre-fix behaviour), the edge map grows
// one key per distinct agent-name pair, forever.
func TestEdgeStatsUnboundedWithoutBounds(t *testing.T) {
	ta := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0), AggregateBounds{})

	const churn = 2000
	for i := 0; i < churn; i++ {
		feedEdgeTrace(ta, fmt.Sprintf("t%04d", i), fmt.Sprintf("caller-pod-%04d", i), "backend")
	}

	if got := ta.EdgeStatCount(); got != churn {
		t.Fatalf("unbounded accumulator: edge keys = %d, want %d (this test documents the pre-fix growth)", got, churn)
	}
}

// TestEdgeStatsKeyCapBoundsGrowth is the "after" half: the same churn under
// the default-shaped bounds never exceeds the cap, checked after EVERY trace
// rather than only at the end.
func TestEdgeStatsKeyCapBoundsGrowth(t *testing.T) {
	const cap = 50
	ta := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0),
		AggregateBounds{Retention: 24 * time.Hour, MaxEntries: cap})

	const churn = 2000
	for i := 0; i < churn; i++ {
		feedEdgeTrace(ta, fmt.Sprintf("t%04d", i), fmt.Sprintf("caller-pod-%04d", i), "backend")
		if got := ta.EdgeStatCount(); got > cap {
			t.Fatalf("after trace %d: edge keys = %d exceeds cap %d", i, got, cap)
		}
	}

	if got := ta.EdgeStatCount(); got == 0 {
		t.Fatal("edge map emptied entirely; the cap is evicting too aggressively")
	}

	// GetEdgeStats must still work off the bounded map.
	edges := ta.GetEdgeStats()
	if len(edges) == 0 {
		t.Fatal("GetEdgeStats returned nothing after 2000 traces")
	}
	if len(edges) > cap {
		t.Fatalf("GetEdgeStats returned %d edges, exceeds cap %d", len(edges), cap)
	}
}

// TestEdgeStatsAgePrune proves the PRIMARY bound: an edge that stopped
// reporting ages out, while a still-active edge survives. Dropping a live edge
// would be worse than holding a dead one, so both directions are asserted.
func TestEdgeStatsAgePrune(t *testing.T) {
	ta := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0),
		AggregateBounds{Retention: time.Hour, MaxEntries: 1000})

	feedEdgeTrace(ta, "t1", "retired-agent", "backend")
	feedEdgeTrace(ta, "t2", "live-agent", "backend")

	if got := ta.EdgeStatCount(); got != 2 {
		t.Fatalf("edge keys = %d, want 2 before pruning", got)
	}

	// Age the retired edge past the window; leave the live one fresh.
	ta.mu.Lock()
	ta.edgeStats[edgeKeyFor("retired-agent", "backend")].LastSeen = time.Now().Add(-2 * time.Hour)
	ta.mu.Unlock()

	ta.pruneEdgeStats()

	if got := ta.EdgeStatCount(); got != 1 {
		t.Fatalf("edge keys = %d after prune, want 1", got)
	}
	ta.mu.RLock()
	_, liveOK := ta.edgeStats[edgeKeyFor("live-agent", "backend")]
	_, deadOK := ta.edgeStats[edgeKeyFor("retired-agent", "backend")]
	ta.mu.RUnlock()
	if !liveOK {
		t.Error("still-active edge was pruned")
	}
	if deadOK {
		t.Error("idle edge survived the prune")
	}
}

// TestEdgeStatsAgePruneDisabled proves retention=0 is an honest no-op rather
// than a silent surprise, matching pruneExpiredCompletedTraces' contract.
func TestEdgeStatsAgePruneDisabled(t *testing.T) {
	ta := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0),
		AggregateBounds{Retention: 0, MaxEntries: 1000})

	feedEdgeTrace(ta, "t1", "ancient", "backend")
	ta.mu.Lock()
	ta.edgeStats[edgeKeyFor("ancient", "backend")].LastSeen = time.Now().Add(-1000 * time.Hour)
	ta.mu.Unlock()

	ta.pruneEdgeStats()

	if got := ta.EdgeStatCount(); got != 1 {
		t.Fatalf("edge keys = %d, want 1 (retention=0 must not prune)", got)
	}
}

// TestEdgeStatsDefaultPathUnchanged is the no-regression guard: a normally
// sized mesh (a handful of agents, repeated calls) sees byte-identical edge
// stats under the shipped defaults. The dashboard must show what it shows
// today.
func TestEdgeStatsDefaultPathUnchanged(t *testing.T) {
	bounded := newTestAccumulator(t, 16) // ships with DefaultAggregateBounds
	unbounded := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0), AggregateBounds{})

	agents := []string{"frontend", "auth", "billing", "search"}
	for i := 0; i < 500; i++ {
		src := agents[i%len(agents)]
		dst := agents[(i+1)%len(agents)]
		id := fmt.Sprintf("t%04d", i)
		feedEdgeTrace(bounded, id, src, dst)
		feedEdgeTrace(unbounded, id, src, dst)
	}

	// Compare as a keyed set rather than as a list: the invariant that matters
	// is that every edge and every number is identical, not the order they
	// arrive in. (GetEdgeStats does now impose a total order — see the
	// truncation argument there — but this test predates it and should keep
	// asserting the weaker, more durable property.)
	index := func(edges []EdgeStats) map[string]EdgeStats {
		m := make(map[string]EdgeStats, len(edges))
		for _, e := range edges {
			m[e.Source+" -> "+e.Target+" -> "+e.TargetFunction] = e
		}
		return m
	}
	bEdges := index(bounded.GetEdgeStats())
	uEdges := index(unbounded.GetEdgeStats())
	if len(bEdges) != len(uEdges) {
		t.Fatalf("edge count differs under defaults: bounded=%d unbounded=%d", len(bEdges), len(uEdges))
	}
	if len(bEdges) == 0 {
		t.Fatal("no edges recorded; the test did not exercise the aggregate path")
	}
	for key, want := range uEdges {
		got, ok := bEdges[key]
		if !ok {
			t.Fatalf("edge %q missing under the shipped defaults", key)
		}
		if got != want {
			t.Fatalf("edge %q differs under defaults:\n bounded=%+v\n   plain=%+v", key, got, want)
		}
	}
	if bounded.GetTotalFinalized() != unbounded.GetTotalFinalized() {
		t.Fatalf("totals differ: %d vs %d", bounded.GetTotalFinalized(), unbounded.GetTotalFinalized())
	}
}
