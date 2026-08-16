package tracing

import (
	"fmt"
	"testing"
)

// The row budget on the edge-stat endpoints was a PER-PAIR budget when a row
// meant an agent pair. Per-function rows (#1531) turned it into a per-function
// budget, and a plain head-truncation of a call-count ranking then lets one busy
// pair take every slot. SelectEdgeStats is what stops that.

// pairsIn returns the distinct "source -> target" pairs present in a row set.
func pairsIn(edges []EdgeStats) map[string]int {
	pairs := make(map[string]int)
	for _, e := range edges {
		pairs[e.Source+" -> "+e.Target]++
	}
	return pairs
}

// TestSelectEdgeStatsDoesNotStarveOtherPairs is the failure the change exists to
// prevent, built as the reviewer described it: one chatty pair with more tools
// than the entire budget, plus a handful of ordinary pairs. Under a head
// truncation the chatty pair takes all 20 slots and every other pair disappears
// from the payload — and because the topology graph leaves an unmatched edge in
// its structural style, it disappears SILENTLY.
func TestSelectEdgeStatsDoesNotStarveOtherPairs(t *testing.T) {
	ta := newTestAccumulator(t, 512)

	// One pair exchanging 25 tools, each busier than anything else in the mesh.
	const chattyTools = 25
	for tool := 0; tool < chattyTools; tool++ {
		for call := 0; call < 50; call++ {
			feedCall(ta, fmt.Sprintf("chat-%02d-%03d", tool, call),
				"chatty-caller", "chatty-provider", fmt.Sprintf("tool_%02d", tool), 5, true)
		}
	}

	// Six ordinary pairs, one call each — the quiet majority of a real mesh.
	quiet := []struct{ src, dst string }{
		{"web", "auth"},
		{"web", "billing"},
		{"worker", "storage"},
		{"worker", "search"},
		{"scheduler", "worker"},
		{"api", "web"},
	}
	for i, p := range quiet {
		feedCall(ta, fmt.Sprintf("quiet-%d", i), p.src, p.dst, "handle", 5, true)
	}

	all := ta.GetEdgeStats()
	if got := len(all); got != chattyTools+len(quiet) {
		t.Fatalf("accumulator holds %d rows, want %d", got, chattyTools+len(quiet))
	}

	// The old behaviour, spelled out so the contrast is in the test rather than
	// only in the commit message.
	head := all[:20]
	if got := len(pairsIn(head)); got != 1 {
		t.Fatalf("precondition failed: a head truncation should show only the chatty "+
			"pair, showed %d pairs", got)
	}

	selected := SelectEdgeStats(all, 20)
	if got := len(selected); got != 20 {
		t.Fatalf("selected %d rows, want the full budget of 20", got)
	}

	pairs := pairsIn(selected)
	for _, p := range quiet {
		if pairs[p.src+" -> "+p.dst] == 0 {
			t.Errorf("pair %s -> %s was starved out of the payload entirely", p.src, p.dst)
		}
	}
	if pairs["chatty-caller -> chatty-provider"] == 0 {
		t.Error("the busiest pair lost its row, which is the opposite failure")
	}
	if got := len(pairs); got != 1+len(quiet) {
		t.Fatalf("payload covers %d pairs, want all %d", got, 1+len(quiet))
	}
}

// TestSelectEdgeStatsKeepsEachPairsBusiestFunction: the one row a starved pair
// keeps must be the row worth keeping.
func TestSelectEdgeStatsKeepsEachPairsBusiestFunction(t *testing.T) {
	ta := newTestAccumulator(t, 256)

	for _, pair := range []string{"a", "b", "c"} {
		for tool, calls := range map[string]int{"quiet_tool": 1, "busy_tool": 40, "middling_tool": 10} {
			for i := 0; i < calls; i++ {
				feedCall(ta, fmt.Sprintf("%s-%s-%03d", pair, tool, i),
					pair+"-caller", pair+"-provider", tool, 5, true)
			}
		}
	}

	selected := SelectEdgeStats(ta.GetEdgeStats(), 3)
	if len(selected) != 3 {
		t.Fatalf("selected %d rows, want 3", len(selected))
	}
	for _, e := range selected {
		if e.TargetFunction != "busy_tool" {
			t.Errorf("%s -> %s kept %q, want its busiest function", e.Source, e.Target, e.TargetFunction)
		}
	}
	if got := len(pairsIn(selected)); got != 3 {
		t.Fatalf("selection covers %d pairs, want 3", got)
	}
}

