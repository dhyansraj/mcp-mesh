package registry

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"mcp-mesh/src/core/registry/generated"
	"mcp-mesh/src/core/registry/tracing"
)

// resolvedDependency is a type alias for the anonymous struct used in heartbeat dependency responses.
// Using an alias (=) ensures type identity with the generated MeshRegistrationResponse field.
type resolvedDependency = struct {
	AgentId      string                                                       `json:"agent_id"`
	Capability   string                                                       `json:"capability"`
	Endpoint     string                                                       `json:"endpoint"`
	FunctionName string                                                       `json:"function_name"`
	Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
}

// EntBusinessLogicHandlers implements the generated server interface using EntService
type EntBusinessLogicHandlers struct {
	entService       *EntService
	startTime        time.Time
	redisClient      *redis.Client
	eventHub         *EventHub
	traceAccumulator *tracing.TraceAccumulator
}

// NewEntBusinessLogicHandlers creates a new handler instance using EntService
func NewEntBusinessLogicHandlers(entService *EntService, eventHub *EventHub) *EntBusinessLogicHandlers {
	// Initialize Redis client for trace streaming
	redisClient := initializeRedisClient()

	return &EntBusinessLogicHandlers{
		entService:  entService,
		startTime:   time.Now().UTC(),
		redisClient: redisClient,
		eventHub:    eventHub,
	}
}

// initializeRedisClient creates a Redis client for trace streaming
func initializeRedisClient() *redis.Client {
	redisURL := "redis://localhost:6379" // Default
	if url := tracing.GetRedisURLFromEnv(); url != "" {
		redisURL = url
	}

	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		// Return nil if Redis is not available - streaming will be disabled
		return nil
	}

	client := redis.NewClient(opts)

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		// Redis not available - return nil to disable streaming
		client.Close()
		return nil
	}

	return client
}

// GetHealth implements GET /health
func (h *EntBusinessLogicHandlers) GetHealth(c *gin.Context) {
	uptime := time.Since(h.startTime).Seconds()

	response := generated.HealthResponse{
		Status:        "healthy",
		Version:       "1.0.0",
		UptimeSeconds: int(uptime),
		Timestamp:     time.Now().UTC(),
		Service:       "mcp-mesh-registry",
	}

	c.JSON(http.StatusOK, response)
}

// HeadHealth implements HEAD /health
func (h *EntBusinessLogicHandlers) HeadHealth(c *gin.Context) {
	uptime := time.Since(h.startTime).Seconds()

	// Set the same headers as GET /health but without response body
	c.Header("Content-Type", "application/json")
	// Optional: Add custom headers that indicate health status
	c.Header("X-Health-Status", "healthy")
	c.Header("X-Service-Version", "1.0.0")
	c.Header("X-Uptime-Seconds", fmt.Sprintf("%d", int(uptime)))

	c.Status(http.StatusOK)
}

// GetRoot implements GET /
func (h *EntBusinessLogicHandlers) GetRoot(c *gin.Context) {
	endpoints := []string{"/health", "/heartbeat", "/agents"}

	// Add traces endpoint if Redis is available
	if h.redisClient != nil {
		endpoints = append(endpoints, "/traces/{trace_id}/stream")
	}

	response := generated.RootResponse{
		Service:   "mcp-mesh-registry",
		Version:   "1.0.0",
		Status:    "running",
		Endpoints: endpoints,
	}

	c.JSON(http.StatusOK, response)
}

