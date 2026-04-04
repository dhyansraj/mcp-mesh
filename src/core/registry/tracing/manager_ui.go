package tracing

import (
	"fmt"
	"log"
	"os"
)

// NewAccumulatorOnlyManager creates a TracingManager that only accumulates
// trace data in-memory without exporting to any backend. Used by the UI
// server which needs trace data for dashboard display but doesn't handle
// the Tempo export pipeline (the registry does that).
// Extra processors (e.g. UI metrics aggregation) are wrapped alongside the
// accumulator via a MultiProcessor so they receive every span event.
func NewAccumulatorOnlyManager(config *TracingConfig, extraProcessors ...TraceEventProcessor) (*TracingManager, error) {
	if config == nil {
		config = DefaultTracingConfig()
	}

	manager := &TracingManager{
		config:            config,
		logger:            log.New(os.Stdout, "[UI-TRACE] ", log.LstdFlags),
		enabled:           config.Enabled,
		streamThroughMode: true, // So query methods use the accumulator
	}

	if !config.Enabled {
		manager.logger.Println("UI tracing: disabled")
		return manager, nil
	}

	// Create accumulator as the primary processor (no OTLP exporter)
	accumulator := NewTraceAccumulator(200, manager.logger)
	manager.accumulator = accumulator

	// Wrap with extra processors if provided (e.g. UI MetricsProcessor)
	var processor TraceEventProcessor = accumulator
	if len(extraProcessors) > 0 {
		allProcessors := make([]TraceEventProcessor, 0, 1+len(extraProcessors))
		allProcessors = append(allProcessors, accumulator)
		allProcessors = append(allProcessors, extraProcessors...)
		processor = NewMultiProcessor(manager.logger, allProcessors...)
	}
	manager.processor = processor

	// Create consumer with UI-specific consumer group
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

	// Create Tempo client for historical trace queries
	if config.TempoQueryURL != "" {
		tc, err := NewTempoClient(config.TempoQueryURL)
		if err != nil {
			manager.logger.Printf("Warning: Tempo client disabled: %v", err)
		} else {
			manager.tempoClient = tc
			manager.logger.Printf("Tempo query client initialized: %s", config.TempoQueryURL)
		}
	}

	manager.logger.Printf("UI tracing: enabled (accumulator-only), redis=%s, group=%s",
		config.RedisURL, config.ConsumerGroup)
	return manager, nil
}
