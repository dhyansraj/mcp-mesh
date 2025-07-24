package tracing

import (
	"context"
	"fmt"
	"log"
	"os"
	"sort"
	"strings"
	"sync"
	"time"
)

// SpanCorrelator correlates individual trace events into complete traces
type SpanCorrelator struct {
	activeTraces    map[string]*TraceBuilder
	completedTraces map[string]*CompletedTrace
	traceMutex      sync.RWMutex
	completedMutex  sync.RWMutex
	logger          *log.Logger
	exporter        TraceExporter
	traceTimeout    time.Duration
	maxStoredTraces int
	cleanupTicker   *time.Ticker
	ctx             context.Context
	cancel          context.CancelFunc
	wg              sync.WaitGroup
}

// TraceBuilder accumulates spans for a single trace
type TraceBuilder struct {
	TraceID   string
	Spans     []*TraceSpan
	StartTime time.Time
	LastSeen  time.Time
	mutex     sync.RWMutex
}

// TraceSpan represents a complete span with start and end events
type TraceSpan struct {
	TraceID      string
	SpanID       string
	ParentSpan   *string
	AgentName    string
	AgentID      string
	IPAddress    string
	Operation    string
	StartTime    time.Time
	EndTime      *time.Time
	DurationMS   *int64
	Success      *bool
	ErrorMessage *string
	Capability   *string
	TargetAgent  *string
	Runtime      string
}

// CompletedTrace represents a fully correlated trace
type CompletedTrace struct {
	TraceID    string
	Spans      []*TraceSpan
	StartTime  time.Time
	EndTime    time.Time
	Duration   time.Duration
	Success    bool
	SpanCount  int
	AgentCount int
	Agents     []string
}

// TraceExporter interface for exporting completed traces
type TraceExporter interface {
	ExportTrace(trace *CompletedTrace) error
}

// SpanExporter interface for exporting individual spans (stream-through mode)
type SpanExporter interface {
	ExportSpan(event *TraceEvent) error
	EstablishSpanContext(event *TraceEvent) error
	ExportCompleteSpan(event *TraceEvent) error  // For single execution trace events
}

// NewSpanCorrelator creates a new span correlator
func NewSpanCorrelator(exporter TraceExporter, traceTimeout time.Duration) *SpanCorrelator {
	ctx, cancel := context.WithCancel(context.Background())

	correlator := &SpanCorrelator{
		activeTraces:    make(map[string]*TraceBuilder),
		completedTraces: make(map[string]*CompletedTrace),
		logger:          log.New(os.Stdout, "[TRACE-CORRELATOR] ", log.LstdFlags),
		exporter:        exporter,
		traceTimeout:    traceTimeout,
		maxStoredTraces: 1000, // Store last 1000 completed traces for querying
		cleanupTicker:   time.NewTicker(1 * time.Minute), // Cleanup every minute
		ctx:             ctx,
		cancel:          cancel,
	}

	// Start cleanup routine
	correlator.wg.Add(1)
	go correlator.cleanupLoop()

	return correlator
}

// ProcessTraceEvent implements TraceEventProcessor interface
func (sc *SpanCorrelator) ProcessTraceEvent(event *TraceEvent) error {
	sc.traceMutex.Lock()
	defer sc.traceMutex.Unlock()

	// Get or create trace builder
	builder, exists := sc.activeTraces[event.TraceID]
	if !exists {
		builder = &TraceBuilder{
			TraceID:   event.TraceID,
			Spans:     make([]*TraceSpan, 0),
			StartTime: time.Now(),
			LastSeen:  time.Now(),
		}
		sc.activeTraces[event.TraceID] = builder
		sc.logger.Printf("🆕 Started tracking trace: %s", event.TraceID[:8])
	}

	builder.mutex.Lock()
	builder.LastSeen = time.Now()

	switch event.EventType {
	case "span_start":
		sc.handleSpanStart(builder, event)
	case "span_end":
		sc.handleSpanEnd(builder, event)
	case "error":
		sc.handleSpanError(builder, event)
	default:
	}

	builder.mutex.Unlock()

	// Check if trace is complete and should be exported
	isComplete := sc.isTraceComplete(builder)
	sc.logger.Printf("🔍 Trace %s completion check: complete=%v, spans=%d, lastSeen=%v ago",
		event.TraceID[:8], isComplete, len(builder.Spans), time.Since(builder.LastSeen))

	if isComplete {
		sc.logger.Printf("🚀 Exporting completed trace: %s", event.TraceID[:8])
		if err := sc.finalizeAndExportTrace(event.TraceID); err != nil {
		}
	}

	return nil
}

