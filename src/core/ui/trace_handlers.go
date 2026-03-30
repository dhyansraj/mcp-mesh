package ui

import (
	"net/http"
	"strconv"
	"time"

	"mcp-mesh/src/core/registry/tracing"

	"github.com/gin-gonic/gin"
)

// handleRecentTraces returns recent trace summaries
func (s *Server) handleRecentTraces(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"traces":  []interface{}{},
			"count":   0,
			"limit":   0,
		})
		return
	}

	limit := 20
	if l := c.Query("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 {
			limit = parsed
		}
	}
	if limit > 100 {
		limit = 100
	}

	traces, err := s.tracingManager.GetRecentTraces(limit)
	if err != nil {
		c.JSON(500, map[string]interface{}{
			"error": err.Error(),
		})
		return
	}

	c.JSON(200, map[string]interface{}{
		"enabled": true,
		"traces":  traces,
		"count":   len(traces),
		"limit":   limit,
	})
}

// handleEdgeStats returns aggregated edge statistics from recent traces
func (s *Server) handleEdgeStats(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled":    false,
			"edges":      []interface{}{},
			"count":      0,
			"edge_count": 0,
		})
		return
	}

	limit := 20
	if l := c.Query("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 {
			limit = parsed
		}
	}
	if limit > 100 {
		limit = 100
	}

	stats, err := s.tracingManager.GetEdgeStats(limit)
	if err != nil {
		c.JSON(500, map[string]interface{}{
			"error": err.Error(),
		})
		return
	}

	c.JSON(200, map[string]interface{}{
		"enabled":    true,
		"edges":      stats,
		"count":      len(stats),
		"edge_count": len(stats),
	})
}

// handleTraceGet retrieves a specific trace by ID
func (s *Server) handleTraceGet(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(404, map[string]interface{}{
			"error":   "tracing not enabled",
			"enabled": false,
		})
		return
	}

	traceID := c.Param("trace_id")
	if traceID == "" {
		c.JSON(400, map[string]interface{}{
			"error": "trace_id parameter required",
		})
		return
	}

	trace, found := s.tracingManager.GetTrace(traceID)
	if !found {
		c.JSON(404, map[string]interface{}{
			"error":    "trace not found",
			"trace_id": traceID,
		})
		return
	}

	c.JSON(200, trace)
}

// handleTraceSearch searches traces based on criteria
func (s *Server) handleTraceSearch(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"traces":  []interface{}{},
			"count":   0,
		})
		return
	}

	criteria := tracing.TraceSearchCriteria{}

	if parentSpanID := c.Query("parent_span_id"); parentSpanID != "" {
		criteria.ParentSpanID = &parentSpanID
	}

	if agentName := c.Query("agent_name"); agentName != "" {
		criteria.AgentName = &agentName
	}

	if operation := c.Query("operation"); operation != "" {
		criteria.Operation = &operation
	}

	if successStr := c.Query("success"); successStr != "" {
		if success, err := strconv.ParseBool(successStr); err == nil {
			criteria.Success = &success
		}
	}

	if startTimeStr := c.Query("start_time"); startTimeStr != "" {
		if startTime, err := time.Parse(time.RFC3339, startTimeStr); err == nil {
			criteria.StartTime = &startTime
		}
	}

	if endTimeStr := c.Query("end_time"); endTimeStr != "" {
		if endTime, err := time.Parse(time.RFC3339, endTimeStr); err == nil {
			criteria.EndTime = &endTime
		}
	}

	if minDurationStr := c.Query("min_duration_ms"); minDurationStr != "" {
		if minDuration, err := strconv.ParseInt(minDurationStr, 10, 64); err == nil {
			criteria.MinDuration = &minDuration
		}
	}

	if maxDurationStr := c.Query("max_duration_ms"); maxDurationStr != "" {
		if maxDuration, err := strconv.ParseInt(maxDurationStr, 10, 64); err == nil {
			criteria.MaxDuration = &maxDuration
		}
	}

	limitStr := c.DefaultQuery("limit", "20")
	if limit, err := strconv.Atoi(limitStr); err == nil && limit > 0 && limit <= 100 {
		criteria.Limit = limit
	} else {
		criteria.Limit = 20
	}

	traces := s.tracingManager.SearchTraces(criteria)

	c.JSON(200, map[string]interface{}{
		"enabled":  true,
		"traces":   traces,
		"count":    len(traces),
		"criteria": criteria,
	})
}

// handleTraceList lists recent traces with pagination
func (s *Server) handleTraceList(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"traces":  []interface{}{},
			"total":   0,
		})
		return
	}

	limitStr := c.DefaultQuery("limit", "20")
	offsetStr := c.DefaultQuery("offset", "0")

	limit, err := strconv.Atoi(limitStr)
	if err != nil || limit < 1 || limit > 100 {
		limit = 20
	}

	offset, err := strconv.Atoi(offsetStr)
	if err != nil || offset < 0 {
		offset = 0
	}

	traces := s.tracingManager.ListTraces(limit, offset)
	total := s.tracingManager.GetTraceCount()

	c.JSON(200, map[string]interface{}{
		"enabled": true,
		"traces":  traces,
		"total":   total,
		"limit":   limit,
		"offset":  offset,
		"count":   len(traces),
	})
}

// handleStreamLiveTraces streams all trace spans in real-time via SSE
func (s *Server) handleStreamLiveTraces(c *gin.Context) {
	if s.tracingManager == nil || s.tracingManager.GetAccumulator() == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": "Live trace streaming not available (tracing not enabled)",
		})
		return
	}

	accumulator := s.tracingManager.GetAccumulator()

	// SSE headers
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")

	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "Streaming not supported",
		})
		return
	}

	ch := accumulator.SubscribeLive()
	defer accumulator.UnsubscribeLive(ch)

	// Send connected event
	writeSSEEvent(c, "connected", map[string]interface{}{
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"message":   "Connected to live trace stream",
	})
	flusher.Flush()

	// Send current active trace snapshots so the client has initial state
	for _, snapshot := range accumulator.GetActiveTraceSnapshots() {
		writeSSEEvent(c, "trace_update", snapshot)
		flusher.Flush()
	}

	ctx := c.Request.Context()
	for {
		select {
		case event, ok := <-ch:
			if !ok {
				return
			}
			writeSSEEvent(c, event.EventType, event.Snapshot)
			flusher.Flush()
		case <-ctx.Done():
			return
		}
	}
}
