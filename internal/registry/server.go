package registry

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"

	"mcp-mesh/internal/config"

	"github.com/gin-gonic/gin"
)

// Server wraps the Gin server with registry-specific functionality
type Server struct {
	engine  *gin.Engine
	service *Service
	config  *config.Config
}

// NewServer creates a new registry server
func NewServer(service *Service, cfg *config.Config) *Server {
	// Set Gin mode based on environment
	if cfg.IsProduction() {
		gin.SetMode(gin.ReleaseMode)
	} else {
		gin.SetMode(gin.DebugMode)
	}

	engine := gin.New()

	// Add middleware
	engine.Use(gin.Logger())
	engine.Use(gin.Recovery())

	// CORS middleware if enabled
	if cfg.EnableCORS {
		engine.Use(corsMiddleware(cfg))
	}

	server := &Server{
		engine:  engine,
		service: service,
		config:  cfg,
	}

	// Setup routes
	server.setupRoutes()

	return server
}

// setupRoutes configures all HTTP routes
// MUST match Python FastAPI endpoints exactly
func (s *Server) setupRoutes() {
	// Root endpoint - service information
	s.engine.GET("/", s.handleRoot)

	// Health endpoints
	s.engine.GET("/health", s.handleHealth)
	s.engine.GET("/health/monitoring", s.handleHealthMonitoring)

	// Agent management endpoints
	s.engine.POST("/agents/register_with_metadata", s.handleRegisterAgent)
	s.engine.GET("/agents", s.handleListAgents)

	// Heartbeat endpoint
	s.engine.POST("/heartbeat", s.handleHeartbeat)

	// Capability discovery endpoint
	s.engine.GET("/capabilities", s.handleCapabilities)
}

// handleRoot returns service information
// MUST match Python root endpoint response exactly
func (s *Server) handleRoot(c *gin.Context) {
	response := ServiceInfo{
		Service: "MCP Mesh Registry Service",
		Version: "1.0.0",
		Endpoints: map[string]string{
			"heartbeat":      "POST /heartbeat - Agent status updates",
			"register_agent": "POST /agents/register_with_metadata - Agent registration with metadata",
			"agents":         "GET /agents - Service discovery with advanced filtering",
			"capabilities":   "GET /capabilities - Capability discovery with search",
			"health":         "GET /health - Health check",
		},
		Features: map[string]string{
			"caching":              "Response caching with 30s TTL",
			"fuzzy_matching":       "Fuzzy string matching for capability search",
			"validation":           "Request validation for all inputs",
			"health_monitoring":    "Timer-based passive health monitoring",
			"automatic_eviction":   "Passive agent eviction on timeout",
		},
		Architecture: "Kubernetes API Server pattern (PASSIVE pull-based)",
		Description:  "Enhanced service registry for MCP agent mesh with advanced discovery capabilities",
	}

	c.JSON(http.StatusOK, response)
}

// handleHealth returns service health status
// MUST match Python health_check response exactly
func (s *Server) handleHealth(c *gin.Context) {
	health := s.service.Health()

	if status, ok := health["status"].(string); ok && status == "healthy" {
		c.JSON(http.StatusOK, health)
	} else {
		c.JSON(http.StatusServiceUnavailable, health)
	}
}

// handleRegisterAgent handles agent registration with metadata
// MUST match Python register_agent_with_metadata behavior exactly
func (s *Server) handleRegisterAgent(c *gin.Context) {
	// DEBUG: Log raw request body before parsing
	bodyBytes, _ := c.GetRawData()
	fmt.Printf("🐛 DEBUG: Received registration payload: %s\n", string(bodyBytes))

	// Reset the body so ShouldBindJSON can read it
	c.Request.Body = io.NopCloser(strings.NewReader(string(bodyBytes)))

	var req AgentRegistrationRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		fmt.Printf("🐛 DEBUG: JSON binding failed: %v\n", err)
		fmt.Printf("🐛 DEBUG: Raw payload was: %s\n", string(bodyBytes))
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Detail: err.Error(),
		})
		return
	}

	fmt.Printf("🐛 DEBUG: Successfully parsed request - AgentID: %s, Metadata keys: %v\n",
		req.AgentID, getMapKeys(req.Metadata))

	response, err := s.service.RegisterAgent(&req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Detail: fmt.Sprintf("Failed to register agent: %s", err.Error()),
		})
		return
	}

	c.JSON(http.StatusCreated, response)
}

