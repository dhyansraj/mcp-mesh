package tracing

import (
	"fmt"
	"log"
	"math"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

// TracingManager manages the entire distributed tracing pipeline
type TracingManager struct {
	config            *TracingConfig
	consumer          *StreamConsumer
	processor         TraceEventProcessor
	otlpExporter      *OTLPExporter
	tempoClient       *TempoClient // For querying traces from Tempo in stream-through mode
	accumulator       *TraceAccumulator
	logger            *log.Logger
	enabled           bool
	streamThroughMode bool
}

// TracingConfig holds configuration for distributed tracing
type TracingConfig struct {
	Enabled              bool          `json:"enabled"`
	RedisURL             string        `json:"redis_url"`
	StreamName           string        `json:"stream_name"`
	ConsumerGroup        string        `json:"consumer_group"`
	ConsumerName         string        `json:"consumer_name"`
	BatchSize            int64         `json:"batch_size"`
	BlockTimeout         time.Duration `json:"block_timeout"`
	TraceTimeout         time.Duration `json:"trace_timeout"`
	ExporterType         string        `json:"exporter_type"`
	PrettyConsoleOutput  bool          `json:"pretty_console_output"`
	JSONOutputDirectory  string        `json:"json_output_directory,omitempty"`
	EnableStats          bool          `json:"enable_stats"`
	// Generic telemetry endpoints (OTLP compatible)
	TelemetryEndpoint    string        `json:"telemetry_endpoint,omitempty"`
	TelemetryProtocol    string        `json:"telemetry_protocol,omitempty"`
	// Tempo query endpoint for fetching traces (HTTP API)
	TempoQueryURL        string        `json:"tempo_query_url,omitempty"`
}

// NewTracingManager creates a new tracing manager with the given configuration
func NewTracingManager(config *TracingConfig) (*TracingManager, error) {
	if config == nil {
		config = DefaultTracingConfig()
	}

	manager := &TracingManager{
		config:  config,
		logger:  log.New(os.Stdout, "[TRACE-MANAGER] ", log.LstdFlags),
		enabled: config.Enabled,
	}

	if !config.Enabled {
		manager.logger.Println("Distributed tracing: disabled")
		return manager, nil
	}

	// Determine if we should use stream-through mode (for OTLP/telemetry backends)
	manager.streamThroughMode = strings.ToLower(config.ExporterType) == "otlp" ||
								strings.ToLower(config.ExporterType) == "telemetry"

	mode := "correlation"
	if manager.streamThroughMode {
		mode = "stream-through"

		if config.TelemetryEndpoint == "" {
			return nil, fmt.Errorf("telemetry endpoint not specified for stream-through mode (use TELEMETRY_ENDPOINT)")
		}

		// Create OTLP exporter (supports Tempo, Jaeger, and other OTLP backends)
		otlpExporter, err := NewOTLPExporter(config.TelemetryEndpoint, config.TelemetryProtocol)
		if err != nil {
			return nil, fmt.Errorf("failed to create OTLP exporter: %w", err)
		}
		manager.otlpExporter = otlpExporter

		// Create Tempo client for trace querying (Issue #310)
		if config.TempoQueryURL != "" {
			tc, err := NewTempoClient(config.TempoQueryURL)
			if err != nil {
				manager.logger.Printf("Warning: Tempo client disabled: %v", err)
			} else {
				manager.tempoClient = tc
				if u, parseErr := url.Parse(config.TempoQueryURL); parseErr == nil {
					manager.logger.Printf("Tempo query client initialized: %s://%s", u.Scheme, u.Host)
				} else {
					manager.logger.Printf("Tempo query client initialized")
				}
			}
		}

		// Create stream-through processor and wrap with accumulator
		streamProcessor := NewStreamThroughProcessor(otlpExporter)
		accumulator := NewTraceAccumulator(200, manager.logger)
		manager.accumulator = accumulator
		manager.processor = NewMultiProcessor(manager.logger, streamProcessor, accumulator)

	} else {
		// Use traditional correlation approach for other exporters
		exporter, err := manager.createExporter()
		if err != nil {
			return nil, fmt.Errorf("failed to create exporter: %w", err)
		}

		// Create correlator for non-Jaeger exporters
		correlator := NewSpanCorrelator(exporter, config.TraceTimeout)
		manager.processor = correlator
	}

	// Create consumer
	consumerConfig := &StreamConsumerConfig{
		RedisURL:      config.RedisURL,
		StreamName:    config.StreamName,
		ConsumerGroup: config.ConsumerGroup,
		ConsumerName:  config.ConsumerName,
		BatchSize:     config.BatchSize,
		BlockTimeout:  config.BlockTimeout,
		Enabled:       config.Enabled,
	}

	consumer, err := NewStreamConsumer(consumerConfig, manager.processor)
	if err != nil {
		return nil, fmt.Errorf("failed to create stream consumer: %w", err)
	}
	manager.consumer = consumer

	manager.logger.Printf("Distributed tracing: enabled, exporter=%s, mode=%s, endpoint=%s", config.ExporterType, mode, config.TelemetryEndpoint)
	return manager, nil
}

// Start starts the tracing manager
func (tm *TracingManager) Start() error {
	if !tm.enabled {
		return nil
	}

	if tm.accumulator != nil {
		tm.accumulator.Start()
	}

	if err := tm.consumer.Start(); err != nil {
		return fmt.Errorf("failed to start consumer: %w", err)
	}

	return nil
}

// Stop stops the tracing manager. The consumer is stopped first so that
// in-flight spans can still be processed by the accumulator before it shuts down.
func (tm *TracingManager) Stop() error {
	if !tm.enabled {
		return nil
	}

	var errors []string

	// Stop consumer first to drain in-flight spans before the accumulator shuts down
	if tm.consumer != nil {
		if err := tm.consumer.Stop(); err != nil {
			errors = append(errors, fmt.Sprintf("consumer stop failed: %v", err))
		}
	}

	// Now stop the accumulator — no more spans will arrive
	if tm.accumulator != nil {
		tm.accumulator.Stop()
	}

	// Stop processor (could be correlator or stream-through)
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		if err := correlator.Stop(); err != nil {
			errors = append(errors, fmt.Sprintf("correlator stop failed: %v", err))
		}
	}

	if tm.otlpExporter != nil {
		if err := tm.otlpExporter.Close(); err != nil {
			errors = append(errors, fmt.Sprintf("OTLP exporter stop failed: %v", err))
		}
	}

	if len(errors) > 0 {
		return fmt.Errorf("shutdown errors: %s", strings.Join(errors, "; "))
	}

	return nil
}

