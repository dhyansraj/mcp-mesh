package ui

import (
	"strconv"
	"testing"
	"time"

	"mcp-mesh/src/core/registry/tracing"
)

// ptr helpers for the optional TraceEvent fields.
func i64(v int64) *int64 { return &v }
func boolp(v bool) *bool { return &v }

// makeCall builds the two spans of one cross-agent call (source -> target):
// a root span on `source` (no parent, has duration) and a child span on
// `target` whose parent is the root span. Both carry `ts` as their timestamp.
// success controls the child span outcome so we can exercise the error counters.
func makeCall(traceID, rootSpanID, source, target string, ts time.Time, success bool) []*tracing.TraceEvent {
	unix := float64(ts.UnixNano()) / 1e9
	childID := rootSpanID + "-child"
	return []*tracing.TraceEvent{
		{
			TraceID:    traceID,
			SpanID:     rootSpanID,
			AgentName:  source,
			Operation:  "root",
			EventType:  "span_end",
			Timestamp:  unix,
			DurationMS: i64(20),
			Success:    boolp(true),
		},
		{
			TraceID:    traceID,
			SpanID:     childID,
			ParentSpan: &rootSpanID,
			AgentName:  target,
			Operation:  "call",
			EventType:  "span_end",
			Timestamp:  unix,
			DurationMS: i64(10),
			Success:    boolp(success),
		},
	}
}

// TestReplayWindowExcludesOlderEvents feeds a set of trace events spanning >1h
// and asserts the 1h replay excludes the older call while the all-time replay
// includes both — proving the windowing narrows edge/agent counts and totals.
func TestReplayWindowExcludesOlderEvents(t *testing.T) {
	now := time.Now()

	// Old call (2h ago): agentA -> agentB, failed.
	old := makeCall("trace-old", "span-old", "agentA", "agentB", now.Add(-2*time.Hour), false)
	// Recent call (10m ago): agentA -> agentC, succeeded.
	recent := makeCall("trace-recent", "span-recent", "agentA", "agentC", now.Add(-10*time.Minute), true)

	all := append(append([]*tracing.TraceEvent{}, old...), recent...)

	// Simulate the XRANGE bound: the 1h window would only return entries newer
	// than (now - 1h), i.e. the recent call. Mirror that by slicing here — the
	// real handler gets this slice from RangeEventsSince.
	windowCutoff := now.Add(-time.Hour)
	var windowed []*tracing.TraceEvent
	for _, e := range all {
		if time.Unix(0, int64(e.Timestamp*1e9)).After(windowCutoff) {
			windowed = append(windowed, e)
		}
	}

	// --- all-time replay: both calls present ---
	edgesAll, agentsAll, _, callsAll, errsAll := replayWindow(all, 20)
	if callsAll != 2 {
		t.Fatalf("all-time total_calls = %d, want 2", callsAll)
	}
	if errsAll != 1 {
		t.Fatalf("all-time total_errors = %d, want 1", errsAll)
	}
	if len(edgesAll) != 2 {
		t.Fatalf("all-time edges = %d, want 2 (A->B, A->C)", len(edgesAll))
	}
	// agentA, agentB, agentC all appear.
	if len(agentsAll) != 3 {
		t.Fatalf("all-time agents = %d, want 3", len(agentsAll))
	}

	// --- 1h replay: only the recent (successful) call ---
	edges1h, agents1h, _, calls1h, errs1h := replayWindow(windowed, 20)
	if calls1h != 1 {
		t.Fatalf("1h total_calls = %d, want 1", calls1h)
	}
	if errs1h != 0 {
		t.Fatalf("1h total_errors = %d, want 0 (old failed call excluded)", errs1h)
	}
	if len(edges1h) != 1 {
		t.Fatalf("1h edges = %d, want 1 (A->C only)", len(edges1h))
	}
	if edges1h[0].Source != "agentA" || edges1h[0].Target != "agentC" {
		t.Fatalf("1h edge = %s->%s, want agentA->agentC", edges1h[0].Source, edges1h[0].Target)
	}
	// agentB (only in the old call) must be excluded from the window.
	for _, a := range agents1h {
		if a.AgentName == "agentB" {
			t.Fatalf("1h agents unexpectedly include agentB (from excluded old call)")
		}
	}
	if len(agents1h) != 2 {
		t.Fatalf("1h agents = %d, want 2 (agentA, agentC)", len(agents1h))
	}

	// The window must strictly narrow the aggregates.
	if calls1h >= callsAll || len(edges1h) >= len(edgesAll) || len(agents1h) >= len(agentsAll) {
		t.Fatalf("1h aggregate did not narrow vs all-time: calls %d/%d edges %d/%d agents %d/%d",
			calls1h, callsAll, len(edges1h), len(edgesAll), len(agents1h), len(agentsAll))
	}
}

