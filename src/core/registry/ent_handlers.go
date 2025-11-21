package registry

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"mcp-mesh/src/core/registry/generated"
	"mcp-mesh/src/core/registry/tracing"
)

// EntBusinessLogicHandlers implements the generated server interface using EntService
type EntBusinessLogicHandlers struct {
	entService  *EntService
	startTime   time.Time
	redisClient *redis.Client
}

// NewEntBusinessLogicHandlers creates a new handler instance using EntService
func NewEntBusinessLogicHandlers(entService *EntService) *EntBusinessLogicHandlers {
	// Initialize Redis client for trace streaming
	redisClient := initializeRedisClient()

	return &EntBusinessLogicHandlers{
		entService:  entService,
		startTime:   time.Now().UTC(),
		redisClient: redisClient,
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
		depsMap := make(map[string][]struct {
			AgentId      string                                                       `json:"agent_id"`
			Capability   string                                                       `json:"capability"`
			Endpoint     string                                                       `json:"endpoint"`
			FunctionName string                                                       `json:"function_name"`
			Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
		})

		for functionName, deps := range serviceResp.DependenciesResolved {
			if len(deps) > 0 {
				depsList := make([]struct {
					AgentId      string                                                       `json:"agent_id"`
					Capability   string                                                       `json:"capability"`
					Endpoint     string                                                       `json:"endpoint"`
					FunctionName string                                                       `json:"function_name"`
					Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
				}, len(deps))

				for i, dep := range deps {
					depsList[i] = struct {
						AgentId      string                                                       `json:"agent_id"`
						Capability   string                                                       `json:"capability"`
						Endpoint     string                                                       `json:"endpoint"`
						FunctionName string                                                       `json:"function_name"`
						Status       generated.MeshRegistrationResponseDependenciesResolvedStatus `json:"status"`
					}{
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
					Name:        tool.FunctionName,
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

// ConvertMeshAgentRegistrationToMap converts generated.MeshAgentRegistration to map[string]interface{}
// for compatibility with the service layer
func ConvertMeshAgentRegistrationToMap(reg generated.MeshAgentRegistration) map[string]interface{} {
	result := make(map[string]interface{})

	// Basic agent information
	if reg.Name != nil {
		result["name"] = *reg.Name
	} else {
		result["name"] = reg.AgentId // Default to agent_id if name not provided
	}

	if reg.AgentType != nil {
		result["agent_type"] = string(*reg.AgentType)
	} else {
		result["agent_type"] = "mcp_agent" // Default type
	}

	if reg.Namespace != nil {
		result["namespace"] = *reg.Namespace
	}

	if reg.Version != nil {
		result["version"] = *reg.Version
	}

	// Include HTTP host and port as separate fields for the service layer
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
					depData["tags"] = *dep.Tags
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
		h.entService.logger.Info("Agent %s: topology changed, returning 202 (last_full_refresh: %v)", agentId, agentEntity.LastFullRefresh)
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

// getHostname gets the hostname for consumer group naming
func getHostname() (string, error) {
	hostname, err := os.Hostname()
	if err != nil {
		return "unknown", err
	}
	return hostname, nil
}
