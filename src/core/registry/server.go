package registry

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"errors"
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

// shutdownHTTPTimeout caps how long ``Server.Stop`` waits for in-flight
// HTTP requests to finish before their listeners are closed out from
// under them.
//
// It is deliberately short. The value cannot be sized to "let everything
// finish": a job-event long-poll runs up to 60s
// (``listJobEventsMaxWait``) and a proxied SSE stream is unbounded, so
// any registry with an idle jobs consumer attached would sit out the
// whole window on every stop. What the window IS sized for is ordinary
// control-plane traffic — heartbeats, registrations, job deltas — which
// completes in milliseconds, so 5s is several orders of magnitude of
// headroom for the requests that can actually be waited out.
//
// On the ceilings: Kubernetes' default terminationGracePeriodSeconds is
// 30s, and Stop's two bounded phases (5s here, then
// ``shutdownDrainTimeout``'s 10s) fit inside it with room for the
// tracing flush. They do NOT both fit inside ``meshctl stop``'s default
// 10s SIGKILL escalation (stop.go --timeout) — 5+10 is 15s. That is
// accepted rather than papered over: both phases only reach their caps
// when something is genuinely stuck (a long-poll parked on the socket, a
// cancel-forward wedged on an unresponsive owner), and in that case a
// dev-loop SIGKILL is the right outcome. The common path returns in
// milliseconds.
const shutdownHTTPTimeout = 5 * time.Second

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

	// httpServers holds every listener ``Run`` started (main + admin) so
	// ``Shutdown`` can drain all of them; ``httpStopping`` closes the
	// race where a signal lands between ``NewServer`` and the moment a
	// listener is registered, which would otherwise leave a listener
	// serving after ``Stop`` returned. maxBodyBytes is resolved once at
	// construction so the main and admin engines share one limit.
	httpMu       sync.Mutex
	httpServers  []*http.Server
	httpStopping bool
	maxBodyBytes int64
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

	// Cap request bodies (issue #1583). Installed after the trust check so
	// an untrusted client in strict mode still sees 403 rather than 413.
	maxBodyBytes := maxRequestBodyBytesFromEnv()
	engine.Use(MaxRequestBodyMiddleware(maxBodyBytes))

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
		maxBodyBytes:   maxBodyBytes,
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

	// Validate the TLS configuration before any listener binds: the admin
	// listener mirrors the main one's TLS settings, so a missing cert has
	// to fail here rather than after a plaintext admin port is already
	// accepting connections.
	tlsRequested := s.config.TlsMode != "" && s.config.TlsMode != "off"
	if tlsRequested && (s.config.TlsCertFile == "" || s.config.TlsKeyFile == "") {
		return fmt.Errorf("TLS mode %q requires MCP_MESH_TLS_CERT and MCP_MESH_TLS_KEY to be set; use MCP_MESH_TLS_MODE=off to run plaintext", s.config.TlsMode)
	}

	// Start admin server if configured
	if s.config.AdminPort > 0 {
		s.startAdminServer(s.config.AdminPort)
	}

	// Use TLS listener when TLS mode is enabled
	if tlsRequested {
		return s.runWithTLS(addr)
	}
	return s.runPlaintext(addr)
}

// Start starts the HTTP server (alias for compatibility)
func (s *Server) Start() error {
	return s.runPlaintext(":8080") // Default port
}

// runPlaintext serves the main engine over plain HTTP.
//
// This used to be ``s.engine.Run(addr)``, which builds an ``http.Server``
// internally with every timeout left at its zero value and no handle on
// it to shut down. Constructing the server here is what lets the
// plaintext path carry the same limits as the TLS path and be drained by
// ``Shutdown`` (issue #1583).
func (s *Server) runPlaintext(addr string) error {
	server := newHardenedServer(addr, s.engine.Handler())
	if !s.registerServer(server) {
		return nil // Stop() already ran; don't start listening.
	}
	return ignoreServerClosed(server.ListenAndServe())
}

// registerServer records a listener for ``Shutdown`` to drain. Returns
// false when the server is already stopping, in which case the caller
// must not start listening — otherwise a signal arriving between
// ``NewServer`` and this call would leave a listener up that ``Stop``
// has already walked past.
func (s *Server) registerServer(srv *http.Server) bool {
	s.httpMu.Lock()
	defer s.httpMu.Unlock()
	if s.httpStopping {
		return false
	}
	s.httpServers = append(s.httpServers, srv)
	return true
}

