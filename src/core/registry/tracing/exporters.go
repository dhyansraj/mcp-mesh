package tracing

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.17.0"
	oteltrace "go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	// Direct OTLP protobuf dependencies
	tracecollectorv1 "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	resourcepb "go.opentelemetry.io/proto/otlp/resource/v1"
	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
)

// OTLPSpanData represents a single span in OTLP format
type OTLPSpanData struct {
	TraceID                 string                 `json:"traceId"`
	SpanID                  string                 `json:"spanId"`
	ParentSpanID            string                 `json:"parentSpanId,omitempty"`
	Name                    string                 `json:"name"`
	Kind                    string                 `json:"kind"`
	StartTimeUnixNano       string                 `json:"startTimeUnixNano"`
	EndTimeUnixNano         string                 `json:"endTimeUnixNano"`
	Attributes              []OTLPAttribute        `json:"attributes"`
	Status                  OTLPStatus             `json:"status"`
}

// OTLPAttribute represents an attribute in OTLP format
type OTLPAttribute struct {
	Key   string    `json:"key"`
	Value OTLPValue `json:"value"`
}

// OTLPValue represents a value in OTLP format
type OTLPValue struct {
	StringValue string `json:"stringValue,omitempty"`
	IntValue    string `json:"intValue,omitempty"`
}

// OTLPStatus represents status in OTLP format
type OTLPStatus struct {
	Code string `json:"code"`
}

// OTLPResourceSpans represents the resource spans structure
type OTLPResourceSpans struct {
	Resource struct {
		Attributes []OTLPAttribute `json:"attributes"`
	} `json:"resource"`
	ScopeSpans []struct {
		Scope struct {
			Name    string `json:"name"`
			Version string `json:"version"`
		} `json:"scope"`
		Spans []OTLPSpanData `json:"spans"`
	} `json:"scopeSpans"`
}

// OTLPBatch represents the top-level OTLP structure
type OTLPBatch struct {
	Batches []OTLPResourceSpans `json:"batches"`
}

// ConsoleExporter exports traces to console/logs for development
type ConsoleExporter struct {
	logger *log.Logger
	pretty bool
}

// NewConsoleExporter creates a new console exporter
func NewConsoleExporter(pretty bool) *ConsoleExporter {
	return &ConsoleExporter{
		logger: log.New(os.Stdout, "[TRACE-EXPORT] ", log.LstdFlags),
		pretty: pretty,
	}
}

// ExportTrace exports a completed trace to console
func (ce *ConsoleExporter) ExportTrace(trace *CompletedTrace) error {
	if ce.pretty {
		ce.exportPrettyTrace(trace)
	} else {
		ce.exportJSONTrace(trace)
	}
	return nil
}

// exportPrettyTrace exports trace in human-readable format
func (ce *ConsoleExporter) exportPrettyTrace(trace *CompletedTrace) {
	ce.logger.Printf("TRACE %s (%v) - %s",
		trace.TraceID[:8],
		trace.Duration.Round(time.Millisecond),
		ce.getTraceStatus(trace))

	// Group spans by agent
	agentSpans := make(map[string][]*TraceSpan)
	for _, span := range trace.Spans {
		agentSpans[span.AgentName] = append(agentSpans[span.AgentName], span)
	}

	// Print spans grouped by agent
	for _, agentName := range trace.Agents {
		ce.logger.Printf("  Agent: %s", agentName)
		spans := agentSpans[agentName]

		for _, span := range spans {
			status := "OK"
			if span.Success != nil && !*span.Success {
				status = "FAIL"
			}

			duration := ""
			if span.EndTime != nil {
				duration = fmt.Sprintf(" (%v)", span.EndTime.Sub(span.StartTime).Round(time.Millisecond))
			}

			capability := ""
			if span.Capability != nil {
				capability = fmt.Sprintf(" [%s]", *span.Capability)
			}

			ce.logger.Printf("    %s %s%s%s", status, span.Operation, capability, duration)

			if span.ErrorMessage != nil {
				ce.logger.Printf("      Error: %s", *span.ErrorMessage)
			}
		}
	}
}

// exportJSONTrace exports trace in JSON format
func (ce *ConsoleExporter) exportJSONTrace(trace *CompletedTrace) {
	data, err := json.Marshal(trace)
	if err != nil {
		ce.logger.Printf("Failed to marshal trace: %v", err)
		return
	}
	ce.logger.Printf("TRACE_JSON: %s", string(data))
}

// getTraceStatus returns a human-readable trace status
func (ce *ConsoleExporter) getTraceStatus(trace *CompletedTrace) string {
	if trace.Success {
		return fmt.Sprintf("SUCCESS (%d spans across %d agents)", trace.SpanCount, trace.AgentCount)
	}
	return fmt.Sprintf("FAILED (%d spans across %d agents)", trace.SpanCount, trace.AgentCount)
}

// MultiExporter exports to multiple exporters
type MultiExporter struct {
	exporters []TraceExporter
	logger    *log.Logger
}

// NewMultiExporter creates a new multi-exporter
func NewMultiExporter(exporters ...TraceExporter) *MultiExporter {
	return &MultiExporter{
		exporters: exporters,
		logger:    log.New(os.Stdout, "[MULTI-EXPORT] ", log.LstdFlags),
	}
}

// ExportTrace exports to all configured exporters
func (me *MultiExporter) ExportTrace(trace *CompletedTrace) error {
	var errors []string

	for i, exporter := range me.exporters {
		if err := exporter.ExportTrace(trace); err != nil {
			errorMsg := fmt.Sprintf("exporter %d failed: %v", i, err)
			errors = append(errors, errorMsg)
			me.logger.Printf("Warning: %s", errorMsg)
		}
	}

	if len(errors) > 0 {
		return fmt.Errorf("export failures: %s", strings.Join(errors, "; "))
	}

	return nil
}

// JSONFileExporter exports traces to JSON files
type JSONFileExporter struct {
	outputDir string
	logger    *log.Logger
}

// NewJSONFileExporter creates a new JSON file exporter
func NewJSONFileExporter(outputDir string) *JSONFileExporter {
	return &JSONFileExporter{
		outputDir: outputDir,
		logger:    log.New(os.Stdout, "[FILE-EXPORT] ", log.LstdFlags),
	}
}

