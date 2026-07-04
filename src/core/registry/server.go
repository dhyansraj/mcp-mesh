package registry

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry/generated"
	"mcp-mesh/src/core/registry/tracing"
	"mcp-mesh/src/core/registry/trust"
)

// shutdownDrainTimeout caps how long ``Server.Stop`` waits for handler-
// spawned background goroutines (e.g. the cancel-forward in
// ``forwardCancelToOwner``) to finish after their parent context is
// cancelled. Set slightly above ``cancelForwardTimeout`` so a forward
// that's already mid-flight has time to return cleanly when its
// transport observes the cancellation, but capped tight enough that
// shutdown can't hang indefinitely on a wedged owner agent.
const shutdownDrainTimeout = 10 * time.Second

// Server represents the registry HTTP server
type Server struct {
	engine         *gin.Engine
	service        *EntService
	config         *RegistryConfig
	startTime      time.Time
	handlers       *EntBusinessLogicHandlers
	healthMonitor  *AgentHealthMonitor
	sweepJob       *SweepJob
	tracingManager *tracing.TracingManager
	trustChain     *trust.TrustChain
	logger         *logger.Logger

	// shutdownCtx + shutdownCancel + shutdownWG together gate handler-
	// spawned background goroutines (currently the cancel-forward in
	// ``ent_handlers_jobs.go::forwardCancelToOwner``) so a registry
	// ``Stop`` cleanly aborts in-flight forwards instead of letting
	// them run on after the process is supposedly stopped. Pattern
	// borrowed from ``SweepJob`` (sweep.go ~line 96) but adapted to a
	// fan-out-per-request goroutine model: instead of a single long-
	// running goroutine, every cancel forward registers itself on the
	// WaitGroup and uses ``shutdownCtx`` as the parent for its HTTP
	// request context.
	shutdownCtx    context.Context
	shutdownCancel context.CancelFunc
	shutdownWG     *sync.WaitGroup
}

// NewServer creates a new registry server using Ent database.
//
// Returns an error if a configured trust backend fails to initialize. This
// ensures the registry refuses to start in a state that would silently reject
// every agent heartbeat with "no backends configured" (issue #989), rather
// than booting healthy and only failing at the heartbeat path.
func NewServer(entDB *database.EntDatabase, config *RegistryConfig, logger *logger.Logger) (*Server, error) {
	// Create Ent-based service
	entService := NewEntService(entDB, config, logger)

	// Shutdown coordination for handler-spawned goroutines
	// (cancel-forward, etc). The context is cancelled by ``Server.Stop``
	// and the WaitGroup is drained alongside; both are passed into the
	// handler constructor so background goroutines can wire themselves
	// into the lifecycle without each handler re-implementing the
	// pattern.
	shutdownCtx, shutdownCancel := context.WithCancel(context.Background())
	shutdownWG := &sync.WaitGroup{}

	// Create Ent-based business logic handlers
	handlers := NewEntBusinessLogicHandlersWithShutdown(entService, shutdownCtx, shutdownWG)

	// Create health monitor using configuration values
	heartbeatTimeout := time.Duration(config.DefaultTimeoutThreshold) * time.Second
	checkInterval := time.Duration(config.HealthCheckInterval) * time.Second
	healthMonitor := NewAgentHealthMonitor(entService, logger, heartbeatTimeout, checkInterval)

	// Create sweep job (issue #835): purge stale agents and old registry events.
	sweepCfg := LoadSweepConfigFromEnv(logger)
	sweepJob := NewSweepJob(sweepCfg, entDB, entService, logger)

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

	// Initialize trust chain if TLS is not "off". A failure here is fatal:
	// see initTrustChain doc and issue #989 — silently dropping a backend
	// would leave the registry running but rejecting every heartbeat with
	// "no backends configured", which is exactly the bug we're closing.
	var trustChain *trust.TrustChain
	if config.TlsMode != "" && config.TlsMode != "off" {
		var err error
		trustChain, err = initTrustChain(config, logger)
		if err != nil {
			shutdownCancel()
			return nil, fmt.Errorf("trust chain init: %w", err)
		}
		logger.Info("🔒 TLS mode: %s | trust backend: %s", config.TlsMode, config.TrustBackend)
		if trustChain != nil {
			entities, _ := trustChain.ListTrustedEntities()
			logger.Info("🔒 Trust chain loaded: %d trusted entity CA(s)", len(entities))
			for _, e := range entities {
				logger.Debug("  Entity: %s | subject: %s | expires: %s | backend: %s",
					e.ID, e.Subject, e.NotAfter.Format("2006-01-02"), e.Metadata["source"])
			}
		}
	} else {
		logger.Info("🔓 TLS mode: off (no registration trust enforcement)")
	}

	// Create Gin engine
	engine := gin.New()
	engine.Use(gin.Recovery())
	engine.Use(gin.Logger())

	// Add TLS middleware before routes (only if trust chain is configured)
	if trustChain != nil {
		engine.Use(TLSVerifyMiddleware(trustChain, config.TlsMode))
	}

	// Create server
	server := &Server{
		engine:         engine,
		service:        entService,
		config:         config,
		startTime:      time.Now().UTC(),
		handlers:       handlers,
		healthMonitor:  healthMonitor,
		sweepJob:       sweepJob,
		tracingManager: tracingManager,
		trustChain:     trustChain,
		logger:         logger,
		shutdownCtx:    shutdownCtx,
		shutdownCancel: shutdownCancel,
		shutdownWG:     shutdownWG,
	}

	// Add operational endpoints first (includes wildcard proxy routes that must be registered before generated routes)
	server.setupOperationalEndpoints()

	// Setup routes using generated interface
	server.SetupGeneratedRoutes()

	return server, nil
}

