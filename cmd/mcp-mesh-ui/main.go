package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"

	"mcp-mesh/src/core/ui"
)

// version is injected at build time via ldflags
var version = "dev"

func main() {
	var (
		port        = flag.Int("port", 0, "Port to bind the UI server to (overrides MCP_MESH_UI_PORT env var)")
		registryURL = flag.String("registry-url", "", "Registry URL to proxy API requests (overrides MCP_MESH_REGISTRY_URL env var)")
		showVersion = flag.Bool("version", false, "Show version information")
		help        = flag.Bool("help", false, "Show help information")
	)

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "MCP Mesh UI Server\n\n")
		fmt.Fprintf(os.Stderr, "Serves the embedded Next.js dashboard and proxies API requests to the registry.\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nEnvironment Variables:\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_UI_PORT         - Port to bind to (default: 3001)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_REGISTRY_URL    - Registry URL for API proxy (default: http://localhost:8000)\n")
		fmt.Fprintf(os.Stderr, "  MCP_MESH_LOG_LEVEL       - Log level: TRACE, DEBUG, INFO, WARNING, ERROR (default: INFO)\n")
	}

	flag.Parse()

	if *help {
		flag.Usage()
		return
	}

	if *showVersion {
		fmt.Printf("MCP Mesh UI Server %s\n", version)
		fmt.Println("Embedded dashboard and registry API proxy for MCP Mesh")
		return
	}

	// Resolve configuration: flags > env > defaults
	uiPort := getEnvIntDefault("MCP_MESH_UI_PORT", 3001)
	if *port != 0 {
		uiPort = *port
	}

	regURL := getEnvDefault("MCP_MESH_REGISTRY_URL", "http://localhost:8000")
	if *registryURL != "" {
		regURL = *registryURL
	}
	// Trim trailing slash for consistent URL joining
	regURL = strings.TrimRight(regURL, "/")

	logLevel := getEnvDefault("MCP_MESH_LOG_LEVEL", "INFO")

	uiConfig := &ui.UIConfig{
		Port:        uiPort,
		RegistryURL: regURL,
		LogLevel:    logLevel,
	}

	log.Printf("Starting MCP Mesh UI Server | port=%d registry=%s", uiPort, regURL)

	// Create UI server
	server := ui.NewServer(uiConfig, EmbeddedSPA, logLevel)

	// Graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		sig := <-sigChan

		log.Printf("Received signal %v, shutting down...", sig)

		if err := server.Stop(); err != nil {
			log.Printf("Error during shutdown: %v", err)
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
