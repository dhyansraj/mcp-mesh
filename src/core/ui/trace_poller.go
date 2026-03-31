package ui

import (
	"context"
	"log"
	"sync"
	"time"

	"mcp-mesh/src/core/registry/tracing"
)

// TracePoller polls the TracingManager for recent trace data and publishes
// summary events via the UI EventHub.
type TracePoller struct {
	tracingManager *tracing.TracingManager
	hub            *EventHub
	interval       time.Duration
	cancel         context.CancelFunc
	wg             sync.WaitGroup
	mu             sync.RWMutex
	running        bool
}

// NewTracePoller creates a new poller that fetches trace data and publishes events
func NewTracePoller(tracingManager *tracing.TracingManager, hub *EventHub, interval time.Duration) *TracePoller {
	return &TracePoller{
		tracingManager: tracingManager,
		hub:            hub,
		interval:       interval,
	}
}

// Start begins the background polling goroutine
func (p *TracePoller) Start() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		log.Println("[ui] Trace poller is already running")
		return
	}

	p.running = true
	ctx, cancel := context.WithCancel(context.Background())
	p.cancel = cancel
	p.wg.Add(1)

	go func() {
		defer p.wg.Done()
		log.Printf("[ui] Starting trace poller (interval: %v)", p.interval)

		ticker := time.NewTicker(p.interval)
		defer ticker.Stop()

		for {
			select {
			case <-ticker.C:
				p.poll()
			case <-ctx.Done():
				log.Println("[ui] Trace poller stopped")
				return
			}
		}
	}()
}

// Stop gracefully stops the trace poller
func (p *TracePoller) Stop() {
	p.mu.Lock()
	if !p.running {
		p.mu.Unlock()
		return
	}

	p.running = false
	if p.cancel != nil {
		p.cancel()
	}
	p.mu.Unlock()

	p.wg.Wait()
	log.Println("[ui] Trace poller stopped successfully")
}

func (p *TracePoller) poll() {
	// Skip polling when no dashboard clients are connected
	if p.hub.SubscriberCount() == 0 {
		return
	}

	now := time.Now().UTC()

	// Prefer accumulator-based agent activity (in-memory, fast)
	agentCounts := p.tracingManager.GetAgentActivity()
	if len(agentCounts) > 0 {
		totalSpans := 0
		for _, count := range agentCounts {
			totalSpans += count
		}
		p.hub.Publish(DashboardEvent{
			Type: "trace_activity",
			Data: map[string]interface{}{
				"agents":      agentCounts,
				"trace_count": totalSpans,
			},
			Timestamp: now,
		})
	} else {
		// Fallback: derive agent activity from recent traces
		traces, err := p.tracingManager.GetRecentTraces(20)
		if err != nil {
			log.Printf("[ui] Trace poller: failed to get recent traces: %v", err)
		} else {
			fallbackCounts := make(map[string]int)
			for _, t := range traces {
				for _, agent := range t.Agents {
					fallbackCounts[agent]++
				}
			}
			p.hub.Publish(DashboardEvent{
				Type: "trace_activity",
				Data: map[string]interface{}{
					"agents":      fallbackCounts,
					"trace_count": len(traces),
				},
				Timestamp: now,
			})
		}
	}

	// Fetch edge stats (reads from accumulator when available)
	edges, edgeErr := p.tracingManager.GetEdgeStats(20)
	if edgeErr != nil {
		log.Printf("[ui] Trace poller: failed to get edge stats: %v", edgeErr)
	} else {
		p.hub.Publish(DashboardEvent{
			Type: "edge_stats",
			Data: map[string]interface{}{
				"edges":      edges,
				"edge_count": len(edges),
			},
			Timestamp: now,
		})
	}
}