// TestSelectEdgeStatsIsDeterministic: the selection is polled every 5s, so the
// same unchanged mesh must produce the same rows every time, whatever order the
// map iteration handed them over in.
func TestSelectEdgeStatsIsDeterministic(t *testing.T) {
	build := func(reversed bool) []EdgeStats {
		ta := newTestAccumulator(t, 512)
		pairs := []string{"alpha", "beta", "gamma", "delta"}
		tools := []string{"one", "two", "three", "four", "five"}
		for pi := range pairs {
			for ti := range tools {
				p, tl := pi, ti
				if reversed {
					p, tl = len(pairs)-1-pi, len(tools)-1-ti
				}
				for i := 0; i < 3; i++ {
					feedCall(ta, fmt.Sprintf("t-%v-%d-%d-%d", reversed, p, tl, i),
						pairs[p]+"-caller", pairs[p]+"-provider", tools[tl], 5, true)
				}
			}
		}
		return SelectEdgeStats(ta.GetEdgeStats(), 9)
	}

	forward, backward := build(false), build(true)
	if len(forward) != 9 || len(backward) != 9 {
		t.Fatalf("selected %d and %d rows, want 9 each", len(forward), len(backward))
	}
	for i := range forward {
		if forward[i] != backward[i] {
			t.Fatalf("row %d differs by insertion order: %+v vs %+v", i, forward[i], backward[i])
		}
	}
}

// TestSelectEdgeStatsBudgetSmallerThanPairCount: when even one row per pair does
// not fit, the pairs served are the busiest ones — the old ranking, at the point
// where the old ranking was still the reasonable answer.
func TestSelectEdgeStatsBudgetSmallerThanPairCount(t *testing.T) {
	edges := []EdgeStats{
		{Source: "a", Target: "z", TargetFunction: "one", CallCount: 100},
		{Source: "a", Target: "z", TargetFunction: "two", CallCount: 90},
		{Source: "b", Target: "z", TargetFunction: "one", CallCount: 80},
		{Source: "c", Target: "z", TargetFunction: "one", CallCount: 70},
		{Source: "d", Target: "z", TargetFunction: "one", CallCount: 60},
	}
	SortEdgeStats(edges)

	selected := SelectEdgeStats(edges, 2)
	if len(selected) != 2 {
		t.Fatalf("selected %d rows, want 2", len(selected))
	}
	pairs := pairsIn(selected)
	if pairs["a -> z"] != 1 || pairs["b -> z"] != 1 {
		t.Fatalf("want one row each for the two busiest pairs, got %v", pairs)
	}
}

// TestSelectEdgeStatsNoLimitAndUnderBudget: the identity cases, including the
// limit <= 0 that means "everything" throughout this package.
func TestSelectEdgeStatsNoLimitAndUnderBudget(t *testing.T) {
	edges := []EdgeStats{
		{Source: "a", Target: "b", TargetFunction: "x", CallCount: 2},
		{Source: "a", Target: "b", TargetFunction: "y", CallCount: 1},
	}
	if got := SelectEdgeStats(edges, 0); len(got) != 2 {
		t.Fatalf("limit 0 returned %d rows, want all 2", len(got))
	}
	if got := SelectEdgeStats(edges, -1); len(got) != 2 {
		t.Fatalf("limit -1 returned %d rows, want all 2", len(got))
	}
	if got := SelectEdgeStats(edges, 5); len(got) != 2 {
		t.Fatalf("over-budget limit returned %d rows, want all 2", len(got))
	}
	if got := SelectEdgeStats(nil, 5); len(got) != 0 {
		t.Fatalf("nil returned %d rows", len(got))
	}
}

// TestSelectEdgeStatsOutputStaysSorted: callers render the result directly, so
// the selection must not leave rows in round-robin order.
func TestSelectEdgeStatsOutputStaysSorted(t *testing.T) {
	edges := []EdgeStats{
		{Source: "a", Target: "z", TargetFunction: "one", CallCount: 100},
		{Source: "b", Target: "z", TargetFunction: "one", CallCount: 90},
		{Source: "a", Target: "z", TargetFunction: "two", CallCount: 80},
		{Source: "b", Target: "z", TargetFunction: "two", CallCount: 70},
	}
	SortEdgeStats(edges)

	selected := SelectEdgeStats(edges, 3)
	for i := 1; i < len(selected); i++ {
		if selected[i-1].CallCount < selected[i].CallCount {
			t.Fatalf("row %d (%d calls) precedes a busier row (%d calls)",
				i-1, selected[i-1].CallCount, selected[i].CallCount)
		}
	}
}
