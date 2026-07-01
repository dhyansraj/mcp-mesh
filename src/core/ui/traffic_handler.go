package ui

import (
	"log"
	"strconv"
	"time"

	"mcp-mesh/src/core/registry/tracing"

	"github.com/gin-gonic/gin"
)

// Windowed-replay bounds. maxWindowEntries caps how many stream entries a single
// windowed request will read+replay so a wide (1d) window can never OOM the UI
// server; windowReadBatch is the XRANGE page size. At ~2 spans per call these
// bounds cover a healthy amount of traffic while staying memory-safe.
const (
	maxWindowEntries = 50000
	windowReadBatch  = 1000
)

// TrafficResponse is the /trace/traffic payload. edge_stats/agent_stats/model_stats
// carry the exact element shapes produced by TraceAccumulator.GetEdgeStats,
// MetricsProcessor.GetAgentMetrics and MetricsProcessor.GetModelMetrics, so the
// frontend consumes the same field casing it already uses for the live endpoints.
type TrafficResponse struct {
	Enabled     bool                `json:"enabled"`
	Window      string              `json:"window"`
	TotalCalls  int                 `json:"total_calls"`
	TotalErrors int                 `json:"total_errors"`
	EdgeStats   []tracing.EdgeStats `json:"edge_stats"`
	AgentStats  []AgentMetricsData  `json:"agent_stats"`
	ModelStats  []ModelMetricsData  `json:"model_stats"`
}

// parseWindow maps a window query value to a duration. The bool result reports
// whether the window is "all" (live aggregates) vs a bounded re-aggregation.
// Unknown values are rejected (ok=false).
func parseWindow(v string) (dur time.Duration, isAll bool, ok bool) {
	switch v {
	case "", "all":
		return 0, true, true
	case "1h":
		return time.Hour, false, true
	case "1d":
		return 24 * time.Hour, false, true
	default:
		return 0, false, false
	}
}

// replayWindow re-aggregates a slice of trace events through FRESH throwaway
// accumulator + metrics-processor instances, feeding each event through the SAME
// entry points the live consumer uses (accumulator.ProcessTraceEvent +
// MetricsProcessor.ProcessTraceEvent). After feeding, it force-finalizes all
// in-flight traces so edge stats and totals are complete. This reuses ALL the
// existing metrics math; the only windowing logic is the event slice the caller
// supplies. Factored out (no Redis) so it is unit-testable directly.
func replayWindow(events []*tracing.TraceEvent, limit int) (edges []tracing.EdgeStats, agents []AgentMetricsData, models []ModelMetricsData, totalCalls, totalErrors int) {
	acc := tracing.NewTraceAccumulator(0, log.Default())
	mp := NewMetricsProcessor()

	// Feed each event through the exact live per-event path (minus SSE publish
	// side effects, which are inert here since there are no subscribers).
	for _, e := range events {
		_ = acc.ProcessTraceEvent(e)
		_ = mp.ProcessTraceEvent(e)
	}

	// Flush all in-flight traces synchronously so edges + totals are complete.
	acc.FinalizeAllActive()

	edges = acc.GetEdgeStats()
	if limit > 0 && limit < len(edges) {
		edges = edges[:limit]
	}
	agents = mp.GetAgentMetrics()
	models = mp.GetModelMetrics()
	totalCalls = acc.GetTotalFinalized()
	totalErrors = acc.GetTotalErrors()
	return edges, agents, models, totalCalls, totalErrors
}

// handleTraffic returns windowed traffic aggregates for the Traffic-page time
// filter. window=all (default) serves the live all-time aggregates unchanged;
// window=1h/1d re-aggregate over a bounded XRANGE of the Redis trace stream.
func (s *Server) handleTraffic(c *gin.Context) {
	limit := 20
	if l := c.Query("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 {
			limit = parsed
		}
	}
	if limit > 100 {
		limit = 100
	}

	windowParam := c.Query("window")
	window, isAll, ok := parseWindow(windowParam)
	if !ok {
		c.JSON(400, gin.H{
			"error": "invalid window; expected one of: 1h, 1d, all",
		})
		return
	}
	normalizedWindow := windowParam
	if normalizedWindow == "" {
		normalizedWindow = "all"
	}

	if s.tracingManager == nil {
		c.JSON(200, TrafficResponse{
			Enabled:    false,
			Window:     normalizedWindow,
			EdgeStats:  []tracing.EdgeStats{},
			AgentStats: []AgentMetricsData{},
			ModelStats: []ModelMetricsData{},
		})
		return
	}

	// window=all: serve the LIVE aggregates exactly as the existing handlers do.
	if isAll {
		edges, err := s.tracingManager.GetEdgeStats(limit)
		if err != nil {
			c.JSON(500, gin.H{"error": err.Error()})
			return
		}
		var agents []AgentMetricsData
		var models []ModelMetricsData
		if s.metricsProcessor != nil {
			agents = s.metricsProcessor.GetAgentMetrics()
			models = s.metricsProcessor.GetModelMetrics()
		}
		if edges == nil {
			edges = []tracing.EdgeStats{}
		}
		if agents == nil {
			agents = []AgentMetricsData{}
		}
		if models == nil {
			models = []ModelMetricsData{}
		}
		c.JSON(200, TrafficResponse{
			Enabled:     true,
			Window:      normalizedWindow,
			TotalCalls:  s.tracingManager.GetTotalFinalized(),
			TotalErrors: s.tracingManager.GetTotalErrors(),
			EdgeStats:   edges,
			AgentStats:  agents,
			ModelStats:  models,
		})
		return
	}

	// window=1h/1d: bounded XRANGE + replay through fresh throwaway instances.
	events, err := s.tracingManager.RangeEventsSince(window, maxWindowEntries, windowReadBatch)
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}

	edges, agents, models, totalCalls, totalErrors := replayWindow(events, limit)
	if edges == nil {
		edges = []tracing.EdgeStats{}
	}
	if agents == nil {
		agents = []AgentMetricsData{}
	}
	if models == nil {
		models = []ModelMetricsData{}
	}

	c.JSON(200, TrafficResponse{
		Enabled:     true,
		Window:      normalizedWindow,
		TotalCalls:  totalCalls,
		TotalErrors: totalErrors,
		EdgeStats:   edges,
		AgentStats:  agents,
		ModelStats:  models,
	})
}