// SendHeartbeat implements POST /heartbeat using EntService
func (h *EntBusinessLogicHandlers) SendHeartbeat(c *gin.Context) {
	var req generated.MeshAgentRegistration
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Convert to heartbeat request format (lighter than full registration)
	metadata := ConvertMeshAgentRegistrationToMap(req)
	heartbeatReq := &HeartbeatRequest{
		AgentID:  req.AgentId,
		Status:   "healthy", // Default status
		Metadata: metadata,
	}

	// Extract entity_id from TLS verification (set by TLSVerifyMiddleware)
	if entityID, exists := c.Get("entity_id"); exists {
		if eid, ok := entityID.(string); ok && eid != "" {
			heartbeatReq.EntityID = eid
		}
	}

	// Call lightweight heartbeat service method using EntService
	serviceResp, err := h.entService.UpdateHeartbeat(heartbeatReq)
	if err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Convert service response to API response
	var status generated.MeshRegistrationResponseStatus
	if serviceResp.Status == "success" {
		status = generated.Success
	} else {
		status = generated.Error
	}

	response := generated.MeshRegistrationResponse{
		Status:    status,
		Timestamp: time.Now().UTC(),
		Message:   serviceResp.Message,
		AgentId:   req.AgentId,
	}

	// Include dependency resolution if available (heartbeat with tools should return dependencies)
	if serviceResp.DependenciesResolved != nil {
		depsMap := make(map[string][]resolvedDependency)

		for functionName, deps := range serviceResp.DependenciesResolved {
			if len(deps) > 0 {
				depsList := make([]resolvedDependency, len(deps))
				for i, dep := range deps {
					depsList[i] = resolvedDependency{
						AgentId:      dep.AgentID,
						Capability:   dep.Capability,
						Endpoint:     dep.Endpoint,
						FunctionName: dep.FunctionName,
						Status:       generated.MeshRegistrationResponseDependenciesResolvedStatus(dep.Status),
					}
				}
				depsMap[functionName] = depsList
			}
		}
		response.DependenciesResolved = &depsMap
	}

	// Include LLM tools if available
	if serviceResp.LLMTools != nil {
		llmToolsMap := make(map[string][]generated.LLMToolInfo)

		for functionName, tools := range serviceResp.LLMTools {
			// IMPORTANT: Always add function key, even if tools array is empty.
			// This supports standalone LLM agents (filter=None case) that don't need tools.
			// The Python client needs to receive {"function_name": []} to create
			// a MeshLlmAgent with empty tools (answers using only model + system prompt).
			generatedTools := make([]generated.LLMToolInfo, len(tools))
			for i, tool := range tools {
				// Convert registry.LLMToolInfo to generated.LLMToolInfo
				generatedTools[i] = generated.LLMToolInfo{
					Name:        tool.Name,
					Capability:  tool.Capability,
					Description: tool.Description,
					Endpoint:    tool.Endpoint,
					InputSchema: tool.InputSchema,
					Tags:        &tool.Tags,
					Version:     &tool.Version,
				}
			}
			llmToolsMap[functionName] = generatedTools
		}
		// Always include llmToolsMap in response (even if empty)
		// This enables LLM agents to receive {"function_name": []} for standalone agents
		response.LlmTools = &llmToolsMap
	}

	// Include LLM providers if available (v0.6.1 mesh delegation)
	if serviceResp.LLMProviders != nil && len(serviceResp.LLMProviders) > 0 {
		llmProvidersMap := make(map[string]generated.ResolvedLLMProvider)
		for functionName, provider := range serviceResp.LLMProviders {
			if provider != nil {
				llmProvidersMap[functionName] = *provider
			}
		}
		response.LlmProviders = &llmProvidersMap
	}

	c.JSON(http.StatusOK, response)
}

