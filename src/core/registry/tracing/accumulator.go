package tracing

import (
	"log"
	"math"
	"sort"
	"sync"
	"time"
)

// TraceSnapshot is a complete trace state sent to live SSE clients
type TraceSnapshot struct {
	TraceID       string         `json:"trace_id"`
	RootAgent     string         `json:"root_agent,omitempty"`
	RootOperation string         `json:"root_operation,omitempty"`
	StartTime     time.Time      `json:"start_time"`
	Completed     bool           `json:"completed"`
	DurationMs    *int64         `json:"duration_ms,omitempty"`
	HasError      bool           `json:"has_error"`
	SpanCount     int            `json:"span_count"`
	Agents        []string       `json:"agents"`
	Spans         []SnapshotSpan `json:"spans"`
}

// SnapshotSpan is a flattened span with effective parent resolution
type SnapshotSpan struct {
	SpanID          string `json:"span_id"`
	EffectiveParent string `json:"effective_parent,omitempty"`
	AgentName       string `json:"agent_name"`
	Operation       string `json:"operation"`
	DurationMs      *int64 `json:"duration_ms,omitempty"`
	Success         *bool  `json:"success,omitempty"`
	Runtime         string `json:"runtime,omitempty"`
}

// LiveTraceEvent is sent to live SSE subscribers
type LiveTraceEvent struct {
	EventType string         `json:"event_type"` // trace_started, trace_update, trace_completed
	Snapshot  *TraceSnapshot `json:"snapshot"`
}

// TraceAccumulator accumulates trace data in-memory as spans stream through
// the Redis consumer. It replaces the Tempo-polling approach for recent traces,
// edge stats, and agent activity.
type TraceAccumulator struct {
	mu sync.RWMutex

	// Recent completed traces (ring buffer)
	recentTraces []RecentTraceSummary
	ringHead     int
	ringSize     int
	ringCount    int // how many entries have been written (up to ringSize)

	// Active (in-progress) traces keyed by trace ID
	activeTraces map[string]*activeTrace

	// Per-edge stats keyed by (source, target, function) — see edgeKey.
	// Bounded by edgeBounds: each entry carries a LastSeen stamp so idle edges
	// age out, and the number of keys is capped as a backstop against name
	// churn (#1424).
	edgeStats  map[edgeKey]*edgeAccum
	edgeBounds AggregateBounds

	// Total number of finalized traces (never resets)
	totalFinalized int

	// Total number of finalized traces that had errors (never resets)
	totalErrors int

	// Live subscribers for SSE streaming
	liveMu      sync.RWMutex
	liveClients map[chan *LiveTraceEvent]struct{}

	// Dirty traces needing debounced update publish
	dirtyTraces map[string]bool

	logger *log.Logger
	cancel chan struct{}
	wg     sync.WaitGroup
}

type activeTrace struct {
	TraceID   string
	Spans     []*TraceEvent
	SpanAgent map[string]string // spanID -> agentName for edge detection
	RootAgent string
	RootOp    string
	RootSpan  *TraceEvent // root span event (for deferred finalization)
	StartTime time.Time
	LastSeen  time.Time
	RootSeen  *time.Time // when root span arrived (nil = not yet seen)
	Agents    map[string]bool
	HasError  bool
}

// edgeKey identifies one traffic row: the calls from Source into Target that
// landed on one particular function of Target.
//
// A STRUCT, not a delimited string (#1531). The previous key was
// `source + " -> " + target`, which the read side had to take apart again by
// scanning for the first " -> " — a parse that is wrong for any agent name
// containing that sequence, and that would only get more fragile with a third
// field appended. Nothing here needs a parse: the map key already holds the
// three values separately.
type edgeKey struct {
	Source string
	Target string
	// Function is the CALLEE's span operation, i.e. the provider's own function
	// name — the caller's proxy span is not what edges are attributed from. For
	// an MCP tool it is character-for-character the `function_name` the registry
	// stores for that capability (Python `func.__name__`, TypeScript `def.name`,
	// Java `method.getName()`; no normalisation on either path), which is what
	// lets the UI join a stat to the exact topology edge that produced it.
	//
	// EMPTY when the span carried no operation. A span with no operation can
	// only come from a malformed event — every runtime names its span after the
	// function it is running — and it is recorded rather than dropped so the
	// call still counts towards the traffic totals. It simply joins to no
	// topology edge, which is the honest outcome: the call happened, but nothing
	// in the payload says what was called.
	Function string
}

