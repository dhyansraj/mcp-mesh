package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"mcp-mesh/src/core/config"
	"mcp-mesh/src/core/database"
	"mcp-mesh/src/core/registry"
)

func main() {
	// Command line flags
	var (
		host    = flag.String("host", "", "Host to bind the server to (overrides HOST env var)")
		port    = flag.Int("port", 0, "Port to bind the server to (overrides PORT env var)")
		version = flag.Bool("version", false, "Show version information")
		help    = flag.Bool("help", false, "Show help information")
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
		fmt.Fprintf(os.Stderr, "  LOG_LEVEL                - Log level (debug, info, warn, error) (default: info)\n")
		fmt.Fprintf(os.Stderr, "  HEALTH_CHECK_INTERVAL    - Health check interval in seconds (default: 30)\n")
		fmt.Fprintf(os.Stderr, "  CACHE_TTL                - Response cache TTL in seconds (default: 30)\n")
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

	if *version {
		fmt.Println("MCP Mesh Registry Service v1.0.0")
		fmt.Println("Built with Go and Kubernetes API Server patterns")
		fmt.Println("Compatible with Python MCP Mesh Registry API")
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

	// Initialize database
	log.Printf("🗄️  Initializing database: %s", cfg.GetDatabaseURL())
	db, err := database.Initialize(cfg.Database)
	if err != nil {
		log.Fatalf("❌ Failed to initialize database: %v", err)
	}
	defer func() {
		if err := db.Close(); err != nil {
			log.Printf("Warning: Failed to close database: %v", err)
		}
	}()

	// Create registry service
	registryConfig := &registry.RegistryConfig{
		CacheTTL:                 cfg.CacheTTL,
		DefaultTimeoutThreshold:  cfg.DefaultTimeoutThreshold,
		DefaultEvictionThreshold: cfg.DefaultEvictionThreshold,
		EnableResponseCache:      cfg.EnableResponseCache,
	}

	// Create and configure server
	server := registry.NewServer(db, registryConfig)

	// Setup graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		sig := <-sigChan

		log.Printf("🛑 Received signal %v, initiating graceful shutdown...", sig)

		// Stop server
		if err := server.Stop(); err != nil {
			log.Printf("Error during server shutdown: %v", err)
		}

		log.Println("✅ Registry service stopped")
		os.Exit(0)
	}()

	// Start server
	log.Printf("🚀 Starting MCP Mesh Registry Service on %s:%d", cfg.Host, cfg.Port)
	addr := fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)
	if err := server.Run(addr); err != nil {
		log.Fatalf("❌ Failed to start server: %v", err)
	}
}
