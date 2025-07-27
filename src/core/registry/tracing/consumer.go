package tracing

import (
	"context"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
)

// StreamConsumer handles Redis Streams consumption for distributed tracing
type StreamConsumer struct {
	client        *redis.Client
	streamName    string
	consumerGroup string
	consumerName  string
	enabled       bool
	logger        *log.Logger
	batchSize     int64
	blockTimeout  time.Duration
	processor     TraceEventProcessor
	ctx           context.Context
	cancel        context.CancelFunc
	wg            sync.WaitGroup
	running       bool
	mu            sync.RWMutex
}

// TraceEventProcessor interface for processing trace events
type TraceEventProcessor interface {
	ProcessTraceEvent(event *TraceEvent) error
}

// StreamThroughProcessor processes trace events by immediately exporting them
type StreamThroughProcessor struct {
	spanExporter SpanExporter
	logger       *log.Logger
}

// NewStreamThroughProcessor creates a new stream-through processor
func NewStreamThroughProcessor(spanExporter SpanExporter) *StreamThroughProcessor {
	return &StreamThroughProcessor{
		spanExporter: spanExporter,
		logger:       log.New(os.Stdout, "[STREAM-THROUGH] ", log.LstdFlags),
	}
}

// ProcessTraceEvent processes a trace event by immediately exporting the span
func (stp *StreamThroughProcessor) ProcessTraceEvent(event *TraceEvent) error {


	// Handle both dual-event (span_start/span_end) and single-event (execution_trace) patterns
	if event.EventType == "span_start" {
		// For span_start events, just establish the context without creating the actual span
		if err := stp.spanExporter.EstablishSpanContext(event); err != nil {

			return fmt.Errorf("failed to establish span context: %w", err)
		}

		return nil
	} else if event.EventType == "span_end" {
		// Export the span immediately to OTLP backend
		if err := stp.spanExporter.ExportSpan(event); err != nil {

			return fmt.Errorf("failed to export span: %w", err)
		}
	} else if event.EventType == "" && event.Operation != "" {
		// Handle single execution trace events from Python (no EventType, but has function_name/operation)


		// Convert execution trace to complete span and export immediately
		if err := stp.spanExporter.ExportCompleteSpan(event); err != nil {

			return fmt.Errorf("failed to export complete span: %w", err)
		}
	} else {

		return nil
	}


		return nil
}

// StreamConsumerConfig configuration for the stream consumer
type StreamConsumerConfig struct {
	RedisURL      string
	StreamName    string
	ConsumerGroup string
	ConsumerName  string
	BatchSize     int64
	BlockTimeout  time.Duration
	Enabled       bool
}

// NewStreamConsumer creates a new Redis Streams consumer for trace events
func NewStreamConsumer(config *StreamConsumerConfig, processor TraceEventProcessor) (*StreamConsumer, error) {
	if !config.Enabled {
		return &StreamConsumer{
			enabled: false,
			logger:  log.New(os.Stdout, "[TRACE-CONSUMER] ", log.LstdFlags),
		}, nil
	}

	// Parse Redis URL
	opts, err := redis.ParseURL(config.RedisURL)
	if err != nil {
		return nil, fmt.Errorf("invalid Redis URL: %w", err)
	}

	client := redis.NewClient(opts)

	// Test connection
	ctx := context.Background()
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("failed to connect to Redis: %w", err)
	}

	// Generate unique consumer name if not provided
	consumerName := config.ConsumerName
	if consumerName == "" {
		hostname, _ := os.Hostname()
		pid := os.Getpid()
		consumerName = fmt.Sprintf("registry-%s-%d", hostname, pid)
	}

	ctx, cancel := context.WithCancel(context.Background())

	consumer := &StreamConsumer{
		client:        client,
		streamName:    config.StreamName,
		consumerGroup: config.ConsumerGroup,
		consumerName:  consumerName,
		enabled:       true,
		logger:        log.New(os.Stdout, "[TRACE-CONSUMER] ", log.LstdFlags),
		batchSize:     config.BatchSize,
		blockTimeout:  config.BlockTimeout,
		processor:     processor,
		ctx:           ctx,
		cancel:        cancel,
	}

	return consumer, nil
}

// Start begins consuming trace events from Redis Streams
func (sc *StreamConsumer) Start() error {
	if !sc.enabled {
		return nil
	}

	sc.mu.Lock()
	if sc.running {
		sc.mu.Unlock()
		return fmt.Errorf("consumer is already running")
	}
	sc.running = true
	sc.mu.Unlock()



	// Create consumer group if it doesn't exist
	if err := sc.createConsumerGroup(); err != nil {
		return fmt.Errorf("failed to create consumer group: %w", err)
	}

	// Start consumption in background
	sc.wg.Add(1)
	go sc.consumeLoop()

	return nil
}