// handleSpanStart processes a span start event
func (sc *SpanCorrelator) handleSpanStart(builder *TraceBuilder, event *TraceEvent) {
	// Check if span already exists
	for _, span := range builder.Spans {
		if span.SpanID == event.SpanID {
			// Span already exists, just update start time if needed
			startTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
			if startTime.Before(span.StartTime) {
				span.StartTime = startTime
			}
			return
		}
	}

	// Create new span
	span := &TraceSpan{
		TraceID:    event.TraceID,
		SpanID:     event.SpanID,
		ParentSpan: event.ParentSpan,
		AgentName:  event.AgentName,
		AgentID:    event.AgentID,
		IPAddress:  event.IPAddress,
		Operation:  event.Operation,
		StartTime:  time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9)),
		Capability: event.Capability,
		TargetAgent: event.TargetAgent,
		Runtime:    event.Runtime,
	}

	builder.Spans = append(builder.Spans, span)
	sc.logger.Printf("➕ Added span start: %s/%s %s", event.TraceID[:8], event.SpanID[:8], event.Operation)
}

// handleSpanEnd processes a span end event
func (sc *SpanCorrelator) handleSpanEnd(builder *TraceBuilder, event *TraceEvent) {
	// Find matching span
	for _, span := range builder.Spans {
		if span.SpanID == event.SpanID {
			endTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
			span.EndTime = &endTime
			span.DurationMS = event.DurationMS
			span.Success = event.Success
			span.ErrorMessage = event.ErrorMessage

			sc.logger.Printf("✅ Completed span: %s/%s %s", event.TraceID[:8], event.SpanID[:8], event.Operation)
			return
		}
	}

	// Span not found, create orphaned span end
	endTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
	span := &TraceSpan{
		TraceID:      event.TraceID,
		SpanID:       event.SpanID,
		AgentName:    event.AgentName,
		AgentID:      event.AgentID,
		IPAddress:    event.IPAddress,
		Operation:    event.Operation,
		StartTime:    endTime, // Use end time as start time for orphaned spans
		EndTime:      &endTime,
		DurationMS:   event.DurationMS,
		Success:      event.Success,
		ErrorMessage: event.ErrorMessage,
		Runtime:      event.Runtime,
	}
	builder.Spans = append(builder.Spans, span)
}

// handleSpanError processes an error event
func (sc *SpanCorrelator) handleSpanError(builder *TraceBuilder, event *TraceEvent) {
	// Find matching span or create new one
	for _, span := range builder.Spans {
		if span.SpanID == event.SpanID {
			span.Success = event.Success
			span.ErrorMessage = event.ErrorMessage
			return
		}
	}

	// Create error-only span
	errorTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
	span := &TraceSpan{
		TraceID:      event.TraceID,
		SpanID:       event.SpanID,
		AgentName:    event.AgentName,
		AgentID:      event.AgentID,
		IPAddress:    event.IPAddress,
		Operation:    event.Operation,
		StartTime:    errorTime,
		EndTime:      &errorTime,
		Success:      event.Success,
		ErrorMessage: event.ErrorMessage,
		Runtime:      event.Runtime,
	}
	builder.Spans = append(builder.Spans, span)
}

