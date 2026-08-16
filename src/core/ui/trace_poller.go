package ui

import (
	"context"
	"log"
	"sync"
	"time"

	"mcp-mesh/src/core/registry/tracing"
)

// edgeStatsStreamLimit is the row budget for the streamed `edge_stats` event.
//
// It is deliberately NOT the 20 the tables' endpoints default to, because the
// stream has a consumer the endpoints do not: the topology graph, whose only
// source of traffic this event is. The graph needs a row for every edge it
// DRAWS, and one edge is one (consumer, provider, function) since #1531 — so a
// budget sized for a readable table starves it. An unmatched edge keeps its
// structural style, which means the starvation is silent: the graph just stops
// reporting traffic for most of the mesh.
//
// A table wants a ranked top-N; a graph wants coverage. One number cannot be
// both, so the stream gets its own, sized for the drawn edges of a substantial
// mesh (100 agents each calling 5 tools of 1 other agent is 500) rather than
// for a screenful. At roughly 200 bytes of JSON a row that is ~100 KB per
// publish, against the full agent snapshot the same dashboard already fetches.
// Rows past the budget are dropped fairly across agent pairs, not by rank —
// see tracing.SelectEdgeStats.
//
// The dashboard's own traffic widget takes its top rows from this same event
// (TrafficTable), which is what keeps the wider budget off the screen.
const edgeStatsStreamLimit = 500

// TracePoller polls the TracingManager for recent trace data and publishes
// summary events via the UI EventHub.
type TracePoller struct {
	tracingManager   *tracing.TracingManager
	metricsProcessor *MetricsProcessor
	hub              *EventHub
	interval         time.Duration
	cancel           context.CancelFunc
	wg               sync.WaitGroup
	mu               sync.RWMutex
	running          bool
}

// NewTracePoller creates a new poller that fetches trace data and publishes events
func NewTracePoller(tracingManager *tracing.TracingManager, metricsProcessor *MetricsProcessor, hub *EventHub, interval time.Duration) *TracePoller {
	return &TracePoller{
		tracingManager:   tracingManager,
		metricsProcessor: metricsProcessor,
		hub:              hub,
		interval:         interval,
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
				"agents":       agentCounts,
				"trace_count":  totalSpans,
				"total_calls":  p.tracingManager.GetTotalFinalized(),
				"total_errors": p.tracingManager.GetTotalErrors(),
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
			fallbackErrors := 0
			for _, t := range traces {
				if !t.Success {
					fallbackErrors++
				}
			}
			p.hub.Publish(DashboardEvent{
				Type: "trace_activity",
				Data: map[string]interface{}{
					"agents":       fallbackCounts,
					"trace_count":  len(traces),
					"total_calls":  len(traces),
					"total_errors": fallbackErrors,
				},
				Timestamp: now,
			})
		}
	}

	// Fetch edge stats (reads from accumulator when available)
	edges, edgeErr := p.tracingManager.GetEdgeStats(edgeStatsStreamLimit)
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

	// Fetch per-agent and per-model stats from the UI metrics processor.
	// Always publish (even when empty) so the UI clears stale data.
	if p.metricsProcessor != nil {
		agentStats := p.metricsProcessor.GetAgentMetrics()
		p.hub.Publish(DashboardEvent{
			Type: "agent_stats",
			Data: map[string]interface{}{
				"agents": agentStats,
				"count":  len(agentStats),
			},
			Timestamp: now,
		})

		modelStats := p.metricsProcessor.GetModelMetrics()
		p.hub.Publish(DashboardEvent{
			Type: "model_stats",
			Data: map[string]interface{}{
				"models": modelStats,
				"count":  len(modelStats),
			},
			Timestamp: now,
		})
	}
}
