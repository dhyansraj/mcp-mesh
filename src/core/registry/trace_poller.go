package registry

import (
	"context"
	"sync"
	"time"

	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/tracing"
)

// TracePoller polls Tempo for recent trace data and publishes summary events via the EventHub
type TracePoller struct {
	tracingManager *tracing.TracingManager
	hub            *EventHub
	logger         *logger.Logger
	interval       time.Duration
	cancel         context.CancelFunc
	wg             sync.WaitGroup
	mu             sync.RWMutex
	running        bool
}

// NewTracePoller creates a new poller that fetches trace data and publishes events
func NewTracePoller(tracingManager *tracing.TracingManager, hub *EventHub, logger *logger.Logger, interval time.Duration) *TracePoller {
	return &TracePoller{
		tracingManager: tracingManager,
		hub:            hub,
		logger:         logger,
		interval:       interval,
	}
}

// Start begins the background polling goroutine
func (p *TracePoller) Start() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		p.logger.Warning("Trace poller is already running")
		return
	}

	p.running = true
	ctx, cancel := context.WithCancel(context.Background())
	p.cancel = cancel
	p.wg.Add(1)

	go func() {
		defer p.wg.Done()
		p.logger.Info("Starting trace poller (interval: %v)", p.interval)

		ticker := time.NewTicker(p.interval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				p.poll()
			case <-ctx.Done():
				p.logger.Info("Trace poller stopped")
				return
			}
		}
	}()
}

// Stop gracefully stops the trace poller
func (p *TracePoller) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.running {
		return
	}

	p.running = false
	if p.cancel != nil {
		p.cancel()
	}
	p.wg.Wait()
	p.logger.Info("Trace poller stopped successfully")
}

func (p *TracePoller) poll() {
	// Skip polling when no dashboard clients are connected
	if p.hub.SubscriberCount() == 0 {
		return
	}

	now := time.Now().UTC()

	// Fetch recent traces
	traces, err := p.tracingManager.GetRecentTraces(20)
	if err != nil {
		p.logger.Warning("Trace poller: failed to get recent traces: %v", err)
		return
	}

	// Build agent activity map from trace data
	agentCounts := make(map[string]int)
	for _, t := range traces {
		for _, agent := range t.Agents {
			agentCounts[agent]++
		}
	}

	// Publish trace_activity event
	p.hub.Publish(DashboardEvent{
		Type: "trace_activity",
		Data: map[string]interface{}{
			"agents":      agentCounts,
			"trace_count": len(traces),
		},
		Timestamp: now,
	})

	// Fetch edge stats
	edges, err := p.tracingManager.GetEdgeStats(20)
	if err != nil {
		p.logger.Warning("Trace poller: failed to get edge stats: %v", err)
		return
	}

	// Publish edge_stats event
	p.hub.Publish(DashboardEvent{
		Type: "edge_stats",
		Data: map[string]interface{}{
			"edges":           edges,
			"traces_analyzed": len(traces),
		},
		Timestamp: now,
	})
}
