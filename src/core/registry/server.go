package registry

import (
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/database"
)

// Server represents the registry HTTP server
type Server struct {
	engine    *gin.Engine
	service   *Service
	startTime time.Time
}

// NewServer creates a new registry server
func NewServer(db *database.Database, config *RegistryConfig) *Server {
	// Create service
	service := NewService(db, config)

	// Create Gin engine
	engine := gin.New()
	engine.Use(gin.Recovery())
	engine.Use(gin.Logger())

	// Create server
	server := &Server{
		engine:    engine,
		service:   service,
		startTime: time.Now(),
	}

	// Setup routes
	server.SetupRoutes()

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