// createExporter creates the appropriate trace exporter based on configuration
func (tm *TracingManager) createExporter() (TraceExporter, error) {
	var exporters []TraceExporter

	switch strings.ToLower(tm.config.ExporterType) {
	case "console":
		exporters = append(exporters, NewConsoleExporter(tm.config.PrettyConsoleOutput))
	case "json":
		if tm.config.JSONOutputDirectory == "" {
			return nil, fmt.Errorf("json output directory not specified")
		}
		exporters = append(exporters, NewJSONFileExporter(tm.config.JSONOutputDirectory))
	case "otlp", "telemetry":
		if tm.config.TelemetryEndpoint == "" {
			return nil, fmt.Errorf("telemetry endpoint not specified")
		}
		otlpExporter, err := NewOTLPExporter(tm.config.TelemetryEndpoint, tm.config.TelemetryProtocol)
		if err != nil {
			return nil, fmt.Errorf("failed to create OTLP exporter: %w", err)
		}
		tm.otlpExporter = otlpExporter
		exporters = append(exporters, otlpExporter)
	case "multi", "multiple", "all":
		// Use multiple exporters
		exporters = append(exporters, NewConsoleExporter(tm.config.PrettyConsoleOutput))
		if tm.config.JSONOutputDirectory != "" {
			exporters = append(exporters, NewJSONFileExporter(tm.config.JSONOutputDirectory))
		}
		if tm.config.TelemetryEndpoint != "" {
			otlpExporter, err := NewOTLPExporter(tm.config.TelemetryEndpoint, tm.config.TelemetryProtocol)
			if err != nil {
				tm.logger.Printf("Failed to create OTLP exporter: %v", err)
			} else {
				tm.otlpExporter = otlpExporter
				exporters = append(exporters, otlpExporter)
			}
		}
	default:
		// Default to console
		exporters = append(exporters, NewConsoleExporter(tm.config.PrettyConsoleOutput))
	}

	// Always add stats exporter if enabled
	if tm.config.EnableStats {
		exporters = append(exporters, NewStatsExporter())
	}

	if len(exporters) == 1 {
		return exporters[0], nil
	}

	return NewMultiExporter(exporters...), nil
}