// Run starts the HTTP server and health monitor
func (s *Server) Run(addr string) error {
	// Cleanup stale agents before serving requests (issue #443)
	// This handles agents left in healthy state from previous sessions
	ctx := context.Background()
	if cleaned, err := s.service.CleanupStaleAgentsOnStartup(ctx); err != nil {
		fmt.Printf("⚠️ Startup cleanup warning: %v\n", err)
	} else if cleaned > 0 {
		fmt.Printf("🧹 Startup cleanup: marked %d stale agents as unhealthy\n", cleaned)
	}

	// Start health monitor
	s.healthMonitor.Start()

	// Start sweep job (issue #835)
	if s.sweepJob != nil {
		s.sweepJob.Start(context.Background())
	}

	// Start distributed tracing if enabled
	if s.tracingManager != nil {
		if err := s.tracingManager.Start(); err != nil {
			// Log warning but don't fail startup
			fmt.Printf("⚠️ Failed to start distributed tracing: %v\n", err)
		}
	}

	// Start admin server if configured
	if s.config.AdminPort > 0 {
		s.startAdminServer(s.config.AdminPort)
	}

	// Use TLS listener when TLS mode is enabled
	if s.config.TlsMode != "" && s.config.TlsMode != "off" {
		if s.config.TlsCertFile == "" || s.config.TlsKeyFile == "" {
			return fmt.Errorf("TLS mode %q requires MCP_MESH_TLS_CERT and MCP_MESH_TLS_KEY to be set; use MCP_MESH_TLS_MODE=off to run plaintext", s.config.TlsMode)
		}
		return s.runWithTLS(addr)
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

	// Stop sweep job
	if s.sweepJob != nil {
		s.sweepJob.Stop()
	}

	// Cancel handler-spawned background goroutines (cancel-forward,
	// etc.) and wait for them to drain. The cancel propagates into each
	// goroutine's HTTP request context so ``http.Client.Do`` returns
	// promptly with a context-cancelled error, and the goroutine exits
	// after logging via the "abandoned: registry shutting down" branch.
	// We bound the wait so a wedged owner-side TCP stack can't hang
	// shutdown — anything still running past the cap is logged as
	// abandoned so an operator sees evidence in the registry log.
	if s.shutdownCancel != nil {
		s.shutdownCancel()
	}
	if s.shutdownWG != nil {
		drainDone := make(chan struct{})
		go func() {
			s.shutdownWG.Wait()
			close(drainDone)
		}()
		select {
		case <-drainDone:
			// All registered goroutines exited cleanly.
		case <-time.After(shutdownDrainTimeout):
			if s.logger != nil {
				s.logger.Warning("Registry shutdown: handler-spawned goroutines did not drain within %s; abandoning", shutdownDrainTimeout)
			} else {
				log.Printf("[registry] shutdown: handler-spawned goroutines did not drain within %s; abandoning", shutdownDrainTimeout)
			}
		}
	}

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

	// Trace detail endpoint (used by meshctl trace)
	s.engine.GET("/trace/:trace_id", s.handleTraceGet)

	// Admin endpoints on main engine only when no separate admin port is configured
	if s.config.AdminPort <= 0 {
		s.engine.GET("/admin/entities", s.handleListEntities)
		s.engine.POST("/admin/rotate", s.handleRotateTrigger)
		s.engine.POST("/admin/drain", s.handleDrainStart)
		s.engine.DELETE("/admin/drain", s.handleDrainStop)
		s.engine.GET("/admin/drain", s.handleDrainStatus)
	}
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
			"enabled":         true,
			"stats_available": false,
			"reason":          "statistics collection not enabled",
		})
		return
	}

	c.JSON(200, stats)
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

