package registry

import (
	"encoding/json"
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
	// Parse query parameters
	var params AgentQueryParams
	if err := c.ShouldBindQuery(&params); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid query parameters: %v", err),
			Timestamp: time.Now(),
		})
		return
	}

	// Call service method to get agents
	serviceResp, err := h.service.ListAgents(&params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now(),
		})
		return
	}

	// Convert service response to generated response format
	agents := make([]generated.AgentInfo, len(serviceResp.Agents))
	for i, agentMap := range serviceResp.Agents {
		agents[i] = convertMapToAgentInfo(agentMap)
	}

	response := generated.AgentsListResponse{
		Agents:    agents,
		Count:     serviceResp.Count,
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
	if metadata.Capabilities != nil {
		result["capabilities"] = *metadata.Capabilities // Dereference pointer
	} else {
		result["capabilities"] = []string{} // Default empty array
	}

	if metadata.Dependencies != nil {
		// Convert union types to appropriate format for service layer
		deps := make([]interface{}, len(*metadata.Dependencies))
		for i, dep := range *metadata.Dependencies {
			// Try to unmarshal as string first, then as object
			if stringDep, err := dep.AsAgentMetadataDependencies0(); err == nil {
				deps[i] = stringDep
			} else if objDep, err := dep.AsAgentMetadataDependencies1(); err == nil {
				deps[i] = map[string]interface{}{
					"capability": objDep.Capability,
					"tags":       objDep.Tags,
					"version":    objDep.Version,
					"namespace":  objDep.Namespace,
				}
			} else {
				// Fallback: try to marshal and unmarshal to get raw interface{}
				if jsonBytes, err := dep.MarshalJSON(); err == nil {
					var rawDep interface{}
					if err := json.Unmarshal(jsonBytes, &rawDep); err == nil {
						deps[i] = rawDep
					}
				}
			}
		}
		result["dependencies"] = deps
	} else {
		result["dependencies"] = []interface{}{} // Default empty array when nil
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

// convertMapToAgentInfo converts service layer map[string]interface{} to generated.AgentInfo
func convertMapToAgentInfo(agentMap map[string]interface{}) generated.AgentInfo {
	agentInfo := generated.AgentInfo{}

	// Required fields
	if id, ok := agentMap["id"].(string); ok {
		agentInfo.Id = id
	}
	if name, ok := agentMap["name"].(string); ok {
		agentInfo.Name = name
	}
	if endpoint, ok := agentMap["endpoint"].(string); ok {
		agentInfo.Endpoint = endpoint
	}
	if status, ok := agentMap["status"].(string); ok {
		agentInfo.Status = generated.AgentInfoStatus(status)
	}

	// Capabilities (required field)
	if caps, ok := agentMap["capabilities"].([]interface{}); ok {
		capabilities := make([]string, len(caps))
		for i, cap := range caps {
			if capStr, ok := cap.(string); ok {
				capabilities[i] = capStr
			} else if capMap, ok := cap.(map[string]interface{}); ok {
				// Extract name from capability object
				if name, ok := capMap["name"].(string); ok {
					capabilities[i] = name
				}
			}
		}
		agentInfo.Capabilities = capabilities
	} else if caps, ok := agentMap["capabilities"].([]string); ok {
		agentInfo.Capabilities = caps
	}

	// Optional fields
	if deps, ok := agentMap["dependencies"].([]interface{}); ok {
		dependencies := make([]string, len(deps))
		for i, dep := range deps {
			if depStr, ok := dep.(string); ok {
				dependencies[i] = depStr
			} else if depObj, ok := dep.(map[string]interface{}); ok {
				// For complex dependencies, create a descriptive string
				if capability, ok := depObj["capability"].(string); ok {
					dependencies[i] = capability
					if tags, ok := depObj["tags"].([]interface{}); ok && len(tags) > 0 {
						// Add first tag to make it more descriptive
						if firstTag, ok := tags[0].(string); ok {
							dependencies[i] = fmt.Sprintf("%s:%s", capability, firstTag)
						}
					}
				} else {
					dependencies[i] = "unknown"
				}
			} else {
				dependencies[i] = "unknown"
			}
		}
		agentInfo.Dependencies = &dependencies
	} else if deps, ok := agentMap["dependencies"].([]string); ok {
		agentInfo.Dependencies = &deps
	}

	if lastSeen, ok := agentMap["last_seen"].(string); ok {
		if t, err := time.Parse(time.RFC3339, lastSeen); err == nil {
			agentInfo.LastSeen = &t
		}
	}

	if version, ok := agentMap["version"].(string); ok {
		agentInfo.Version = &version
	}

	return agentInfo
}