// ExportTrace exports trace to a JSON file
func (jfe *JSONFileExporter) ExportTrace(trace *CompletedTrace) error {
	// Create output directory if it doesn't exist
	if err := os.MkdirAll(jfe.outputDir, 0755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	// Generate filename with timestamp
	filename := fmt.Sprintf("trace_%s_%d.json",
		trace.TraceID[:8],
		trace.StartTime.Unix())
	filepath := fmt.Sprintf("%s/%s", jfe.outputDir, filename)

	// Write trace to file
	data, err := json.MarshalIndent(trace, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal trace: %w", err)
	}

	if err := os.WriteFile(filepath, data, 0644); err != nil {
		return fmt.Errorf("failed to write trace file: %w", err)
	}

	jfe.logger.Printf("Exported trace to: %s", filepath)
	return nil
}

// StatsExporter collects and exports trace statistics
type StatsExporter struct {
	stats  *TraceStats
	logger *log.Logger
}

// TraceStats accumulates statistics about traces
type TraceStats struct {
	TotalTraces    int64     `json:"total_traces"`
	SuccessTraces  int64     `json:"success_traces"`
	FailedTraces   int64     `json:"failed_traces"`
	TotalSpans     int64     `json:"total_spans"`
	TotalDuration  int64     `json:"total_duration_ms"`
	AvgDuration    float64   `json:"avg_duration_ms"`
	AgentsSeen     []string  `json:"agents_seen"`
	FirstTrace     time.Time `json:"first_trace"`
	LastTrace      time.Time `json:"last_trace"`
	agentSet       map[string]bool
}

// NewStatsExporter creates a new statistics exporter
func NewStatsExporter() *StatsExporter {
	return &StatsExporter{
		stats: &TraceStats{
			agentSet: make(map[string]bool),
		},
		logger: log.New(os.Stdout, "[STATS-EXPORT] ", log.LstdFlags),
	}
}

// ExportTrace processes trace for statistics
func (se *StatsExporter) ExportTrace(trace *CompletedTrace) error {
	se.stats.TotalTraces++
	se.stats.TotalSpans += int64(trace.SpanCount)
	se.stats.TotalDuration += trace.Duration.Milliseconds()

	if trace.Success {
		se.stats.SuccessTraces++
	} else {
		se.stats.FailedTraces++
	}

	// Update timing
	if se.stats.FirstTrace.IsZero() || trace.StartTime.Before(se.stats.FirstTrace) {
		se.stats.FirstTrace = trace.StartTime
	}
	if trace.EndTime.After(se.stats.LastTrace) {
		se.stats.LastTrace = trace.EndTime
	}

	// Update agents
	for _, agent := range trace.Agents {
		se.stats.agentSet[agent] = true
	}

	// Update averages
	se.stats.AvgDuration = float64(se.stats.TotalDuration) / float64(se.stats.TotalTraces)

	// Update agent list
	se.stats.AgentsSeen = make([]string, 0, len(se.stats.agentSet))
	for agent := range se.stats.agentSet {
		se.stats.AgentsSeen = append(se.stats.AgentsSeen, agent)
	}

	// Log periodic stats
	if se.stats.TotalTraces%10 == 0 {
		se.logger.Printf("Processed %d traces (%.1f%% success, avg %.1fms)",
			se.stats.TotalTraces,
			float64(se.stats.SuccessTraces)/float64(se.stats.TotalTraces)*100,
			se.stats.AvgDuration)
	}

	return nil
}

// GetStats returns current statistics
func (se *StatsExporter) GetStats() *TraceStats {
	return se.stats
}

// PrintStats prints current statistics to console
func (se *StatsExporter) PrintStats() {
	se.logger.Printf("📈 TRACE STATISTICS:")
	se.logger.Printf("  Total Traces: %d", se.stats.TotalTraces)
	se.logger.Printf("  Success Rate: %.1f%% (%d/%d)",
		float64(se.stats.SuccessTraces)/float64(se.stats.TotalTraces)*100,
		se.stats.SuccessTraces, se.stats.TotalTraces)
	se.logger.Printf("  Total Spans: %d", se.stats.TotalSpans)
	se.logger.Printf("  Avg Duration: %.1fms", se.stats.AvgDuration)
	se.logger.Printf("  Agents Seen: %d (%v)", len(se.stats.AgentsSeen), se.stats.AgentsSeen)
	if !se.stats.FirstTrace.IsZero() {
		se.logger.Printf("  Time Range: %s to %s",
			se.stats.FirstTrace.Format("15:04:05"),
			se.stats.LastTrace.Format("15:04:05"))
	}
}

// JaegerExporter exports traces to Jaeger via OTLP gRPC
type JaegerExporter struct {
	exporter        sdktrace.SpanExporter
	tracerProviders map[string]*sdktrace.TracerProvider  // Per-agent tracer providers
	tracers         map[string]oteltrace.Tracer           // Per-agent tracers
	logger          *log.Logger
	ctx             context.Context
	cancel          context.CancelFunc
}

// NewJaegerExporter creates a new Jaeger OTLP exporter
func NewJaegerExporter(endpoint string) (*JaegerExporter, error) {
	ctx, cancel := context.WithCancel(context.Background())

	// Create OTLP gRPC exporter for Jaeger
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithTLSCredentials(insecure.NewCredentials()),
		otlptracegrpc.WithDialOption(grpc.WithTransportCredentials(insecure.NewCredentials())),
	)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to create OTLP exporter: %w", err)
	}

	return &JaegerExporter{
		exporter:        exporter,
		tracerProviders: make(map[string]*sdktrace.TracerProvider),
		tracers:         make(map[string]oteltrace.Tracer),
		logger:          log.New(os.Stdout, "[JAEGER-EXPORT] ", log.LstdFlags),
		ctx:             ctx,
		cancel:          cancel,
	}, nil
}

// getTracerForAgent gets or creates a tracer for a specific agent
func (je *JaegerExporter) getTracerForAgent(agentName string) (oteltrace.Tracer, error) {
	if tracer, exists := je.tracers[agentName]; exists {
		return tracer, nil
	}

	// Create resource for this specific agent
	res, err := resource.New(je.ctx,
		resource.WithAttributes(
			semconv.ServiceNameKey.String(agentName),
			semconv.ServiceVersionKey.String("0.3.0"),
			semconv.DeploymentEnvironmentKey.String("development"),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create resource for agent %s: %w", agentName, err)
	}

	// Create tracer provider for this agent
	tracerProvider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(je.exporter),
		sdktrace.WithResource(res),
	)

	// Create tracer for this agent
	tracer := tracerProvider.Tracer("mcp-mesh")

	// Store both for reuse
	je.tracerProviders[agentName] = tracerProvider
	je.tracers[agentName] = tracer

	return tracer, nil
}

// ExportSpan exports an individual span immediately to Jaeger (stream-through mode)
func (je *JaegerExporter) EstablishSpanContext(event *TraceEvent) error {
	// JaegerExporter doesn't need context establishment since it doesn't support parent-child relationships in the same way
	return nil
}

