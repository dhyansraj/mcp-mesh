package registry

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/generated"
)

// BusinessLogicHandlers implements the generated server interface
//
// 🤖 AI BEHAVIOR GUIDANCE:
// This file contains the actual business logic for registry operations.
// The handler signatures are generated from OpenAPI spec - DO NOT modify them.
//
// TO ADD NEW ENDPOINTS:
// 1. Update api/mcp-mesh-registry.openapi.yaml
// 2. Run: make generate
// 3. Implement new methods in this file
type BusinessLogicHandlers struct {
	service   *Service
	startTime time.Time
}

// NewBusinessLogicHandlers creates a new handler instance
func NewBusinessLogicHandlers(service *Service) *BusinessLogicHandlers {
	return &BusinessLogicHandlers{
		service:   service,
		startTime: time.Now(),
	}
}

// GetHealth implements GET /health
func (h *BusinessLogicHandlers) GetHealth(c *gin.Context) {
	uptime := time.Since(h.startTime).Seconds()

	response := generated.HealthResponse{
		Status:        "healthy",
		Version:       "1.0.0",
		UptimeSeconds: int(uptime),
		Timestamp:     time.Now(),
		Service:       "mcp-mesh-registry",
	}

	c.JSON(http.StatusOK, response)
}

// GetRoot implements GET /
func (h *BusinessLogicHandlers) GetRoot(c *gin.Context) {
	response := generated.RootResponse{
		Service:   "mcp-mesh-registry",
		Version:   "1.0.0",
		Status:    "running",
		Endpoints: []string{"/health", "/heartbeat", "/agents", "/agents/register"},
	}

	c.JSON(http.StatusOK, response)
}

// RegisterAgent implements POST /agents/register
func (h *BusinessLogicHandlers) RegisterAgent(c *gin.Context) {
	var req generated.AgentRegistration
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now(),
		})
		return
	}

	// Convert generated.AgentRegistration to service.AgentRegistrationRequest
	serviceReq := &AgentRegistrationRequest{
		AgentID:   req.AgentId,
		Timestamp: req.Timestamp.Format(time.RFC3339),
		Metadata:  convertAgentMetadataToMap(req.Metadata),
	}

	// Call the actual service registration logic
	serviceResp, err := h.service.RegisterAgent(serviceReq)
	if err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now(),
		})
		return
	}

	// Convert service response to generated response format
	response := generated.RegistrationResponse{
		Status:    generated.RegistrationResponseStatus(serviceResp.Status),
		Timestamp: time.Now(),
		Message:   serviceResp.Message,
		AgentId:   serviceResp.AgentID,
	}

	// Include dependency resolution if available
	if serviceResp.DependenciesResolved != nil {
		deps := make(map[string]generated.DependencyInfo)
		for key, dep := range serviceResp.DependenciesResolved {
			if dep != nil {
				deps[key] = generated.DependencyInfo{
					AgentId:  dep.AgentID,
					Endpoint: dep.Endpoint,
					Status:   generated.DependencyInfoStatus(dep.Status),
				}
			}
		}
		response.DependenciesResolved = &deps
	}

	c.JSON(http.StatusCreated, response)
}

// SendHeartbeat implements POST /heartbeat
func (h *BusinessLogicHandlers) SendHeartbeat(c *gin.Context) {
	var req generated.HeartbeatRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     "Invalid JSON payload",
			Timestamp: time.Now(),
		})
		return
	}

	// TODO: Implement actual heartbeat logic
	// This is where you add business logic for heartbeat processing

	response := generated.HeartbeatResponse{
		Status:    "success",
		Timestamp: time.Now(),
		Message:   "Heartbeat received",
	}

	c.JSON(http.StatusOK, response)
}

// ListAgents implements GET /agents
func (h *BusinessLogicHandlers) ListAgents(c *gin.Context) {
	// TODO: Implement actual agent listing logic
	// This is where you add business logic for listing agents

	response := generated.AgentsListResponse{
		Agents:    []generated.AgentInfo{},
		Count:     0,
		Timestamp: time.Now(),
	}

	c.JSON(http.StatusOK, response)
}

// convertAgentMetadataToMap converts generated.AgentMetadata to map[string]interface{}
// for compatibility with the service layer
func convertAgentMetadataToMap(metadata generated.AgentMetadata) map[string]interface{} {
	result := make(map[string]interface{})

	result["name"] = metadata.Name
	result["agent_type"] = string(metadata.AgentType)
	result["namespace"] = metadata.Namespace
	result["endpoint"] = metadata.Endpoint
	result["capabilities"] = metadata.Capabilities

	if metadata.Dependencies != nil {
		result["dependencies"] = *metadata.Dependencies
	}

	if metadata.HealthInterval != nil {
		result["health_interval"] = *metadata.HealthInterval
	}

	if metadata.TimeoutThreshold != nil {
		result["timeout_threshold"] = *metadata.TimeoutThreshold
	}

	if metadata.EvictionThreshold != nil {
		result["eviction_threshold"] = *metadata.EvictionThreshold
	}

	if metadata.Version != nil {
		result["version"] = *metadata.Version
	}

	if metadata.Description != nil {
		result["description"] = *metadata.Description
	}

	if metadata.Tags != nil {
		result["tags"] = *metadata.Tags
	}

	if metadata.SecurityContext != nil {
		result["security_context"] = *metadata.SecurityContext
	}

	return result
}
