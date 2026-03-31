package ui

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"time"

	"mcp-mesh/src/core/registry/generated"

	"github.com/gin-gonic/gin"
)

// StreamDashboardEvents implements GET /api/events (SSE stream for dashboard)
func (s *Server) StreamDashboardEvents(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")

	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "streaming not supported"})
		return
	}

	// Subscribe to dashboard events
	ch := s.eventHub.Subscribe()
	defer s.eventHub.Unsubscribe(ch)

	// Send initial connected event with current agent summary
	resp, err := s.entService.ListAgents(nil)
	if err != nil {
		writeSSEEvent(c, "connected", map[string]interface{}{
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"message":   "Connected to dashboard event stream",
			"agents":    0,
		})
	} else {
		writeSSEEvent(c, "connected", map[string]interface{}{
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"message":   "Connected to dashboard event stream",
			"agents":    resp.Count,
		})
	}
	flusher.Flush()

	// Backfill recent events so a newly-connected dashboard sees history
	if recentEvents, err := s.entService.ListRecentEvents(50, ""); err == nil {
		for i := len(recentEvents) - 1; i >= 0; i-- {
			e := recentEvents[i]
			sseType := mapRegistryEventToSSEType(e.EventType, e.Data)
			if sseType == "" {
				continue
			}
			writeSSEEvent(c, sseType, DashboardEvent{
				Type:      sseType,
				AgentID:   e.AgentID,
				AgentName: e.AgentName,
				Data:      e.Data,
				Timestamp: e.Timestamp,
			})
		}
		flusher.Flush()
	}

	// Stream events until client disconnects
	for {
		select {
		case event, ok := <-ch:
			if !ok {
				return
			}
			writeSSEEvent(c, event.Type, event)
			flusher.Flush()
		case <-c.Request.Context().Done():
			return
		}
	}
}

// GetEventsHistory implements GET /api/events/history
func (s *Server) GetEventsHistory(c *gin.Context) {
	limit := 50
	if limitStr := c.Query("limit"); limitStr != "" {
		if parsed, err := strconv.Atoi(limitStr); err == nil {
			limit = parsed
			if limit > 200 {
				limit = 200
			}
			if limit < 1 {
				limit = 1
			}
		}
	}

	eventType := c.Query("event_type")

	events, err := s.entService.ListRecentEvents(limit, eventType)
	if err != nil {
		log.Printf("ui: [events-history] Failed to query events: %v", err)
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     "Failed to query event history",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	eventInfos := make([]generated.RegistryEventInfo, 0, len(events))
	for _, e := range events {
		info := generated.RegistryEventInfo{
			EventType: generated.RegistryEventInfoEventType(e.EventType),
			AgentId:   e.AgentID,
			Timestamp: e.Timestamp,
		}
		if e.AgentName != "" {
			name := e.AgentName
			info.AgentName = &name
		}
		if e.FunctionName != "" {
			fn := e.FunctionName
			info.FunctionName = &fn
		}
		if len(e.Data) > 0 {
			data := e.Data
			info.Data = &data
		}
		eventInfos = append(eventInfos, info)
	}

	c.JSON(http.StatusOK, generated.EventsHistoryResponse{
		Count:  len(eventInfos),
		Events: eventInfos,
	})
}

// writeSSEEvent writes a single SSE event to the response writer
func writeSSEEvent(c *gin.Context, eventType string, data interface{}) {
	jsonData, err := json.Marshal(data)
	if err != nil {
		log.Printf("[ui] SSE marshal error: %v", err)
		return
	}
	fmt.Fprintf(c.Writer, "event: %s\ndata: %s\n\n", eventType, string(jsonData))
}

// mapRegistryEventToSSEType converts a registry event_type to a dashboard SSE
// event name. Returns "" for event types that are noise for the dashboard.
func mapRegistryEventToSSEType(eventType string, data map[string]interface{}) string {
	switch eventType {
	case "register":
		return "agent_registered"
	case "unregister":
		return "agent_deregistered"
	case "unhealthy":
		return "agent_unhealthy"
	case "update":
		if ns, ok := data["new_status"]; ok {
			if ns == "healthy" {
				return "agent_healthy"
			}
		}
		return ""
	default:
		return ""
	}
}