func (je *JaegerExporter) ExportSpan(event *TraceEvent) error {
	ctx := je.ctx


	// Get tracer for this specific agent
	tracer, err := je.getTracerForAgent(event.AgentName)
	if err != nil {
		return fmt.Errorf("failed to get tracer for agent %s: %w", event.AgentName, err)
	}

	// Convert timestamp from float64 to time.Time
	timestamp := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))

	// Create span context - for immediate export, we can't wait for parent relationships
	// The OTel Collector will handle proper parent-child relationships during grouping
	spanCtx, otSpan := tracer.Start(ctx, event.Operation,
		oteltrace.WithTimestamp(timestamp),
	)

	// Set span attributes
	attributes := []attribute.KeyValue{
		attribute.String("mcp.agent.name", event.AgentName),
		attribute.String("mcp.agent.id", event.AgentID),
		attribute.String("mcp.operation", event.Operation),
		attribute.String("mcp.runtime", event.Runtime),
		attribute.String("mcp.trace_id", event.TraceID),
		attribute.String("mcp.span_id", event.SpanID),
		attribute.String("mcp.event_type", event.EventType),
	}

	if event.IPAddress != "" {
		attributes = append(attributes, attribute.String("mcp.agent.ip", event.IPAddress))
	}
	if event.Capability != nil && *event.Capability != "" {
		attributes = append(attributes, attribute.String("mcp.capability", *event.Capability))
	}
	if event.TargetAgent != nil && *event.TargetAgent != "" {
		attributes = append(attributes, attribute.String("mcp.target_agent", *event.TargetAgent))
	}
	if event.ParentSpan != nil && *event.ParentSpan != "" {
		attributes = append(attributes, attribute.String("mcp.parent_span", *event.ParentSpan))
	}

	otSpan.SetAttributes(attributes...)

	// Handle span completion for end events
	if event.EventType == "span_end" {
		if event.Success != nil {
			if *event.Success {
				otSpan.SetStatus(codes.Ok, "")
			} else {
				otSpan.SetStatus(codes.Error, "Operation failed")
				if event.ErrorMessage != nil && *event.ErrorMessage != "" {
					otSpan.SetAttributes(attribute.String("error.message", *event.ErrorMessage))
				}
			}
		}

		// End the span with the timestamp
		otSpan.End(oteltrace.WithTimestamp(timestamp))
	} else {
		// For span_start events, we'll end immediately since we're streaming
		// The OTel Collector will reconstruct proper timing from the events
		otSpan.End(oteltrace.WithTimestamp(timestamp))
	}

	// Force flush to ensure span is sent immediately
	if tracerProvider, exists := je.tracerProviders[event.AgentName]; exists {
		if err := tracerProvider.ForceFlush(ctx); err != nil {
			return fmt.Errorf("failed to flush span for agent %s: %w", event.AgentName, err)
		}
	}

	// Store context for reference (though we won't use it much in stream mode)
	_ = spanCtx

	return nil
}

// ExportTrace exports a completed trace to Jaeger
func (je *JaegerExporter) ExportTrace(trace *CompletedTrace) error {
	ctx := je.ctx


	// Sort spans by start time to maintain proper parent-child relationships
	spans := make([]*TraceSpan, len(trace.Spans))
	copy(spans, trace.Spans)
	sort.Slice(spans, func(i, j int) bool {
		return spans[i].StartTime.Before(spans[j].StartTime)
	})

	// Create spans using the tracer properly
	spanMap := make(map[string]oteltrace.Span)

	for _, span := range spans {
		// Get tracer for this specific agent
		tracer, err := je.getTracerForAgent(span.AgentName)
		if err != nil {
			continue
		}

		// Determine parent context
		var parentCtx context.Context = ctx
		if span.ParentSpan != nil {
			if parentSpan, exists := spanMap[*span.ParentSpan]; exists {
				parentCtx = oteltrace.ContextWithSpan(ctx, parentSpan)
			}
		}

		// Create span using the agent-specific tracer
		spanCtx, otSpan := tracer.Start(parentCtx, span.Operation,
			oteltrace.WithTimestamp(span.StartTime),
		)

		// Set span attributes including service name for this agent
		attributes := []attribute.KeyValue{
			attribute.String("service.name", span.AgentName),  // This makes each agent a separate service
			attribute.String("mcp.agent.name", span.AgentName),
			attribute.String("mcp.agent.id", span.AgentID),
			attribute.String("mcp.operation", span.Operation),
			attribute.String("mcp.runtime", span.Runtime),
			attribute.String("mcp.trace_id", span.TraceID),
			attribute.String("mcp.span_id", span.SpanID),
		}

		if span.IPAddress != "" {
			attributes = append(attributes, attribute.String("mcp.agent.ip", span.IPAddress))
		}
		if span.Capability != nil {
			attributes = append(attributes, attribute.String("mcp.capability", *span.Capability))
		}
		if span.TargetAgent != nil {
			attributes = append(attributes, attribute.String("mcp.target_agent", *span.TargetAgent))
		}
		if span.DurationMS != nil {
			attributes = append(attributes, attribute.Int64("mcp.duration_ms", *span.DurationMS))
		}
		if span.ParentSpan != nil {
			attributes = append(attributes, attribute.String("mcp.parent_span", *span.ParentSpan))
		}

		otSpan.SetAttributes(attributes...)

		// Set span status
		if span.Success != nil {
			if *span.Success {
				otSpan.SetStatus(codes.Ok, "")
			} else {
				otSpan.SetStatus(codes.Error, "Operation failed")
				if span.ErrorMessage != nil {
					otSpan.SetAttributes(attribute.String("error.message", *span.ErrorMessage))
				}
			}
		}

		// End span with correct timing
		if span.EndTime != nil {
			otSpan.End(oteltrace.WithTimestamp(*span.EndTime))
		} else {
			otSpan.End()
		}

		spanMap[span.SpanID] = otSpan

		// Store context for potential child spans
		ctx = spanCtx
	}

	// Force flush all tracer providers to ensure spans are sent to Jaeger
	for agentName, tracerProvider := range je.tracerProviders {
		if err := tracerProvider.ForceFlush(ctx); err != nil {
			return fmt.Errorf("failed to flush spans for agent %s to Jaeger: %w", agentName, err)
		}
	}

	return nil
}

// findRootSpan finds the root span (span with no parent)
func (je *JaegerExporter) findRootSpan(spans []*TraceSpan) *TraceSpan {
	for _, span := range spans {
		if span.ParentSpan == nil {
			return span
		}
	}
	// If no root found, return first span
	if len(spans) > 0 {
		return spans[0]
	}
	return nil
}

// parseTraceID converts string trace ID to OpenTelemetry TraceID
func (je *JaegerExporter) parseTraceID(traceIDStr string) (oteltrace.TraceID, error) {
	// Remove dashes from UUID format
	cleaned := strings.ReplaceAll(traceIDStr, "-", "")

	// Ensure we have 32 characters (128 bits)
	if len(cleaned) != 32 {
		return oteltrace.TraceID{}, fmt.Errorf("trace ID must be 32 characters, got %d", len(cleaned))
	}

	// Convert hex string to bytes
	var traceID oteltrace.TraceID
	for i := 0; i < 16; i++ {
		b, err := strconv.ParseUint(cleaned[i*2:i*2+2], 16, 8)
		if err != nil {
			return oteltrace.TraceID{}, fmt.Errorf("invalid hex in trace ID: %w", err)
		}
		traceID[i] = byte(b)
	}

	return traceID, nil
}

// parseSpanID converts string span ID to OpenTelemetry SpanID
func (je *JaegerExporter) parseSpanID(spanIDStr string) (oteltrace.SpanID, error) {
	// Remove dashes from UUID format and take first 16 characters (64 bits)
	cleaned := strings.ReplaceAll(spanIDStr, "-", "")
	if len(cleaned) > 16 {
		cleaned = cleaned[:16]
	}

	// Pad with zeros if too short
	for len(cleaned) < 16 {
		cleaned = "0" + cleaned
	}

	// Convert hex string to bytes
	var spanID oteltrace.SpanID
	for i := 0; i < 8; i++ {
		b, err := strconv.ParseUint(cleaned[i*2:i*2+2], 16, 8)
		if err != nil {
			return oteltrace.SpanID{}, fmt.Errorf("invalid hex in span ID: %w", err)
		}
		spanID[i] = byte(b)
	}

	return spanID, nil
}

