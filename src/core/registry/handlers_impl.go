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
	var req generated.MeshAgentRegistration
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now(),
		})
		return
	}

	// Convert generated.MeshAgentRegistration to service.AgentRegistrationRequest
	serviceReq := &AgentRegistrationRequest{
		AgentID:   req.AgentId,
		Timestamp: time.Now().Format(time.RFC3339),
		Metadata:  ConvertMeshAgentRegistrationToMap(req),
	}
	if req.Timestamp != nil {
		serviceReq.Timestamp = req.Timestamp.Format(time.RFC3339)
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
	response := generated.MeshRegistrationResponse{
		Status:    generated.MeshRegistrationResponseStatus(serviceResp.Status),
		Timestamp: time.Now(),
		Message:   serviceResp.Message,
		AgentId:   serviceResp.AgentID,
	}

	// Include dependency resolution if available
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

	c.JSON(http.StatusCreated, response)
}

// SendHeartbeat implements POST /heartbeat
func (h *BusinessLogicHandlers) SendHeartbeat(c *gin.Context) {
	var req generated.MeshAgentRegistration
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid JSON payload: %v", err),
			Timestamp: time.Now(),
		})
		return
	}

	// Convert to heartbeat request format (lighter than full registration)
	heartbeatReq := &HeartbeatRequest{
		AgentID:  req.AgentId,
		Status:   "healthy", // Default status
		Metadata: ConvertMeshAgentRegistrationToMap(req),
	}

	// Call lightweight heartbeat service method
	serviceResp, err := h.service.UpdateHeartbeat(heartbeatReq)
	if err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now(),
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
		Timestamp: time.Now(),
		Message:   serviceResp.Message,
		AgentId:   req.AgentId,
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

	// Construct endpoint from http_host and http_port
	endpoint := ""
	if reg.HttpHost != nil && reg.HttpPort != nil {
		if *reg.HttpPort == 0 {
			endpoint = "stdio" // Port 0 indicates stdio transport
		} else {
			endpoint = fmt.Sprintf("http://%s:%d", *reg.HttpHost, *reg.HttpPort)
		}
	} else {
		endpoint = "stdio" // Default to stdio if not specified
	}
	result["endpoint"] = endpoint

	// Extract capabilities from tools
	capabilities := make([]string, len(reg.Tools))
	for i, tool := range reg.Tools {
		capabilities[i] = tool.Capability
	}
	result["capabilities"] = capabilities

	// Extract dependencies from tools
	allDependencies := make([]interface{}, 0)
	for _, tool := range reg.Tools {
		if tool.Dependencies != nil {
			for _, dep := range *tool.Dependencies {
				depMap := map[string]interface{}{
					"capability": dep.Capability,
				}
				if dep.Namespace != nil {
					depMap["namespace"] = *dep.Namespace
				}
				if dep.Tags != nil {
					depMap["tags"] = *dep.Tags
				}
				if dep.Version != nil {
					depMap["version"] = *dep.Version
				}
				allDependencies = append(allDependencies, depMap)
			}
		}
	}
	result["dependencies"] = allDependencies

	// Store tools information for potential future use
	toolsData := make([]interface{}, len(reg.Tools))
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
		toolsData[i] = toolData
	}
	result["tools"] = toolsData

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
	// Note: Dependencies field removed from API spec - using real-time resolution instead

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
