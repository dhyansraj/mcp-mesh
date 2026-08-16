package tracing

import (
	"fmt"
	"io"
	"log"
	"strings"
	"testing"
	"time"
)

// Edge stats keyed by (source, target, function) — issue #1531. Before this,
// every call between one pair of agents landed in one bucket, so a pair that
// exchanged three different tools reported one averaged number three times over
// and the topology graph stamped it onto all three edges.

// makeCalleeSpan is makeEndEvent with the operation spelled out: the operation
// is now part of the key, so a test that cannot set it cannot see the change.
func makeCalleeSpan(traceID, spanID, parent, agent, operation string, durationMs int64, success bool) *TraceEvent {
	e := makeEndEvent(traceID, spanID, parent, agent, durationMs, success)
	e.Operation = operation
	return e
}

// feedCall drives one caller->callee trace where the callee's span names the
// provider function it ran. That span is the one the edge is attributed from.
func feedCall(ta *TraceAccumulator, traceID, caller, callee, calleeOp string, durationMs int64, success bool) {
	_ = ta.ProcessTraceEvent(makeCalleeSpan(traceID, "root-"+traceID, "", caller, "caller_entrypoint", 1, true))
	_ = ta.ProcessTraceEvent(makeCalleeSpan(traceID, "child-"+traceID, "root-"+traceID, callee, calleeOp, durationMs, success))
	ta.FinalizeAllActive()
}

// statFor finds the single row for one (source, target, function).
func statFor(t *testing.T, edges []EdgeStats, source, target, fn string) EdgeStats {
	t.Helper()
	var found []EdgeStats
	for _, e := range edges {
		if e.Source == source && e.Target == target && e.TargetFunction == fn {
			found = append(found, e)
		}
	}
	if len(found) == 0 {
		t.Fatalf("no edge stat for %s -> %s (%s); got %+v", source, target, fn, edges)
	}
	if len(found) > 1 {
		t.Fatalf("%d rows for %s -> %s (%s), want exactly 1", len(found), source, target, fn)
	}
	return found[0]
}

// TestEdgeStatsSplitByProviderFunction is the bug itself: one pair, three tools
// with very different latencies. Before the finer key all three read the same
// average; now each carries its own numbers.
func TestEdgeStatsSplitByProviderFunction(t *testing.T) {
	ta := newTestAccumulator(t, 64)

	// A fast tool, a slow one, and a very slow one — 100 calls each.
	for i := 0; i < 100; i++ {
		feedCall(ta, fmt.Sprintf("fast%03d", i), "caller", "provider", "lookup", 2, true)
		feedCall(ta, fmt.Sprintf("slow%03d", i), "caller", "provider", "summarise", 400, true)
		feedCall(ta, fmt.Sprintf("job%03d", i), "caller", "provider", "bulk_export", 9000, true)
	}

	edges := ta.GetEdgeStats()
	if len(edges) != 3 {
		t.Fatalf("got %d edge rows, want 3 (one per called function): %+v", len(edges), edges)
	}

	lookup := statFor(t, edges, "caller", "provider", "lookup")
	summarise := statFor(t, edges, "caller", "provider", "summarise")
	bulk := statFor(t, edges, "caller", "provider", "bulk_export")

	if lookup.AvgLatencyMs != 2 || summarise.AvgLatencyMs != 400 || bulk.AvgLatencyMs != 9000 {
		t.Fatalf("averages bled across functions: lookup=%v summarise=%v bulk=%v",
			lookup.AvgLatencyMs, summarise.AvgLatencyMs, bulk.AvgLatencyMs)
	}
	// The pair-level average these used to share, spelled out so the assertion
	// above is visibly about the thing that was wrong.
	const pairAverage = (2.0 + 400.0 + 9000.0) / 3.0
	for _, e := range edges {
		if e.AvgLatencyMs == pairAverage {
			t.Fatalf("%s still reports the pair-level average %v", e.TargetFunction, pairAverage)
		}
		if e.CallCount != 100 {
			t.Fatalf("%s call count = %d, want 100", e.TargetFunction, e.CallCount)
		}
	}
}

