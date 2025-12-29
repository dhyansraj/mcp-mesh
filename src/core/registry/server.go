package registry

import (
	"fmt"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
	"mcp-mesh/src/core/registry/tracing"
)

// Server represents the registry HTTP server
type Server struct {
	engine         *gin.Engine
	service        *EntService
	startTime      time.Time
	handlers       *EntBusinessLogicHandlers
	healthMonitor  *AgentHealthMonitor
	tracingManager *tracing.TracingManager
}

// NewServer creates a new registry server using Ent database
func NewServer(entDB *database.EntDatabase, config *RegistryConfig, logger *logger.Logger) *Server {
	// Create Ent-based service
	entService := NewEntService(entDB, config, logger)

	// Create Ent-based business logic handlers
	handlers := NewEntBusinessLogicHandlers(entService)

	// Create health monitor using configuration values
	heartbeatTimeout := time.Duration(config.DefaultTimeoutThreshold) * time.Second
	checkInterval := time.Duration(config.HealthCheckInterval) * time.Second
	healthMonitor := NewAgentHealthMonitor(entService, logger, heartbeatTimeout, checkInterval)

	// Initialize distributed tracing if enabled
	var tracingManager *tracing.TracingManager
	if config.TracingEnabled {
		tracingConfig := tracing.LoadTracingConfigFromEnv()
		if tm, err := tracing.NewTracingManager(tracingConfig); err != nil {
			logger.Warning("Failed to initialize tracing manager: %v", err)
		} else {
			tracingManager = tm
		}
	}

	// Create Gin engine
	engine := gin.New()
	engine.Use(gin.Recovery())
	engine.Use(gin.Logger())

	// Create server
	server := &Server{
		engine:         engine,
		service:        entService,
		startTime:      time.Now().UTC(),
		handlers:       handlers,
		healthMonitor:  healthMonitor,
		tracingManager: tracingManager,
	}

	// Add operational endpoints first (includes wildcard proxy routes that must be registered before generated routes)
	server.setupOperationalEndpoints()

	// Setup routes using generated interface
	server.SetupGeneratedRoutes()

	return server
}

// Run starts the HTTP server and health monitor
func (s *Server) Run(addr string) error {
	// Start health monitor
	s.healthMonitor.Start()

	// Start distributed tracing if enabled
	if s.tracingManager != nil {
		if err := s.tracingManager.Start(); err != nil {
			// Log warning but don't fail startup
			fmt.Printf("⚠️ Failed to start distributed tracing: %v\n", err)
		}
	}

	return s.engine.Run(addr)
}

// Start starts the HTTP server (alias for compatibility)
func (s *Server) Start() error {
	return s.engine.Run(":8080") // Default port
}

// Stop stops the HTTP server and health monitor
func (s *Server) Stop() error {
	// Stop health monitor
	s.healthMonitor.Stop()

	// Stop distributed tracing if enabled
	if s.tracingManager != nil {
		if err := s.tracingManager.Stop(); err != nil {
			fmt.Printf("⚠️ Failed to stop distributed tracing: %v\n", err)
		}
	}

	// TODO: Implement graceful shutdown for HTTP server
	return nil
}

// SetupGeneratedRoutes configures all routes using the generated OpenAPI interface
//
// 🤖 AI BEHAVIOR GUIDANCE:
// This method uses the auto-generated router setup from OpenAPI specification.
// DO NOT add manual routes here - they will not match the contract.
//
// TO ADD NEW ENDPOINTS:
// 1. Update api/mcp-mesh-registry.openapi.yaml
// 2. Run: make generate
// 3. This method will automatically include new routes
func (s *Server) SetupGeneratedRoutes() {
	// Register all routes from OpenAPI spec using handlers directly
	generated.RegisterHandlers(s.engine, s.handlers)
}

// setupOperationalEndpoints adds operational endpoints not part of the OpenAPI spec
func (s *Server) setupOperationalEndpoints() {
	// Note: /health is already defined in OpenAPI spec, so we use different paths

	// Proxy endpoints - need wildcard routes since OpenAPI :target only captures one segment
	// These override the generated single-segment routes to capture multi-segment paths
	s.engine.POST("/proxy/*target", s.handleProxyRequest)
	s.engine.GET("/proxy/*target", s.handleProxyGetRequest)

	// Tracing status endpoint
	s.engine.GET("/trace/status", s.handleTracingStatus)

	// Tracing stats endpoint
	s.engine.GET("/trace/stats", s.handleTracingStats)

	// Tracing manager info endpoint
	s.engine.GET("/trace/info", s.handleTracingInfo)

	// Trace query endpoints
	s.engine.GET("/trace/list", s.handleTraceList)
	s.engine.GET("/trace/:trace_id", s.handleTraceGet)
	s.engine.GET("/trace/search", s.handleTraceSearch)
}

// handleTracingInfo provides detailed tracing manager information
func (s *Server) handleTracingInfo(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"reason":  "tracing not initialized",
			"config":  "MCP_MESH_DISTRIBUTED_TRACING_ENABLED=false",
		})
		return
	}

	info := s.tracingManager.GetInfo()
	c.JSON(200, info)
}

// handleTracingStatus provides tracing status information
func (s *Server) handleTracingStatus(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"reason":  "tracing not initialized",
		})
		return
	}

	status := s.tracingManager.GetInfo()
	c.JSON(200, status)
}

// handleTracingStats provides tracing statistics
func (s *Server) handleTracingStats(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"reason":  "tracing not initialized",
		})
		return
	}

	stats := s.tracingManager.GetStats()
	if stats == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": true,
			"stats_available": false,
			"reason": "statistics collection not enabled",
		})
		return
	}

	c.JSON(200, stats)
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

	// Parse query parameters
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

	// Get traces
	traces := s.tracingManager.ListTraces(limit, offset)
	total := s.tracingManager.GetTraceCount()

	response := map[string]interface{}{
		"enabled": true,
		"traces":  traces,
		"total":   total,
		"limit":   limit,
		"offset":  offset,
		"count":   len(traces),
	}

	c.JSON(200, response)
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

// handleProxyRequest handles POST /proxy/*target (wildcard path for multi-segment targets)
func (s *Server) handleProxyRequest(c *gin.Context) {
	target := c.Param("target")
	// Gin wildcard captures with leading slash, remove it
	if len(target) > 0 && target[0] == '/' {
		target = target[1:]
	}
	s.handlers.ProxyMcpRequest(c, target)
}

// handleProxyGetRequest handles GET /proxy/*target (wildcard path for multi-segment targets)
func (s *Server) handleProxyGetRequest(c *gin.Context) {
	target := c.Param("target")
	// Gin wildcard captures with leading slash, remove it
	if len(target) > 0 && target[0] == '/' {
		target = target[1:]
	}
	s.handlers.ProxyMcpGetRequest(c, target)
}

// handleTraceSearch searches traces based on criteria
func (s *Server) handleTraceSearch(c *gin.Context) {
	if s.tracingManager == nil {
		c.JSON(200, map[string]interface{}{
			"enabled": false,
			"traces":  []interface{}{},
			"total":   0,
		})
		return
	}

	// Parse search criteria from query parameters
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

	// Perform search
	traces := s.tracingManager.SearchTraces(criteria)

	response := map[string]interface{}{
		"enabled":  true,
		"traces":   traces,
		"count":    len(traces),
		"criteria": criteria,
	}

	c.JSON(200, response)
}
