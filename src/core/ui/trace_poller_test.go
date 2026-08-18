package ui

import (
	"fmt"
	"io"
	"log"
	"testing"
	"time"

	"mcp-mesh/src/core/registry/tracing"
)

// The streamed `edge_stats` event is the topology graph's ONLY source of
// traffic, and it is also what the dashboard's traffic widget reads. Those two
// want different things from one payload — a graph wants a row for every edge it
// draws, a widget wants a screenful — which is why the stream has a budget of
// its own rather than the tables' ceiling.

// TestEdgeStatsStreamBudgetIsNotTableSized pins the relationship rather than the
// number: whatever edgeStatsStreamLimit is set to, it has to be far above what a
// table asks for, or the graph is back to being served by a ranking that can
// starve it.
func TestEdgeStatsStreamBudgetIsNotTableSized(t *testing.T) {
	if edgeStatsStreamLimit <= trafficMaxLimit {
		t.Fatalf("edgeStatsStreamLimit = %d, which is within the tables' ceiling of %d — "+
			"the graph's feed is sized for a table again", edgeStatsStreamLimit, trafficMaxLimit)
	}
}

// TestEdgeStatsStreamBudgetCoversAMeshOfDrawnEdges builds the starvation case at
// the budget the poller actually publishes with: one pair exchanging more tools
// than a table budget would hold, plus many other pairs. Every pair has to reach
// the payload, because an edge with no row keeps its structural style and the
// loss is invisible on screen.
func TestEdgeStatsStreamBudgetCoversAMeshOfDrawnEdges(t *testing.T) {
	acc := tracing.NewTraceAccumulator(64, log.New(io.Discard, "", 0))

	seq := 0
	call := func(source, target, calleeOp string) {
		seq++
		id := fmt.Sprintf("t%05d", seq)
		root := fmt.Sprintf("r%05d", seq)
		for _, e := range makeCall(id, root, source, target, time.Now(), true) {
			if e.ParentSpan != nil {
				e.Operation = calleeOp
			}
			_ = acc.ProcessTraceEvent(e)
		}
	}

	// The chatty pair: 40 tools, each busier than anything else.
	for tool := 0; tool < 40; tool++ {
		for i := 0; i < 5; i++ {
			call("chatty-caller", "chatty-provider", fmt.Sprintf("tool_%02d", tool))
		}
	}
	// 60 quiet pairs with 2 tools each — 120 more rows, past any table budget.
	for p := 0; p < 60; p++ {
		for _, tool := range []string{"read", "write"} {
			call(fmt.Sprintf("caller-%02d", p), fmt.Sprintf("provider-%02d", p), tool)
		}
	}
	acc.FinalizeAllActive()

	published := tracing.SelectEdgeStats(acc.GetEdgeStats(), edgeStatsStreamLimit)

	pairs := make(map[string]int)
	for _, e := range published {
		pairs[e.Source+" -> "+e.Target]++
	}
	if got := len(pairs); got != 61 {
		t.Fatalf("published payload covers %d pairs, want all 61", got)
	}
	// And not merely present: every drawn edge of every pair has its own row, so
	// nothing on the graph is left guessing.
	if len(published) != 40+120 {
		t.Fatalf("published %d rows, want one per drawn edge (%d)", len(published), 40+120)
	}

	// Contrast: the table's ceiling could not have done this. It covers all 61
	// pairs — that is what fairness buys — but it cannot carry a row for each of
	// the 160 edges the graph draws, which is the difference between a budget
	// sized for depth in a table and one sized for a graph's coverage.
	tableSized := tracing.SelectEdgeStats(acc.GetEdgeStats(), trafficMaxLimit)
	if len(tableSized) != trafficMaxLimit {
		t.Fatalf("table-ceiling selection returned %d rows, want %d", len(tableSized), trafficMaxLimit)
	}
	if len(tableSized) >= len(published) {
		t.Fatalf("table ceiling (%d rows) is no smaller than the stream's payload (%d rows)",
			len(tableSized), len(published))
	}
}