// TestEdgeStatsErrorsStayWithTheirFunction: a failing tool must not colour the
// healthy tools between the same two agents. This is what drives the graph's
// heat colour, so the leak was visible as red edges that were never failing.
func TestEdgeStatsErrorsStayWithTheirFunction(t *testing.T) {
	ta := newTestAccumulator(t, 64)

	for i := 0; i < 10; i++ {
		feedCall(ta, fmt.Sprintf("ok%02d", i), "caller", "provider", "healthy_tool", 5, true)
		feedCall(ta, fmt.Sprintf("bad%02d", i), "caller", "provider", "broken_tool", 5, false)
	}

	edges := ta.GetEdgeStats()
	healthy := statFor(t, edges, "caller", "provider", "healthy_tool")
	broken := statFor(t, edges, "caller", "provider", "broken_tool")

	if healthy.ErrorCount != 0 || healthy.ErrorRate != 0 {
		t.Fatalf("healthy tool inherited errors: count=%d rate=%v", healthy.ErrorCount, healthy.ErrorRate)
	}
	if broken.ErrorCount != 10 || broken.ErrorRate != 100 {
		t.Fatalf("broken tool: count=%d rate=%v, want 10 / 100", broken.ErrorCount, broken.ErrorRate)
	}
}

// TestEdgeStatsDifferentPairsSameFunctionStaySeparate: the function is the
// THIRD component, not a replacement for either of the first two. Two agents
// happening to publish a tool of the same name must not merge.
func TestEdgeStatsDifferentPairsSameFunctionStaySeparate(t *testing.T) {
	ta := newTestAccumulator(t, 64)

	feedCall(ta, "t1", "caller-a", "provider-x", "search", 10, true)
	feedCall(ta, "t2", "caller-b", "provider-x", "search", 20, true)
	feedCall(ta, "t3", "caller-a", "provider-y", "search", 30, true)

	edges := ta.GetEdgeStats()
	if len(edges) != 3 {
		t.Fatalf("got %d rows, want 3: %+v", len(edges), edges)
	}
	if got := statFor(t, edges, "caller-a", "provider-x", "search").AvgLatencyMs; got != 10 {
		t.Fatalf("caller-a -> provider-x avg = %v, want 10", got)
	}
	if got := statFor(t, edges, "caller-b", "provider-x", "search").AvgLatencyMs; got != 20 {
		t.Fatalf("caller-b -> provider-x avg = %v, want 20", got)
	}
	if got := statFor(t, edges, "caller-a", "provider-y", "search").AvgLatencyMs; got != 30 {
		t.Fatalf("caller-a -> provider-y avg = %v, want 30", got)
	}
}

// TestEdgeStatsKeyIsNotAParsedString is the reason the key is a struct. The old
// key was `source + " -> " + target`, taken apart again on the read side by
// scanning for the FIRST " -> ": an agent named with that sequence in it split
// in the wrong place and reported traffic for two agents that do not exist.
func TestEdgeStatsKeyIsNotAParsedString(t *testing.T) {
	const hostile = "weird -> name"
	ta := newTestAccumulator(t, 16)
	feedCall(ta, "t1", hostile, "backend", "handle", 7, true)

	edges := ta.GetEdgeStats()
	if len(edges) != 1 {
		t.Fatalf("got %d rows, want 1: %+v", len(edges), edges)
	}
	if edges[0].Source != hostile || edges[0].Target != "backend" {
		t.Fatalf("names came apart: source=%q target=%q, want %q -> %q",
			edges[0].Source, edges[0].Target, hostile, "backend")
	}
	if strings.Contains(edges[0].Target, "->") {
		t.Fatalf("target %q still carries a fragment of the source", edges[0].Target)
	}
}