// Close gracefully shuts down the Jaeger exporter
func (je *JaegerExporter) Close() error {
	je.logger.Println("🛑 Shutting down Jaeger exporter...")

	// Shutdown all tracer providers with timeout
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var errors []string
	for agentName, tracerProvider := range je.tracerProviders {
		if err := tracerProvider.Shutdown(shutdownCtx); err != nil {
			errors = append(errors, fmt.Sprintf("agent %s: %v", agentName, err))
		}
	}

	if len(errors) > 0 {
		return fmt.Errorf("failed to shutdown tracer providers: %s", strings.Join(errors, "; "))
	}

	je.cancel()
	je.logger.Println("✅ Jaeger exporter shut down")
	return nil
}

// ExportCompleteSpan exports a single complete execution trace as an OpenTelemetry span
func (je *JaegerExporter) ExportCompleteSpan(event *TraceEvent) error {

	// Get tracer for this agent
	tracer, err := je.getTracerForAgent(event.AgentName)
	if err != nil {
		return fmt.Errorf("failed to get tracer for agent %s: %w", event.AgentName, err)
	}

	// Parse timestamps
	startTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
	endTime := startTime
	if event.DurationMS != nil {
		endTime = startTime.Add(time.Duration(*event.DurationMS) * time.Millisecond)
	}

	// Create and complete the span with full timing information
	_, span := tracer.Start(je.ctx, event.Operation,
		oteltrace.WithTimestamp(startTime),
	)

	// Set attributes
	attributes := []attribute.KeyValue{
		attribute.String("service.name", event.AgentName),
		attribute.String("mcp.agent.name", event.AgentName),
		attribute.String("mcp.agent.id", event.AgentID),
		attribute.String("mcp.operation", event.Operation),
		attribute.String("mcp.runtime", event.Runtime),
		attribute.String("mcp.trace_id", event.TraceID),
		attribute.String("mcp.span_id", event.SpanID),
	}

	if event.ParentSpan != nil && *event.ParentSpan != "" {
		attributes = append(attributes, attribute.String("mcp.parent_span", *event.ParentSpan))
	}
	if event.DurationMS != nil {
		attributes = append(attributes, attribute.Int64("mcp.duration_ms", *event.DurationMS))
	}

	span.SetAttributes(attributes...)

	// Set span status
	if event.Success != nil {
		if *event.Success {
			span.SetStatus(codes.Ok, "")
		} else {
			span.SetStatus(codes.Error, "Operation failed")
			if event.ErrorMessage != nil && *event.ErrorMessage != "" {
				span.SetAttributes(attribute.String("error.message", *event.ErrorMessage))
			}
		}
	}

	// End the span with correct timing
	span.End(oteltrace.WithTimestamp(endTime))

	// Force flush to ensure span is sent immediately
	if tracerProvider, exists := je.tracerProviders[event.AgentName]; exists {
		if err := tracerProvider.ForceFlush(je.ctx); err != nil {
			return fmt.Errorf("failed to flush execution trace for agent %s: %w", event.AgentName, err)
		}
	}

	return nil
}

// OTLPExporter exports traces to any OTLP-compatible backend (Tempo, Jaeger, etc.)
// PendingSpan represents a span waiting to be exported
type PendingSpan struct {
	Event     *TraceEvent
	Timestamp time.Time
}

// TraceBuffer holds spans for a specific trace ID
type TraceBuffer struct {
	TraceID   string
	Spans     []*PendingSpan
	CreatedAt time.Time
	mutex     sync.RWMutex
}

type OTLPExporter struct {
	exporter        sdktrace.SpanExporter
	tracerProviders map[string]*sdktrace.TracerProvider  // Per-agent tracer providers
	tracers         map[string]oteltrace.Tracer          // Per-agent tracers
	logger          *log.Logger
	ctx             context.Context
	cancel          context.CancelFunc
	endpoint        string
	protocol        string
	// Track active spans by span ID to enable proper parent-child relationships
	activeSpans     map[string]context.Context
	spansMutex      sync.RWMutex
	// Track OpenTelemetry span objects that need to be completed during span_end
	pendingSpans    map[string]oteltrace.Span
	pendingMutex    sync.RWMutex

	// Trace buffering for ordered export
	traceBuffers     map[string]*TraceBuffer             // Buffer spans by trace ID
	bufferMutex      sync.RWMutex                        // Protect traceBuffers map
	bufferTimeout    time.Duration                       // How long to wait for complete traces
	flushTicker      *time.Ticker                        // Periodic buffer flush

	// Direct OTLP client for exact span ID preservation
	directClient     tracecollectorv1.TraceServiceClient
	directConn       *grpc.ClientConn
}

// NewOTLPExporter creates a new generic OTLP exporter
func NewOTLPExporter(endpoint, protocol string) (*OTLPExporter, error) {
	ctx, cancel := context.WithCancel(context.Background())

	var exporter sdktrace.SpanExporter
	var err error

	// Support both gRPC and HTTP protocols
	switch strings.ToLower(protocol) {
	case "http", "http/protobuf":
		// Create OTLP HTTP exporter
		exporter, err = otlptracehttp.New(ctx,
			otlptracehttp.WithEndpoint("http://"+endpoint),
			otlptracehttp.WithInsecure(),
		)
	case "grpc", "":
		// Create OTLP gRPC exporter (default)
		exporter, err = otlptracegrpc.New(ctx,
			otlptracegrpc.WithEndpoint(endpoint),
			otlptracegrpc.WithTLSCredentials(insecure.NewCredentials()),
			otlptracegrpc.WithDialOption(grpc.WithTransportCredentials(insecure.NewCredentials())),
		)
	default:
		cancel()
		return nil, fmt.Errorf("unsupported OTLP protocol: %s (supported: grpc, http)", protocol)
	}

	if err != nil {
		cancel()
		return nil, fmt.Errorf("failed to create OTLP exporter: %w", err)
	}

	// Create direct gRPC client for exact span ID preservation (only for gRPC protocol)
	var directClient tracecollectorv1.TraceServiceClient
	var directConn *grpc.ClientConn
	if strings.ToLower(protocol) == "grpc" || protocol == "" {
		directConn, err = grpc.Dial(endpoint,
			grpc.WithTransportCredentials(insecure.NewCredentials()),
		)
		if err != nil {
			cancel()
			return nil, fmt.Errorf("failed to create direct gRPC connection: %w", err)
		}
		directClient = tracecollectorv1.NewTraceServiceClient(directConn)
	}

	otlpExporter := &OTLPExporter{
		exporter:        exporter,
		tracerProviders: make(map[string]*sdktrace.TracerProvider),
		tracers:         make(map[string]oteltrace.Tracer),
		logger:          log.New(os.Stdout, "[OTLP-EXPORT] ", log.LstdFlags),
		ctx:             ctx,
		cancel:          cancel,
		endpoint:        endpoint,
		protocol:        protocol,
		activeSpans:     make(map[string]context.Context),
		pendingSpans:    make(map[string]oteltrace.Span),
		spansMutex:      sync.RWMutex{},

		// Initialize trace buffering
		traceBuffers:     make(map[string]*TraceBuffer),
		bufferMutex:      sync.RWMutex{},
		bufferTimeout:    1 * time.Second, // Wait up to 1 second for complete traces
		flushTicker:      time.NewTicker(500 * time.Millisecond), // Check for expired buffers every 500ms

		// Direct OTLP client for exact span ID preservation
		directClient:     directClient,
		directConn:       directConn,
	}

	// Start buffer flush routine
	go otlpExporter.bufferFlushLoop()

	return otlpExporter, nil
}