// TestReplayWindowKeysEdgesPerFunction: the windowed (1h/1d) path re-aggregates
// through a throwaway TraceAccumulator fed by the same ProcessTraceEvent the
// live consumer uses, so it inherits the per-function edge key (#1531) with no
// windowing-specific code. Asserted rather than assumed — the two paths reading
// the same field is the whole reason the Traffic page can offer a time filter
// over the finer rows.
func TestReplayWindowKeysEdgesPerFunction(t *testing.T) {
	now := time.Now()
	var events []*tracing.TraceEvent

	withOp := func(traceID, rootID, source, target, calleeOp string) {
		spans := makeCall(traceID, rootID, source, target, now, true)
		spans[1].Operation = calleeOp
		events = append(events, spans...)
	}

	withOp("t1", "r1", "agentA", "agentB", "lookup")
	withOp("t2", "r2", "agentA", "agentB", "lookup")
	withOp("t3", "r3", "agentA", "agentB", "summarise")

	edges, _, _, _, _ := replayWindow(events, 20)
	if len(edges) != 2 {
		t.Fatalf("replayed edges = %d, want 2 (one per called function): %+v", len(edges), edges)
	}

	byFunction := make(map[string]tracing.EdgeStats, len(edges))
	for _, e := range edges {
		if e.Source != "agentA" || e.Target != "agentB" {
			t.Fatalf("unexpected pair %s -> %s", e.Source, e.Target)
		}
		byFunction[e.TargetFunction] = e
	}
	if got := byFunction["lookup"].CallCount; got != 2 {
		t.Fatalf("lookup call count = %d, want 2", got)
	}
	if got := byFunction["summarise"].CallCount; got != 1 {
		t.Fatalf("summarise call count = %d, want 1", got)
	}
}

// TestReplayWindowTruncatesFairlyAcrossPairs: the windowed path truncates too,
// and it must starve the same way the live path does — which is to say, not by
// dropping whole pairs. Same shape as the accumulator's own starvation test: one
// chatty pair with more tools than the budget, plus quiet pairs.
func TestReplayWindowTruncatesFairlyAcrossPairs(t *testing.T) {
	now := time.Now()
	var events []*tracing.TraceEvent
	seq := 0

	call := func(source, target, calleeOp string) {
		seq++
		id := "t" + strconv.Itoa(seq)
		spans := makeCall(id, "r"+strconv.Itoa(seq), source, target, now, true)
		spans[1].Operation = calleeOp
		events = append(events, spans...)
	}

	const budget = 5
	for tool := 0; tool < budget*2; tool++ {
		for i := 0; i < 10; i++ {
			call("chatty-caller", "chatty-provider", "tool_"+strconv.Itoa(tool))
		}
	}
	quiet := [][2]string{{"web", "auth"}, {"worker", "storage"}, {"api", "web"}}
	for _, p := range quiet {
		call(p[0], p[1], "handle")
	}

	edges, _, _, _, _ := replayWindow(events, budget)
	if len(edges) != budget {
		t.Fatalf("replayed %d rows, want the full budget of %d", len(edges), budget)
	}

	pairs := make(map[string]bool, len(edges))
	for _, e := range edges {
		pairs[e.Source+" -> "+e.Target] = true
	}
	for _, p := range quiet {
		if !pairs[p[0]+" -> "+p[1]] {
			t.Errorf("windowed payload starved out %s -> %s", p[0], p[1])
		}
	}
	if !pairs["chatty-caller -> chatty-provider"] {
		t.Error("windowed payload dropped the busiest pair")
	}
}

