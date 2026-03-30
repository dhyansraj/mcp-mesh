package tracing

import (
	"log"
	"math"
	"sort"
	"sync"
	"time"
)

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
	liveClients map[chan *TraceEvent]struct{}

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
	StartTime time.Time
	LastSeen  time.Time
	Agents    map[string]bool
	HasError  bool
}

type edgeAccum struct {
	CallCount  int
	ErrorCount int
	Latencies  []int64
	TotalMs    int64
	MaxMs      int64
	MinMs      int64
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
		liveClients:   make(map[chan *TraceEvent]struct{}),
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

	// 3. Publish to live subscribers (non-blocking)
	ta.publishLive(event)

	// 4. On root span completion (span_end with no parent), finalize trace + detect edges
	if event.DurationMS != nil && event.ParentSpan == nil {
		// Root span completed — all spans should be in the map now
		// Detect cross-agent edges from all spans in this trace
		for _, s := range at.Spans {
			if s.ParentSpan == nil || s.DurationMS == nil {
				continue
			}
			parentAgent, ok := at.SpanAgent[*s.ParentSpan]
			if ok && parentAgent != s.AgentName {
				ta.recordEdge(parentAgent, s.AgentName, *s.DurationMS, s.Success)
			}
		}
		ta.finalizeTrace(at, event)
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
	ea.Latencies = append(ea.Latencies, durationMs)
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

// publishLive sends the event to all live subscribers (non-blocking).
// Caller must NOT hold liveMu.
func (ta *TraceAccumulator) publishLive(event *TraceEvent) {
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
func (ta *TraceAccumulator) SubscribeLive() chan *TraceEvent {
	ta.liveMu.Lock()
	defer ta.liveMu.Unlock()
	ch := make(chan *TraceEvent, 64)
	ta.liveClients[ch] = struct{}{}
	return ch
}

// UnsubscribeLive removes a live subscriber and closes its channel.
func (ta *TraceAccumulator) UnsubscribeLive(ch chan *TraceEvent) {
	ta.liveMu.Lock()
	defer ta.liveMu.Unlock()
	if _, ok := ta.liveClients[ch]; ok {
		delete(ta.liveClients, ch)
		close(ch)
	}
}

// LiveSubscriberCount returns the number of active live SSE subscribers.
func (ta *TraceAccumulator) LiveSubscriberCount() int {
	ta.liveMu.RLock()
	defer ta.liveMu.RUnlock()
	return len(ta.liveClients)
}

// Start begins the background cleanup goroutine that removes stale active traces.
func (ta *TraceAccumulator) Start() {
	ta.wg.Add(1)
	go ta.cleanupLoop()
}

// Stop cancels the cleanup goroutine and waits for it to finish.
func (ta *TraceAccumulator) Stop() {
	close(ta.cancel)
	ta.wg.Wait()
}

func (ta *TraceAccumulator) cleanupLoop() {
	defer ta.wg.Done()
	ticker := time.NewTicker(30 * time.Second)
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

func (ta *TraceAccumulator) cleanupStaleTraces() {
	ta.mu.Lock()
	defer ta.mu.Unlock()

	cutoff := time.Now().Add(-2 * time.Minute)
	stale := 0
	for id, at := range ta.activeTraces {
		if at.LastSeen.Before(cutoff) {
			delete(ta.activeTraces, id)
			stale++
		}
	}
	if stale > 0 {
		ta.logger.Printf("TraceAccumulator: cleaned up %d stale active traces", stale)
	}
}