// isTraceComplete determines if a trace is complete and ready for export
func (sc *SpanCorrelator) isTraceComplete(builder *TraceBuilder) bool {
	// Simple heuristic: if no new events for 5 seconds and all spans have end times
	timeSinceLastSeen := time.Since(builder.LastSeen)
	if timeSinceLastSeen < 5*time.Second {
		sc.logger.Printf("🕐 Trace %s not ready: only %v since last event (need 5s)",
			builder.TraceID[:8], timeSinceLastSeen)
		return false
	}

	// Check if all spans are complete
	incompleteSpans := 0
	for _, span := range builder.Spans {
		if span.EndTime == nil {
			incompleteSpans++
		}
	}

	if incompleteSpans > 0 {
		sc.logger.Printf("⏳ Trace %s not ready: %d spans missing end times",
			builder.TraceID[:8], incompleteSpans)
		return false
	}

	hasSpans := len(builder.Spans) > 0
	if !hasSpans {
	} else {
		sc.logger.Printf("✅ Trace %s ready: %d complete spans, %v since last event",
			builder.TraceID[:8], len(builder.Spans), timeSinceLastSeen)
	}

	return hasSpans
}

// finalizeAndExportTrace finalizes and exports a completed trace
func (sc *SpanCorrelator) finalizeAndExportTrace(traceID string) error {
	builder, exists := sc.activeTraces[traceID]
	if !exists {
		return fmt.Errorf("trace %s not found", traceID)
	}

	builder.mutex.RLock()
	defer builder.mutex.RUnlock()

	// Build completed trace
	completedTrace := sc.buildCompletedTrace(builder)

	// Store completed trace for querying
	sc.storeCompletedTrace(completedTrace)

	// Export the trace
	if err := sc.exporter.ExportTrace(completedTrace); err != nil {
		return fmt.Errorf("failed to export trace: %w", err)
	}

	// Remove from active traces
	delete(sc.activeTraces, traceID)
	sc.logger.Printf("🚀 Exported trace: %s (%d spans, %v duration)",
		traceID[:8], completedTrace.SpanCount, completedTrace.Duration)

	return nil
}

// buildCompletedTrace builds a CompletedTrace from a TraceBuilder
func (sc *SpanCorrelator) buildCompletedTrace(builder *TraceBuilder) *CompletedTrace {
	// Sort spans by start time
	spans := make([]*TraceSpan, len(builder.Spans))
	copy(spans, builder.Spans)
	sort.Slice(spans, func(i, j int) bool {
		return spans[i].StartTime.Before(spans[j].StartTime)
	})

	// Calculate trace timing
	var startTime, endTime time.Time
	success := true
	agentSet := make(map[string]bool)

	if len(spans) > 0 {
		startTime = spans[0].StartTime
		endTime = spans[0].StartTime

		for _, span := range spans {
			if span.StartTime.Before(startTime) {
				startTime = span.StartTime
			}
			if span.EndTime != nil && span.EndTime.After(endTime) {
				endTime = *span.EndTime
			}
			if span.Success != nil && !*span.Success {
				success = false
			}
			agentSet[span.AgentName] = true
		}
	}

	// Build agent list
	agents := make([]string, 0, len(agentSet))
	for agent := range agentSet {
		agents = append(agents, agent)
	}
	sort.Strings(agents)

	return &CompletedTrace{
		TraceID:    builder.TraceID,
		Spans:      spans,
		StartTime:  startTime,
		EndTime:    endTime,
		Duration:   endTime.Sub(startTime),
		Success:    success,
		SpanCount:  len(spans),
		AgentCount: len(agents),
		Agents:     agents,
	}
}

// cleanupLoop periodically cleans up old traces
func (sc *SpanCorrelator) cleanupLoop() {
	defer sc.wg.Done()

	for {
		select {
		case <-sc.ctx.Done():
			return
		case <-sc.cleanupTicker.C:
			sc.cleanupOldTraces()
		}
	}
}

