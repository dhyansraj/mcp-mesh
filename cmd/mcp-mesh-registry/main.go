package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/logger"
	"mcp-mesh/src/core/registry"
)

// version is injected at build time via ldflags
var version = "dev"

func main() {
	// Command line flags
	var (
		host        = flag.String("host", "", "Host to bind the server to (overrides HOST env var)")
		port        = flag.Int("port", 0, "Port to bind the server to (overrides PORT env var)")
		showVersion = flag.Bool("version", false, "Show version information")
		help        = flag.Bool("help", false, "Show help information")
	)

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "MCP Mesh Registry Service\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nExamples:\n")
		fmt.Fprintf(os.Stderr, "  %s\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s --host 0.0.0.0 --port 9000\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "\nEnvironment Variables:\n")
		fmt.Fprintf(os.Stderr, "  HOST                     - Host to bind to (default: localhost)\n")
		fmt.Fprintf(os.Stderr, "  PORT                     - Port to bind to (default: 8000)\n")
		fmt.Fprintf(os.Stderr, "  DATABASE_URL             - Database connection URL (default: mcp_mesh_registry.db)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_LOG_LEVEL       - Log level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL) (default: INFO)\n")
		fmt.Fprintf(os.Stderr, "                             TRACE enables SQL query logging, DEBUG is for general debugging\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_DEBUG_MODE      - Enable debug mode (true/false, 1/0, yes/no) - forces DEBUG level\n")
		fmt.Fprintf(os.Stderr, "  HEALTH_CHECK_INTERVAL    - Health check interval in seconds (default: 10)\n")
		fmt.Fprintf(os.Stderr, "  DEFAULT_TIMEOUT_THRESHOLD - Agent heartbeat timeout in seconds (default: 20)\n")
		fmt.Fprintf(os.Stderr, "  CACHE_TTL                - Response cache TTL in seconds (default: 30)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_DISTRIBUTED_TRACING_ENABLED - Enable distributed tracing (true/false, default: false)\n")
		fmt.Fprintf(os.Stderr, "  REDIS_URL                - Redis URL for distributed tracing (default: redis://localhost:6379)\n")
		fmt.Fprintf(os.Stderr, "\nThe registry service provides:\n")
		fmt.Fprintf(os.Stderr, "  - Agent registration and discovery\n")
		fmt.Fprintf(os.Stderr, "  - Capability-based service matching\n")
		fmt.Fprintf(os.Stderr, "  - Health monitoring and heartbeat tracking\n")
		fmt.Fprintf(os.Stderr, "  - Kubernetes API server patterns\n")
		fmt.Fprintf(os.Stderr, "  - PASSIVE pull-based architecture\n")
	}

	flag.Parse()

	if *help {
		flag.Usage()
		return
	}

	if *showVersion {
		fmt.Printf("MCP Mesh Registry %s\n", version)
		fmt.Println("Central service discovery and agent coordination for MCP Mesh")
		return
	}

	// Load configuration from environment
	cfg := config.LoadFromEnv()

	// Override with command line flags if provided
	if *host != "" {
		cfg.Host = *host
	}
	if *port != 0 {
		cfg.Port = *port
	}

	// Validate configuration
	if err := cfg.Validate(); err != nil {
		log.Fatalf("❌ Configuration validation failed: %v", err)
	}

	// Initialize structured logger
	appLogger := logger.New(cfg)

	// Set Gin mode early before any Gin engine creation
	appLogger.SetGinMode()

	// Show startup banner with log level info
	appLogger.Info("🚀 Starting MCP Mesh Registry Service | %s", appLogger.GetStartupBanner())

	// Initialize database with Ent
	appLogger.Info("🗄️  Initializing database: %s", cfg.GetDatabaseURL())
	db, err := database.InitializeEnt(cfg.Database, cfg.IsTraceMode())
	if err != nil {
		appLogger.Error("❌ Failed to initialize database: %v", err)
		os.Exit(1)
	}
	defer func() {
		if err := db.Close(); err != nil {
			appLogger.Warning("Failed to close database: %v", err)
		}
	}()

	// Create registry service
	registryConfig := &registry.RegistryConfig{
		CacheTTL:                 cfg.CacheTTL,
		DefaultTimeoutThreshold:  cfg.DefaultTimeoutThreshold,
		DefaultEvictionThreshold: cfg.DefaultEvictionThreshold,
		HealthCheckInterval:      cfg.HealthCheckInterval,
		EnableResponseCache:      cfg.EnableResponseCache,
		TracingEnabled:           strings.ToLower(os.Getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED")) == "true",
	}

	// Create and configure server using Ent
	server := registry.NewServer(db, registryConfig, appLogger)

	// Setup graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		sig := <-sigChan

		appLogger.Info("🛑 Received signal %v, initiating graceful shutdown...", sig)

		// Stop server
		if err := server.Stop(); err != nil {
			appLogger.Error("Error during server shutdown: %v", err)
		}

		appLogger.Info("✅ Registry service stopped")
		os.Exit(0)
	}()

	// Start server
	addr := fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)
	appLogger.Info("🌟 MCP Mesh Registry Service listening on %s", addr)
	if err := server.Run(addr); err != nil {
		appLogger.Error("❌ Failed to start server: %v", err)
		os.Exit(1)
	}
}