type edgeAccum struct {
	CallCount  int
	ErrorCount int
	// Latency percentiles come from a fixed-bucket histogram rather than a
	// reservoir of raw samples, so per-key memory no longer scales with
	// traffic — a flat ~2 KB per key instead of anywhere from nothing to 80 KB.
	// The floor is therefore HIGHER than the reservoir's for a key that saw one
	// call, which is the trade: bounded and predictable rather than cheap until
	// it is not, on a key that is now per function and so far more numerous.
	//
	// The histogram holds a ROLLING WINDOW of recent samples, as the reservoir
	// did; Total/Max/Min are exact and lifetime, as they were. See
	// latency_histogram.go.
	//
	// The aggregate of this per-key cost is what bounds the map, not this
	// number: see the ceiling arithmetic on AggregateBounds in aggregates.go,
	// which is where an operator tuning
	// MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES ends up.
	Latency  latencyHistogram
	TotalMs  int64
	MaxMs    int64
	MinMs    int64
	LastSeen time.Time // last observation, drives age-based pruning
}

// NewTraceAccumulator creates a new accumulator with the given ring buffer
// size and the process-wide aggregate bounds (see DefaultAggregateBounds).
func NewTraceAccumulator(ringSize int, logger *log.Logger) *TraceAccumulator {
	return NewTraceAccumulatorWithBounds(ringSize, logger, DefaultAggregateBounds())
}

// NewTraceAccumulatorWithBounds is NewTraceAccumulator with explicit edge-stat
// bounds. Production callers should use NewTraceAccumulator so the operator's
// env configuration applies; this exists for tests.
func NewTraceAccumulatorWithBounds(ringSize int, logger *log.Logger, bounds AggregateBounds) *TraceAccumulator {
	if ringSize <= 0 {
		ringSize = 200
	}
	return &TraceAccumulator{
		recentTraces: make([]RecentTraceSummary, ringSize),
		ringSize:     ringSize,
		activeTraces: make(map[string]*activeTrace),
		edgeStats:    make(map[edgeKey]*edgeAccum),
		edgeBounds:   bounds,
		liveClients:  make(map[chan *LiveTraceEvent]struct{}),
		dirtyTraces:  make(map[string]bool),
		logger:       logger,
		cancel:       make(chan struct{}),
	}
}

// ProcessTraceEvent implements TraceEventProcessor.
func (ta *TraceAccumulator) ProcessTraceEvent(event *TraceEvent) error {
	ta.mu.Lock()
	defer ta.mu.Unlock()

	// Note: agent activity counts are derived from the recent-traces ring buffer
	// in GetAgentActivity(); they are no longer incremented per span event.

	// Add to active trace (create if first span for this trace)
	at, exists := ta.activeTraces[event.TraceID]
	if !exists {
		at = &activeTrace{
			TraceID:   event.TraceID,
			Spans:     make([]*TraceEvent, 0, 16),
			SpanAgent: make(map[string]string),
			StartTime: time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9)),
			Agents:    make(map[string]bool),
		}
		ta.activeTraces[event.TraceID] = at
	}
	at.Spans = append(at.Spans, event)
	at.LastSeen = time.Now()

	if event.AgentName != "" {
		at.Agents[event.AgentName] = true
		at.SpanAgent[event.SpanID] = event.AgentName
	}

	// Track errors
	if event.Success != nil && !*event.Success {
		at.HasError = true
	}

	// Track root span (no parent)
	if event.ParentSpan == nil && at.RootAgent == "" {
		at.RootAgent = event.AgentName
		at.RootOp = event.Operation
	}

	// Publish live events based on trace state
	if !exists {
		// New trace — publish trace_started
		ta.publishLive(&LiveTraceEvent{
			EventType: "trace_started",
			Snapshot:  at.buildSnapshot(false),
		})
	}

	// On root span completion (span_end with no parent), mark for deferred finalization.
	// Don't finalize immediately — wait a short grace period for remaining in-flight
	// spans from other processes to arrive via Redis consumer.
	if event.DurationMS != nil && event.ParentSpan == nil {
		now := time.Now()
		at.RootSeen = &now
		at.RootSpan = event
		// Mark dirty so debounce loop picks it up for finalization
		ta.dirtyTraces[event.TraceID] = true
	} else if exists {
		// Existing trace with a new span — mark dirty for debounced update
		ta.dirtyTraces[event.TraceID] = true
	}

	return nil
}