// ignoreServerClosed maps the sentinel returned by a listener that was
// deliberately shut down onto a nil error, so ``Run`` returning after a
// graceful ``Stop`` is not reported by main() as a startup failure.
func ignoreServerClosed(err error) error {
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

// Stop stops the HTTP server and health monitor
func (s *Server) Stop() error {
	// Stop health monitor
	s.healthMonitor.Stop()

	// Stop sweep job
	if s.sweepJob != nil {
		s.sweepJob.Stop()
	}

	// Stop accepting new connections and let in-flight requests finish
	// before the handler-spawned goroutines below are cancelled: a
	// request that is mid-flight when the process is asked to stop
	// should complete, and cancelling its background forwards first
	// would abort work that is still legitimately running (issue #1583).
	httpCtx, cancelHTTP := context.WithTimeout(context.Background(), shutdownHTTPTimeout)
	defer cancelHTTP()
	httpShutdownErr := s.Shutdown(httpCtx)

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

	return httpShutdownErr
}

// Shutdown gracefully stops every HTTP listener the registry started
// (main + admin), waiting for in-flight requests to finish until ctx is
// done. Callers that want a bound should pass a context with a deadline;
// ``Stop`` uses shutdownHTTPTimeout.
//
// An SSE response being relayed through ``/proxy/*`` and a job-event
// long-poll both count as in-flight requests, so hitting the deadline
// with one of them parked is the EXPECTED outcome, not a failure. Note
// what ``http.Server.Shutdown`` does at the deadline: it has already
// closed the listeners and idle connections, but it does not terminate
// the still-active ones — it just returns ``ctx.Err()`` and leaves them
// running until the process exits. Shutdown therefore logs that case at
// info and does not report it as an error; only a genuine listener
// failure is returned.
func (s *Server) Shutdown(ctx context.Context) error {
	s.httpMu.Lock()
	s.httpStopping = true
	servers := s.httpServers
	s.httpServers = nil
	s.httpMu.Unlock()

	var firstErr error
	for _, srv := range servers {
		err := srv.Shutdown(ctx)
		if err == nil {
			continue
		}
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			// Routine: something long-lived was still attached. Say so
			// plainly instead of surfacing it to the operator as a
			// shutdown error on every restart of a registry that has a
			// jobs consumer long-polling it.
			s.logShutdown("Registry shutdown: listener %s still had long-lived requests attached after the grace period (long-polls / SSE streams); exiting anyway", srv.Addr)
			continue
		}
		if firstErr == nil {
			firstErr = err
		}
		s.logShutdown("Registry shutdown: listener %s failed to shut down: %v", srv.Addr, err)
	}
	return firstErr
}