// TestTrafficBudgetCarriesARoutesFunctions is the server half of a defect whose
// other half is in the SPA: fair-across-pairs truncation spends its first `pairs`
// slots on ONE ROW EACH, so a budget at or below the pair count returns exactly
// one row per pair — coverage without depth. Against a live mesh of 42 pairs the
// Traffic page's old budget of 20 produced 40 rows over 40 routes with not one
// route showing a second function, which is the page's entire purpose since
// #1531.
//
// So the budget the page asks for (trafficMaxLimit) has to be large enough that
// a route's several functions survive the truncation, and this pins that against
// the measured shape rather than against a number someone hopes is comfortable.
func TestTrafficBudgetCarriesARoutesFunctions(t *testing.T) {
	now := time.Now()
	var events []*tracing.TraceEvent
	seq := 0

	call := func(source, target, calleeOp string) {
		seq++
		id := "t" + strconv.Itoa(seq)
		spans := makeCall(id, "r"+strconv.Itoa(seq), source, target, now, true)
		spans[1].Operation = calleeOp
		events = append(events, spans...)
	}

	// The measured mesh: 42 pairs, 19 of them multi-function, the busiest with 8.
	const (
		pairCount            = 42
		multiFunctionPairs   = 19
		busiestPairFunctions = 8
	)
	functionsOn := func(pair int) int {
		if pair == 0 {
			return busiestPairFunctions
		}
		if pair < multiFunctionPairs {
			return 2
		}
		return 1
	}
	totalRows := 0
	for p := 0; p < pairCount; p++ {
		id := strconv.Itoa(p)
		for fn := 0; fn < functionsOn(p); fn++ {
			totalRows++
			call("caller-"+id, "provider-"+id, "tool_"+id+"_"+strconv.Itoa(fn))
		}
	}
	if totalRows <= pairCount {
		t.Fatalf("fixture has %d rows over %d pairs and cannot show the defect", totalRows, pairCount)
	}

	countRows := func(edges []tracing.EdgeStats) (pairs int, deepest int) {
		perPair := make(map[string]int, len(edges))
		for _, e := range edges {
			perPair[e.Source+" -> "+e.Target]++
		}
		for _, n := range perPair {
			if n > deepest {
				deepest = n
			}
		}
		return len(perPair), deepest
	}

	// The budget the page asks for: every row survives, so the busiest route
	// arrives with all 8 of its functions.
	atCap, _, _, _, _ := replayWindow(events, trafficMaxLimit)
	pairs, deepest := countRows(atCap)
	if pairs != pairCount {
		t.Fatalf("at the page's budget the payload covers %d pairs, want %d", pairs, pairCount)
	}
	if deepest != busiestPairFunctions {
		t.Fatalf("at the page's budget the busiest route shows %d functions, want %d — "+
			"the Traffic page is back to one row per route", deepest, busiestPairFunctions)
	}
	if len(atCap) != totalRows {
		t.Fatalf("at the page's budget the payload has %d rows, want all %d", len(atCap), totalRows)
	}

	// The contrast, and the failure as it was measured: the endpoint DEFAULT is
	// at or below this pair count, so it flattens the same data to one row each.
	// This is not a bug in the default — it is why the page must not take it.
	if trafficDefaultLimit > pairCount {
		t.Skipf("trafficDefaultLimit (%d) now exceeds the measured pair count (%d); "+
			"the flattening contrast no longer applies", trafficDefaultLimit, pairCount)
	}
	atDefault, _, _, _, _ := replayWindow(events, trafficDefaultLimit)
	if _, deepestAtDefault := countRows(atDefault); deepestAtDefault != 1 {
		t.Fatalf("at the endpoint default the deepest route shows %d functions, want 1 — "+
			"fair selection no longer spends its first pass one row per pair, so the "+
			"reasoning behind the page's budget needs revisiting", deepestAtDefault)
	}
	if trafficMaxLimit <= pairCount {
		t.Fatalf("trafficMaxLimit (%d) is at or below a realistic pair count (%d), so the "+
			"page's budget buys it exactly one row per route", trafficMaxLimit, pairCount)
	}
}

// TestParseWindow covers the accepted values and rejection of unknown windows.
func TestParseWindow(t *testing.T) {
	cases := []struct {
		in      string
		wantDur time.Duration
		wantAll bool
		wantOK  bool
	}{
		{"", 0, true, true},
		{"all", 0, true, true},
		{"1h", time.Hour, false, true},
		{"1d", 24 * time.Hour, false, true},
		{"5m", 0, false, false},
		{"garbage", 0, false, false},
	}
	for _, tc := range cases {
		dur, isAll, ok := parseWindow(tc.in)
		if dur != tc.wantDur || isAll != tc.wantAll || ok != tc.wantOK {
			t.Errorf("parseWindow(%q) = (%v,%v,%v), want (%v,%v,%v)",
				tc.in, dur, isAll, ok, tc.wantDur, tc.wantAll, tc.wantOK)
		}
	}
}