// recordEdge records a cross-agent edge observation. `function` is the callee's
// span operation; see edgeKey.Function for what an empty one means.
func (ta *TraceAccumulator) recordEdge(source, target, function string, durationMs int64, success *bool) {
	// An edge with an unnamed end names no edge at all and has never been
	// reported. Refused HERE rather than filtered at read time so it does not
	// occupy a slot under the key ceiling: an unnamed key kept in the map would
	// evict a real, displayable edge to hold a row nothing can ever show. (An
	// empty FUNCTION is different — a partial observation, and kept. See
	// edgeKey.Function.)
	if source == "" || target == "" {
		return
	}

	key := edgeKey{Source: source, Target: target, Function: function}
	ea, exists := ta.edgeStats[key]
	if !exists {
		ea = &edgeAccum{
			MinMs: math.MaxInt64,
		}
		ta.edgeStats[key] = ea
	}
	ea.CallCount++
	ea.TotalMs += durationMs
	ea.Latency.Record(durationMs)
	if durationMs > ea.MaxMs {
		ea.MaxMs = durationMs
	}
	if durationMs < ea.MinMs {
		ea.MinMs = durationMs
	}
	if success != nil && !*success {
		ea.ErrorCount++
	}
	ea.LastSeen = time.Now()

	// Hard key ceiling. Age pruning (pruneEdgeStats) is the primary bound;
	// this only trips when new edge names appear faster than the retention
	// window retires them, and it evicts least-recently-seen first.
	//
	// The finer key raises cardinality by the number of distinct provider
	// functions called across each pair, so the ceiling is reached sooner than
	// it used to be on the same mesh. It is still names, not volume: one key
	// per (caller, provider, tool) actually in use.
	if evicted := EnforceMaxEntries(ta.edgeStats, edgeLastSeen, ta.edgeBounds.MaxEntries, edgeKeyLess); evicted > 0 && ta.logger != nil {
		ta.logger.Printf("TraceAccumulator: edge-stat key cap (%d) reached, evicted %d least-recently-seen edges "+
			"(raise MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES or shorten MCP_MESH_TELEMETRY_AGGREGATE_RETENTION)",
			ta.edgeBounds.MaxEntries, evicted)
	}
}

// edgeLastSeen adapts edgeAccum to the PruneOlderThan/EnforceMaxEntries
// accessor signature.
func edgeLastSeen(ea *edgeAccum) time.Time { return ea.LastSeen }

// edgeKeyLess is EnforceMaxEntries' deterministic tiebreak for edge keys,
// ordering on the three fields in turn.
func edgeKeyLess(a, b edgeKey) bool {
	if a.Source != b.Source {
		return a.Source < b.Source
	}
	if a.Target != b.Target {
		return a.Target < b.Target
	}
	return a.Function < b.Function
}

// pruneEdgeStats removes edge entries not observed within the retention
// window. Mirrors SpanCorrelator.pruneExpiredCompletedTraces: age-based, with
// a retention <= 0 no-op. Called from cleanupLoop.
func (ta *TraceAccumulator) pruneEdgeStats() {
	if ta.edgeBounds.Retention <= 0 {
		return
	}

	cutoff := time.Now().Add(-ta.edgeBounds.Retention)

	ta.mu.Lock()
	removed := PruneOlderThan(ta.edgeStats, edgeLastSeen, cutoff)
	ta.mu.Unlock()

	if removed > 0 && ta.logger != nil {
		ta.logger.Printf("TraceAccumulator: pruned %d edge stats idle longer than %s", removed, ta.edgeBounds.Retention)
	}
}