// handleHeartbeat handles agent heartbeat updates
// MUST match Python heartbeat_endpoint behavior exactly
func (s *Server) handleHeartbeat(c *gin.Context) {
	var req HeartbeatRequest

	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Detail: err.Error(),
		})
		return
	}

	// Set default status if not provided
	if req.Status == "" {
		req.Status = "healthy"
	}

	response, err := s.service.UpdateHeartbeat(&req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Detail: fmt.Sprintf("Failed to process heartbeat: %s", err.Error()),
		})
		return
	}

	// Check if agent was not found (matches Python logic)
	if response.Status == "error" && strings.Contains(response.Message, "not found") {
		c.JSON(http.StatusNotFound, ErrorResponse{
			Detail: response.Message,
		})
		return
	}

	c.JSON(http.StatusOK, response)
}

// handleListAgents handles agent discovery with filtering
// MUST match Python get_agents behavior exactly
func (s *Server) handleListAgents(c *gin.Context) {
	params := &AgentQueryParams{}

	// Bind query parameters
	if err := c.ShouldBindQuery(params); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Detail: err.Error(),
		})
		return
	}

	// Handle single capability parameter (convert to slice)
	if params.Capability != "" {
		params.Capabilities = []string{params.Capability}
	}

	// Parse capability_tags from comma-separated string
	if capabilityTags := c.Query("capability_tags"); capabilityTags != "" {
		params.CapabilityTags = strings.Split(capabilityTags, ",")
		// Trim whitespace
		for i, tag := range params.CapabilityTags {
			params.CapabilityTags[i] = strings.TrimSpace(tag)
		}
	}

	// Parse label_selector (simple format: key=value,key2=value2)
	if labelSelector := c.Query("label_selector"); labelSelector != "" {
		params.LabelSelector = make(map[string]string)
		selectors := strings.Split(labelSelector, ",")
		for _, selector := range selectors {
			if strings.Contains(selector, "=") {
				parts := strings.SplitN(selector, "=", 2)
				if len(parts) == 2 {
					key := strings.TrimSpace(parts[0])
					value := strings.TrimSpace(parts[1])
					params.LabelSelector[key] = value
				}
			} else {
				c.JSON(http.StatusBadRequest, ErrorResponse{
					Detail: fmt.Sprintf("Invalid label selector format: %s. Expected 'key=value'", selector),
				})
				return
			}
		}
	}

	response, err := s.service.ListAgents(params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Detail: fmt.Sprintf("Failed to list agents: %s", err.Error()),
		})
		return
	}

	c.JSON(http.StatusOK, response)
}

// handleCapabilities handles capability discovery with search
// MUST match Python get_capabilities behavior exactly
func (s *Server) handleCapabilities(c *gin.Context) {
	params := &CapabilityQueryParams{}

	// Bind query parameters
	if err := c.ShouldBindQuery(params); err != nil {
		c.JSON(http.StatusBadRequest, ErrorResponse{
			Detail: err.Error(),
		})
		return
	}

	// Parse tags from comma-separated string
	if tags := c.Query("tags"); tags != "" {
		params.Tags = strings.Split(tags, ",")
		// Trim whitespace
		for i, tag := range params.Tags {
			params.Tags[i] = strings.TrimSpace(tag)
		}
	}

	// Set default agent_status if not provided (matches Python default)
	if params.AgentStatus == "" {
		params.AgentStatus = "healthy"
	}

	response, err := s.service.SearchCapabilities(params)
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Detail: fmt.Sprintf("Failed to list capabilities: %s", err.Error()),
		})
		return
	}

	c.JSON(http.StatusOK, response)
}

// handleHealthMonitoring returns health monitoring statistics
// MUST match Python health monitoring endpoints
func (s *Server) handleHealthMonitoring(c *gin.Context) {
	stats, err := s.service.GetHealthMonitoringStats()
	if err != nil {
		c.JSON(http.StatusInternalServerError, ErrorResponse{
			Detail: fmt.Sprintf("Failed to get health monitoring stats: %s", err.Error()),
		})
		return
	}

	c.JSON(http.StatusOK, stats)
}