// getTracerForAgent gets or creates a tracer for a specific agent
func (oe *OTLPExporter) getTracerForAgent(agentName string) (oteltrace.Tracer, error) {
	if tracer, exists := oe.tracers[agentName]; exists {
		return tracer, nil
	}


	// Create resource for this specific agent
	res, err := resource.New(oe.ctx,
		resource.WithAttributes(
			semconv.ServiceNameKey.String(agentName),
			semconv.ServiceVersionKey.String("1.0.0"),
			attribute.String("telemetry.sdk.language", "go"),
			attribute.String("telemetry.sdk.name", "mcp-mesh"),
			attribute.String("deployment.environment", "docker-compose"),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create resource for agent %s: %w", agentName, err)
	}

	// Create tracer provider for this agent with proper resource
	// Each agent needs its own TracerProvider with distinct service.name resource attribute
	tracerProvider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(oe.exporter), // Use shared exporter for batching
		sdktrace.WithResource(res),        // Agent-specific resource with service.name
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
	)

	// Create tracer for this agent
	tracer := tracerProvider.Tracer(
		"mcp-mesh/"+agentName,
		oteltrace.WithInstrumentationVersion("1.0.0"),
	)

	// Store both for reuse and proper shutdown
	oe.tracerProviders[agentName] = tracerProvider
	oe.tracers[agentName] = tracer


	return tracer, nil
}

// ExportSpan exports a single span immediately (stream-through mode) with preserved trace correlation
// EstablishSpanContext creates span contexts for span_start events to enable proper parent-child relationships
func (oe *OTLPExporter) EstablishSpanContext(event *TraceEvent) error {

	// Parse the start time
	startTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))

	// Use context tracking to maintain proper parent-child span relationships
	oe.spansMutex.Lock()
	defer oe.spansMutex.Unlock()

	// Determine the context to use based on parent_span relationship
	ctx := oe.ctx
	if event.ParentSpan != nil && *event.ParentSpan != "" {
		// This span has a parent - look up the parent's context
		if parentCtx, exists := oe.activeSpans[*event.ParentSpan]; exists {
			ctx = parentCtx
		} else {
		}
	} else {
		// Root span - no parent
	}

	// Get tracer for this specific agent
	tracer, err := oe.getTracerForAgent(event.AgentName)
	if err != nil {
		return fmt.Errorf("failed to get tracer for agent %s: %w", event.AgentName, err)
	}

	// Create the span context - we start the span but don't end it yet
	spanCtx, span := tracer.Start(ctx, event.Operation,
		oteltrace.WithSpanKind(oteltrace.SpanKindServer),
		oteltrace.WithTimestamp(startTime),
	)

	// Store both the span context and the span object for later completion
	oe.activeSpans[event.SpanID] = spanCtx
	oe.pendingMutex.Lock()
	oe.pendingSpans[event.SpanID] = span
	oe.pendingMutex.Unlock()


	return nil
}

func (oe *OTLPExporter) ExportSpan(event *TraceEvent) error {

	// Use direct OTLP protobuf generation for exact span ID preservation
	if oe.directClient != nil {
		return oe.exportDirectOTLP(event)
	}

	// Fallback to SDK-based approach for HTTP protocol
	return oe.exportSDKSpan(event)
}

// exportDirectOTLP creates and exports spans using direct OTLP protobuf generation for exact span ID preservation
func (oe *OTLPExporter) exportDirectOTLP(event *TraceEvent) error {

	// Parse hex IDs to bytes for OTLP protobuf
	traceIDBytes, err := hex.DecodeString(strings.ReplaceAll(event.TraceID, "-", ""))
	if err != nil {
		return fmt.Errorf("failed to decode trace ID %s: %w", event.TraceID, err)
	}
	if len(traceIDBytes) != 16 {
		return fmt.Errorf("trace ID must be 16 bytes, got %d", len(traceIDBytes))
	}

	spanIDBytes, err := hex.DecodeString(strings.ReplaceAll(event.SpanID, "-", "")[:16])
	if err != nil {
		return fmt.Errorf("failed to decode span ID %s: %w", event.SpanID, err)
	}
	if len(spanIDBytes) != 8 {
		return fmt.Errorf("span ID must be 8 bytes, got %d", len(spanIDBytes))
	}

	// Parse parent span ID if present
	var parentSpanIDBytes []byte
	if event.ParentSpan != nil && *event.ParentSpan != "" && *event.ParentSpan != "null" {
		parentSpanIDBytes, err = hex.DecodeString(strings.ReplaceAll(*event.ParentSpan, "-", "")[:16])
		if err != nil {
			parentSpanIDBytes = nil
		} else if len(parentSpanIDBytes) != 8 {
			parentSpanIDBytes = nil
		}
	}

	// Parse timestamps
	startTimeNano := uint64(event.Timestamp * 1e9)
	endTimeNano := startTimeNano
	if event.DurationMS != nil {
		endTimeNano = startTimeNano + uint64(*event.DurationMS * 1e6)
	}

	// Determine span kind
	spanKind := tracepb.Span_SPAN_KIND_SERVER
	if event.ParentSpan != nil && *event.ParentSpan != "" {
		spanKind = tracepb.Span_SPAN_KIND_INTERNAL
	}

	// Create OTLP span with exact IDs
	span := &tracepb.Span{
		TraceId:           traceIDBytes,   // Exact ID from Redis
		SpanId:            spanIDBytes,    // Exact ID from Redis
		ParentSpanId:      parentSpanIDBytes,
		Name:              event.Operation,
		Kind:              spanKind,
		StartTimeUnixNano: startTimeNano,
		EndTimeUnixNano:   endTimeNano,
		Attributes:        oe.buildOTLPAttributes(event),
		Status: &tracepb.Status{
			Code: tracepb.Status_STATUS_CODE_OK,
		},
	}

	// Set error status if applicable
	if event.Success != nil && !*event.Success {
		span.Status.Code = tracepb.Status_STATUS_CODE_ERROR
		if event.ErrorMessage != nil {
			span.Status.Message = *event.ErrorMessage
		}
	}

	// Create resource spans grouped by service
	resourceSpans := &tracepb.ResourceSpans{
		Resource: &resourcepb.Resource{
			Attributes: []*commonpb.KeyValue{
				{
					Key: "service.name",
					Value: &commonpb.AnyValue{
						Value: &commonpb.AnyValue_StringValue{
							StringValue: event.AgentName,
						},
					},
				},
				{
					Key: "service.version",
					Value: &commonpb.AnyValue{
						Value: &commonpb.AnyValue_StringValue{
							StringValue: "1.0.0",
						},
					},
				},
				{
					Key: "deployment.environment",
					Value: &commonpb.AnyValue{
						Value: &commonpb.AnyValue_StringValue{
							StringValue: "docker-compose",
						},
					},
				},
			},
		},
		ScopeSpans: []*tracepb.ScopeSpans{
			{
				Scope: &commonpb.InstrumentationScope{
					Name:    "mcp-mesh/" + event.AgentName,
					Version: "1.0.0",
				},
				Spans: []*tracepb.Span{span},
			},
		},
	}

	// Send to Tempo via direct gRPC
	req := &tracecollectorv1.ExportTraceServiceRequest{
		ResourceSpans: []*tracepb.ResourceSpans{resourceSpans},
	}

	_, err = oe.directClient.Export(oe.ctx, req)
	if err != nil {
		return fmt.Errorf("failed to export direct OTLP span: %w", err)
	}

	return nil
}

