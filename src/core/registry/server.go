package registry

import (
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/registry/generated"
)

// Server represents the registry HTTP server
type Server struct {
	engine    *gin.Engine
	service   *Service
	startTime time.Time
	handlers  *BusinessLogicHandlers
}

// NewServer creates a new registry server using generated OpenAPI handlers
func NewServer(db *database.Database, config *RegistryConfig) *Server {
	// Create service
	service := NewService(db, config)

	// Create business logic handlers that implement the generated interface
	handlers := NewBusinessLogicHandlers(service)

	// Create Gin engine
	engine := gin.New()
	engine.Use(gin.Recovery())
	engine.Use(gin.Logger())

	// Create server
	server := &Server{
		engine:    engine,
		service:   service,
		startTime: time.Now(),
		handlers:  handlers,
	}

	// Setup routes using generated interface
	server.SetupGeneratedRoutes()
	
	// Setup additional decorator-based routes (until OpenAPI generation supports them)
	server.SetupDecoratorRoutes()

	// Create and start health monitor (temporarily disabled due to field conflicts)
	// healthMonitor := NewHealthMonitor(service, 10*time.Second)
	// service.healthMonitor = healthMonitor
	// go healthMonitor.Start()

	return server
}

// Run starts the HTTP server
func (s *Server) Run(addr string) error {
	return s.engine.Run(addr)
}

// Start starts the HTTP server (alias for compatibility)
func (s *Server) Start() error {
	return s.engine.Run(":8080") // Default port
}

// Stop stops the HTTP server
func (s *Server) Stop() error {
	// TODO: Implement graceful shutdown
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
	// Use the generated server interface wrapper
	wrapper := generated.ServerInterfaceWrapper{
		Handler: s.handlers,
	}

	// Register all routes from OpenAPI spec
	generated.RegisterHandlers(s.engine, &wrapper)
}

// SetupDecoratorRoutes configures decorator-based endpoints
// These will be integrated into OpenAPI spec once the generator supports complex schemas
func (s *Server) SetupDecoratorRoutes() {
	// Add decorator-based endpoints with different paths to avoid conflicts
	// Both endpoints use the same DecoratorAgentRequest/Response format
	s.engine.POST("/agents/register_decorators", s.service.DecoratorRegistrationHandler)
	s.engine.POST("/heartbeat_decorators", s.service.DecoratorHeartbeatHandler)
}
