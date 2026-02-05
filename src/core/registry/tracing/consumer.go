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

// ConnectionState represents the current state of Redis connection
type ConnectionState string

const (
	StateDisconnected ConnectionState = "disconnected"
	StateConnecting   ConnectionState = "connecting"
	StateConnected    ConnectionState = "connected"
	StateFailed       ConnectionState = "failed"
)

// StreamConsumer handles Redis Streams consumption for distributed tracing
// with resilient connection management - Redis is optional
type StreamConsumer struct {
	// Configuration (stored for reconnection)
	config *StreamConsumerConfig

	// Redis client (may be nil if not connected)
	client *redis.Client

	// Consumer identity
	streamName    string
	consumerGroup string
	consumerName  string

	// State
	enabled         bool
	connectionState ConnectionState
	lastError       error
	lastErrorTime   time.Time
	retryCount      int

	// Runtime
	logger       *log.Logger
	batchSize    int64
	blockTimeout time.Duration
	processor    TraceEventProcessor
	ctx          context.Context
	cancel       context.CancelFunc
	wg           sync.WaitGroup
	running      bool
	consuming    bool
	mu           sync.RWMutex
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
// This never fails - it stores config and attempts connection in background
func NewStreamConsumer(config *StreamConsumerConfig, processor TraceEventProcessor) (*StreamConsumer, error) {
	logger := log.New(os.Stdout, "[TRACE-CONSUMER] ", log.LstdFlags)

	if !config.Enabled {
		logger.Println("Tracing disabled via configuration")
		return &StreamConsumer{
			enabled:         false,
			connectionState: StateDisconnected,
			logger:          logger,
		}, nil
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
		config:          config,
		streamName:      config.StreamName,
		consumerGroup:   config.ConsumerGroup,
		consumerName:    consumerName,
		enabled:         true,
		connectionState: StateDisconnected,
		logger:          logger,
		batchSize:       config.BatchSize,
		blockTimeout:    config.BlockTimeout,
		processor:       processor,
		ctx:             ctx,
		cancel:          cancel,
	}

	logger.Printf("Consumer created for stream=%s, group=%s (connection will be established in background)",
		config.StreamName, config.ConsumerGroup)

	return consumer, nil
}

// Start begins the consumer - connection is managed in background
func (sc *StreamConsumer) Start() error {
	if !sc.enabled {
		sc.logger.Println("Consumer disabled, skipping start")
		return nil
	}

	sc.mu.Lock()
	if sc.running {
		sc.mu.Unlock()
		return fmt.Errorf("consumer is already running")
	}
	sc.running = true
	sc.mu.Unlock()

	sc.logger.Printf("Starting consumer for stream=%s, group=%s, consumer=%s",
		sc.streamName, sc.consumerGroup, sc.consumerName)

	// Start connection management goroutine
	sc.wg.Add(1)
	go sc.connectionManager()

	sc.logger.Println("Consumer started (connection manager running in background)")
	return nil
}

// connectionManager handles Redis connection with retry logic
func (sc *StreamConsumer) connectionManager() {
	defer sc.wg.Done()

	retryInterval := 5 * time.Second
	maxRetryInterval := 60 * time.Second

	for {
		select {
		case <-sc.ctx.Done():
			sc.logger.Println("Connection manager shutting down")
			return
		default:
		}

		// Check current state
		sc.mu.RLock()
		state := sc.connectionState
		sc.mu.RUnlock()

		switch state {
		case StateDisconnected, StateFailed:
			// Attempt to connect
			sc.attemptConnection()

		case StateConnected:
			// Connection is healthy, start consuming if not already
			sc.mu.RLock()
			consuming := sc.consuming
			sc.mu.RUnlock()

			if !consuming {
				sc.startConsuming()
			}

			// Check connection health periodically
			if err := sc.checkConnectionHealth(); err != nil {
				sc.logger.Printf("Connection health check failed: %v", err)
				sc.handleConnectionLoss()
			}
		}

		// Calculate retry interval with exponential backoff
		sc.mu.RLock()
		retryCount := sc.retryCount
		sc.mu.RUnlock()

		if retryCount > 0 {
			backoff := retryInterval * time.Duration(1<<uint(min(retryCount-1, 5)))
			if backoff > maxRetryInterval {
				backoff = maxRetryInterval
			}
			select {
			case <-sc.ctx.Done():
				return
			case <-time.After(backoff):
			}
		} else {
			// Health check interval when connected
			select {
			case <-sc.ctx.Done():
				return
			case <-time.After(2 * time.Second):
			}
		}
	}
}

// attemptConnection tries to connect to Redis
func (sc *StreamConsumer) attemptConnection() {
	sc.mu.Lock()
	sc.connectionState = StateConnecting
	sc.mu.Unlock()

	sc.logger.Printf("Attempting to connect to Redis (attempt %d)...", sc.retryCount+1)

	// Parse Redis URL
	opts, err := redis.ParseURL(sc.config.RedisURL)
	if err != nil {
		sc.handleConnectionError(fmt.Errorf("invalid Redis URL: %w", err))
		return
	}

	client := redis.NewClient(opts)

	// Test connection with timeout
	ctx, cancel := context.WithTimeout(sc.ctx, 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		client.Close()
		sc.handleConnectionError(fmt.Errorf("Redis ping failed: %w", err))
		return
	}

	// Connection successful
	sc.mu.Lock()
	sc.client = client
	sc.connectionState = StateConnected
	sc.lastError = nil
	sc.retryCount = 0
	sc.mu.Unlock()

	sc.logger.Println("Successfully connected to Redis")

	// Create consumer group
	if err := sc.createConsumerGroup(); err != nil {
		sc.logger.Printf("Warning: Failed to create consumer group: %v (will retry)", err)
		// Don't disconnect - the group might already exist or stream not created yet
	}
}

// handleConnectionError records connection failure and updates state
func (sc *StreamConsumer) handleConnectionError(err error) {
	sc.mu.Lock()
	sc.connectionState = StateFailed
	sc.lastError = err
	sc.lastErrorTime = time.Now()
	sc.retryCount++
	sc.mu.Unlock()

	sc.logger.Printf("Connection failed: %v (will retry, attempt %d)", err, sc.retryCount)
}

// handleConnectionLoss cleans up after losing connection
func (sc *StreamConsumer) handleConnectionLoss() {
	sc.mu.Lock()
	defer sc.mu.Unlock()

	sc.connectionState = StateDisconnected
	sc.consuming = false

	if sc.client != nil {
		sc.client.Close()
		sc.client = nil
	}

	sc.logger.Println("Connection lost, will attempt to reconnect")
}

// checkConnectionHealth verifies Redis connection is still healthy
func (sc *StreamConsumer) checkConnectionHealth() error {
	sc.mu.RLock()
	client := sc.client
	sc.mu.RUnlock()

	if client == nil {
		return fmt.Errorf("client is nil")
	}

	ctx, cancel := context.WithTimeout(sc.ctx, 3*time.Second)
	defer cancel()

	return client.Ping(ctx).Err()
}

// startConsuming begins the consumption loop
func (sc *StreamConsumer) startConsuming() {
	sc.mu.Lock()
	if sc.consuming {
		sc.mu.Unlock()
		return
	}
	sc.consuming = true
	sc.mu.Unlock()

	sc.logger.Println("Starting consumption loop")

	sc.wg.Add(1)
	go sc.consumeLoop()
}

// createConsumerGroup creates the consumer group if it doesn't exist
func (sc *StreamConsumer) createConsumerGroup() error {
	sc.mu.RLock()
	client := sc.client
	sc.mu.RUnlock()

	if client == nil {
		return fmt.Errorf("not connected to Redis")
	}

	sc.logger.Printf("Creating consumer group: stream=%s, group=%s", sc.streamName, sc.consumerGroup)

	// Try to create the consumer group with MKSTREAM option to auto-create the stream
	ctx, cancel := context.WithTimeout(sc.ctx, 5*time.Second)
	defer cancel()

	err := client.XGroupCreateMkStream(ctx, sc.streamName, sc.consumerGroup, "0").Err()
	if err != nil {
		// If group already exists, that's fine
		if strings.Contains(err.Error(), "BUSYGROUP") {
			sc.logger.Printf("Consumer group already exists: %s", sc.consumerGroup)
			return nil
		}
		sc.logger.Printf("ERROR: XGroupCreateMkStream failed: %v", err)
		return fmt.Errorf("failed to create consumer group: %w", err)
	}

	sc.logger.Printf("Consumer group created successfully: %s", sc.consumerGroup)
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
	sc.consuming = false
	sc.mu.Unlock()

	sc.logger.Println("Stopping consumer...")

	// Cancel context to signal stop
	sc.cancel()

	// Wait for goroutines to finish
	sc.wg.Wait()

	// Close Redis client
	sc.mu.Lock()
	if sc.client != nil {
		if err := sc.client.Close(); err != nil {
			sc.logger.Printf("Warning: Error closing Redis client: %v", err)
		}
		sc.client = nil
	}
	sc.connectionState = StateDisconnected
	sc.mu.Unlock()

	sc.logger.Println("Consumer stopped")
	return nil
}

// consumeLoop is the main consumption loop
func (sc *StreamConsumer) consumeLoop() {
	defer sc.wg.Done()
	defer func() {
		sc.mu.Lock()
		sc.consuming = false
		sc.mu.Unlock()
	}()

	sc.logger.Println("Consumption loop started")

	for {
		select {
		case <-sc.ctx.Done():
			sc.logger.Println("Consumption loop stopping")
			return
		default:
			// Check if still connected
			sc.mu.RLock()
			state := sc.connectionState
			client := sc.client
			sc.mu.RUnlock()

			if state != StateConnected || client == nil {
				sc.logger.Println("Connection lost, stopping consumption loop")
				return
			}

			if err := sc.processNextBatch(); err != nil {
				// Check if it's a connection error
				if strings.Contains(err.Error(), "connection") ||
					strings.Contains(err.Error(), "EOF") ||
					strings.Contains(err.Error(), "closed") {
					sc.logger.Printf("Connection error during consumption: %v", err)
					sc.handleConnectionLoss()
					return
				}
				// Other errors - continue processing
				time.Sleep(1 * time.Second)
			}
		}
	}
}

// processNextBatch processes the next batch of messages
func (sc *StreamConsumer) processNextBatch() error {
	sc.mu.RLock()
	client := sc.client
	sc.mu.RUnlock()

	if client == nil {
		return fmt.Errorf("not connected")
	}

	// Read from consumer group (pending messages first, then new ones)
	args := &redis.XReadGroupArgs{
		Group:    sc.consumerGroup,
		Consumer: sc.consumerName,
		Streams:  []string{sc.streamName, ">"},
		Count:    sc.batchSize,
		Block:    sc.blockTimeout,
	}

	result, err := client.XReadGroup(sc.ctx, args).Result()
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
			if err := client.XAck(sc.ctx, sc.streamName, sc.consumerGroup, message.ID).Err(); err != nil {
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
		"enabled":          sc.enabled,
		"running":          sc.running,
		"connection_state": string(sc.connectionState),
		"consuming":        sc.consuming,
		"stream_name":      sc.streamName,
		"consumer_group":   sc.consumerGroup,
		"consumer_name":    sc.consumerName,
		"retry_count":      sc.retryCount,
	}

	if sc.lastError != nil {
		info["last_error"] = sc.lastError.Error()
		info["last_error_time"] = sc.lastErrorTime.Format(time.RFC3339)
	}

	if sc.enabled && sc.client != nil && sc.connectionState == StateConnected {
		// Get stream info
		ctx, cancel := context.WithTimeout(sc.ctx, 2*time.Second)
		defer cancel()

		if streamInfo, err := sc.client.XInfoStream(ctx, sc.streamName).Result(); err == nil {
			info["stream_length"] = streamInfo.Length
			info["stream_last_entry_id"] = streamInfo.LastGeneratedID
		}

		// Get consumer group info
		if groupInfo, err := sc.client.XInfoGroups(ctx, sc.streamName).Result(); err == nil {
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

// IsConnected returns true if connected to Redis
func (sc *StreamConsumer) IsConnected() bool {
	sc.mu.RLock()
	defer sc.mu.RUnlock()
	return sc.connectionState == StateConnected
}

// GetConnectionState returns the current connection state
func (sc *StreamConsumer) GetConnectionState() ConnectionState {
	sc.mu.RLock()
	defer sc.mu.RUnlock()
	return sc.connectionState
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

// min returns the smaller of two integers
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