// EdgeStatCount returns the current number of tracked edge keys. Exposed for
// tests and diagnostics.
func (ta *TraceAccumulator) EdgeStatCount() int {
	ta.mu.RLock()
	defer ta.mu.RUnlock()
	return len(ta.edgeStats)
}

// finalizeTrace converts an active trace into a RecentTraceSummary and pushes
// it into the ring buffer. The active trace is then removed.
func (ta *TraceAccumulator) finalizeTrace(at *activeTrace, rootSpan *TraceEvent) {
	agents := make([]string, 0, len(at.Agents))
	for a := range at.Agents {
		agents = append(agents, a)
	}
	sort.Strings(agents)

	durationMs := int64(0)
	if rootSpan.DurationMS != nil {
		durationMs = *rootSpan.DurationMS
	}

	summary := RecentTraceSummary{
		TraceID:       at.TraceID,
		RootAgent:     at.RootAgent,
		RootOperation: at.RootOp,
		DurationMs:    durationMs,
		StartTime:     at.StartTime,
		SpanCount:     len(at.Spans),
		AgentCount:    len(at.Agents),
		Success:       !at.HasError,
		Agents:        agents,
	}

	ta.totalFinalized++
	if !summary.Success {
		ta.totalErrors++
	}

	// Push to ring buffer
	ta.recentTraces[ta.ringHead] = summary
	ta.ringHead = (ta.ringHead + 1) % ta.ringSize
	if ta.ringCount < ta.ringSize {
		ta.ringCount++
	}

	// Remove from active traces
	delete(ta.activeTraces, at.TraceID)
}

// buildSnapshot creates a TraceSnapshot from the current state of the activeTrace.
// Caller must hold ta.mu (read or write).
func (at *activeTrace) buildSnapshot(completed bool) *TraceSnapshot {
	// Build wrapper ID set for proxy_call_wrapper filtering
	wrapperIDs := make(map[string]bool)
	for _, s := range at.Spans {
		if s.Operation == "proxy_call_wrapper" {
			wrapperIDs[s.SpanID] = true
		}
	}

	// Resolve effective parent: skip through proxy_call_wrapper spans
	resolveParent := func(parentID string) string {
		visited := make(map[string]bool)
		current := parentID
		for wrapperIDs[current] {
			if visited[current] {
				break
			}
			visited[current] = true
			for _, s := range at.Spans {
				if s.SpanID == current && s.ParentSpan != nil {
					current = *s.ParentSpan
					break
				}
			}
		}
		return current
	}

	// Build filtered spans
	var spans []SnapshotSpan
	for _, s := range at.Spans {
		if s.Operation == "proxy_call_wrapper" {
			continue
		}

		ss := SnapshotSpan{
			SpanID:     s.SpanID,
			AgentName:  s.AgentName,
			Operation:  s.Operation,
			DurationMs: s.DurationMS,
			Success:    s.Success,
			Runtime:    s.Runtime,
		}

		if s.ParentSpan != nil {
			resolved := resolveParent(*s.ParentSpan)
			if !wrapperIDs[resolved] {
				ss.EffectiveParent = resolved
			}
		}

		spans = append(spans, ss)
	}

	// Build agents list
	agents := make([]string, 0, len(at.Agents))
	for a := range at.Agents {
		agents = append(agents, a)
	}
	sort.Strings(agents)

	// Find root span duration
	var durationMs *int64
	for _, s := range at.Spans {
		if s.ParentSpan == nil && s.DurationMS != nil && *s.DurationMS > 0 {
			durationMs = s.DurationMS
			break
		}
	}

	return &TraceSnapshot{
		TraceID:       at.TraceID,
		RootAgent:     at.RootAgent,
		RootOperation: at.RootOp,
		StartTime:     at.StartTime,
		Completed:     completed,
		DurationMs:    durationMs,
		HasError:      at.HasError,
		SpanCount:     len(spans),
		Agents:        agents,
		Spans:         spans,
	}
}