// Stop gracefully stops the consumer
func (sc *StreamConsumer) Stop() error {
	if !sc.enabled {
		return nil
	}

	sc.mu.Lock()
	if !sc.running {
		sc.mu.Unlock()
		return nil
	}
	sc.running = false
	sc.mu.Unlock()


	// Cancel context to signal stop
	sc.cancel()

	// Wait for consumption loop to finish
	sc.wg.Wait()

	// Close Redis client
	if err := sc.client.Close(); err != nil {

	}

	return nil
}

// createConsumerGroup creates the consumer group if it doesn't exist
func (sc *StreamConsumer) createConsumerGroup() error {
	// Try to create the consumer group with MKSTREAM option to auto-create the stream
	err := sc.client.XGroupCreateMkStream(sc.ctx, sc.streamName, sc.consumerGroup, "0").Err()
	if err != nil {
		// If group already exists, that's fine
		if strings.Contains(err.Error(), "BUSYGROUP") {

			return nil
		}
		return fmt.Errorf("failed to create consumer group: %w", err)
	}


	return nil
}

// consumeLoop is the main consumption loop
func (sc *StreamConsumer) consumeLoop() {
	defer sc.wg.Done()



	for {
		select {
		case <-sc.ctx.Done():
			return
		default:
			if err := sc.processNextBatch(); err != nil {

				// Continue processing even if there's an error
				time.Sleep(1 * time.Second)
			}
		}
	}
}

// processNextBatch processes the next batch of messages
func (sc *StreamConsumer) processNextBatch() error {
	// Read from consumer group (pending messages first, then new ones)
	args := &redis.XReadGroupArgs{
		Group:    sc.consumerGroup,
		Consumer: sc.consumerName,
		Streams:  []string{sc.streamName, ">"},
		Count:    sc.batchSize,
		Block:    sc.blockTimeout,
	}

	result, err := sc.client.XReadGroup(sc.ctx, args).Result()
	if err != nil {
		if err == redis.Nil {
			// No new messages, this is normal
			return nil
		}
		return fmt.Errorf("failed to read from stream: %w", err)
	}

	// Process each stream (should only be one in our case)
	for _, stream := range result {
		for _, message := range stream.Messages {
			if err := sc.processMessage(message); err != nil {
				// Continue processing other messages even if one fails
				sc.logger.Printf("ERROR: Failed to process message %s: %v", message.ID, err)
				continue
			}

			// Acknowledge successful processing
			if err := sc.client.XAck(sc.ctx, sc.streamName, sc.consumerGroup, message.ID).Err(); err != nil {
				sc.logger.Printf("WARN: Failed to acknowledge message %s: %v", message.ID, err)
			}
		}
	}

	return nil
}

// processMessage processes a single Redis stream message
func (sc *StreamConsumer) processMessage(message redis.XMessage) error {
	// Convert Redis message to TraceEvent
	event := &TraceEvent{}
	if err := event.FromRedisMap(message.Values); err != nil {
		return fmt.Errorf("failed to parse trace event: %w", err)
	}

	// Debug logging for development


	// Process the event
	if err := sc.processor.ProcessTraceEvent(event); err != nil {
		return fmt.Errorf("failed to process trace event: %w", err)
	}

	return nil
}

// GetConsumerInfo returns information about the consumer
func (sc *StreamConsumer) GetConsumerInfo() map[string]interface{} {
	sc.mu.RLock()
	defer sc.mu.RUnlock()

	info := map[string]interface{}{
		"enabled":        sc.enabled,
		"running":        sc.running,
		"stream_name":    sc.streamName,
		"consumer_group": sc.consumerGroup,
		"consumer_name":  sc.consumerName,
	}

	if sc.enabled && sc.client != nil {
		// Get stream info
		if streamInfo, err := sc.client.XInfoStream(sc.ctx, sc.streamName).Result(); err == nil {
			info["stream_length"] = streamInfo.Length
			info["stream_last_entry_id"] = streamInfo.LastGeneratedID
		}

		// Get consumer group info
		if groupInfo, err := sc.client.XInfoGroups(sc.ctx, sc.streamName).Result(); err == nil {
			for _, group := range groupInfo {
				if group.Name == sc.consumerGroup {
					info["group_pending"] = group.Pending
					info["group_last_delivered_id"] = group.LastDeliveredID
					break
				}
			}
		}
	}

	return info
}

// DefaultStreamConsumerConfig returns a default configuration
func DefaultStreamConsumerConfig() *StreamConsumerConfig {
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

	return &StreamConsumerConfig{
		RedisURL:      redisURL,
		StreamName:    "mesh:trace", // Matches Python publisher
		ConsumerGroup: "mcp-mesh-registry-processors",
		ConsumerName:  "", // Will be auto-generated
		BatchSize:     batchSize,
		BlockTimeout:  5 * time.Second,
		Enabled:       enabled,
	}
}