// TestEdgeStatsEmptyOperationIsRecordedNotDropped pins the deliberate choice for
// a span carrying no operation: keep the call, under an empty function.
//
// Dropping it would be the quiet option and the wrong one — the call really did
// happen, and losing it makes the traffic totals disagree with the traces they
// were computed from. Recorded, it is a row that joins to no topology edge,
// which is exactly what the payload supports: something was called, and nothing
// says what.
func TestEdgeStatsEmptyOperationIsRecordedNotDropped(t *testing.T) {
	ta := newTestAccumulator(t, 16)

	feedCall(ta, "t1", "caller", "provider", "", 42, true)
	feedCall(ta, "t2", "caller", "provider", "named_tool", 8, true)

	edges := ta.GetEdgeStats()
	if len(edges) != 2 {
		t.Fatalf("got %d rows, want 2 (the unnamed call must not be folded into the named one): %+v",
			len(edges), edges)
	}
	unnamed := statFor(t, edges, "caller", "provider", "")
	if unnamed.CallCount != 1 || unnamed.AvgLatencyMs != 42 {
		t.Fatalf("unnamed row: count=%d avg=%v, want 1 / 42", unnamed.CallCount, unnamed.AvgLatencyMs)
	}
	named := statFor(t, edges, "caller", "provider", "named_tool")
	if named.CallCount != 1 || named.AvgLatencyMs != 8 {
		t.Fatalf("named row: count=%d avg=%v, want 1 / 8", named.CallCount, named.AvgLatencyMs)
	}
}

// TestEdgeStatsMissingAgentNameNeverEntersTheMap is the other half of that
// decision: a row with no source or no target names no edge at all. An empty
// FUNCTION is a partial observation; an empty AGENT is not an observation.
//
// Refused on the way IN, not filtered on the way out. A read-time filter left
// the key sitting in the map holding a slot under the key ceiling, so an
// undisplayable row could evict a real edge.
func TestEdgeStatsMissingAgentNameNeverEntersTheMap(t *testing.T) {
	ta := newTestAccumulator(t, 16)
	ta.mu.Lock()
	ta.recordEdge("", "provider", "tool", 5, nil)
	ta.recordEdge("caller", "", "tool", 5, nil)
	ta.recordEdge("", "", "tool", 5, nil)
	ta.recordEdge("caller", "provider", "tool", 5, nil)
	ta.mu.Unlock()

	if got := ta.EdgeStatCount(); got != 1 {
		t.Fatalf("edge map holds %d keys, want 1 — an unnamed edge is occupying a "+
			"slot under the key ceiling", got)
	}

	edges := ta.GetEdgeStats()
	if len(edges) != 1 {
		t.Fatalf("got %d rows, want 1: %+v", len(edges), edges)
	}
	if edges[0].Source != "caller" || edges[0].Target != "provider" {
		t.Fatalf("wrong row survived: %+v", edges[0])
	}
}

// TestEdgeStatsEvictionUnderTheFinerKey: the key ceiling still holds when the
// cardinality comes from FUNCTIONS rather than agent names. One pair calling
// thousands of distinct tools is the shape the finer key introduces, and it must
// be bounded the same way name churn is.
func TestEdgeStatsEvictionUnderTheFinerKey(t *testing.T) {
	const cap = 40
	ta := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0),
		AggregateBounds{Retention: 24 * time.Hour, MaxEntries: cap})

	const tools = 1000
	for i := 0; i < tools; i++ {
		feedCall(ta, fmt.Sprintf("t%04d", i), "caller", "provider", fmt.Sprintf("tool_%04d", i), 5, true)
		if got := ta.EdgeStatCount(); got > cap {
			t.Fatalf("after tool %d: edge keys = %d exceeds cap %d", i, got, cap)
		}
	}
	if got := ta.EdgeStatCount(); got == 0 {
		t.Fatal("edge map emptied entirely under function churn")
	}

	// The survivors are the most recently seen, so the newest tool is present
	// and the oldest is gone: eviction is least-recently-seen, not arbitrary.
	edges := ta.GetEdgeStats()
	seen := make(map[string]bool, len(edges))
	for _, e := range edges {
		seen[e.TargetFunction] = true
	}
	if !seen[fmt.Sprintf("tool_%04d", tools-1)] {
		t.Error("the most recent function was evicted")
	}
	if seen["tool_0000"] {
		t.Error("the oldest function survived a full cap turnover")
	}
}