// publishLive sends a LiveTraceEvent to all live subscribers (non-blocking).
// Caller must NOT hold liveMu.
func (ta *TraceAccumulator) publishLive(event *LiveTraceEvent) {
	ta.liveMu.RLock()
	defer ta.liveMu.RUnlock()
	for ch := range ta.liveClients {
		select {
		case ch <- event:
		default:
			// Skip slow clients
		}
	}
}

// GetRecentTraces returns the last N completed trace summaries, newest first.
func (ta *TraceAccumulator) GetRecentTraces(limit int) []RecentTraceSummary {
	ta.mu.RLock()
	defer ta.mu.RUnlock()

	count := ta.ringCount
	if limit > 0 && limit < count {
		count = limit
	}

	result := make([]RecentTraceSummary, 0, count)
	// Read backwards from the most recent entry
	for i := 0; i < count; i++ {
		idx := (ta.ringHead - 1 - i + ta.ringSize) % ta.ringSize
		result = append(result, ta.recentTraces[idx])
	}
	return result
}

// GetEdgeStats computes EdgeStats from the accumulated edge data. Returns EVERY
// edge; truncation belongs to the caller (SelectEdgeStats), because the two
// consumers of these rows want different budgets.
func (ta *TraceAccumulator) GetEdgeStats() []EdgeStats {
	ta.mu.RLock()
	defer ta.mu.RUnlock()

	edges := make([]EdgeStats, 0, len(ta.edgeStats))
	for key, ea := range ta.edgeStats {
		// No read-time filter for unnamed agents: recordEdge refuses to create
		// such a key in the first place, so one cannot be here. Dropping them on
		// the way in matters because a row skipped here would still be holding a
		// slot under the key ceiling, evicting a real edge to keep a row nothing
		// will ever display.
		avgLatency := float64(ea.TotalMs) / float64(ea.CallCount)
		errorRate := 100.0 * float64(ea.ErrorCount) / float64(ea.CallCount)

		// P99 is a bucket estimate over a rolling window of recent calls, and it
		// never understates what is inside that window (latency_histogram.go).
		// Clamped to the exactly-tracked lifetime max so it can never claim a latency
		// larger than one that was actually observed.
		p99 := ea.Latency.Quantile(0.99)
		if p99 > ea.MaxMs {
			p99 = ea.MaxMs
		}

		minMs := ea.MinMs
		if minMs == math.MaxInt64 {
			minMs = 0
		}

		edges = append(edges, EdgeStats{
			Source:         key.Source,
			Target:         key.Target,
			TargetFunction: key.Function,
			CallCount:      ea.CallCount,
			ErrorCount:     ea.ErrorCount,
			ErrorRate:      errorRate,
			AvgLatencyMs:   avgLatency,
			P99LatencyMs:   float64(p99),
			MaxLatencyMs:   ea.MaxMs,
			MinLatencyMs:   minMs,
		})
	}

	// Busiest first, then a total order on the key — see SortEdgeStats. This
	// returns EVERY edge; truncation is the caller's, through SelectEdgeStats,
	// because the right budget differs per consumer.
	SortEdgeStats(edges)

	return edges
}

// GetTotalFinalized returns the total number of finalized traces.
func (ta *TraceAccumulator) GetTotalFinalized() int {
	ta.mu.RLock()
	defer ta.mu.RUnlock()
	return ta.totalFinalized
}

// GetTotalErrors returns the total number of finalized traces that had errors.
func (ta *TraceAccumulator) GetTotalErrors() int {
	ta.mu.RLock()
	defer ta.mu.RUnlock()
	return ta.totalErrors
}

// GetAgentActivity returns the per-agent count of finalized traces currently in
// the recent-traces ring buffer that involve each agent. By construction this
// matches what /trace/recent would return when filtered by an agent: the badge
// count never exceeds the number of recent traces visible to the user.
//
// The map is computed on read by walking the ring buffer (size O(ringSize)
// with small per-trace agent lists, so the cost is negligible at the ring
// sizes we care about).
func (ta *TraceAccumulator) GetAgentActivity() map[string]int {
	ta.mu.RLock()
	defer ta.mu.RUnlock()
	result := make(map[string]int)
	for i := 0; i < ta.ringCount; i++ {
		idx := (ta.ringHead - 1 - i + ta.ringSize) % ta.ringSize
		for _, agent := range ta.recentTraces[idx].Agents {
			if agent != "" {
				result[agent]++
			}
		}
	}
	return result
}