// Start starts the HTTP server
func (s *Server) Start() error {
	addr := fmt.Sprintf("%s:%d", s.config.Host, s.config.Port)

	// Start health monitoring (matches Python behavior)
	if err := s.service.StartHealthMonitoring(); err != nil {
		log.Printf("Warning: Failed to start health monitoring: %v", err)
	}

	fmt.Printf("🚀 Starting MCP Mesh Registry Service\n")
	fmt.Printf("📡 Server: http://%s:%d\n", s.config.Host, s.config.Port)
	fmt.Printf("📊 Health monitoring: enabled\n")
	fmt.Printf("🏗️  Architecture: Kubernetes API Server pattern\n")
	fmt.Printf("🔄 Mode: PASSIVE (pull-based)\n")
	fmt.Printf("🌐 REST Endpoints:\n")
	fmt.Printf("   POST /heartbeat - Agent status updates\n")
	fmt.Printf("   POST /agents/register_with_metadata - Agent registration with metadata\n")
	fmt.Printf("   GET  /agents - Service discovery (with fuzzy matching & filtering)\n")
	fmt.Printf("   GET  /capabilities - Capability discovery (with advanced search)\n")
	fmt.Printf("   GET  /health - Health check\n")
	fmt.Printf("   GET  /health/monitoring - Health monitoring statistics\n")
	fmt.Printf("🚀 Features:\n")
	fmt.Printf("   ✓ Response caching (30s TTL)\n")
	fmt.Printf("   ✓ Fuzzy matching for capabilities\n")
	fmt.Printf("   ✓ Version constraint filtering\n")
	fmt.Printf("   ✓ Request validation\n")
	fmt.Printf("   ✓ Kubernetes-style label selectors\n")
	fmt.Printf("   ✓ Timer-based health monitoring (10s interval)\n")
	fmt.Printf("   ✓ Configurable timeout thresholds per agent type\n")
	fmt.Printf("   ✓ Automatic agent eviction (passive)\n")
	fmt.Printf("-" + strings.Repeat("-", 59) + "\n")

	return s.engine.Run(addr)
}

// Stop gracefully shuts down the server
func (s *Server) Stop() error {
	// Stop health monitoring first
	if err := s.service.StopHealthMonitoring(); err != nil {
		log.Printf("Warning: Failed to stop health monitoring: %v", err)
	}

	// In production, you would implement graceful shutdown here
	return nil
}

// corsMiddleware adds CORS headers if enabled
func corsMiddleware(cfg *config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := c.Request.Header.Get("Origin")

		// Check if origin is allowed
		allowed := false
		for _, allowedOrigin := range cfg.AllowedOrigins {
			if allowedOrigin == "*" || allowedOrigin == origin {
				allowed = true
				break
			}
		}

		if allowed {
			c.Header("Access-Control-Allow-Origin", origin)
		}

		c.Header("Access-Control-Allow-Methods", strings.Join(cfg.AllowedMethods, ","))
		c.Header("Access-Control-Allow-Headers", strings.Join(cfg.AllowedHeaders, ","))
		c.Header("Access-Control-Allow-Credentials", "true")

		// Handle preflight requests
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}

		c.Next()
	}
}

// Additional helper functions for query parameter parsing

func parseIntQuery(c *gin.Context, key string, defaultValue int) int {
	if value := c.Query(key); value != "" {
		if intValue, err := strconv.Atoi(value); err == nil {
			return intValue
		}
	}
	return defaultValue
}

func parseBoolQuery(c *gin.Context, key string, defaultValue bool) bool {
	if value := c.Query(key); value != "" {
		if boolValue, err := strconv.ParseBool(value); err == nil {
			return boolValue
		}
	}
	return defaultValue
}

func parseStringSliceQuery(c *gin.Context, key string) []string {
	if value := c.Query(key); value != "" {
		parts := strings.Split(value, ",")
		result := make([]string, len(parts))
		for i, part := range parts {
			result[i] = strings.TrimSpace(part)
		}
		return result
	}
	return nil
}

// Helper function for debug logging
func getMapKeys(m map[string]interface{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