// runWithTLS starts the server with TLS configured to request (but not require)
// client certificates. Enforcement is handled by TLSVerifyMiddleware based on TlsMode.
func (s *Server) runWithTLS(addr string) error {
	s.logger.Info("🔒 Starting TLS listener (ClientAuth: RequestClientCert)")

	tlsConfig := &tls.Config{
		ClientAuth: tls.RequestClientCert,
	}

	cert, err := tls.LoadX509KeyPair(s.config.TlsCertFile, s.config.TlsKeyFile)
	if err != nil {
		return fmt.Errorf("loading TLS certificate: %w", err)
	}
	tlsConfig.Certificates = []tls.Certificate{cert}

	server := &http.Server{
		Addr:      addr,
		Handler:   s.engine,
		TLSConfig: tlsConfig,
	}

	return server.ListenAndServeTLS("", "")
}

// initTrustChain parses the TrustBackend config and builds a TrustChain
// from the configured backends.
//
// Error policy (issue #989):
//   - "User configured a backend but a prerequisite is missing" (e.g. filestore
//     listed but MCP_MESH_TRUST_DIR unset) is a non-fatal warn-and-skip: the
//     operator clearly didn't intend to enable that backend.
//   - "User configured a backend AND the prerequisite is set, but init failed"
//     (e.g. fsnotify denied, k8s API unreachable, SPIRE socket missing) is a
//     fatal startup error. Returning a chain without the requested backend
//     would silently produce a 0-backend chain that rejects every cert with
//     "no backends configured" — exactly the original #989 symptom we're
//     fixing. Better to refuse to start so the operator sees the real cause.
//   - An unknown backend name is fatal: that's a typo in operator config and
//     limping along masks the bug.
func initTrustChain(config *RegistryConfig, l *logger.Logger) (*trust.TrustChain, error) {
	names := trust.ParseBackendConfig(config.TrustBackend)
	chain := trust.NewTrustChain()

	for _, name := range names {
		switch name {
		case "filestore":
			if config.TrustDir == "" {
				l.Warning("filestore backend requires MCP_MESH_TRUST_DIR")
				continue
			}
			fs, err := trust.NewFileStore(config.TrustDir, true)
			if err != nil {
				return nil, fmt.Errorf("initializing filestore backend (MCP_MESH_TRUST_DIR=%s): %w", config.TrustDir, err)
			}
			chain.Add(fs)
			l.Info("🔒 Trust backend '%s' initialized", name)
			l.Debug("  Trust dir: %s", config.TrustDir)
		case "localca":
			if config.TrustDir == "" {
				l.Warning("localca backend requires MCP_MESH_TRUST_DIR")
				continue
			}
			lca, err := trust.NewLocalCA(config.TrustDir)
			if err != nil {
				return nil, fmt.Errorf("initializing localca backend (MCP_MESH_TRUST_DIR=%s): %w", config.TrustDir, err)
			}
			chain.Add(lca)
			l.Info("🔒 Trust backend '%s' initialized", name)
			l.Debug("  Trust dir: %s", config.TrustDir)
		case "k8s-secrets":
			namespace := os.Getenv("MCP_MESH_K8S_NAMESPACE")
			if namespace == "" {
				namespace = "default"
			}
			labelSelector := os.Getenv("MCP_MESH_K8S_LABEL_SELECTOR")
			ks, err := trust.NewK8sSecretsFromConfig(namespace, labelSelector)
			if err != nil {
				return nil, fmt.Errorf("initializing k8s-secrets backend (namespace=%s, selector=%q): %w", namespace, labelSelector, err)
			}
			chain.Add(ks)
			l.Info("🔒 Trust backend '%s' initialized", name)
			l.Debug("  Namespace: %s, LabelSelector: %s", namespace, labelSelector)
		case "spire":
			socketPath := os.Getenv("MCP_MESH_SPIRE_SOCKET")
			if socketPath == "" {
				socketPath = "/run/spire/agent/sockets/agent.sock"
			}
			sb, err := trust.NewSPIRE(context.Background(), socketPath)
			if err != nil {
				return nil, fmt.Errorf("initializing spire backend (socket=%s): %w", socketPath, err)
			}
			chain.Add(sb)
			l.Info("🔒 Trust backend '%s' initialized (socket: %s)", name, socketPath)
		default:
			return nil, fmt.Errorf("unknown trust backend %q (configured via MCP_MESH_TRUST_BACKEND)", name)
		}
	}

	return chain, nil
}