// buildOTLPAttributes creates OTLP attributes from MCP trace event
func (oe *OTLPExporter) buildOTLPAttributes(event *TraceEvent) []*commonpb.KeyValue {
	attrs := []*commonpb.KeyValue{
		{
			Key: "mcp.agent.id",
			Value: &commonpb.AnyValue{
				Value: &commonpb.AnyValue_StringValue{
					StringValue: event.AgentID,
				},
			},
		},
		{
			Key: "mcp.operation",
			Value: &commonpb.AnyValue{
				Value: &commonpb.AnyValue_StringValue{
					StringValue: event.Operation,
				},
			},
		},
		{
			Key: "mcp.runtime",
			Value: &commonpb.AnyValue{
				Value: &commonpb.AnyValue_StringValue{
					StringValue: event.Runtime,
				},
			},
		},
	}

	if event.ParentSpan != nil && *event.ParentSpan != "" {
		attrs = append(attrs, &commonpb.KeyValue{
			Key: "mcp.parent.span",
			Value: &commonpb.AnyValue{
				Value: &commonpb.AnyValue_StringValue{
					StringValue: *event.ParentSpan,
				},
			},
		})
	}

	if event.DurationMS != nil {
		attrs = append(attrs, &commonpb.KeyValue{
			Key: "mcp.duration.ms",
			Value: &commonpb.AnyValue{
				Value: &commonpb.AnyValue_IntValue{
					IntValue: *event.DurationMS,
				},
			},
		})
	}

	return attrs
}

// exportSDKSpan creates and exports a span using OpenTelemetry SDK (fallback for HTTP protocol)
func (oe *OTLPExporter) exportSDKSpan(event *TraceEvent) error {
	// Parse exact IDs from Redis
	traceID, err := oteltrace.TraceIDFromHex(strings.ReplaceAll(event.TraceID, "-", ""))
	if err != nil {
		return fmt.Errorf("failed to parse trace ID %s: %w", event.TraceID, err)
	}

	spanID, err := oteltrace.SpanIDFromHex(strings.ReplaceAll(event.SpanID, "-", "")[:16])
	if err != nil {
		return fmt.Errorf("failed to parse span ID %s: %w", event.SpanID, err)
	}

	// Parse parent span ID if present
	var parentSpanID oteltrace.SpanID
	if event.ParentSpan != nil && *event.ParentSpan != "" && *event.ParentSpan != "null" {
		parentSpanID, err = oteltrace.SpanIDFromHex(strings.ReplaceAll(*event.ParentSpan, "-", "")[:16])
		if err != nil {
		}
	}


	// Create parent context if available
	ctx := oe.ctx
	if parentSpanID.IsValid() {
		parentSpanContext := oteltrace.NewSpanContext(oteltrace.SpanContextConfig{
			TraceID:    traceID,
			SpanID:     parentSpanID,
			TraceFlags: oteltrace.FlagsSampled,
			Remote:     true,
		})
		ctx = oteltrace.ContextWithSpanContext(ctx, parentSpanContext)
	} else {
		// For root spans, set trace context to preserve trace ID
		rootSpanContext := oteltrace.NewSpanContext(oteltrace.SpanContextConfig{
			TraceID:    traceID,
			SpanID:     oteltrace.SpanID{}, // Empty span ID - tracer will generate new one
			TraceFlags: oteltrace.FlagsSampled,
		})
		ctx = oteltrace.ContextWithSpanContext(ctx, rootSpanContext)
	}

	// Get tracer for this agent
	tracer, err := oe.getTracerForAgent(event.AgentName)
	if err != nil {
		return fmt.Errorf("failed to get tracer for agent %s: %w", event.AgentName, err)
	}

	// Parse timestamps
	startTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
	endTime := startTime
	if event.DurationMS != nil {
		endTime = startTime.Add(time.Duration(*event.DurationMS) * time.Millisecond)
	}

	// Create span with preserved context
	_, span := tracer.Start(ctx, event.Operation,
		oteltrace.WithSpanKind(oteltrace.SpanKindServer),
		oteltrace.WithTimestamp(startTime),
	)

	// Set span attributes
	span.SetAttributes(oe.buildSpanAttributes(event)...)

	// Set span status
	status := oe.buildSpanStatus(event)
	span.SetStatus(status.Code, status.Description)

	// End span with correct timing
	span.End(oteltrace.WithTimestamp(endTime))

	// Force flush to ensure immediate export
	if tracerProvider, exists := oe.tracerProviders[event.AgentName]; exists {
		if err := tracerProvider.ForceFlush(ctx); err != nil {
			return fmt.Errorf("failed to flush span: %w", err)
		}
	}

	oe.logger.Printf("🎯 SDK span export completed: %s/%s", traceID.String()[:16], spanID.String()[:16])
	return nil
}

// buildSpanAttributes creates OpenTelemetry attributes from MCP trace event
func (oe *OTLPExporter) buildSpanAttributes(event *TraceEvent) []attribute.KeyValue {
	attrs := []attribute.KeyValue{
		// service.name is set at resource level, not span level for proper TraceQL aggregation
		attribute.String("mcp.agent.name", event.AgentName),    // Agent identity in tags
		attribute.String("mcp.agent.id", event.AgentID),
		attribute.String("mcp.operation", event.Operation),
		attribute.String("mcp.event.type", event.EventType),
		attribute.String("mcp.runtime", event.Runtime),
		attribute.String("mcp.ip.address", event.IPAddress),
		attribute.String("mcp.trace.id", event.TraceID),
		attribute.String("mcp.span.id", event.SpanID),
	}

	if event.Capability != nil && *event.Capability != "" {
		attrs = append(attrs, attribute.String("mcp.capability", *event.Capability))
	}

	if event.TargetAgent != nil && *event.TargetAgent != "" {
		attrs = append(attrs, attribute.String("mcp.target.agent", *event.TargetAgent))
	}

	if event.ParentSpan != nil && *event.ParentSpan != "" {
		attrs = append(attrs, attribute.String("mcp.parent.span", *event.ParentSpan))
	}

	if event.DurationMS != nil {
		attrs = append(attrs, attribute.Int64("mcp.duration.ms", *event.DurationMS))
	}

	return attrs
}