// cleanupOldTraces removes traces that have timed out and exports completed traces
func (sc *SpanCorrelator) cleanupOldTraces() {
	sc.traceMutex.Lock()
	defer sc.traceMutex.Unlock()

	now := time.Now()
	var expiredTraces []string
	var completedTraces []string

	for traceID, builder := range sc.activeTraces {
		if now.Sub(builder.LastSeen) > sc.traceTimeout {
			// Trace has expired (5 minutes of inactivity)
			expiredTraces = append(expiredTraces, traceID)
		} else if sc.isTraceComplete(builder) {
			// Trace is complete (all spans finished + 5 seconds of inactivity)
			completedTraces = append(completedTraces, traceID)
		}
	}

	// Export completed traces
	for _, traceID := range completedTraces {
		sc.logger.Printf("🚀 Exporting completed trace from cleanup: %s", traceID[:8])
		if err := sc.finalizeAndExportTrace(traceID); err != nil {
		}
	}

	// Export expired traces
	for _, traceID := range expiredTraces {
		builder := sc.activeTraces[traceID]
		sc.logger.Printf("🧹 Cleaning up expired trace: %s (%d spans)", traceID[:8], len(builder.Spans))

		// Try to export incomplete trace
		if len(builder.Spans) > 0 {
			completedTrace := sc.buildCompletedTrace(builder)
			sc.storeCompletedTrace(completedTrace)
			if err := sc.exporter.ExportTrace(completedTrace); err != nil {
			}
		}

		delete(sc.activeTraces, traceID)
	}

	if len(expiredTraces) > 0 {
		sc.logger.Printf("🧹 Cleaned up %d expired traces", len(expiredTraces))
	}
}

// Stop gracefully stops the correlator
func (sc *SpanCorrelator) Stop() error {
	sc.logger.Println("🛑 Stopping trace correlator...")

	sc.cancel()
	sc.cleanupTicker.Stop()
	sc.wg.Wait()

	// Export any remaining traces
	sc.traceMutex.Lock()
	defer sc.traceMutex.Unlock()

	for _, builder := range sc.activeTraces {
		if len(builder.Spans) > 0 {
			completedTrace := sc.buildCompletedTrace(builder)
			if err := sc.exporter.ExportTrace(completedTrace); err != nil {
			}
		}
	}

	sc.logger.Println("✅ Trace correlator stopped")
	return nil
}

// GetStats returns correlator statistics
func (sc *SpanCorrelator) GetStats() map[string]interface{} {
	sc.traceMutex.RLock()
	defer sc.traceMutex.RUnlock()

	stats := map[string]interface{}{
		"active_traces": len(sc.activeTraces),
		"trace_timeout": sc.traceTimeout.String(),
	}

	// Add details about active traces
	if len(sc.activeTraces) > 0 {
		oldestTrace := time.Now()
		totalSpans := 0

		for _, builder := range sc.activeTraces {
			if builder.StartTime.Before(oldestTrace) {
				oldestTrace = builder.StartTime
			}
			totalSpans += len(builder.Spans)
		}

		stats["oldest_trace_age"] = time.Since(oldestTrace).String()
		stats["total_spans"] = totalSpans
		stats["avg_spans_per_trace"] = float64(totalSpans) / float64(len(sc.activeTraces))
	}

	return stats
}

// storeCompletedTrace stores a completed trace for querying
func (sc *SpanCorrelator) storeCompletedTrace(trace *CompletedTrace) {
	sc.completedMutex.Lock()
	defer sc.completedMutex.Unlock()

	// Store the trace
	sc.completedTraces[trace.TraceID] = trace

	// Cleanup old traces if we exceed the limit
	if len(sc.completedTraces) > sc.maxStoredTraces {
		sc.cleanupOldCompletedTraces()
	}
}

// cleanupOldCompletedTraces removes the oldest completed traces
func (sc *SpanCorrelator) cleanupOldCompletedTraces() {
	// Find the oldest traces to remove
	type traceAge struct {
		traceID string
		endTime time.Time
	}

	traces := make([]traceAge, 0, len(sc.completedTraces))
	for id, trace := range sc.completedTraces {
		traces = append(traces, traceAge{id, trace.EndTime})
	}

	// Sort by end time (oldest first)
	sort.Slice(traces, func(i, j int) bool {
		return traces[i].endTime.Before(traces[j].endTime)
	})

	// Remove oldest 20% to make room
	removeCount := len(traces) / 5
	if removeCount < 10 {
		removeCount = 10
	}

	for i := 0; i < removeCount && i < len(traces); i++ {
		delete(sc.completedTraces, traces[i].traceID)
	}

	sc.logger.Printf("🧹 Cleaned up %d old completed traces", removeCount)
}

