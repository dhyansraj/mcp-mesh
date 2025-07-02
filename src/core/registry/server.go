package registry

import (
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
)

// Server represents the registry HTTP server
type Server struct {
	engine        *gin.Engine
	service       *EntService
	startTime     time.Time
	handlers      *EntBusinessLogicHandlers
	healthMonitor *AgentHealthMonitor
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

	// Create Gin engine
	engine := gin.New()
	engine.Use(gin.Recovery())
	engine.Use(gin.Logger())

	// Create server
	server := &Server{
		engine:        engine,
		service:       entService,
		startTime:     time.Now().UTC(),
		handlers:      handlers,
		healthMonitor: healthMonitor,
	}

	// Setup routes using generated interface
	server.SetupGeneratedRoutes()

	return server
}

// Run starts the HTTP server and health monitor
func (s *Server) Run(addr string) error {
	// Start health monitor
	s.healthMonitor.Start()

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