// GetInfo returns information about the tracing manager
func (tm *TracingManager) GetInfo() map[string]interface{} {
	info := map[string]interface{}{
		"enabled":       tm.enabled,
		"exporter_type": tm.config.ExporterType,
	}

	if tm.enabled {
		info["config"] = tm.config
		info["stream_through_mode"] = tm.streamThroughMode

		if tm.consumer != nil {
			info["consumer"] = tm.consumer.GetConsumerInfo()
		}

		// Only show correlator stats if we're using correlation mode
		if correlator, ok := tm.processor.(*SpanCorrelator); ok {
			info["correlator"] = correlator.GetStats()
		}
	}

	return info
}

// GetStats returns statistics if stats exporter is enabled (only available in correlation mode)
func (tm *TracingManager) GetStats() *TraceStats {
	if !tm.enabled || !tm.config.EnableStats || tm.streamThroughMode {
		return nil
	}

	// Only available when using correlator with traditional exporters
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		// We'd need to access the correlator's exporter, but for now return nil
		// Stats are not supported in stream-through mode
		_ = correlator
	}

	return nil
}

// GetTrace retrieves a specific trace by ID
// In correlation mode: queries local storage
// In stream-through mode: queries Tempo API (Issue #310)
func (tm *TracingManager) GetTrace(traceID string) (*CompletedTrace, bool) {
	if !tm.enabled {
		return nil, false
	}

	// Stream-through mode: query Tempo
	if tm.streamThroughMode {
		if tm.tempoClient == nil {
			tm.logger.Println("Cannot query traces: Tempo client not configured (set TEMPO_URL)")
			return nil, false
		}

		trace, err := tm.tempoClient.GetTrace(traceID)
		if err != nil {
			tm.logger.Printf("Failed to query trace %s from Tempo: %v", traceID, err)
			return nil, false
		}
		if trace == nil {
			return nil, false
		}
		return trace, true
	}

	// Correlation mode: query local storage
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.GetTrace(traceID)
	}
	return nil, false
}

// ListTraces returns a list of completed traces with pagination
func (tm *TracingManager) ListTraces(limit, offset int) []*CompletedTrace {
	if !tm.enabled {
		return []*CompletedTrace{}
	}

	// Stream-through mode: use accumulator's recent traces
	if tm.streamThroughMode {
		if tm.accumulator == nil {
			return []*CompletedTrace{}
		}
		summaries := tm.accumulator.GetRecentTraces(0) // 0 = all
		// Apply offset and limit
		if offset < 0 {
			offset = 0
		}
		if offset >= len(summaries) {
			return []*CompletedTrace{}
		}
		summaries = summaries[offset:]
		if limit > 0 && limit < len(summaries) {
			summaries = summaries[:limit]
		}
		return summariesToCompletedTraces(summaries)
	}

	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.ListTraces(limit, offset)
	}
	return []*CompletedTrace{}
}

// SearchTraces searches for traces matching specific criteria
func (tm *TracingManager) SearchTraces(criteria TraceSearchCriteria) []*CompletedTrace {
	if !tm.enabled {
		return []*CompletedTrace{}
	}

	// Stream-through mode: filter accumulator's recent traces
	if tm.streamThroughMode {
		if tm.accumulator == nil {
			return []*CompletedTrace{}
		}
		// Accumulator stores trace summaries, not span-level data —
		// cannot filter by ParentSpanID. Fail closed.
		if criteria.ParentSpanID != nil {
			return []*CompletedTrace{}
		}
		summaries := tm.accumulator.GetRecentTraces(0) // 0 = all
		var filtered []RecentTraceSummary
		for _, s := range summaries {
			if matchesCriteria(s, criteria) {
				filtered = append(filtered, s)
			}
		}
		limit := criteria.Limit
		if limit <= 0 {
			limit = 20
		}
		if limit < len(filtered) {
			filtered = filtered[:limit]
		}
		return summariesToCompletedTraces(filtered)
	}

	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.SearchTraces(criteria)
	}
	return []*CompletedTrace{}
}

