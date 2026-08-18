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
// only getting one.
//
// PAIR ORDER IS BY THE PAIR'S TOTAL, summed over all its functions, which
// decides who is served when the budget is smaller than the number of pairs.
// That total is what the old pair-level row reported, so this degrades into the
// old ranking at the point where the old ranking was still the reasonable
// answer. Ranking pairs by their busiest SINGLE function instead — which is
// what their first appearance in the call-count-sorted input gives — would put
// a pair with one 1,000-call tool ahead of a pair with ten 500-call ones, and
// the old payload ranked the second pair five times higher.
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
	type pairRows struct {
		key   pair
		total int
		// rows in input order, i.e. busiest function first (SortEdgeStats).
		rows []EdgeStats
	}
	byPair := make(map[pair]*pairRows, limit)
	order := make([]*pairRows, 0, limit)
	for _, e := range edges {
		p := pair{e.Source, e.Target}
		pr, seen := byPair[p]
		if !seen {
			pr = &pairRows{key: p}
			byPair[p] = pr
			order = append(order, pr)
		}
		pr.total += e.CallCount
		pr.rows = append(pr.rows, e)
	}

	// Busiest pair first, then a total order on the pair, so the selection is a
	// pure function of the input rather than of map iteration order.
	sort.Slice(order, func(i, j int) bool {
		if order[i].total != order[j].total {
			return order[i].total > order[j].total
		}
		if order[i].key.source != order[j].key.source {
			return order[i].key.source < order[j].key.source
		}
		return order[i].key.target < order[j].key.target
	})

	kept := make([]EdgeStats, 0, limit)
	for rank := 0; len(kept) < limit; rank++ {
		progressed := false
		for _, pr := range order {
			if rank >= len(pr.rows) {
				continue
			}
			progressed = true
			kept = append(kept, pr.rows[rank])
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