// TestEdgeStatsAgePruneUnderTheFinerKey: one function of a pair going quiet ages
// out on its own while the pair's other function keeps reporting. Under the
// pair-level key there was nothing finer than the pair to age out.
func TestEdgeStatsAgePruneUnderTheFinerKey(t *testing.T) {
	ta := NewTraceAccumulatorWithBounds(16, log.New(io.Discard, "", 0),
		AggregateBounds{Retention: time.Hour, MaxEntries: 1000})

	feedCall(ta, "t1", "caller", "provider", "retired_tool", 5, true)
	feedCall(ta, "t2", "caller", "provider", "live_tool", 5, true)

	ta.mu.Lock()
	ta.edgeStats[edgeKey{Source: "caller", Target: "provider", Function: "retired_tool"}].
		LastSeen = time.Now().Add(-2 * time.Hour)
	ta.mu.Unlock()

	ta.pruneEdgeStats()

	edges := ta.GetEdgeStats()
	if len(edges) != 1 {
		t.Fatalf("got %d rows after prune, want 1: %+v", len(edges), edges)
	}
	if edges[0].TargetFunction != "live_tool" {
		t.Fatalf("survivor is %q, want live_tool", edges[0].TargetFunction)
	}
}

// TestEdgeStatsOrderIsTotal: rows are truncated to a limit by every caller, so
// equal-traffic rows — now the common case — must not swap places between polls.
func TestEdgeStatsOrderIsTotal(t *testing.T) {
	build := func(reversed bool) []EdgeStats {
		ta := newTestAccumulator(t, 64)
		names := []string{"alpha", "beta", "gamma", "delta", "epsilon"}
		for i := range names {
			j := i
			if reversed {
				j = len(names) - 1 - i
			}
			feedCall(ta, fmt.Sprintf("t%02d%v", i, reversed), "caller", "provider", names[j], 5, true)
		}
		return ta.GetEdgeStats()
	}

	forward, backward := build(false), build(true)
	if len(forward) != 5 || len(backward) != 5 {
		t.Fatalf("expected 5 rows each, got %d and %d", len(forward), len(backward))
	}
	for i := range forward {
		if forward[i].TargetFunction != backward[i].TargetFunction {
			t.Fatalf("row %d differs by insertion order: %q vs %q",
				i, forward[i].TargetFunction, backward[i].TargetFunction)
		}
	}
	// And that order is by name, since every row here has the same call count.
	want := []string{"alpha", "beta", "delta", "epsilon", "gamma"}
	for i, w := range want {
		if forward[i].TargetFunction != w {
			t.Fatalf("row %d = %q, want %q", i, forward[i].TargetFunction, w)
		}
	}
}

// TestEdgeStatsP99StaysWithinTheObservedMax: the percentile is a bucket estimate
// now, and GetEdgeStats clamps it. A dashboard reporting a P99 above a latency
// no call ever took would be reporting the bucket layout, not the mesh.
func TestEdgeStatsP99StaysWithinTheObservedMax(t *testing.T) {
	ta := newTestAccumulator(t, 256)
	for i := 0; i < 500; i++ {
		// Values just above an octave boundary, where the bucket's upper bound
		// sits furthest above anything actually observed.
		feedCall(ta, fmt.Sprintf("t%03d", i), "caller", "provider", "tool", 1025, true)
	}
	e := statFor(t, ta.GetEdgeStats(), "caller", "provider", "tool")
	if e.MaxLatencyMs != 1025 || e.MinLatencyMs != 1025 {
		t.Fatalf("min/max must stay exact: min=%d max=%d", e.MinLatencyMs, e.MaxLatencyMs)
	}
	if e.AvgLatencyMs != 1025 {
		t.Fatalf("avg must stay exact: %v", e.AvgLatencyMs)
	}
	if e.P99LatencyMs > float64(e.MaxLatencyMs) {
		t.Fatalf("P99 %v exceeds the observed max %d", e.P99LatencyMs, e.MaxLatencyMs)
	}
	if e.P99LatencyMs < float64(e.MinLatencyMs) {
		t.Fatalf("P99 %v is below the observed min %d", e.P99LatencyMs, e.MinLatencyMs)
	}
}