// startAdminServer starts a secondary Gin engine on the admin port with
// admin-only endpoints. Runs in its own goroutine.
func (s *Server) startAdminServer(port int) {
	adminEngine := gin.New()
	adminEngine.Use(gin.Recovery())

	adminEngine.GET("/admin/entities", s.handleListEntities)
	adminEngine.POST("/admin/rotate", s.handleRotateTrigger)
	adminEngine.POST("/admin/drain", s.handleDrainStart)
	adminEngine.DELETE("/admin/drain", s.handleDrainStop)
	adminEngine.GET("/admin/drain", s.handleDrainStatus)

	go func() {
		addr := fmt.Sprintf(":%d", port)
		log.Printf("[admin] Admin API listening on %s", addr)
		if err := adminEngine.Run(addr); err != nil {
			log.Printf("[admin] Admin server error: %v", err)
		}
	}()
}

func (s *Server) handleListEntities(c *gin.Context) {
	type entityEntry struct {
		Name    string `json:"name"`
		Subject string `json:"subject"`
		Expires string `json:"expires"`
	}

	entities := make([]entityEntry, 0)

	// If trust chain is configured, use it (covers all backends: filestore, localca, k8s-secrets, spire)
	if s.trustChain != nil {
		trusted, err := s.trustChain.ListTrustedEntities()
		if err != nil {
			s.logger.Warning("Failed to list trusted entities: %v", err)
		}
		for _, e := range trusted {
			entities = append(entities, entityEntry{
				Name:    e.ID,
				Subject: e.Subject,
				Expires: e.NotAfter.Format("2006-01-02"),
			})
		}
		c.JSON(200, gin.H{"entities": entities})
		return
	}

	// Fallback: read entity CA files directly from the trust directory
	trustDir := s.config.TrustDir
	if trustDir == "" {
		trustDir = os.Getenv("MCP_MESH_TRUST_DIR")
	}
	if trustDir == "" {
		home, _ := os.UserHomeDir()
		if home != "" {
			trustDir = home + "/.mcp-mesh/tls"
		}
	}

	if trustDir != "" {
		entitiesDir := trustDir + "/entities"
		entries, err := os.ReadDir(entitiesDir)
		if err == nil {
			for _, entry := range entries {
				if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".pem") {
					continue
				}
				pemPath := entitiesDir + "/" + entry.Name()
				data, err := os.ReadFile(pemPath)
				if err != nil {
					continue
				}
				block, _ := pem.Decode(data)
				if block == nil || block.Type != "CERTIFICATE" {
					continue
				}
				cert, err := x509.ParseCertificate(block.Bytes)
				if err != nil {
					continue
				}
				name := strings.TrimSuffix(entry.Name(), ".pem")
				subject := cert.Subject.String()
				if cert.Subject.CommonName != "" {
					parts := []string{"CN=" + cert.Subject.CommonName}
					for _, o := range cert.Subject.Organization {
						parts = append(parts, "O="+o)
					}
					subject = strings.Join(parts, ",")
				}
				entities = append(entities, entityEntry{
					Name:    name,
					Subject: subject,
					Expires: cert.NotAfter.Format("2006-01-02"),
				})
			}
		}
	}

	c.JSON(200, gin.H{"entities": entities})
}