// buildSpanStatus creates OpenTelemetry status from MCP trace event
func (oe *OTLPExporter) buildSpanStatus(event *TraceEvent) sdktrace.Status {
	// Default to Ok status for successful operations (fixes Grafana pie chart compatibility)
	if event.Success != nil && *event.Success {
		return sdktrace.Status{Code: codes.Ok, Description: "Success"}
	} else if event.Success != nil && !*event.Success {
		description := "Failed"
		if event.ErrorMessage != nil && *event.ErrorMessage != "" {
			description = *event.ErrorMessage
		}
		return sdktrace.Status{Code: codes.Error, Description: description}
	}
	// Default to Ok for spans without explicit success/failure indication
	return sdktrace.Status{Code: codes.Ok, Description: ""}
}


// ExportTrace exports a completed trace (correlation mode - not used in stream-through)
func (oe *OTLPExporter) ExportTrace(trace *CompletedTrace) error {
	oe.logger.Printf("📊 Exporting trace %s (%d spans) via OTLP", trace.TraceID[:8], len(trace.Spans))

	// Implementation similar to JaegerExporter but for generic OTLP
	// This would be used in correlation mode, but we're focusing on stream-through
	return fmt.Errorf("correlation mode not implemented for OTLP exporter - use stream-through mode")
}

// parseTraceID parses a trace ID string into OTEL TraceID
func (oe *OTLPExporter) parseTraceID(traceIDStr string) (oteltrace.TraceID, error) {
	// Remove dashes and ensure it's 32 hex characters (UUID format)
	cleaned := strings.ReplaceAll(traceIDStr, "-", "")
	if len(cleaned) != 32 {
		return oteltrace.TraceID{}, fmt.Errorf("trace ID must be 32 hex characters, got %d", len(cleaned))
	}

	// Convert hex string to TraceID (16 bytes)
	var traceID oteltrace.TraceID
	for i := 0; i < 16; i++ {
		b, err := strconv.ParseUint(cleaned[i*2:i*2+2], 16, 8)
		if err != nil {
			return oteltrace.TraceID{}, fmt.Errorf("invalid hex in trace ID: %w", err)
		}
		traceID[i] = byte(b)
	}

	return traceID, nil
}

// parseSpanID parses a span ID string into OTEL SpanID
func (oe *OTLPExporter) parseSpanID(spanIDStr string) (oteltrace.SpanID, error) {
	// Remove dashes and take first 16 chars (UUID to SpanID - 8 bytes)
	cleaned := strings.ReplaceAll(spanIDStr, "-", "")
	if len(cleaned) < 16 {
		return oteltrace.SpanID{}, fmt.Errorf("span ID too short: %s", spanIDStr)
	}

	// Take first 16 hex characters (8 bytes for SpanID)
	hexStr := cleaned[:16]

	// Convert hex string to SpanID (8 bytes)
	var spanID oteltrace.SpanID
	for i := 0; i < 8; i++ {
		b, err := strconv.ParseUint(hexStr[i*2:i*2+2], 16, 8)
		if err != nil {
			return oteltrace.SpanID{}, fmt.Errorf("invalid hex in span ID: %w", err)
		}
		spanID[i] = byte(b)
	}

	return spanID, nil
}

// Close gracefully shuts down the OTLP exporter
func (oe *OTLPExporter) Close() error {

	// Close direct gRPC connection if exists
	if oe.directConn != nil {
		if err := oe.directConn.Close(); err != nil {
		}
	}

	// Shutdown all tracer providers with timeout
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var errors []string
	for agentName, tracerProvider := range oe.tracerProviders {
		if err := tracerProvider.Shutdown(shutdownCtx); err != nil {
			errors = append(errors, fmt.Sprintf("agent %s: %v", agentName, err))
		}
	}

	oe.cancel()

	if len(errors) > 0 {
		return fmt.Errorf("failed to shutdown tracer providers: %s", strings.Join(errors, "; "))
	}

	return nil
}

// truncateID safely truncates an ID to max 8 characters
func truncateID(id string, maxLen int) string {
	if len(id) <= maxLen {
		return id
	}
	return id[:maxLen]
}

// parseTraceID converts a UUID string to OpenTelemetry trace ID
func parseTraceID(uuidStr string) (oteltrace.TraceID, error) {
	// Remove hyphens from UUID: "1322f09d-baee-4241-a45d-a4ee78dc199f" -> "1322f09dbaee4241a45da4ee78dc199f"
	cleanUUID := strings.ReplaceAll(uuidStr, "-", "")

	// Convert hex string to bytes
	bytes, err := hex.DecodeString(cleanUUID)
	if err != nil {
		return oteltrace.TraceID{}, fmt.Errorf("invalid trace ID format: %w", err)
	}

	// OpenTelemetry TraceID is 16 bytes
	if len(bytes) != 16 {
		return oteltrace.TraceID{}, fmt.Errorf("trace ID must be 16 bytes, got %d", len(bytes))
	}

	var traceID oteltrace.TraceID
	copy(traceID[:], bytes)
	return traceID, nil
}

// parseSpanID converts a UUID string to OpenTelemetry span ID
func parseSpanID(uuidStr string) (oteltrace.SpanID, error) {
	// Remove hyphens from UUID and take first 16 hex characters (8 bytes)
	cleanUUID := strings.ReplaceAll(uuidStr, "-", "")
	if len(cleanUUID) < 16 {
		return oteltrace.SpanID{}, fmt.Errorf("span ID too short: %s", uuidStr)
	}

	// Take first 16 hex characters for 8-byte span ID
	spanHex := cleanUUID[:16]
	bytes, err := hex.DecodeString(spanHex)
	if err != nil {
		return oteltrace.SpanID{}, fmt.Errorf("invalid span ID format: %w", err)
	}

	var spanID oteltrace.SpanID
	copy(spanID[:], bytes)
	return spanID, nil
}

// bufferFlushLoop periodically flushes expired trace buffers
func (oe *OTLPExporter) bufferFlushLoop() {
	for {
		select {
		case <-oe.ctx.Done():
			oe.logger.Println("🛑 Buffer flush loop stopping...")
			return
		case <-oe.flushTicker.C:
			oe.flushExpiredBuffers()
		}
	}
}

// flushExpiredBuffers exports traces that have been buffered too long
func (oe *OTLPExporter) flushExpiredBuffers() {
	oe.bufferMutex.Lock()
	defer oe.bufferMutex.Unlock()

	now := time.Now()
	var expiredTraces []string

	for traceID, buffer := range oe.traceBuffers {
		if now.Sub(buffer.CreatedAt) >= oe.bufferTimeout {
			expiredTraces = append(expiredTraces, traceID)
		}
	}

	for _, traceID := range expiredTraces {
		buffer := oe.traceBuffers[traceID]

		// Export all spans in the buffer
		oe.exportBufferedTrace(buffer)

		// Remove from buffer
		delete(oe.traceBuffers, traceID)
	}
}

