package tracing

import (
	"log"
	"os"
	"sort"
	"strconv"
	"time"
)

// Bounds for the in-memory telemetry AGGREGATE maps that sit on top of the
// trace stream: TraceAccumulator.edgeStats and the UI MetricsProcessor's
// per-agent / per-model maps. The stream itself is bounded by
// MCP_MESH_TRACE_RETENTION; these maps are keyed by agent / model / edge name
// and, before #1424, were written on every event and never pruned.
//
// Cardinality here is names, not volume, so the primary bound is AGE: a key
// that has not been written to within the retention window has stopped
// reporting and ages out. MaxEntries is a hard ceiling for the pathological
// case (name churn faster than the retention window can absorb); it evicts
// least-recently-seen first, so it only ever degrades into LRU once age
// pruning has already failed to keep up.
//
// WHAT THE CEILING COSTS. MaxEntries is a key count, so the memory it admits
// depends on the map. The expensive one is the edge map, whose value carries a
// fixed-size latency histogram: 1,992 bytes per edgeAccum plus a 48-byte
// edgeKey, the agent and function names it retains, and the map's own overhead
// — call it ~2.1 KB an entry. At the 10,000 default that is a steady-state
// ceiling of roughly 20 MB for the edge map, reached only by a mesh with that
// many live (caller, provider, function) triples; the per-agent and per-model
// maps hold counters only and are negligible beside it. An operator raising
// MaxEntries is buying edge rows at ~2.1 KB each.
//
// The default is NOT lowered to compensate for per-function edge keys (#1531)
// multiplying the row count: 20 MB is a fair ceiling for a process whose job is
// telemetry, and lowering it would silently start evicting live edges in meshes
// that fit today. If it should move, it should move on its own evidence.
const (
	defaultAggregateRetention  = 24 * time.Hour
	defaultAggregateMaxEntries = 10000

	// AggregatePruneInterval is how often age pruning runs. The accumulator
	// piggybacks its existing 10s cleanup loop; the MetricsProcessor gates its
	// inline prune on the same interval so both maps age out at the same rate.
	AggregatePruneInterval = 10 * time.Second
)

// AggregateBounds bounds a telemetry aggregate map.
//
// Retention is the age-out window for a key that has stopped being written to
// (0 disables age pruning). MaxEntries is the hard per-map key ceiling
// (0 disables the ceiling). Both are set from the environment by
// LoadAggregateBoundsFromEnv; tests inject values directly.
type AggregateBounds struct {
	Retention  time.Duration
	MaxEntries int
}

// defaultAggregateBounds is read once at package init, mirroring the
// sweepInterval convention in the registry package: the env read has to happen
// before any structured logger exists, and the value cannot change at runtime.
var defaultAggregateBounds = LoadAggregateBoundsFromEnv()

// DefaultAggregateBounds returns the process-wide aggregate bounds derived
// from the environment at init time. Both the registry and meshui construct
// their aggregate maps from this.
func DefaultAggregateBounds() AggregateBounds {
	return defaultAggregateBounds
}

