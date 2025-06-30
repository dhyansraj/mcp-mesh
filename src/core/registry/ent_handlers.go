package registry

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/registry/generated"
)

// EntBusinessLogicHandlers implements the generated server interface using EntService
type EntBusinessLogicHandlers struct {
	entService *EntService
	startTime  time.Time
}

// NewEntBusinessLogicHandlers creates a new handler instance using EntService
func NewEntBusinessLogicHandlers(entService *EntService) *EntBusinessLogicHandlers {
	return &EntBusinessLogicHandlers{
		entService: entService,
		startTime:  time.Now(),
	}
}

// GetHealth implements GET /health
func (h *EntBusinessLogicHandlers) GetHealth(c *gin.Context) {
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
	response := generated.RootResponse{
		Service:   "mcp-mesh-registry",
		Version:   "1.0.0",
		Status:    "running",
		Endpoints: []string{"/health", "/heartbeat", "/agents"},
	}

	c.JSON(http.StatusOK, response)
}

// SendHeartbeat implements POST /heartbeat using EntService
func (h *EntBusinessLogicHandlers) SendHeartbeat(c *gin.Context) {
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

	// Call lightweight heartbeat service method using EntService
	serviceResp, err := h.entService.UpdateHeartbeat(heartbeatReq)
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

	c.JSON(http.StatusOK, response)
}

// ListAgents implements GET /agents using EntService
func (h *EntBusinessLogicHandlers) ListAgents(c *gin.Context) {
	// Parse query parameters
	var params AgentQueryParams
	if err := c.ShouldBindQuery(&params); err != nil {
		c.JSON(http.StatusBadRequest, generated.ErrorResponse{
			Error:     fmt.Sprintf("Invalid query parameters: %v", err),
			Timestamp: time.Now(),
		})
		return
	}

	// Call service method to get agents using EntService
	serviceResp, err := h.entService.ListAgents(&params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, generated.ErrorResponse{
			Error:     err.Error(),
			Timestamp: time.Now(),
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
