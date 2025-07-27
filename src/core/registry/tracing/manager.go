package tracing

import (
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"
)

// TracingManager manages the entire distributed tracing pipeline
type TracingManager struct {
	config           *TracingConfig
	consumer         *StreamConsumer
	processor        TraceEventProcessor
	otlpExporter     *OTLPExporter
	logger           *log.Logger
	enabled          bool
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

		// Create stream-through processor
		manager.processor = NewStreamThroughProcessor(otlpExporter)

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

	if err := tm.consumer.Start(); err != nil {
		return fmt.Errorf("failed to start consumer: %w", err)
	}

	return nil
}

// Stop stops the tracing manager
func (tm *TracingManager) Stop() error {
	if !tm.enabled {
		return nil
	}


	var errors []string

	if tm.consumer != nil {
		if err := tm.consumer.Stop(); err != nil {
			errors = append(errors, fmt.Sprintf("consumer stop failed: %v", err))
		}
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

// GetTrace retrieves a specific trace by ID (only available in correlation mode)
func (tm *TracingManager) GetTrace(traceID string) (*CompletedTrace, bool) {
	if !tm.enabled || tm.streamThroughMode {
		return nil, false
	}
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.GetTrace(traceID)
	}
	return nil, false
}

// ListTraces returns a list of completed traces with pagination (only available in correlation mode)
func (tm *TracingManager) ListTraces(limit, offset int) []*CompletedTrace {
	if !tm.enabled || tm.streamThroughMode {
		return []*CompletedTrace{}
	}
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.ListTraces(limit, offset)
	}
	return []*CompletedTrace{}
}

// SearchTraces searches for traces matching specific criteria (only available in correlation mode)
func (tm *TracingManager) SearchTraces(criteria TraceSearchCriteria) []*CompletedTrace {
	if !tm.enabled || tm.streamThroughMode {
		return []*CompletedTrace{}
	}
	if correlator, ok := tm.processor.(*SpanCorrelator); ok {
		return correlator.SearchTraces(criteria)
	}
	return []*CompletedTrace{}
}

// GetTraceCount returns the number of stored completed traces (only available in correlation mode)
func (tm *TracingManager) GetTraceCount() int {
	if !tm.enabled || tm.streamThroughMode {
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
		exporterType = "console"
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
	}
}

// LoadTracingConfigFromEnv loads tracing configuration from environment variables
func LoadTracingConfigFromEnv() *TracingConfig {
	return DefaultTracingConfig()
}