// GetTrace retrieves a specific trace by ID
func (sc *SpanCorrelator) GetTrace(traceID string) (*CompletedTrace, bool) {
	sc.completedMutex.RLock()
	defer sc.completedMutex.RUnlock()

	trace, exists := sc.completedTraces[traceID]
	return trace, exists
}

// ListTraces returns a list of completed traces with optional filtering
func (sc *SpanCorrelator) ListTraces(limit int, offset int) []*CompletedTrace {
	sc.completedMutex.RLock()
	defer sc.completedMutex.RUnlock()

	// Convert map to slice and sort by end time (newest first)
	traces := make([]*CompletedTrace, 0, len(sc.completedTraces))
	for _, trace := range sc.completedTraces {
		traces = append(traces, trace)
	}

	sort.Slice(traces, func(i, j int) bool {
		return traces[i].EndTime.After(traces[j].EndTime)
	})

	// Apply pagination
	if offset >= len(traces) {
		return []*CompletedTrace{}
	}

	end := offset + limit
	if end > len(traces) {
		end = len(traces)
	}

	return traces[offset:end]
}

// SearchTraces searches for traces matching specific criteria
func (sc *SpanCorrelator) SearchTraces(criteria TraceSearchCriteria) []*CompletedTrace {
	sc.completedMutex.RLock()
	defer sc.completedMutex.RUnlock()

	var results []*CompletedTrace

	for _, trace := range sc.completedTraces {
		if sc.matchesSearchCriteria(trace, criteria) {
			results = append(results, trace)
		}
	}

	// Sort by end time (newest first)
	sort.Slice(results, func(i, j int) bool {
		return results[i].EndTime.After(results[j].EndTime)
	})

	// Apply limit
	if criteria.Limit > 0 && len(results) > criteria.Limit {
		results = results[:criteria.Limit]
	}

	return results
}

// TraceSearchCriteria defines search parameters for traces
type TraceSearchCriteria struct {
	ParentSpanID *string    `json:"parent_span_id,omitempty"`
	AgentName    *string    `json:"agent_name,omitempty"`
	Operation    *string    `json:"operation,omitempty"`
	Success      *bool      `json:"success,omitempty"`
	StartTime    *time.Time `json:"start_time,omitempty"`
	EndTime      *time.Time `json:"end_time,omitempty"`
	MinDuration  *int64     `json:"min_duration_ms,omitempty"`
	MaxDuration  *int64     `json:"max_duration_ms,omitempty"`
	Limit        int        `json:"limit,omitempty"`
}

// matchesSearchCriteria checks if a trace matches the search criteria
func (sc *SpanCorrelator) matchesSearchCriteria(trace *CompletedTrace, criteria TraceSearchCriteria) bool {
	// Check parent span ID
	if criteria.ParentSpanID != nil {
		found := false
		for _, span := range trace.Spans {
			if span.ParentSpan != nil && *span.ParentSpan == *criteria.ParentSpanID {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}

	// Check agent name
	if criteria.AgentName != nil {
		found := false
		for _, agent := range trace.Agents {
			if agent == *criteria.AgentName {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}

	// Check operation
	if criteria.Operation != nil {
		found := false
		for _, span := range trace.Spans {
			if strings.Contains(span.Operation, *criteria.Operation) {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}

	// Check success status
	if criteria.Success != nil && trace.Success != *criteria.Success {
		return false
	}

	// Check time range
	if criteria.StartTime != nil && trace.StartTime.Before(*criteria.StartTime) {
		return false
	}
	if criteria.EndTime != nil && trace.EndTime.After(*criteria.EndTime) {
		return false
	}

	// Check duration range
	durationMs := trace.Duration.Milliseconds()
	if criteria.MinDuration != nil && durationMs < *criteria.MinDuration {
		return false
	}
	if criteria.MaxDuration != nil && durationMs > *criteria.MaxDuration {
		return false
	}

	return true
}

// GetTraceCount returns the number of stored completed traces
func (sc *SpanCorrelator) GetTraceCount() int {
	sc.completedMutex.RLock()
	defer sc.completedMutex.RUnlock()
	return len(sc.completedTraces)
}