func (s *Server) handleRotateTrigger(c *gin.Context) {
	entityID := c.Query("entity_id")

	count, err := s.service.TriggerRotation(c.Request.Context(), entityID)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": err.Error(),
		})
		return
	}

	target := "all agents"
	if entityID != "" {
		target = fmt.Sprintf("entity '%s'", entityID)
	}

	c.JSON(http.StatusOK, gin.H{
		"message":         fmt.Sprintf("Rotation triggered for %s", target),
		"affected_agents": count,
		"entity_id":       entityID,
	})
}

// drainStatusResponse writes the current drain state plus the live-claim
// count. live_claims = non-terminal jobs with a non-null owner (the signal an
// operator watches drop to zero before restarting). Shared by all three
// /admin/drain verbs so they always report a consistent view.
func (s *Server) drainStatusResponse(c *gin.Context) {
	live, err := s.service.CountLiveClaims(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": fmt.Sprintf("failed to count live claims: %v", err),
		})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"draining":    s.service.IsDraining(),
		"live_claims": live,
	})
}

// handleDrainStart implements POST /admin/drain (issue #1267). Enters drain
// mode: ClaimNextJob dispatches no new work while running jobs finish
// normally. In-memory only — a registry restart clears drain.
//
// The live-claim count is taken BEFORE engaging the flag so a backend error
// returns 503 without silently leaving the registry drained (the operator sees
// a clean failure and can retry, rather than a registry that has quietly
// stopped dispatching behind a 503).
func (s *Server) handleDrainStart(c *gin.Context) {
	live, err := s.service.CountLiveClaims(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": fmt.Sprintf("failed to count live claims: %v", err),
		})
		return
	}
	s.service.SetDraining(true)
	s.logger.Info("🛠️ Registry drain mode ENABLED — new job claims are paused")
	c.JSON(http.StatusOK, gin.H{
		"draining":    true,
		"live_claims": live,
	})
}

// handleDrainStop implements DELETE /admin/drain (issue #1267). Resumes
// normal dispatch; queued jobs become claimable again in FIFO order.
func (s *Server) handleDrainStop(c *gin.Context) {
	s.service.SetDraining(false)
	s.logger.Info("🛠️ Registry drain mode DISABLED — job claims resumed")
	s.drainStatusResponse(c)
}

// handleDrainStatus implements GET /admin/drain (issue #1267). Reports
// {draining, live_claims} without changing state.
func (s *Server) handleDrainStatus(c *gin.Context) {
	s.drainStatusResponse(c)
}
