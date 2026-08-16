package tracing

import "sort"

// SortEdgeStats orders a computed edge-stat list: busiest first, then a total
// order on the key.
//
// The tiebreak is not decoration. Callers TRUNCATE this list to a limit, and one
// row per (source, target, function) makes equal call counts the common case
// rather than a rarity — without a deterministic order the same unchanged mesh
// would drop a different row from the bottom of the dashboard on every 5s poll.
func SortEdgeStats(edges []EdgeStats) {
	sort.Slice(edges, func(i, j int) bool {
		if edges[i].CallCount != edges[j].CallCount {
			return edges[i].CallCount > edges[j].CallCount
		}
		if edges[i].Source != edges[j].Source {
			return edges[i].Source < edges[j].Source
		}
		if edges[i].Target != edges[j].Target {
			return edges[i].Target < edges[j].Target
		}
		return edges[i].TargetFunction < edges[j].TargetFunction
	})
}

// SelectEdgeStats truncates a SortEdgeStats-ordered list to at most `limit`
// rows, choosing them FAIRLY ACROSS AGENT PAIRS rather than taking the head.
// limit <= 0 means no limit.
//
// WHY NOT THE HEAD. The row limits on these endpoints were chosen when one row
// meant one agent pair, so taking the busiest `limit` rows dropped the quietest
// PAIRS — a proportionate thing to do. Since #1531 a row is one (caller,
// provider, function), so a single pair exchanging 25 tools can occupy every
// slot on its own and every other pair falls out of the payload entirely. The
// topology graph reads the same payload and leaves an unmatched edge in its
// structural style, so the failure is silent: most of the mesh simply stops
// reporting traffic, with no error and no empty state.
//
// WHAT FAIR MEANS HERE. One pass per rank: every pair contributes its busiest
// remaining function, then every pair its second-busiest, and so on until the
// budget runs out. So a pair is only starved once EVERY pair has a row, and the
// row a pair keeps is its busiest — the number a reader would want if they are
// only getting one. Pairs are visited in the order they first appear in the
// sorted input, so when the budget is smaller than the number of pairs the
// busiest pairs are the ones served, which is the old behaviour at the point
// where the old behaviour was still reasonable.
//
// This bounds the damage; it does not remove it. A consumer that needs a row for
// every edge it draws needs a budget large enough for them — see
// edgeStatsStreamLimit in the ui package, which is why the graph's feed and the
// tables' feed no longer share one number.
func SelectEdgeStats(edges []EdgeStats, limit int) []EdgeStats {
	if limit <= 0 || len(edges) <= limit {
		return edges
	}

	type pair struct{ source, target string }
	byPair := make(map[pair][]EdgeStats, limit)
	// Pair visit order = first appearance in the sorted input, which is a total
	// order, so the selection is a pure function of the input.
	order := make([]pair, 0, limit)
	for _, e := range edges {
		p := pair{e.Source, e.Target}
		if _, seen := byPair[p]; !seen {
			order = append(order, p)
		}
		byPair[p] = append(byPair[p], e)
	}

	kept := make([]EdgeStats, 0, limit)
	for rank := 0; len(kept) < limit; rank++ {
		progressed := false
		for _, p := range order {
			rows := byPair[p]
			if rank >= len(rows) {
				continue
			}
			progressed = true
			kept = append(kept, rows[rank])
			if len(kept) == limit {
				break
			}
		}
		if !progressed {
			// Every pair is exhausted, which cannot happen while len(edges) >
			// limit, but a loop with no unconditional exit does not get to
			// depend on that.
			break
		}
	}

	SortEdgeStats(kept)
	return kept
}
