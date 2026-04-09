package ui

import (
	"embed"
	"io/fs"
	"log"
	"net/http"
	"strings"
	"time"

	"mcp-mesh/src/core/registry"
	"mcp-mesh/src/core/registry/tracing"
	"mcp-mesh/src/core/tlsutil"

	"github.com/gin-gonic/gin"
)

// Server is the MCP Mesh UI HTTP server. It serves the embedded Vite
// dashboard SPA and proxies /api/* requests to the registry.
type Server struct {
	engine         *gin.Engine
	config         *UIConfig
	httpClient     *http.Client
	startTime      time.Time
	entService     *registry.EntService
	eventHub       *EventHub
	eventPoller    *EventPoller
	tracingManager      *tracing.TracingManager
	metricsProcessor    *MetricsProcessor
	tracePoller         *TracePoller
	configuredIndexHTML []byte
	version             string
}

// NewServer creates a new UI server that serves the embedded SPA and proxies
// API requests to the registry at config.RegistryURL. If tracingManager is
// non-nil, trace endpoints are handled locally instead of being proxied.
func NewServer(config *UIConfig, entService *registry.EntService, tracingManager *tracing.TracingManager, metricsProcessor *MetricsProcessor, embeddedFS embed.FS, logLevel string, version string) *Server {
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
			Timeout:   10 * time.Second,
			Transport: tlsutil.NewHTTPTransport(config.RegistryTLS),
		},
		startTime:        time.Now().UTC(),
		version:          version,
		entService:       entService,
		eventHub:         eventHub,
		eventPoller:      eventPoller,
		tracingManager:   tracingManager,
		metricsProcessor: metricsProcessor,
	}

	// If tracing is enabled, create a trace poller for dashboard events
	if tracingManager != nil {
		s.tracePoller = NewTracePoller(tracingManager, metricsProcessor, eventHub, 3*time.Second)
	}

	// --- API routes (proxied to registry) ---
	api := engine.Group("/api")
	{
		api.GET("/health", s.proxyToRegistry)
		api.GET("/agents", s.proxyToRegistry)
		api.GET("/agents/*path", s.proxyToRegistry)
		api.GET("/events/history", s.GetEventsHistory)
		api.GET("/events", s.StreamDashboardEvents)
		api.GET("/trace/recent", s.handleRecentTraces)
		api.GET("/trace/edge-stats", s.handleEdgeStats)
		api.GET("/trace/agent-stats", s.handleAgentStats)
		api.GET("/trace/model-stats", s.handleModelStats)
		api.GET("/trace/list", s.handleTraceList)
		api.GET("/trace/search", s.handleTraceSearch)
		api.GET("/trace/:trace_id", s.handleTraceGet)
		api.GET("/traces/live", s.handleStreamLiveTraces)
	}

	// Local health endpoint for the UI server itself
	engine.GET("/api/ui-health", s.handleUIHealth)

	// --- SPA static file serving ---
	subFS, err := fs.Sub(embeddedFS, "dist")
	if err != nil {
		log.Fatalf("ui: failed to open embedded dist/ directory: %v", err)
	}

	// Read index.html and inject runtime base path so users can customize
	// the serving path at deploy-time without rebuilding.
	// Note: __MESH_REGISTRY_URL__ is NOT injected here — the browser uses
	// same-origin /api requests, and the Go server proxies them to the registry.
	rawIndex, err := fs.ReadFile(subFS, "index.html")
	if err != nil {
		log.Fatalf("ui: failed to read embedded index.html: %v", err)
	}
	configuredIndex := string(rawIndex)
	// Inject <base> tag so relative asset paths (./assets/...) resolve correctly
	// even when the browser URL is a deep SPA route like /traffic or /topology.
	baseHref := "/"
	if config.BasePath != "" {
		baseHref = config.BasePath + "/"
		configuredIndex = strings.Replace(configuredIndex,
			`window.__MESH_BASE_PATH__ = window.__MESH_BASE_PATH__ || ""`,
			`window.__MESH_BASE_PATH__ = "`+config.BasePath+`"`,
			1)
	}
	configuredIndex = strings.Replace(configuredIndex,
		`<meta charset="UTF-8" />`,
		`<meta charset="UTF-8" /><base href="`+baseHref+`" />`,
		1)
	s.configuredIndexHTML = []byte(configuredIndex)

	fileServer := http.FileServer(http.FS(subFS))

	engine.NoRoute(func(c *gin.Context) {
		path := c.Request.URL.Path

		// Don't serve SPA for unmatched /api/* paths
		if path == "/api" || strings.HasPrefix(path, "/api/") {
			c.JSON(http.StatusNotFound, gin.H{"error": "API endpoint not found"})
			return
		}

		// Try to serve the file directly (JS, CSS, assets)
		filePath := strings.TrimPrefix(path, "/")
		if filePath == "" {
			c.Data(http.StatusOK, "text/html; charset=utf-8", s.configuredIndexHTML)
			return
		}

		f, err := subFS.Open(filePath)
		if err == nil {
			stat, statErr := f.Stat()
			f.Close()
			if statErr == nil && !stat.IsDir() {
				fileServer.ServeHTTP(c.Writer, c.Request)
				return
			}
		}

		// SPA fallback: serve configured index.html for client-side routing
		c.Data(http.StatusOK, "text/html; charset=utf-8", s.configuredIndexHTML)
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
		"version":      s.version,
	})
}

// Run starts the Gin HTTP server on the given address (e.g. ":3080").
func (s *Server) Run(addr string) error {
	s.eventPoller.Start()
	if s.tracingManager != nil {
		if err := s.tracingManager.Start(); err != nil {
			log.Printf("[ui] Warning: failed to start tracing manager: %v", err)
		}
	}
	if s.tracePoller != nil {
		s.tracePoller.Start()
	}

	var handler http.Handler = s.engine
	if s.config.BasePath != "" {
		handler = http.StripPrefix(s.config.BasePath, s.engine)
	}

	err := http.ListenAndServe(addr, handler)

	// ListenAndServe returned — clean up background components
	if s.tracePoller != nil {
		s.tracePoller.Stop()
	}
	if s.tracingManager != nil {
		s.tracingManager.Stop()
	}
	s.eventPoller.Stop()
	return err
}

// Stop performs a graceful shutdown of the UI server.
func (s *Server) Stop() error {
	if s.tracePoller != nil {
		s.tracePoller.Stop()
	}
	if s.tracingManager != nil {
		if err := s.tracingManager.Stop(); err != nil {
			log.Printf("[ui] Warning: failed to stop tracing manager: %v", err)
		}
	}
	if s.eventPoller != nil {
		s.eventPoller.Stop()
	}
	// Close the HTTP client transport to release idle connections
	if transport, ok := s.httpClient.Transport.(*http.Transport); ok {
		transport.CloseIdleConnections()
	}
	return nil
}