// logShutdown routes a shutdown message to the structured logger when the
// server has one and to the stdlib logger otherwise — Shutdown runs on
// Servers built directly in tests, which have no logger.
func (s *Server) logShutdown(format string, args ...interface{}) {
	if s.logger != nil {
		s.logger.Info(format, args...)
		return
	}
	log.Printf("[registry] "+format, args...)
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

// tlsEnabled reports whether the registry was configured to serve TLS.
func (s *Server) tlsEnabled() bool {
	return s.config.TlsMode != "" && s.config.TlsMode != "off" &&
		s.config.TlsCertFile != "" && s.config.TlsKeyFile != ""
}

// serverTLSConfig builds the TLS configuration shared by every listener
// the registry starts.
//
// ClientAuth stays RequestClientCert on purpose: enforcement happens at
// the application layer in TLSVerifyMiddleware, which needs certless
// handshakes to succeed so "auto" mode can admit them and "strict" mode
// can answer 403 rather than dropping the connection mid-handshake.
func (s *Server) serverTLSConfig() (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(s.config.TlsCertFile, s.config.TlsKeyFile)
	if err != nil {
		return nil, fmt.Errorf("loading TLS certificate: %w", err)
	}
	return &tls.Config{
		ClientAuth:   tls.RequestClientCert,
		Certificates: []tls.Certificate{cert},
	}, nil
}

// runWithTLS starts the server with TLS configured to request (but not require)
// client certificates. Enforcement is handled by TLSVerifyMiddleware based on TlsMode.
func (s *Server) runWithTLS(addr string) error {
	s.logger.Info("🔒 Starting TLS listener (ClientAuth: RequestClientCert)")

	tlsConfig, err := s.serverTLSConfig()
	if err != nil {
		return err
	}

	server := newHardenedServer(addr, s.engine.Handler())
	server.TLSConfig = tlsConfig

	if !s.registerServer(server) {
		return nil // Stop() already ran; don't start listening.
	}
	return ignoreServerClosed(server.ListenAndServeTLS("", ""))
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

// newAdminEngine builds the engine served on the admin port.
//
// Middleware here is deliberately kept in one place: the admin engine is
// a second, separately-constructed engine, so anything installed on the
// main engine in NewServer has to be repeated or it silently does not
// apply to /admin/* when MCP_MESH_ADMIN_PORT is set.
func (s *Server) newAdminEngine() *gin.Engine {
	adminEngine := gin.New()
	adminEngine.Use(gin.Recovery())

	// Request logging, same as the main engine. Without it the privileged
	// port produced no access log at all — including for rejected calls.
	adminEngine.Use(gin.Logger())

	// Client-certificate policy, OPT-IN via MCP_MESH_ADMIN_TLS (issue
	// #1583). The main engine always installs this when a trust chain
	// exists; the admin engine cannot, because there is no client in the
	// project that can present a certificate — meshctl's only TLS knob is
	// --insecure — so installing it unconditionally would make
	// ``meshctl registry drain`` (the documented pre-upgrade step) return
	// 403 in strict mode with no workaround. Off by default therefore
	// means: the admin port behaves exactly as it always has.
	if s.adminTLSEnabled() && s.trustChain != nil {
		adminEngine.Use(TLSVerifyMiddleware(s.trustChain, s.config.TlsMode))
	}

	// Body cap after the trust check, matching the main engine's order so
	// an untrusted strict-mode caller sees 403 rather than 413. Applied
	// unconditionally: a size limit breaks no client.
	adminEngine.Use(MaxRequestBodyMiddleware(s.maxBodyBytes))

	adminEngine.GET("/admin/entities", s.handleListEntities)
	adminEngine.POST("/admin/rotate", s.handleRotateTrigger)
	adminEngine.POST("/admin/drain", s.handleDrainStart)
	adminEngine.DELETE("/admin/drain", s.handleDrainStop)
	adminEngine.GET("/admin/drain", s.handleDrainStatus)

	return adminEngine
}

// adminTLSEnabled reports whether the operator opted the admin listener
// into the main listener's transport and trust policy
// (MCP_MESH_ADMIN_TLS). It is a single switch on purpose: serving TLS on
// the admin port without the client-certificate check, or the check
// without TLS, are both half-configurations no operator asked for.
//
// Warns rather than silently doing nothing when the opt-in is set but
// the registry has no TLS to inherit.
func (s *Server) adminTLSEnabled() bool {
	if !s.config.AdminTLS {
		return false
	}
	if !s.tlsEnabled() {
		return false
	}
	return true
}

// startAdminServer starts a secondary Gin engine on the admin port with
// admin-only endpoints. Runs in its own goroutine.
//
// The listener always carries the connection limits and body cap of the
// main one (newHardenedServer, MaxRequestBodyMiddleware) — those break no
// client. Transport and trust are opt-in through MCP_MESH_ADMIN_TLS: with
// it unset the admin port is plaintext and unauthenticated, exactly as it
// has always been, and must be restricted at the network layer. With it
// set the port inherits the registry's certificate and tls.Config, which
// also changes its scheme to https for every existing admin client
// (issue #1583).
func (s *Server) startAdminServer(port int) {
	adminEngine := s.newAdminEngine()

	addr := fmt.Sprintf(":%d", port)
	server := newHardenedServer(addr, adminEngine.Handler())

	if s.config.AdminTLS && !s.tlsEnabled() {
		log.Printf("[admin] MCP_MESH_ADMIN_TLS is set but the registry has no TLS configured (MCP_MESH_TLS_MODE/MCP_MESH_TLS_CERT/MCP_MESH_TLS_KEY); admin port stays plaintext")
	}

	serveTLS := false
	if s.adminTLSEnabled() {
		tlsConfig, err := s.serverTLSConfig()
		if err != nil {
			log.Printf("[admin] Admin server not started: %v", err)
			return
		}
		server.TLSConfig = tlsConfig
		serveTLS = true
	}

	if !s.registerServer(server) {
		return // Stop() already ran; don't start listening.
	}

	go func() {
		scheme := "http"
		if serveTLS {
			scheme = "https"
		}
		if serveTLS {
			log.Printf("[admin] Admin API listening on %s (%s, client certs: %s)", addr, scheme, s.config.TlsMode)
		} else {
			log.Printf("[admin] Admin API listening on %s (%s, unauthenticated — restrict this port at the network layer)", addr, scheme)
		}

		var err error
		if serveTLS {
			err = server.ListenAndServeTLS("", "")
		} else {
			err = server.ListenAndServe()
		}
		if err := ignoreServerClosed(err); err != nil {
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
