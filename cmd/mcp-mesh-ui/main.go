package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	flag "github.com/spf13/pflag"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry"
	"mcp-mesh/src/core/registry/tracing"
	"mcp-mesh/src/core/tlsutil"
	"mcp-mesh/src/core/ui"
)

// version is injected at build time via ldflags
var version = "dev"

func main() {
	var (
		port        int
		registryURL string
		redisURL    string
		tempoURL    string
		showVersion bool
		help        bool
	)
	flag.IntVarP(&port, "port", "p", 0, "Port to bind the UI server to (overrides MCP_MESH_UI_PORT env var)")
	flag.StringVarP(&registryURL, "registry-url", "r", "", "Registry URL to proxy API requests (overrides MCP_MESH_REGISTRY_URL env var)")
	flag.StringVar(&redisURL, "redis-url", "", "Redis URL for live trace streaming (overrides REDIS_URL)")
	flag.StringVarP(&tempoURL, "tempo-url", "t", "", "Tempo HTTP query URL for historical traces (overrides TEMPO_URL env var)")
	flag.BoolVarP(&showVersion, "version", "v", false, "Show version information")
	flag.BoolVarP(&help, "help", "h", false, "Show help information")

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "MCP Mesh UI Server\n\n")
		fmt.Fprintf(os.Stderr, "Serves the embedded dashboard and proxies API requests to the registry.\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nEnvironment Variables:\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_UI_PORT         - Port to bind to (default: 3080)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_REGISTRY_URL    - Registry URL for API proxy (default: http://localhost:8000)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_LOG_LEVEL       - Log level: TRACE, DEBUG, INFO, WARNING, ERROR (default: INFO)\n")
		fmt.Fprintf(os.Stderr, "  DATABASE_URL             - Path to SQLite database or PostgreSQL URL (default: mcp_mesh_registry.db)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_DISTRIBUTED_TRACING_ENABLED - Enable trace streaming (default: false)\n")
		fmt.Fprintf(os.Stderr, "  REDIS_URL                - Redis URL for trace streaming (default: redis://localhost:6379)\n")
		fmt.Fprintf(os.Stderr, "  TEMPO_URL              - Tempo HTTP query URL (default: http://localhost:3200)\n")
		fmt.Fprintf(os.Stderr, "  TELEMETRY_ENDPOINT     - OTLP endpoint; Tempo URL auto-derived if TEMPO_URL not set\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_UI_BASE_PATH    - Base path for path-based ingress (default: empty)\n")
	}

	flag.Parse()

	if help {
		flag.Usage()
		return
	}

	if showVersion {
		fmt.Printf("MCP Mesh UI Server %s\n", version)
		fmt.Println("Embedded dashboard and registry API proxy for MCP Mesh")
		return
	}

	// Resolve configuration: flags > env > defaults
	uiPort := getEnvIntDefault("MCP_MESH_UI_PORT", 3080)
	if port != 0 {
		uiPort = port
	}

	regURL := getEnvDefault("MCP_MESH_REGISTRY_URL", "http://localhost:8000")
	if registryURL != "" {
		regURL = registryURL
	}
	// Trim trailing slash for consistent URL joining
	regURL = strings.TrimRight(regURL, "/")

	// Load basePath for path-based ingress routing.
	// The base path is injected into the SPA at serve-time, so it can be changed
	// at runtime without rebuilding.
	basePath := os.Getenv("MCP_MESH_UI_BASE_PATH")
	if basePath != "" {
		// Normalize: must start with /, no trailing slash
		if !strings.HasPrefix(basePath, "/") {
			basePath = "/" + basePath
		}
		basePath = strings.TrimRight(basePath, "/")
		// After normalization, "/" becomes "" (root path) — skip validation
		if basePath != "" {
			// Validate: only allow safe URL path characters to prevent injection
			// when the value is embedded in HTML/JavaScript at serve-time.
			matched := regexp.MustCompile(`^[a-zA-Z0-9/_-]+$`).MatchString(basePath)
			if !matched {
				log.Fatalf("Invalid MCP_MESH_UI_BASE_PATH %q: only alphanumeric, '/', '_', and '-' characters are allowed", basePath)
			}
		}
	}

	// Load TLS config for registry proxy
	registryTLS, err := tlsutil.LoadFromEnv("MCP_MESH_REGISTRY_TLS")
	if err != nil {
		log.Fatalf("Failed to load registry TLS config: %v", err)
	}

	logLevel := getEnvDefault("MCP_MESH_LOG_LEVEL", "INFO")

	uiConfig := &ui.UIConfig{
		Port:        uiPort,
		RegistryURL: regURL,
		BasePath:    basePath,
		LogLevel:    logLevel,
		RegistryTLS: registryTLS,
	}

	if basePath != "" {
		log.Printf("Starting MCP Mesh UI Server | port=%d registry=%s basePath=%s", uiPort, regURL, basePath)
	} else {
		log.Printf("Starting MCP Mesh UI Server | port=%d registry=%s", uiPort, regURL)
	}

	// Initialize database (read-only, shared with registry)
	dbURL := getEnvDefault("DATABASE_URL", "mcp_mesh_registry.db")
	dbConfig := &database.Config{
		DatabaseURL:        dbURL,
		MaxOpenConnections: 5,
		MaxIdleConnections: 2,
		ConnMaxLifetime:    300,
		BusyTimeout:        5000,
		JournalMode:        "WAL",
		Synchronous:        "NORMAL",
		CacheSize:          10000,
		EnableForeignKeys:  true,
	}
	db, err := database.InitializeEnt(dbConfig, strings.ToUpper(logLevel) == "TRACE")
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	// Create EntService for read-only DB queries (agent list, event history)
	meshLogger := logger.New(&config.Config{LogLevel: logLevel})
	entService := registry.NewEntService(db, nil, meshLogger)

	// Initialize distributed tracing (accumulator-only, no OTLP export)
	var tracingManager *tracing.TracingManager
	var metricsProc *ui.MetricsProcessor
	// Default to true — the UI server handles Redis unavailability gracefully
	// (logs warning, continues without tracing). This ensures the dashboard shows
	// trace data without requiring users to explicitly set the env var.
	tracingEnabled := strings.ToLower(getEnvDefault("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "true")) == "true"
	if tracingEnabled {
		hostname, _ := os.Hostname()
		tracingConfig := &tracing.TracingConfig{
			Enabled:       true,
			RedisURL:      resolveRedisURL(redisURL),
			StreamName:    "mesh:trace",
			ConsumerGroup: "mcp-mesh-ui-dashboard",
			ConsumerName:  fmt.Sprintf("ui-%s", hostname),
			BatchSize:     100,
			BlockTimeout:  2 * time.Second,
			TraceTimeout:  5 * time.Minute,
			TempoQueryURL: resolveTempoURL(tempoURL),
		}

		metricsProc = ui.NewMetricsProcessor()
		tm, err := tracing.NewAccumulatorOnlyManager(tracingConfig, metricsProc)
		if err != nil {
			log.Printf("Warning: failed to initialize tracing: %v", err)
		} else {
			tracingManager = tm
			log.Printf("Distributed tracing enabled (accumulator-only, group=%s)", tracingConfig.ConsumerGroup)
		}
	}

	// Create UI server
	server := ui.NewServer(uiConfig, entService, tracingManager, metricsProc, EmbeddedSPA, logLevel)

	// Graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		sig := <-sigChan

		log.Printf("Received signal %v, shutting down...", sig)

		if err := server.Stop(); err != nil {
			log.Printf("Error during shutdown: %v", err)
		}
		if err := db.Close(); err != nil {
			log.Printf("Failed to close database: %v", err)
		}

		log.Println("UI server stopped")
		os.Exit(0)
	}()

	// Start serving
	addr := fmt.Sprintf(":%d", uiPort)
	if err := server.Run(addr); err != nil {
		log.Fatalf("Failed to start UI server: %v", err)
	}
}

func getEnvDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func getEnvIntDefault(key string, defaultValue int) int {
	if value := os.Getenv(key); value != "" {
		if intValue, err := strconv.Atoi(value); err == nil {
			return intValue
		}
	}
	return defaultValue
}

func resolveRedisURL(flagValue string) string {
	if flagValue != "" {
		return flagValue
	}
	return getEnvDefault("REDIS_URL", "redis://localhost:6379")
}

func resolveTempoURL(flagValue string) string {
	if flagValue != "" {
		return flagValue
	}
	return tracing.GetTempoURLFromEnv()
}