// ListAgents implements GET /agents using EntService
func (h *EntBusinessLogicHandlers) ListAgents(c *gin.Context) {
	// Parse query parameters
	var params AgentQueryParams
	if err := c.ShouldBindQuery(&params); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid query parameters: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Call service method to get agents using EntService
	serviceResp, err := h.entService.ListAgents(&params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Service response is already in the correct format
	response := *serviceResp

	c.JSON(http.StatusOK, response)
}

// derefStringOr returns the dereferenced string pointer value, or the fallback if nil.
func derefStringOr(p *string, fallback string) string {
	if p != nil {
		return *p
	}
	return fallback
}

// derefStringType returns the string value of a typed pointer, or the fallback if nil.
// Used for generated enum types that have an underlying string type.
func derefStringType[T ~string](p *T, fallback string) string {
	if p != nil {
		return string(*p)
	}
	return fallback
}

// ConvertMeshAgentRegistrationToMap converts generated.MeshAgentRegistration to map[string]interface{}
// for compatibility with the service layer
func ConvertMeshAgentRegistrationToMap(reg generated.MeshAgentRegistration) map[string]interface{} {
	result := make(map[string]interface{})

	// Basic agent information
	result["name"] = derefStringOr(reg.Name, reg.AgentId)
	result["agent_type"] = derefStringType(reg.AgentType, "mcp_agent")
	if reg.Namespace != nil {
		result["namespace"] = *reg.Namespace
	}
	if reg.Version != nil {
		result["version"] = *reg.Version
	}
	if reg.Runtime != nil {
		result["runtime"] = string(*reg.Runtime)
	}
	if reg.HttpHost != nil {
		result["http_host"] = *reg.HttpHost
	}
	if reg.HttpPort != nil {
		result["http_port"] = *reg.HttpPort
	}

	// Store tools information for potential future use
	var toolsData []interface{}
	if reg.Tools != nil {
		toolsData = make([]interface{}, len(reg.Tools))
		for i, tool := range reg.Tools {
		toolData := map[string]interface{}{
			"function_name": tool.FunctionName,
			"capability":    tool.Capability,
		}
		if tool.Description != nil {
			toolData["description"] = *tool.Description
		}
		if tool.Version != nil {
			toolData["version"] = *tool.Version
		}
		if tool.Tags != nil {
			toolData["tags"] = *tool.Tags
		}
		if tool.InputSchema != nil {
			toolData["inputSchema"] = *tool.InputSchema
		}
		if tool.LlmFilter != nil {
			toolData["llm_filter"] = *tool.LlmFilter
		}
		if tool.LlmProvider != nil {
			toolData["llm_provider"] = *tool.LlmProvider
		}
		if tool.Dependencies != nil {
			deps := make([]map[string]interface{}, len(*tool.Dependencies))
			for j, dep := range *tool.Dependencies {
				depData := map[string]interface{}{
					"capability": dep.Capability,
				}
				if dep.Namespace != nil {
					depData["namespace"] = *dep.Namespace
				}
				if dep.Tags != nil {
					// Convert union type items to actual values (string or []string for OR alternatives)
					tags := make([]interface{}, len(*dep.Tags))
					for k, tagItem := range *dep.Tags {
						// Try to extract as string first
						if str, err := tagItem.AsMeshToolDependencyRegistrationTags0(); err == nil {
							tags[k] = str
						} else if arr, err := tagItem.AsMeshToolDependencyRegistrationTags1(); err == nil {
							// OR alternative: convert []string to []interface{} for parseDependencySpec
							arrInterface := make([]interface{}, len(arr))
							for m, s := range arr {
								arrInterface[m] = s
							}
							tags[k] = arrInterface
						}
					}
					depData["tags"] = tags
				}
				if dep.Version != nil {
					depData["version"] = *dep.Version
				}
				deps[j] = depData
			}
			toolData["dependencies"] = deps
		}
		if tool.Kwargs != nil {
			toolData["kwargs"] = *tool.Kwargs
		}
			toolsData[i] = toolData
		}
	}
	result["tools"] = toolsData

	return result
}

// FastHeartbeatCheck implements HEAD /heartbeat/{agent_id}
func (h *EntBusinessLogicHandlers) FastHeartbeatCheck(c *gin.Context, agentId string) {
	// Check if agent exists in registry
	agentEntity, err := h.entService.GetAgent(c.Request.Context(), agentId)
	if err != nil || agentEntity == nil {
		// Unknown agent - please register with POST heartbeat
		c.Status(http.StatusGone) // 410
		return
	}

	// Update agent timestamp to indicate recent activity (prevents health monitor eviction)
	// This also handles recovery from unhealthy status if needed
	err = h.entService.UpdateAgentHeartbeatTimestamp(c.Request.Context(), agentId)
	if err != nil {
		// Service error - back off and retry
		c.Status(http.StatusServiceUnavailable) // 503
		return
	}

	// Check for topology changes since last full refresh
	hasChanges, err := h.entService.HasTopologyChanges(c.Request.Context(), agentId, agentEntity.LastFullRefresh)
	if err != nil {
		// Service error - back off and retry
		c.Status(http.StatusServiceUnavailable) // 503
		return
	}

	if hasChanges {
		// Topology changed - please send full POST heartbeat
		c.Status(http.StatusAccepted) // 202
		return
	}

	// No changes - keep sending HEAD requests
	c.Status(http.StatusOK) // 200
}

// UnregisterAgent implements DELETE /agents/{agent_id}
func (h *EntBusinessLogicHandlers) UnregisterAgent(c *gin.Context, agentId string) {
	err := h.entService.UnregisterAgent(c.Request.Context(), agentId)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Return 204 No Content - successfully unregistered (idempotent)
	c.Status(http.StatusNoContent)
}

// StreamTrace implements GET /traces/{trace_id}/stream
func (h *EntBusinessLogicHandlers) StreamTrace(c *gin.Context, traceId string) {
	if h.redisClient == nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     "Trace streaming not available - Redis not connected",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Validate trace ID format
	if traceId == "" || len(traceId) < 3 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Invalid trace ID format",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Set SSE headers
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("Access-Control-Allow-Origin", "*")
	c.Header("Access-Control-Allow-Headers", "Cache-Control")

	// Create context for this streaming connection
	ctx, cancel := context.WithCancel(c.Request.Context())
	defer cancel()

	// Create unique consumer group per registry instance
	hostname := "registry"
	if h, err := getHostname(); err == nil {
		hostname = h
	}
	consumerGroup := fmt.Sprintf("registry-stream-%s", hostname)
	consumerName := fmt.Sprintf("trace-stream-%s-%d", traceId, time.Now().Unix())

	// Create consumer group for this trace
	streamName := "mesh:trace" // Match the main tracing stream
	if err := h.createTraceConsumerGroup(ctx, streamName, consumerGroup); err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to create consumer group: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Start streaming trace events
	h.streamTraceEvents(ctx, c, streamName, consumerGroup, consumerName, traceId)
}

// createTraceConsumerGroup creates a consumer group for trace streaming
func (h *EntBusinessLogicHandlers) createTraceConsumerGroup(ctx context.Context, streamName, consumerGroup string) error {
	// Try to create the consumer group with MKSTREAM option
	err := h.redisClient.XGroupCreateMkStream(ctx, streamName, consumerGroup, "0").Err()
	if err != nil && !strings.Contains(err.Error(), "BUSYGROUP") {
		return fmt.Errorf("failed to create consumer group: %w", err)
	}
	return nil
}

// streamTraceEvents streams trace events for a specific trace ID using SSE
func (h *EntBusinessLogicHandlers) streamTraceEvents(ctx context.Context, c *gin.Context, streamName, consumerGroup, consumerName, traceId string) {
	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     "Streaming not supported",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Send initial connection event
	h.writeSSEEvent(c, "connected", map[string]interface{}{
		"trace_id":  traceId,
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"message":   "Connected to trace stream",
	})
	flusher.Flush()

	// Stream events until context is cancelled
	for {
		select {
		case <-ctx.Done():
			return
		default:
			// Read events from Redis stream
			args := &redis.XReadGroupArgs{
				Group:    consumerGroup,
				Consumer: consumerName,
				Streams:  []string{streamName, ">"},
				Count:    10, // Small batch for real-time streaming
				Block:    1 * time.Second,
			}

			result, err := h.redisClient.XReadGroup(ctx, args).Result()
			if err != nil {
				if err == redis.Nil {
					// No new messages, continue
					continue
				}
				// Send error event and continue
				h.writeSSEEvent(c, "error", map[string]interface{}{
					"trace_id":  traceId,
					"timestamp": time.Now().UTC().Format(time.RFC3339),
					"error":     err.Error(),
				})
				flusher.Flush()
				time.Sleep(1 * time.Second)
				continue
			}

			// Process messages and filter by trace ID
			for _, stream := range result {
				for _, message := range stream.Messages {
					// Parse trace event
					event := &tracing.TraceEvent{}
					if err := event.FromRedisMap(message.Values); err != nil {
						continue // Skip invalid events
					}

					// Filter by trace ID
					if event.TraceID == traceId {
						// Convert to API-compatible format
						apiEvent := h.convertToAPITraceEvent(event)

						// Send as SSE event
						h.writeSSEEvent(c, "trace_event", apiEvent)
						flusher.Flush()
					}

					// Acknowledge message
					h.redisClient.XAck(ctx, streamName, consumerGroup, message.ID)
				}
			}
		}
	}
}

// convertToAPITraceEvent converts internal TraceEvent to API format
func (h *EntBusinessLogicHandlers) convertToAPITraceEvent(event *tracing.TraceEvent) map[string]interface{} {
	apiEvent := map[string]interface{}{
		"event_type": h.mapEventType(event.EventType),
		"trace_id":   event.TraceID,
		"timestamp":  time.Unix(int64(event.Timestamp), 0).UTC().Format(time.RFC3339),
		"agent_id":   event.AgentID,
		"details": map[string]interface{}{
			"operation":   event.Operation,
			"agent_name":  event.AgentName,
			"ip_address":  event.IPAddress,
			"runtime":     event.Runtime,
		},
	}

	// Add optional fields
	if event.ParentSpan != nil {
		apiEvent["parent_span_id"] = *event.ParentSpan
	}
	if event.DurationMS != nil {
		details := apiEvent["details"].(map[string]interface{})
		details["duration_ms"] = *event.DurationMS
	}
	if event.Success != nil {
		details := apiEvent["details"].(map[string]interface{})
		details["success"] = *event.Success
	}
	if event.ErrorMessage != nil {
		details := apiEvent["details"].(map[string]interface{})
		details["error_message"] = *event.ErrorMessage
	}
	if event.Capability != nil {
		details := apiEvent["details"].(map[string]interface{})
		details["capability"] = *event.Capability
	}
	if event.TargetAgent != nil {
		details := apiEvent["details"].(map[string]interface{})
		details["target_agent"] = *event.TargetAgent
	}

	return apiEvent
}

// mapEventType maps internal event types to API event types
func (h *EntBusinessLogicHandlers) mapEventType(eventType string) string {
	switch eventType {
	case "span_start":
		return "task_started"
	case "span_end":
		return "task_completed"
	case "error":
		return "task_failed"
	default:
		return "agent_called" // Default for unknown types
	}
}

// writeSSEEvent writes an SSE event to the response
func (h *EntBusinessLogicHandlers) writeSSEEvent(c *gin.Context, eventType string, data interface{}) {
	jsonData, _ := json.Marshal(data)
	fmt.Fprintf(c.Writer, "event: %s\ndata: %s\n\n", eventType, string(jsonData))
}

// StreamDashboardEvents implements GET /events (SSE stream for dashboard)
func (h *EntBusinessLogicHandlers) StreamDashboardEvents(c *gin.Context) {
	// Set SSE headers (CORS handled by middleware in server.go)
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")

	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, map[string]interface{}{
			"error": "streaming not supported",
		})
		return
	}

	// Subscribe to dashboard events
	ch := h.eventHub.Subscribe()
	defer h.eventHub.Unsubscribe(ch)

	// Send initial connected event with current agent summary
	resp, err := h.entService.ListAgents(nil)
	if err != nil {
		h.writeSSEEvent(c, "connected", map[string]interface{}{
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"message":   "Connected to dashboard event stream",
			"agents":    0,
		})
	} else {
		h.writeSSEEvent(c, "connected", map[string]interface{}{
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"message":   "Connected to dashboard event stream",
			"agents":    resp.Count,
		})
	}
	flusher.Flush()

	// Backfill recent events so a newly-connected dashboard sees history
	if recentEvents, err := h.entService.ListRecentEvents(50, ""); err == nil {
		for i := len(recentEvents) - 1; i >= 0; i-- {
			e := recentEvents[i]
			sseType := mapRegistryEventToSSEType(e.EventType, e.Data)
			if sseType == "" {
				continue
			}
			h.writeSSEEvent(c, sseType, DashboardEvent{
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
			h.writeSSEEvent(c, event.Type, event)
			flusher.Flush()
		case <-c.Request.Context().Done():
			return
		}
	}
}

// StreamLiveTraces implements GET /traces/live — streams ALL trace spans in real-time via SSE
func (h *EntBusinessLogicHandlers) StreamLiveTraces(c *gin.Context) {
	if h.traceAccumulator == nil {
		c.JSON(http.StatusServiceUnavailable, generated.ErrorResponse{
			Error:     "Live trace streaming not available (tracing not enabled)",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// SSE headers (CORS handled by middleware)
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")

	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     "Streaming not supported",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	ch := h.traceAccumulator.SubscribeLive()
	defer h.traceAccumulator.UnsubscribeLive(ch)

	// Send connected event
	h.writeSSEEvent(c, "connected", map[string]interface{}{
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"message":   "Connected to live trace stream",
	})
	flusher.Flush()

	// Send current active trace snapshots so the client has initial state
	for _, snapshot := range h.traceAccumulator.GetActiveTraceSnapshots() {
		h.writeSSEEvent(c, "trace_update", snapshot)
		flusher.Flush()
	}

	ctx := c.Request.Context()
	for {
		select {
		case event, ok := <-ch:
			if !ok {
				return
			}
			h.writeSSEEvent(c, event.EventType, event.Snapshot)
			flusher.Flush()
		case <-ctx.Done():
			return
		}
	}
}

// GetEventsHistory implements GET /events/history
func (h *EntBusinessLogicHandlers) GetEventsHistory(c *gin.Context, params generated.GetEventsHistoryParams) {
	limit := 50
	if params.Limit != nil {
		limit = *params.Limit
		if limit > 200 {
			limit = 200
		}
		if limit < 1 {
			limit = 1
		}
	}

	eventType := ""
	if params.EventType != nil {
		eventType = string(*params.EventType)
	}

	events, err := h.entService.ListRecentEvents(limit, eventType)
	if err != nil {
		log.Printf("[events-history] Failed to query events: %v", err)
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

// mapRegistryEventToSSEType converts a registry event_type to a dashboard SSE
// event name. Returns "" for event types that are noise for the dashboard
// (heartbeat, expire, rotate).
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

// getHostname gets the hostname for consumer group naming
func getHostname() (string, error) {
	hostname, err := os.Hostname()
	if err != nil {
		return "unknown", err
	}
	return hostname, nil
}

// ProxyMcpRequest implements POST /proxy/{target}
// Acts as a reverse proxy for MCP requests to internal agents
func (h *EntBusinessLogicHandlers) ProxyMcpRequest(c *gin.Context, target string) {
	h.proxyRequest(c, target, "POST")
}

// ProxyMcpGetRequest implements GET /proxy/{target}
// Acts as a reverse proxy for MCP GET requests to internal agents
func (h *EntBusinessLogicHandlers) ProxyMcpGetRequest(c *gin.Context, target string) {
	h.proxyRequest(c, target, "GET")
}

// proxyRequest handles the actual proxying logic for both GET and POST
func (h *EntBusinessLogicHandlers) proxyRequest(c *gin.Context, target string, method string) {
	// Parse target: expected format is {host}:{port}/mcp/...
	// Example: hello-world-agent:8080/mcp/v1/tools/call

	// Find the first / to split host:port from path
	slashIdx := strings.Index(target, "/")
	if slashIdx == -1 {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Invalid target format: missing path. Expected format: {host}:{port}/mcp/{path}",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	hostPort := target[:slashIdx]
	path := target[slashIdx:] // Includes the leading /

	// Security: Only allow /mcp or /mcp/* paths
	if path != "/mcp" && !strings.HasPrefix(path, "/mcp/") {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Only /mcp/* paths are allowed for proxying",
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Security: Validate target is a registered agent
	isRegistered, scheme, err := h.isRegisteredAgentEndpoint(c.Request.Context(), hostPort)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to validate agent: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	if !isRegistered {
		c.JSON(http.StatusForbidden, generated.ErrorResponse{
			Error:     fmt.Sprintf("Target host '%s' is not a registered agent", hostPort),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Build target URL using the scheme from the agent's registered endpoint
	targetURL := fmt.Sprintf("%s://%s%s", scheme, hostPort, path)

	// Create the proxied request
	var reqBody io.Reader
	if method == "POST" {
		reqBody = c.Request.Body
	}

	proxyReq, err := http.NewRequestWithContext(c.Request.Context(), method, targetURL, reqBody)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to create proxy request: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Copy relevant headers
	proxyReq.Header.Set("Content-Type", c.Request.Header.Get("Content-Type"))
	if accept := c.Request.Header.Get("Accept"); accept != "" {
		proxyReq.Header.Set("Accept", accept)
	}

	// Forward trace headers for distributed tracing (Issue #310)
	if traceID := c.Request.Header.Get("X-Trace-ID"); traceID != "" {
		proxyReq.Header.Set("X-Trace-ID", traceID)
	}
	if parentSpan := c.Request.Header.Get("X-Parent-Span"); parentSpan != "" {
		proxyReq.Header.Set("X-Parent-Span", parentSpan)
	}

	// Respect client timeout if provided via X-Mesh-Timeout header (#656)
	proxyTimeout := 60 * time.Second
	if timeoutHeader := c.Request.Header.Get("X-Mesh-Timeout"); timeoutHeader != "" {
		if secs, err := strconv.Atoi(timeoutHeader); err == nil && secs > 0 {
			if secs > 600 {
				secs = 600 // Cap at 10 minutes
			}
			proxyTimeout = time.Duration(secs) * time.Second
		}
	}
	client := &http.Client{
		Timeout: proxyTimeout,
	}

	// Configure TLS transport for HTTPS targets (mTLS proxy support).
	// Hostname verification is intentionally skipped because --tls-auto
	// generates certs with SANs for 127.0.0.1/::1 only, while agents in
	// K8s bind to pod IPs.  We still verify the peer cert chain against
	// our mesh CA so only certs issued by the same CA are accepted.
	// Target legitimacy is already enforced by isRegisteredAgentEndpoint().
	if scheme == "https" {
		// Require the full mTLS bundle for HTTPS proxy calls.
		caPath := os.Getenv("MCP_MESH_TLS_CA")
		certPath := os.Getenv("MCP_MESH_TLS_CERT")
		keyPath := os.Getenv("MCP_MESH_TLS_KEY")
		if caPath == "" || certPath == "" || keyPath == "" {
			log.Printf("ERROR: HTTPS proxy requires MCP_MESH_TLS_CA, MCP_MESH_TLS_CERT, MCP_MESH_TLS_KEY (ca=%q, cert=%q, key=%q)", caPath, certPath, keyPath)
			c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
				Error:     "Proxy TLS misconfiguration: missing required TLS environment variables for HTTPS proxy",
				Timestamp: time.Now().UTC(),
			})
			return
		}

		caCert, err := os.ReadFile(caPath)
		if err != nil {
			log.Printf("ERROR: failed to read CA cert %s: %v", caPath, err)
			c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
				Error:     fmt.Sprintf("Proxy TLS misconfiguration: failed to read CA cert: %v", err),
				Timestamp: time.Now().UTC(),
			})
			return
		}
		caCertPool := x509.NewCertPool()
		caCertPool.AppendCertsFromPEM(caCert)

		clientCert, err := tls.LoadX509KeyPair(certPath, keyPath)
		if err != nil {
			log.Printf("ERROR: failed to load client cert/key (%s, %s): %v", certPath, keyPath, err)
			c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
				Error:     fmt.Sprintf("Proxy TLS misconfiguration: failed to load client certificate: %v", err),
				Timestamp: time.Now().UTC(),
			})
			return
		}

		// Skip hostname check but verify the cert chain against our CA.
		tlsConfig := &tls.Config{
			InsecureSkipVerify: true,
			Certificates:      []tls.Certificate{clientCert},
			VerifyConnection: func(cs tls.ConnectionState) error {
				if len(cs.PeerCertificates) == 0 {
					return fmt.Errorf("no peer certificates presented")
				}
				opts := x509.VerifyOptions{
					Roots:         caCertPool,
					Intermediates: x509.NewCertPool(),
				}
				for _, cert := range cs.PeerCertificates[1:] {
					opts.Intermediates.AddCert(cert)
				}
				_, err := cs.PeerCertificates[0].Verify(opts)
				return err
			},
		}
		client.Transport = &http.Transport{TLSClientConfig: tlsConfig}
	}

	resp, err := client.Do(proxyReq)
	if err != nil {
		c.JSON(http.StatusBadGateway, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to reach target agent: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}
	defer resp.Body.Close()

	// Read response body
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		c.JSON(http.StatusBadGateway, generated.ErrorResponse{
			Error:     fmt.Sprintf("Failed to read response from agent: %v", err),
			Timestamp: time.Now().UTC(),
		})
		return
	}

	// Copy response headers
	for key, values := range resp.Header {
		for _, value := range values {
			c.Header(key, value)
		}
	}

	// Return the response with the same status code
	c.Data(resp.StatusCode, resp.Header.Get("Content-Type"), body)
}

// isRegisteredAgentEndpoint checks if the given host:port is a registered agent.
// Returns (isRegistered, scheme, error) where scheme is "http" or "https".
func (h *EntBusinessLogicHandlers) isRegisteredAgentEndpoint(ctx context.Context, hostPort string) (bool, string, error) {
	// Parse host and port
	parts := strings.Split(hostPort, ":")
	if len(parts) != 2 {
		return false, "", nil // Invalid format
	}

	host := parts[0]

	// Query all agents and check if any matches this endpoint
	params := &AgentQueryParams{}
	resp, err := h.entService.ListAgents(params)
	if err != nil {
		return false, "", err
	}

	port := parts[1]

	for _, agent := range resp.Agents {
		// Parse the registered endpoint URL for accurate host:port matching
		if agent.Endpoint != "" {
			parsedEP, err := url.Parse(agent.Endpoint)
			if err == nil {
				// Direct host:port match against parsed endpoint
				if parsedEP.Host == hostPort {
					return true, parsedEP.Scheme, nil
				}
				// Match by agent name (Docker/K8s hostname) with port verification
				if agent.Name == host && parsedEP.Port() == port {
					return true, parsedEP.Scheme, nil
				}
			}
		}
	}

	return false, "", nil
}