// GetTraceCount returns the number of stored completed traces
func (tm *TracingManager) GetTraceCount() int {
	if !tm.enabled {
		return 0
	}
	if tm.streamThroughMode {
		if tm.accumulator != nil {
			return len(tm.accumulator.GetRecentTraces(0))
		}
		return 0
	}
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.GetTraceCount()
	}
	return 0
}

// PrintStats prints current statistics if available
func (tm *TracingManager) PrintStats() {
	if !tm.enabled || !tm.config.EnableStats {
		tm.logger.Println("📊 Statistics not available (tracing disabled or stats not enabled)")
		return
	}

	if tm.streamThroughMode {
		tm.logger.Println("📊 Statistics not available in stream-through mode (traces sent immediately to Jaeger)")
		return
	}

	tm.logger.Println("📊 Statistics only available in correlation mode")
}

// DefaultTracingConfig returns a default tracing configuration
func DefaultTracingConfig() *TracingConfig {
	// Check if tracing is enabled via environment variable
	enabled := strings.ToLower(os.Getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED")) == "true"

	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = "redis://localhost:6379"
	}

	batchSize := int64(100)
	if batchSizeStr := os.Getenv("TRACE_BATCH_SIZE"); batchSizeStr != "" {
		if size, err := strconv.ParseInt(batchSizeStr, 10, 64); err == nil {
			batchSize = size
		}
	}

	traceTimeout := 5 * time.Minute
	if timeoutStr := os.Getenv("TRACE_TIMEOUT"); timeoutStr != "" {
		if duration, err := time.ParseDuration(timeoutStr); err == nil {
			traceTimeout = duration
		}
	}

	exporterType := os.Getenv("TRACE_EXPORTER_TYPE")
	if exporterType == "" {
		exporterType = "otlp"
	}

	prettyOutput := strings.ToLower(os.Getenv("TRACE_PRETTY_OUTPUT")) != "false"
	enableStats := strings.ToLower(os.Getenv("TRACE_ENABLE_STATS")) != "false"

	// Generic telemetry configuration (OTLP compatible)
	telemetryEndpoint := os.Getenv("TELEMETRY_ENDPOINT")
	if telemetryEndpoint == "" {
		telemetryEndpoint = os.Getenv("OTLP_ENDPOINT") // Alternative name
	}
	if telemetryEndpoint == "" {
		telemetryEndpoint = "localhost:4317" // Default OTLP gRPC endpoint
	}

	telemetryProtocol := os.Getenv("TELEMETRY_PROTOCOL")
	if telemetryProtocol == "" {
		telemetryProtocol = "grpc" // Default to gRPC
	}

	// Tempo query URL for fetching traces (Issue #310)
	tempoQueryURL := GetTempoURLFromEnv()

	return &TracingConfig{
		Enabled:             enabled,
		RedisURL:            redisURL,
		StreamName:          "mesh:trace", // Matches Python publisher
		ConsumerGroup:       "mcp-mesh-registry-processors",
		ConsumerName:        "", // Will be auto-generated
		BatchSize:           batchSize,
		BlockTimeout:        5 * time.Second,
		TraceTimeout:        traceTimeout,
		ExporterType:        exporterType,
		PrettyConsoleOutput: prettyOutput,
		JSONOutputDirectory: os.Getenv("TRACE_JSON_OUTPUT_DIR"),
		EnableStats:         enableStats,
		TelemetryEndpoint:   telemetryEndpoint,
		TelemetryProtocol:   telemetryProtocol,
		TempoQueryURL:       tempoQueryURL,
	}
}

// LoadTracingConfigFromEnv loads tracing configuration from environment variables
func LoadTracingConfigFromEnv() *TracingConfig {
	return DefaultTracingConfig()
}

// GetRedisURLFromEnv returns the Redis URL from environment variables
func GetRedisURLFromEnv() string {
	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = "redis://localhost:6379"
	}
	return redisURL
}

// RecentTraceSummary is a lightweight trace summary for dashboard display
type RecentTraceSummary struct {
	TraceID       string    `json:"trace_id"`
	RootAgent     string    `json:"root_agent"`
	RootOperation string    `json:"root_operation"`
	DurationMs    int64     `json:"duration_ms"`
	StartTime     time.Time `json:"start_time"`
	SpanCount     int       `json:"span_count"`
	AgentCount    int       `json:"agent_count"`
	Success       bool      `json:"success"`
	Agents        []string  `json:"agents"`
}

