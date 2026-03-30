package ui

import (
	"embed"
	"io/fs"
	"log"
	"net/http"
	"strings"
	"time"

	"mcp-mesh/src/core/registry"

	"github.com/gin-gonic/gin"
)

// Server is the MCP Mesh UI HTTP server. It serves the embedded Next.js
// dashboard SPA and proxies /api/* requests to the registry.
type Server struct {
	engine      *gin.Engine
	config      *UIConfig
	httpClient  *http.Client
	startTime   time.Time
	entService  *registry.EntService
	eventHub    *EventHub
	eventPoller *EventPoller
}

// NewServer creates a new UI server that serves the embedded SPA and proxies
// API requests to the registry at config.RegistryURL.
func NewServer(config *UIConfig, entService *registry.EntService, embeddedFS embed.FS, logLevel string) *Server {
	// Set Gin mode based on log level
	upperLevel := strings.ToUpper(logLevel)
	if upperLevel == "DEBUG" || upperLevel == "TRACE" {
		gin.SetMode(gin.DebugMode)
	} else {
		gin.SetMode(gin.ReleaseMode)
	}

	engine := gin.New()
	engine.Use(gin.Recovery())
	engine.Use(gin.Logger())

	eventHub := NewEventHub()
	eventPoller := NewEventPoller(entService, eventHub, 3*time.Second)

	s := &Server{
		engine: engine,
		config: config,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		startTime:   time.Now().UTC(),
		entService:  entService,
		eventHub:    eventHub,
		eventPoller: eventPoller,
	}

	// --- API routes (proxied to registry) ---
	api := engine.Group("/api")
	{
		api.GET("/health", s.proxyToRegistry)
		api.GET("/agents", s.proxyToRegistry)
		api.GET("/agents/*path", s.proxyToRegistry)
		api.GET("/events/history", s.GetEventsHistory)
		api.GET("/events", s.StreamDashboardEvents)
		api.GET("/trace/recent", s.proxyToRegistry)
		api.GET("/trace/edge-stats", s.proxyToRegistry)
		api.GET("/trace/:trace_id", s.proxyToRegistry)
	}

	// Local health endpoint for the UI server itself
	engine.GET("/api/ui-health", s.handleUIHealth)

	// --- SPA static file serving ---
	subFS, err := fs.Sub(embeddedFS, "out")
	if err != nil {
		log.Fatalf("ui: failed to open embedded out/ directory: %v", err)
	}

	fileServer := http.FileServer(http.FS(subFS))

	engine.NoRoute(func(c *gin.Context) {
		path := c.Request.URL.Path

		// Don't serve SPA for unmatched /api/* paths
		if strings.HasPrefix(path, "/api/") {
			c.JSON(http.StatusNotFound, gin.H{"error": "API endpoint not found"})
			return
		}

		// Resolve the file path from the URL
		filePath := strings.TrimPrefix(path, "/")
		if filePath == "" {
			filePath = "index.html"
		}

		// Try to serve the file directly
		f, err := subFS.Open(filePath)
		if err == nil {
			stat, statErr := f.Stat()
			f.Close()
			if statErr == nil {
				if !stat.IsDir() {
					// Regular file — serve it (handles _next/static/*, favicon, etc.)
					fileServer.ServeHTTP(c.Writer, c.Request)
					return
				}
				// Directory — check for index.html inside it (Next.js trailingSlash pages)
				indexPath := strings.TrimRight(filePath, "/") + "/index.html"
				if data, readErr := fs.ReadFile(subFS, indexPath); readErr == nil {
					c.Data(http.StatusOK, "text/html; charset=utf-8", data)
					return
				}
			}
		}

		// SPA fallback: serve root index.html for unresolved paths
		data, readErr := fs.ReadFile(subFS, "index.html")
		if readErr != nil {
			c.String(http.StatusInternalServerError, "index.html not found in embedded assets")
			return
		}
		c.Data(http.StatusOK, "text/html; charset=utf-8", data)
	})

	return s
}

// handleUIHealth returns a local health status for the UI server itself.
func (s *Server) handleUIHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":       "healthy",
		"service":      "mcp-mesh-ui",
		"uptime_secs":  int(time.Since(s.startTime).Seconds()),
		"registry_url": s.config.RegistryURL,
	})
}

// Run starts the Gin HTTP server on the given address (e.g. ":3080").
func (s *Server) Run(addr string) error {
	s.eventPoller.Start()
	return s.engine.Run(addr)
}

// Stop performs a graceful shutdown of the UI server.
func (s *Server) Stop() error {
	if s.eventPoller != nil {
		s.eventPoller.Stop()
	}
	// Close the HTTP client transport to release idle connections
	if transport, ok := s.httpClient.Transport.(*http.Transport); ok {
		transport.CloseIdleConnections()
	}
	return nil
}