// SubscribeLive creates a new live subscriber channel for SSE streaming.
func (ta *TraceAccumulator) SubscribeLive() chan *LiveTraceEvent {
	ta.liveMu.Lock()
	defer ta.liveMu.Unlock()
	ch := make(chan *LiveTraceEvent, 64)
	ta.liveClients[ch] = struct{}{}
	return ch
}

// UnsubscribeLive removes a live subscriber and closes its channel.
func (ta *TraceAccumulator) UnsubscribeLive(ch chan *LiveTraceEvent) {
	ta.liveMu.Lock()
	defer ta.liveMu.Unlock()
	if _, ok := ta.liveClients[ch]; ok {
		delete(ta.liveClients, ch)
		close(ch)
	}
}

// GetActiveTraceSnapshots returns snapshots for all currently active traces.
func (ta *TraceAccumulator) GetActiveTraceSnapshots() []*TraceSnapshot {
	ta.mu.RLock()
	defer ta.mu.RUnlock()
	var snapshots []*TraceSnapshot
	for _, at := range ta.activeTraces {
		snapshots = append(snapshots, at.buildSnapshot(false))
	}
	return snapshots
}

// LiveSubscriberCount returns the number of active live SSE subscribers.
func (ta *TraceAccumulator) LiveSubscriberCount() int {
	ta.liveMu.RLock()
	defer ta.liveMu.RUnlock()
	return len(ta.liveClients)
}

// Start begins the background cleanup and debounce goroutines.
func (ta *TraceAccumulator) Start() {
	ta.wg.Add(2)
	go ta.cleanupLoop()
	go ta.debounceLoop()
}

// Stop cancels the cleanup goroutine and waits for it to finish.
func (ta *TraceAccumulator) Stop() {
	close(ta.cancel)
	ta.wg.Wait()
}

func (ta *TraceAccumulator) cleanupLoop() {
	defer ta.wg.Done()
	ticker := time.NewTicker(AggregatePruneInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ta.cancel:
			return
		case <-ticker.C:
			ta.cleanupStaleTraces()
			ta.pruneEdgeStats()
		}
	}
}

// traceGracePeriod is the time to wait after seeing a root span before finalizing,
// allowing in-flight spans from other processes to arrive via Redis consumer.
const traceGracePeriod = 3 * time.Second

// finalizeReadyTraces finalizes traces that have seen their root span and waited
// the grace period. Called from the debounce loop every 500ms.
func (ta *TraceAccumulator) finalizeReadyTraces() {
	ta.mu.Lock()

	now := time.Now()
	var completedEvents []*LiveTraceEvent
	for id, at := range ta.activeTraces {
		if at.RootSeen != nil && now.Sub(*at.RootSeen) >= traceGracePeriod {
			// Grace period elapsed — finalize this trace

			// Detect cross-agent edges from all spans. The edge is attributed
			// from the CALLEE's span, so s.Operation is the provider's own
			// function name — see edgeKey.Function.
			for _, s := range at.Spans {
				if s.ParentSpan == nil || s.DurationMS == nil {
					continue
				}
				parentAgent, ok := at.SpanAgent[*s.ParentSpan]
				if ok && parentAgent != s.AgentName {
					ta.recordEdge(parentAgent, s.AgentName, s.Operation, *s.DurationMS, s.Success)
				}
			}

			// Publish trace_completed event
			completedEvents = append(completedEvents, &LiveTraceEvent{
				EventType: "trace_completed",
				Snapshot:  at.buildSnapshot(true),
			})

			// Finalize into ring buffer
			if at.RootSpan != nil {
				ta.finalizeTrace(at, at.RootSpan)
			} else if len(at.Spans) > 0 {
				ta.finalizeTrace(at, at.Spans[0])
			} else {
				delete(ta.activeTraces, id)
			}
			delete(ta.dirtyTraces, id)
		}
	}

	ta.mu.Unlock()

	// Publish outside of mu lock
	for _, evt := range completedEvents {
		ta.publishLive(evt)
	}
}

