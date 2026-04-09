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

	// Per-edge stats keyed by "source -> target"
	edgeStats map[string]*edgeAccum

	// Per-agent activity count (spans seen per agent)
	agentActivity map[string]int

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

const maxEdgeLatencies = 10000

type edgeAccum struct {
	CallCount   int
	ErrorCount  int
	Latencies   []int64
	latencyHead int // ring buffer write position (used once Latencies reaches cap)
	TotalMs     int64
	MaxMs       int64
	MinMs       int64
}

// NewTraceAccumulator creates a new accumulator with the given ring buffer size.
func NewTraceAccumulator(ringSize int, logger *log.Logger) *TraceAccumulator {
	if ringSize <= 0 {
		ringSize = 200
	}
	return &TraceAccumulator{
		recentTraces:  make([]RecentTraceSummary, ringSize),
		ringSize:      ringSize,
		activeTraces:  make(map[string]*activeTrace),
		edgeStats:     make(map[string]*edgeAccum),
		agentActivity: make(map[string]int),
		liveClients:   make(map[chan *LiveTraceEvent]struct{}),
		dirtyTraces:   make(map[string]bool),
		logger:        logger,
		cancel:        make(chan struct{}),
	}
}

// ProcessTraceEvent implements TraceEventProcessor.
func (ta *TraceAccumulator) ProcessTraceEvent(event *TraceEvent) error {
	ta.mu.Lock()
	defer ta.mu.Unlock()

	// 1. Update agent activity count
	if event.AgentName != "" {
		ta.agentActivity[event.AgentName]++
	}

	// 2. Add to active trace (create if first span for this trace)
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

	// 3. Publish live events based on trace state
	if !exists {
		// New trace — publish trace_started
		ta.publishLive(&LiveTraceEvent{
			EventType: "trace_started",
			Snapshot:  at.buildSnapshot(false),
		})
	}

	// 4. On root span completion (span_end with no parent), mark for deferred finalization.
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

// recordEdge records a cross-agent edge observation.
func (ta *TraceAccumulator) recordEdge(source, target string, durationMs int64, success *bool) {
	key := source + " -> " + target
	ea, exists := ta.edgeStats[key]
	if !exists {
		ea = &edgeAccum{
			MinMs: math.MaxInt64,
		}
		ta.edgeStats[key] = ea
	}
	ea.CallCount++
	ea.TotalMs += durationMs
	if len(ea.Latencies) < maxEdgeLatencies {
		ea.Latencies = append(ea.Latencies, durationMs)
	} else {
		ea.Latencies[ea.latencyHead] = durationMs
		ea.latencyHead = (ea.latencyHead + 1) % maxEdgeLatencies
	}
	if durationMs > ea.MaxMs {
		ea.MaxMs = durationMs
	}
	if durationMs < ea.MinMs {
		ea.MinMs = durationMs
	}
	if success != nil && !*success {
		ea.ErrorCount++
	}
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
			SpanID:    s.SpanID,
			AgentName: s.AgentName,
			Operation: s.Operation,
			DurationMs: s.DurationMS,
			Success:   s.Success,
			Runtime:   s.Runtime,
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

// GetEdgeStats computes EdgeStats from the accumulated edge data.
func (ta *TraceAccumulator) GetEdgeStats() []EdgeStats {
	ta.mu.RLock()
	defer ta.mu.RUnlock()

	edges := make([]EdgeStats, 0, len(ta.edgeStats))
	for key, ea := range ta.edgeStats {
		// Parse "source -> target"
		var source, target string
		for i := 0; i+3 < len(key); i++ {
			if key[i:i+4] == " -> " {
				source = key[:i]
				target = key[i+4:]
				break
			}
		}
		if source == "" || target == "" {
			continue
		}

		avgLatency := float64(ea.TotalMs) / float64(ea.CallCount)
		errorRate := 100.0 * float64(ea.ErrorCount) / float64(ea.CallCount)

		// P99 calculation
		sorted := make([]int64, len(ea.Latencies))
		copy(sorted, ea.Latencies)
		sort.Slice(sorted, func(i, j int) bool { return sorted[i] < sorted[j] })
		p99Index := int(math.Ceil(float64(len(sorted))*0.99)) - 1
		if p99Index < 0 {
			p99Index = 0
		}
		if p99Index >= len(sorted) {
			p99Index = len(sorted) - 1
		}
		p99Latency := float64(sorted[p99Index])

		minMs := ea.MinMs
		if minMs == math.MaxInt64 {
			minMs = 0
		}

		edges = append(edges, EdgeStats{
			Source:       source,
			Target:       target,
			CallCount:    ea.CallCount,
			ErrorCount:   ea.ErrorCount,
			ErrorRate:    errorRate,
			AvgLatencyMs: avgLatency,
			P99LatencyMs: p99Latency,
			MaxLatencyMs: ea.MaxMs,
			MinLatencyMs: minMs,
		})
	}

	sort.Slice(edges, func(i, j int) bool {
		return edges[i].CallCount > edges[j].CallCount
	})

	return edges
}

// GetAgentActivity returns a copy of the agent activity map.
func (ta *TraceAccumulator) GetAgentActivity() map[string]int {
	ta.mu.RLock()
	defer ta.mu.RUnlock()
	result := make(map[string]int, len(ta.agentActivity))
	for k, v := range ta.agentActivity {
		result[k] = v
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
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ta.cancel:
			return
		case <-ticker.C:
			ta.cleanupStaleTraces()
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

			// Detect cross-agent edges from all spans
			for _, s := range at.Spans {
				if s.ParentSpan == nil || s.DurationMS == nil {
					continue
				}
				parentAgent, ok := at.SpanAgent[*s.ParentSpan]
				if ok && parentAgent != s.AgentName {
					ta.recordEdge(parentAgent, s.AgentName, *s.DurationMS, s.Success)
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
