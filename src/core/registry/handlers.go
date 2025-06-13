package registry

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// SetupRoutes configures all registry endpoints
func (s *Server) SetupRoutes() {
	// Health check - minimal implementation
	s.engine.GET("/health", s.handleHealth)

	// Root endpoint for basic connectivity test
	s.engine.GET("/", s.handleRoot)

	// Basic heartbeat endpoint for agent connectivity
	s.engine.POST("/heartbeat", s.handleHeartbeat)

	// Agent registration endpoint
	s.engine.POST("/agents/register", s.handleRegisterAgent)

	// Basic agents listing endpoint
	s.engine.GET("/agents", s.handleListAgents)
}

// handleRegisterAgent handles agent registration requests
func (s *Server) handleRegisterAgent(c *gin.Context) {
	var reqMap map[string]interface{}
	if err := c.ShouldBindJSON(&reqMap); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid JSON payload",
		})
		return
	}

	// Basic registration response - just acknowledge the registration
	c.JSON(http.StatusCreated, gin.H{
		"status": "success",
		"timestamp": time.Now().Format(time.RFC3339),
		"message": "Agent registered successfully",
		"agent_id": reqMap["agent_id"],
	})
}

// handleHeartbeat handles agent heartbeat requests
func (s *Server) handleHeartbeat(c *gin.Context) {
	var reqMap map[string]interface{}
	if err := c.ShouldBindJSON(&reqMap); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": "Invalid JSON payload",
		})
		return
	}

	// Basic heartbeat response - just acknowledge the agent
	c.JSON(http.StatusOK, gin.H{
		"status": "success",
		"timestamp": time.Now().Format(time.RFC3339),
		"message": "Heartbeat received",
	})
}

// handleListAgents lists all agents (basic implementation)
func (s *Server) handleListAgents(c *gin.Context) {
	// For now, return empty agents list
	c.JSON(http.StatusOK, gin.H{
		"agents": []map[string]interface{}{},
		"count":  0,
		"timestamp": time.Now().Format(time.RFC3339),
	})
}

// handleHealth returns registry health status
func (s *Server) handleHealth(c *gin.Context) {
	uptime := time.Since(s.startTime).Seconds()

	c.JSON(http.StatusOK, gin.H{
		"status":         "healthy",
		"version":        "1.0.0",
		"uptime_seconds": int(uptime),
		"timestamp":      time.Now().Format(time.RFC3339),
		"service":        "mcp-mesh-registry",
	})
}

// handleRoot returns basic registry info
func (s *Server) handleRoot(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"service":   "mcp-mesh-registry",
		"version":   "1.0.0",
		"status":    "running",
		"endpoints": []string{"/health", "/heartbeat", "/agents", "/agents/register"},
	})
}