// FinalizeAllActive force-finalizes every currently-active trace immediately,
// bypassing the grace period. It runs the same edge-detection + finalizeTrace
// path as finalizeReadyTraces, so edge stats and total finalized/error counters
// end up identical to the live consumer's — just without the async wait.
//
// This exists for windowed replay over a throwaway accumulator: after feeding a
// bounded batch of stream events, the caller flushes all in-flight traces so the
// aggregates (edges, totals) are complete. It is NOT used on the live
// accumulator, which relies on the grace period to absorb late cross-process
// spans.
func (ta *TraceAccumulator) FinalizeAllActive() {
	ta.mu.Lock()
	defer ta.mu.Unlock()

	for id, at := range ta.activeTraces {
		// Detect cross-agent edges from all spans (mirrors finalizeReadyTraces).
		for _, s := range at.Spans {
			if s.ParentSpan == nil || s.DurationMS == nil {
				continue
			}
			parentAgent, ok := at.SpanAgent[*s.ParentSpan]
			if ok && parentAgent != s.AgentName {
				ta.recordEdge(parentAgent, s.AgentName, s.Operation, *s.DurationMS, s.Success)
			}
		}

		// Finalize into ring buffer + totals, preferring the root span.
		if at.RootSpan != nil {
			ta.finalizeTrace(at, at.RootSpan)
		} else {
			var rootSpan *TraceEvent
			for _, s := range at.Spans {
				if s.ParentSpan == nil {
					rootSpan = s
					break
				}
			}
			if rootSpan == nil && len(at.Spans) > 0 {
				rootSpan = at.Spans[0]
			}
			if rootSpan != nil {
				ta.finalizeTrace(at, rootSpan)
			} else {
				delete(ta.activeTraces, id)
			}
		}
		delete(ta.dirtyTraces, id)
	}
}

func (ta *TraceAccumulator) cleanupStaleTraces() {
	ta.mu.Lock()

	cutoff := time.Now().Add(-30 * time.Second)
	var staleEvents []*LiveTraceEvent
	stale := 0
	for id, at := range ta.activeTraces {
		if at.LastSeen.Before(cutoff) {
			staleEvents = append(staleEvents, &LiveTraceEvent{
				EventType: "trace_completed",
				Snapshot:  at.buildSnapshot(true),
			})
			// Finalize into ring buffer so GetRecentTraces() returns them.
			// Find the best "root" span: prefer one without a parent, fall back to the first span.
			var rootSpan *TraceEvent
			for _, s := range at.Spans {
				if s.ParentSpan == nil {
					rootSpan = s
					break
				}
			}
			if rootSpan == nil && len(at.Spans) > 0 {
				rootSpan = at.Spans[0]
			}
			if rootSpan != nil {
				ta.finalizeTrace(at, rootSpan)
			} else {
				delete(ta.activeTraces, id)
			}
			delete(ta.dirtyTraces, id)
			stale++
		}
	}
	ta.mu.Unlock()

	// Publish outside of mu lock
	for _, evt := range staleEvents {
		ta.publishLive(evt)
	}

	if stale > 0 {
		ta.logger.Printf("TraceAccumulator: cleaned up %d stale active traces", stale)
	}
}

func (ta *TraceAccumulator) debounceLoop() {
	defer ta.wg.Done()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-ta.cancel:
			return
		case <-ticker.C:
			ta.finalizeReadyTraces()
			ta.publishDirtyTraces()
		}
	}
}

func (ta *TraceAccumulator) publishDirtyTraces() {
	ta.mu.Lock()
	if len(ta.dirtyTraces) == 0 {
		ta.mu.Unlock()
		return
	}

	// Copy dirty set and build snapshots under lock
	var events []*LiveTraceEvent
	for id := range ta.dirtyTraces {
		at, ok := ta.activeTraces[id]
		if ok {
			events = append(events, &LiveTraceEvent{
				EventType: "trace_update",
				Snapshot:  at.buildSnapshot(false),
			})
		}
	}
	ta.dirtyTraces = make(map[string]bool)
	ta.mu.Unlock()

	// Publish outside of mu lock
	for _, evt := range events {
		ta.publishLive(evt)
	}
}