// EdgeStats represents aggregated call stats for a dependency edge
type EdgeStats struct {
	Source       string  `json:"source"`
	Target       string  `json:"target"`
	CallCount    int     `json:"call_count"`
	ErrorCount   int     `json:"error_count"`
	ErrorRate    float64 `json:"error_rate"`
	AvgLatencyMs float64 `json:"avg_latency_ms"`
	P99LatencyMs float64 `json:"p99_latency_ms"`
	MaxLatencyMs int64   `json:"max_latency_ms"`
	MinLatencyMs int64   `json:"min_latency_ms"`
}

// GetRecentTraces returns recent trace summaries. Prefers the in-memory
// accumulator when available, falling back to the Tempo search API.
func (tm *TracingManager) GetRecentTraces(limit int) ([]RecentTraceSummary, error) {
	if !tm.enabled {
		return []RecentTraceSummary{}, nil
	}

	// Prefer accumulator (fast, in-memory)
	if tm.accumulator != nil {
		return tm.accumulator.GetRecentTraces(limit), nil
	}

	if !tm.streamThroughMode || tm.tempoClient == nil {
		return []RecentTraceSummary{}, nil
	}

	results, err := tm.tempoClient.SearchRecentTraces(limit)
	if err != nil {
		return nil, fmt.Errorf("failed to search recent traces: %w", err)
	}

	summaries := make([]RecentTraceSummary, 0, len(results))
	for _, r := range results {
		startNano := parseNanoTimestamp(r.StartTimeUnixNano)
		startTime := time.Unix(0, startNano)

		// Fetch full trace details to get span/agent counts and success status
		trace, err := tm.tempoClient.GetTrace(r.TraceID)
		if err != nil || trace == nil {
			// Fall back to search result data only
			summaries = append(summaries, RecentTraceSummary{
				TraceID:       r.TraceID,
				RootAgent:     r.RootServiceName,
				RootOperation: r.RootTraceName,
				DurationMs:    r.DurationMs,
				StartTime:     startTime,
				SpanCount:     0,
				AgentCount:    0,
				Success:       true,
				Agents:        []string{r.RootServiceName},
			})
			continue
		}

		summaries = append(summaries, RecentTraceSummary{
			TraceID:       r.TraceID,
			RootAgent:     r.RootServiceName,
			RootOperation: r.RootTraceName,
			DurationMs:    r.DurationMs,
			StartTime:     startTime,
			SpanCount:     trace.SpanCount,
			AgentCount:    trace.AgentCount,
			Success:       trace.Success,
			Agents:        trace.Agents,
		})
	}

	return summaries, nil
}