// exportBufferedTrace exports all spans in a trace buffer in the correct order
func (oe *OTLPExporter) exportBufferedTrace(buffer *TraceBuffer) {
	buffer.mutex.RLock()
	defer buffer.mutex.RUnlock()

	// Sort spans by parent-child relationship (root first, then children)
	sortedSpans := oe.sortSpansByHierarchy(buffer.Spans)


	// Export spans in correct order
	for _, pendingSpan := range sortedSpans {
		if err := oe.ExportSpan(pendingSpan.Event); err != nil {
			oe.logger.Printf("Failed to export buffered span %s: %v",
				truncateID(pendingSpan.Event.SpanID, 8), err)
		}
	}
}

// sortSpansByHierarchy sorts spans so parents are processed before children
func (oe *OTLPExporter) sortSpansByHierarchy(spans []*PendingSpan) []*PendingSpan {
	// Simple approach: root spans first, then others
	var rootSpans []*PendingSpan
	var childSpans []*PendingSpan

	for _, span := range spans {
		if span.Event.ParentSpan == nil || *span.Event.ParentSpan == "null" || *span.Event.ParentSpan == "" {
			rootSpans = append(rootSpans, span)
		} else {
			childSpans = append(childSpans, span)
		}
	}

	// Return root spans first, then child spans
	result := make([]*PendingSpan, 0, len(spans))
	result = append(result, rootSpans...)
	result = append(result, childSpans...)

	return result
}

// ExportCompleteSpan buffers spans and exports them in correct order
func (oe *OTLPExporter) ExportCompleteSpan(event *TraceEvent) error {

	// Add span to buffer
	oe.bufferMutex.Lock()
	defer oe.bufferMutex.Unlock()

	buffer, exists := oe.traceBuffers[event.TraceID]
	if !exists {
		buffer = &TraceBuffer{
			TraceID:   event.TraceID,
			Spans:     make([]*PendingSpan, 0),
			CreatedAt: time.Now(),
		}
		oe.traceBuffers[event.TraceID] = buffer
	}

	buffer.mutex.Lock()
	buffer.Spans = append(buffer.Spans, &PendingSpan{
		Event:     event,
		Timestamp: time.Now(),
	})
	spanCount := len(buffer.Spans)
	buffer.mutex.Unlock()


	// Check if we should flush this trace immediately (heuristic: if we have 3+ spans for this trace)
	if spanCount >= 3 {
		oe.exportBufferedTrace(buffer)
		delete(oe.traceBuffers, event.TraceID)
	}

	return nil
}


// exportSingleSpan exports a single span using predetermined trace/span IDs
func (oe *OTLPExporter) exportSingleSpan(event *TraceEvent) error {

	// Parse the existing trace and span IDs from Python
	traceID, err := parseTraceID(event.TraceID)
	if err != nil {
		return fmt.Errorf("failed to parse trace ID %s: %w", event.TraceID, err)
	}

	spanID, err := parseSpanID(event.SpanID)
	if err != nil {
		return fmt.Errorf("failed to parse span ID %s: %w", event.SpanID, err)
	}

	// Parse parent span ID if present
	var parentSpanID oteltrace.SpanID
	if event.ParentSpan != nil && *event.ParentSpan != "" && *event.ParentSpan != "null" {
		parentSpanID, err = parseSpanID(*event.ParentSpan)
		if err != nil {
			// Continue without parent - treat as root span
		} else {
		}
	}

	// Parse timestamps - Python sends start_time and end_time as floats
	startTime := time.Unix(int64(event.Timestamp), int64((event.Timestamp-float64(int64(event.Timestamp)))*1e9))
	endTime := startTime
	if event.DurationMS != nil {
		endTime = startTime.Add(time.Duration(*event.DurationMS) * time.Millisecond)
	} else {
	}

	// CRITICAL FIX: Instead of using the tracer.Start() which auto-generates IDs,
	// we need to manually create OTLP span data with exact IDs and parent relationships
	return oe.exportSpanDirectlyToOTLP(event, traceID, spanID, parentSpanID, startTime, endTime)
}

// exportSpanDirectlyToOTLP creates OTLP span data with exact IDs and parent relationships
func (oe *OTLPExporter) exportSpanDirectlyToOTLP(event *TraceEvent, traceID oteltrace.TraceID, spanID oteltrace.SpanID, parentSpanID oteltrace.SpanID, startTime, endTime time.Time) error {

	// Build span attributes
	attributes := oe.buildSpanAttributes(event)
	attributes = append(attributes,
		// Remove service.name from span attributes - it's already set at resource level
		attribute.String("operation.name", event.Operation),
		attribute.String("span.name", event.Operation),
	)

	// Add parent info for debugging
	if parentSpanID.IsValid() {
		attributes = append(attributes,
			attribute.String("parent.span.id", parentSpanID.String()),
			attribute.String("span.kind", "child"),
		)
	} else {
		attributes = append(attributes,
			attribute.String("span.kind", "root"),
		)
	}

	// Create a tracer to export via the SDK but with manual span creation
	tracer, err := oe.getTracerForAgent(event.AgentName)
	if err != nil {
		return fmt.Errorf("failed to get tracer for agent %s: %w", event.AgentName, err)
	}

	// Create the proper context for parent-child relationships
	ctx := oe.ctx
	if parentSpanID.IsValid() {
		// Create parent span context for child spans
		parentSpanContextConfig := oteltrace.SpanContextConfig{
			TraceID:    traceID,
			SpanID:     parentSpanID,
			TraceFlags: oteltrace.FlagsSampled,
			Remote:     true, // Mark as remote for cross-service
		}
		parentSpanContext := oteltrace.NewSpanContext(parentSpanContextConfig)
		ctx = oteltrace.ContextWithSpanContext(oe.ctx, parentSpanContext)
	} else {
		// For root spans, we still need to set the trace context to use the predetermined trace ID
		// Without this, tracer.Start() will generate a new trace ID instead of using our Python trace ID
		rootSpanContextConfig := oteltrace.SpanContextConfig{
			TraceID:    traceID, // Use the predetermined trace ID from Python
			SpanID:     oteltrace.SpanID{}, // Empty span ID - tracer will generate a new one
			TraceFlags: oteltrace.FlagsSampled,
			Remote:     false,
		}
		rootSpanContext := oteltrace.NewSpanContext(rootSpanContextConfig)
		ctx = oteltrace.ContextWithSpanContext(oe.ctx, rootSpanContext)
	}

	// Start span with parent context - this automatically sets parentSpanId in OTLP
	_, span := tracer.Start(ctx, event.Operation,
		oteltrace.WithSpanKind(oteltrace.SpanKindServer),
		oteltrace.WithTimestamp(startTime),
	)

	// Set all attributes
	span.SetAttributes(attributes...)

	// Set status
	status := oe.buildSpanStatus(event)
	span.SetStatus(status.Code, status.Description)

	// End span with correct timing
	span.End(oteltrace.WithTimestamp(endTime))

	oe.logger.Printf("✅ Exported OTLP span: %s (parent: %s, duration: %v)",
		truncateID(event.SpanID, 8),
		func() string {
			if parentSpanID.IsValid() {
				return truncateID(fmt.Sprintf("%x", parentSpanID[:]), 8)
			}
			return "none"
		}(),
		endTime.Sub(startTime))

	return nil
}