// LoadAggregateBoundsFromEnv reads the aggregate bounds from the environment.
//
// MCP_MESH_TELEMETRY_AGGREGATE_RETENTION (Go duration):
//   - unset / empty: 24h
//   - positive: use it
//   - "0" / "0s": age pruning disabled — logged as a removed bound
//   - negative / unparseable: warn and fall back to the default
//
// MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES (integer):
//   - unset / empty: 10000
//   - positive: use it
//   - "0": key ceiling disabled — logged as a removed bound
//   - negative / unparseable: warn and fall back to the default
//
// See the bounds comment above for what a key costs before changing this: an
// edge entry is ~2.1 KB, so the default admits ~20 MB of edge aggregates.
//
// Uses the stdlib log package because it runs at package init, before any
// manager (and therefore any manager logger) exists.
func LoadAggregateBoundsFromEnv() AggregateBounds {
	b := AggregateBounds{
		Retention:  defaultAggregateRetention,
		MaxEntries: defaultAggregateMaxEntries,
	}

	if raw := os.Getenv("MCP_MESH_TELEMETRY_AGGREGATE_RETENTION"); raw != "" {
		d, err := time.ParseDuration(raw)
		switch {
		case err != nil:
			log.Printf("[TRACE-AGGREGATES] Invalid MCP_MESH_TELEMETRY_AGGREGATE_RETENTION %q, using default %s: %v",
				raw, defaultAggregateRetention, err)
		case d < 0:
			log.Printf("[TRACE-AGGREGATES] Invalid MCP_MESH_TELEMETRY_AGGREGATE_RETENTION %q: negative durations are not allowed (use 0 to disable); using default %s",
				raw, defaultAggregateRetention)
		case d == 0:
			log.Printf("[TRACE-AGGREGATES] MCP_MESH_TELEMETRY_AGGREGATE_RETENTION=0: per-agent/model/edge aggregates will NOT age out; only the MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES ceiling bounds them")
			b.Retention = 0
		default:
			b.Retention = d
		}
	}

	if raw := os.Getenv("MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES"); raw != "" {
		n, err := strconv.Atoi(raw)
		switch {
		case err != nil:
			log.Printf("[TRACE-AGGREGATES] Invalid MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES %q, using default %d: %v",
				raw, defaultAggregateMaxEntries, err)
		case n < 0:
			log.Printf("[TRACE-AGGREGATES] Invalid MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES %q: negative values are not allowed (use 0 to disable); using default %d",
				raw, defaultAggregateMaxEntries)
		case n == 0:
			log.Printf("[TRACE-AGGREGATES] MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES=0: per-agent/model/edge aggregate maps have NO key ceiling; only MCP_MESH_TELEMETRY_AGGREGATE_RETENTION bounds them")
			b.MaxEntries = 0
		default:
			b.MaxEntries = n
		}
	}

	if b.Retention == 0 && b.MaxEntries == 0 {
		log.Printf("[TRACE-AGGREGATES] WARNING: both MCP_MESH_TELEMETRY_AGGREGATE_RETENTION and MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES are 0 — in-memory telemetry aggregates are UNBOUNDED and will grow with agent/model name cardinality")
	}

	return b
}

// PruneOlderThan removes every entry from m whose lastSeen timestamp is before
// cutoff, returning the number removed. No-op on a nil/empty map.
//
// Exported so the UI package's MetricsProcessor can share the accumulator's
// pruning semantics rather than reimplementing them.
//
// The key is any comparable type: agent and model aggregates are keyed by name,
// edge stats by a (source, target, function) struct (#1531).
func PruneOlderThan[K comparable, V any](m map[K]V, lastSeen func(V) time.Time, cutoff time.Time) int {
	removed := 0
	for k, v := range m {
		if lastSeen(v).Before(cutoff) {
			delete(m, k)
			removed++
		}
	}
	return removed
}

// KeyLess orders two map keys. It is only ever consulted to break a tie between
// entries sharing a lastSeen timestamp, so it needs to be deterministic, not
// meaningful. StringKeyLess covers the name-keyed maps; a struct-keyed map
// supplies its own (see edgeKeyLess).
type KeyLess[K comparable] func(a, b K) bool

// StringKeyLess is the KeyLess for name-keyed aggregate maps.
func StringKeyLess(a, b string) bool { return a < b }

// EnforceMaxEntries drops the least-recently-seen entries when m exceeds max,
// returning the number evicted. max <= 0 disables the ceiling.
//
// Eviction is batched: once the cap is breached we drop down to ~90% of it
// (always at least one entry) so the O(n log n) sort is amortised over many
// subsequent inserts instead of being paid on every insert past the cap. The
// post-condition callers rely on is len(m) <= max.
func EnforceMaxEntries[K comparable, V any](m map[K]V, lastSeen func(V) time.Time, max int, keyLess KeyLess[K]) int {
	if max <= 0 || len(m) <= max {
		return 0
	}

	target := max - max/10
	if target >= max {
		// max < 10, so the 10% batch rounded to zero. Evict one entry so the
		// call always makes progress.
		target = max - 1
	}
	if target < 1 {
		// Never empty the map: with max == 1 the newest entry must survive.
		target = 1
	}

	type entry struct {
		key  K
		seen time.Time
	}
	entries := make([]entry, 0, len(m))
	for k, v := range m {
		entries = append(entries, entry{key: k, seen: lastSeen(v)})
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].seen.Equal(entries[j].seen) {
			// Stable tiebreak so eviction is deterministic when many keys
			// share a timestamp (common in tests and in bursty churn).
			return keyLess(entries[i].key, entries[j].key)
		}
		return entries[i].seen.Before(entries[j].seen)
	})

	evict := len(m) - target
	for i := 0; i < evict && i < len(entries); i++ {
		delete(m, entries[i].key)
	}
	return evict
}