// GetEdgeStats computes aggregated edge statistics. Prefers the in-memory
// accumulator when available, falling back to Tempo trace analysis.
func (tm *TracingManager) GetEdgeStats(limit int) ([]EdgeStats, error) {
	if !tm.enabled {
		return []EdgeStats{}, nil
	}

	// Prefer accumulator (fast, in-memory)
	if tm.accumulator != nil {
		edges := tm.accumulator.GetEdgeStats()
		if limit > 0 && limit < len(edges) {
			edges = edges[:limit]
		}
		return edges, nil
	}

	if !tm.streamThroughMode || tm.tempoClient == nil {
		return []EdgeStats{}, nil
	}

	// Get recent trace IDs from Tempo search
	results, err := tm.tempoClient.SearchRecentTraces(limit)
	if err != nil {
		return nil, fmt.Errorf("failed to search traces for edge stats: %w", err)
	}

	// edgeKey -> list of observations
	type edgeObs struct {
		durationMs int64
		success    bool
	}
	edgeData := make(map[string][]edgeObs)

	for _, r := range results {
		trace, err := tm.tempoClient.GetTrace(r.TraceID)
		if err != nil || trace == nil {
			continue
		}

		// Build spanID -> agentName map
		spanAgent := make(map[string]string)
		for _, span := range trace.Spans {
			spanAgent[span.SpanID] = span.AgentName
		}

		// Detect cross-agent edges from parent-child relationships
		for _, span := range trace.Spans {
			if span.ParentSpan == nil {
				continue
			}
			parentAgent, ok := spanAgent[*span.ParentSpan]
			if !ok {
				continue
			}
			childAgent := span.AgentName
			if parentAgent == childAgent {
				continue
			}

			key := parentAgent + " -> " + childAgent
			dur := int64(0)
			if span.DurationMS != nil {
				dur = *span.DurationMS
			}
			success := true
			if span.Success != nil {
				success = *span.Success
			}
			edgeData[key] = append(edgeData[key], edgeObs{durationMs: dur, success: success})
		}
	}

	// Aggregate per edge
	edges := make([]EdgeStats, 0, len(edgeData))
	for key, observations := range edgeData {
		parts := strings.SplitN(key, " -> ", 2)
		if len(parts) != 2 {
			continue
		}

		callCount := len(observations)
		errorCount := 0
		var totalLatency int64
		var maxLatency int64
		minLatency := int64(math.MaxInt64)
		latencies := make([]int64, 0, callCount)

		for _, obs := range observations {
			if !obs.success {
				errorCount++
			}
			totalLatency += obs.durationMs
			latencies = append(latencies, obs.durationMs)
			if obs.durationMs > maxLatency {
				maxLatency = obs.durationMs
			}
			if obs.durationMs < minLatency {
				minLatency = obs.durationMs
			}
		}

		sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })

		avgLatency := float64(totalLatency) / float64(callCount)
		// ErrorRate as a percentage (0-100) for direct display in the UI
		errorRate := 100.0 * float64(errorCount) / float64(callCount)

		// P99: index at 99th percentile
		p99Index := int(math.Ceil(float64(callCount)*0.99)) - 1
		if p99Index < 0 {
			p99Index = 0
		}
		if p99Index >= callCount {
			p99Index = callCount - 1
		}
		p99Latency := float64(latencies[p99Index])

		edges = append(edges, EdgeStats{
			Source:       parts[0],
			Target:       parts[1],
			CallCount:    callCount,
			ErrorCount:   errorCount,
			ErrorRate:    errorRate,
			AvgLatencyMs: avgLatency,
			P99LatencyMs: p99Latency,
			MaxLatencyMs: maxLatency,
			MinLatencyMs: minLatency,
		})
	}

	// Sort edges by call count descending for consistent ordering
	sort.Slice(edges, func(i, j int) bool {
		return edges[i].CallCount > edges[j].CallCount
	})

	return edges, nil
}

// GetAccumulator returns the trace accumulator (may be nil if tracing is
// disabled or not in stream-through mode).
func (tm *TracingManager) GetAccumulator() *TraceAccumulator {
	return tm.accumulator
}

// GetAgentActivity returns per-agent span counts from the accumulator.
func (tm *TracingManager) GetAgentActivity() map[string]int {
	if tm.accumulator != nil {
		return tm.accumulator.GetAgentActivity()
	}
	return map[string]int{}
}

// summariesToCompletedTraces converts RecentTraceSummary slice to CompletedTrace slice
func summariesToCompletedTraces(summaries []RecentTraceSummary) []*CompletedTrace {
	result := make([]*CompletedTrace, len(summaries))
	for i, s := range summaries {
		result[i] = &CompletedTrace{
			TraceID:    s.TraceID,
			StartTime:  s.StartTime,
			EndTime:    s.StartTime.Add(time.Duration(s.DurationMs) * time.Millisecond),
			Duration:   time.Duration(s.DurationMs) * time.Millisecond,
			Success:    s.Success,
			SpanCount:  s.SpanCount,
			AgentCount: s.AgentCount,
			Agents:     s.Agents,
		}
	}
	return result
}

// matchesCriteria checks if a RecentTraceSummary matches search criteria
func matchesCriteria(s RecentTraceSummary, c TraceSearchCriteria) bool {
	if c.AgentName != nil {
		found := false
		for _, a := range s.Agents {
			if a == *c.AgentName {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	if c.Operation != nil && s.RootOperation != *c.Operation {
		return false
	}
	if c.Success != nil && s.Success != *c.Success {
		return false
	}
	if c.StartTime != nil && s.StartTime.Before(*c.StartTime) {
		return false
	}
	if c.EndTime != nil {
		endTime := s.StartTime.Add(time.Duration(s.DurationMs) * time.Millisecond)
		if endTime.After(*c.EndTime) {
			return false
		}
	}
	if c.MinDuration != nil && s.DurationMs < *c.MinDuration {
		return false
	}
	if c.MaxDuration != nil && s.DurationMs > *c.MaxDuration {
		return false
	}
	return true
}
