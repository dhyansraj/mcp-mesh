package cli

import (
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/spf13/cobra"
)

// isLocalhostRegistry checks if the registry host is localhost/local.
// "0.0.0.0" is treated as localhost because it means "bind to all interfaces"
// — for deciding whether to start a local registry, this counts as local.
func isLocalhostRegistry(host string) bool {
	switch strings.ToLower(host) {
	case "localhost", "127.0.0.1", "::1", "0.0.0.0":
		return true
	default:
		return false
	}
}

// Registry-only mode
func startRegistryOnlyMode(cmd *cobra.Command, config *CLIConfig) error {
	pm := GetGlobalProcessManager()
	// Update ProcessManager config with current config (including command-line flags)
	pm.mutex.Lock()
	pm.config = config
	pm.mutex.Unlock()
	quiet, _ := cmd.Flags().GetBool("quiet")

	if !quiet {
		fmt.Printf("Starting MCP Mesh registry on %s:%d\n", config.RegistryHost, config.RegistryPort)
	}

	// Check if registry is already running via HTTP (primary check)
	registryURL := config.GetRegistryURL()
	if IsRegistryRunning(registryURL) {
		if !quiet {
			fmt.Printf("Registry is already running at %s\n", registryURL)
		}
		return fmt.Errorf("registry is already running at %s", registryURL)
	}

	// Check if port is available (secondary check for better error messages)
	if !IsPortAvailable(config.RegistryHost, config.RegistryPort) {
		return fmt.Errorf("port %d is already in use on %s - another service may be using this port", config.RegistryPort, config.RegistryHost)
	}

	// Setup security if specified
	secure, _ := cmd.Flags().GetBool("secure")
	if secure {
		certFile, _ := cmd.Flags().GetString("cert-file")
		keyFile, _ := cmd.Flags().GetString("key-file")
		if certFile == "" || keyFile == "" {
			return fmt.Errorf("--cert-file and --key-file required when using --secure")
		}
		// TODO: Implement TLS configuration
	}

	// Start registry using process manager
	metadata := map[string]interface{}{
		"secure": secure,
	}

	processInfo, err := pm.StartRegistryProcess(config.RegistryPort, config.DBPath, metadata)
	if err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Write PID file for registry process
	pidMgr, pidErr := NewPIDManager()
	if pidErr == nil {
		if err := pidMgr.WritePID("registry", processInfo.PID); err != nil && !quiet {
			fmt.Printf("Warning: failed to write registry PID file: %v\n", err)
		}
	}

	detach, _ := cmd.Flags().GetBool("detach")
	if detach {
		if !quiet {
			fmt.Printf("Registry started in detach (PID: %d)\n", processInfo.PID)
			fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		}
		// Start UI server if --ui flag is set (detach mode)
		maybeStartUIServer(cmd, config, config.GetRegistryURL())
		return nil
	}

	// Start UI server if --ui flag is set (before blocking on signals)
	maybeStartUIServer(cmd, config, config.GetRegistryURL())

	// Foreground mode - wait for signal
	if !quiet {
		fmt.Printf("Registry started (PID: %d)\n", processInfo.PID)
		fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		fmt.Println("Registry is running. Press Ctrl+C to stop.")
	}

	// Don't start CLI health monitoring when we have an embedded registry
	// The registry will handle health monitoring internally

	// Wait for shutdown signal
	signalHandler := GetGlobalSignalHandler()
	signalHandler.WaitForShutdown()

	return nil
}

func startRegistryWithOptions(config *CLIConfig, detach bool, cmd *cobra.Command) error {
	// Start the registry service
	registryCmd, err := startRegistryService(config)
	if err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	if detach {
		// Set up log file for detached registry
		lm, err := NewLogManager()
		if err != nil {
			return fmt.Errorf("failed to initialize log manager: %w", err)
		}

		// Rotate existing logs
		quiet, _ := cmd.Flags().GetBool("quiet")
		if err := lm.RotateLogs("registry"); err != nil && !quiet {
			fmt.Printf("Warning: failed to rotate logs for registry: %v\n", err)
		}

		// Create log file and redirect output
		logFile, err := lm.CreateLogFile("registry")
		if err != nil {
			return fmt.Errorf("failed to create log file for registry: %w", err)
		}
		registryCmd.Stdout = logFile
		registryCmd.Stderr = logFile

		// Start in detach
		if err := registryCmd.Start(); err != nil {
			logFile.Close()
			return fmt.Errorf("failed to start registry in detach: %w", err)
		}
		// Close parent's copy of log file — child process has its own file descriptor
		logFile.Close()

		// Write PID file for registry
		pm, err := NewPIDManager()
		if err == nil {
			if err := pm.WritePID("registry", registryCmd.Process.Pid); err != nil {
				fmt.Printf("Warning: failed to write PID file for registry: %v\n", err)
			}
		}

		// Record the process
		proc := ProcessInfo{
			PID:       registryCmd.Process.Pid,
			Name:      "mcp-mesh-registry",
			Type:      "registry",
			Command:   registryCmd.String(),
			StartTime: time.Now(),
			Status:    "running",
		}
		if err := AddRunningProcess(proc); err != nil {
			fmt.Printf("Warning: failed to record process: %v\n", err)
		}

		if !quiet {
			fmt.Printf("Registry started in detach (PID: %d)\n", registryCmd.Process.Pid)
			fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
			fmt.Printf("Logs: ~/.mcp-mesh/logs/registry.log\n")
		}
		return nil
	}

	// Start in foreground
	if err := registryCmd.Start(); err != nil {
		return fmt.Errorf("failed to start registry: %w", err)
	}

	// Record the process
	proc := ProcessInfo{
		PID:       registryCmd.Process.Pid,
		Name:      "mcp-mesh-registry",
		Type:      "registry",
		Command:   registryCmd.String(),
		StartTime: time.Now(),
		Status:    "running",
	}
	if err := AddRunningProcess(proc); err != nil {
		fmt.Printf("Warning: failed to record process: %v\n", err)
	}

	quiet, _ := cmd.Flags().GetBool("quiet")
	if !quiet {
		fmt.Printf("Registry started (PID: %d)\n", registryCmd.Process.Pid)
		fmt.Printf("Registry URL: %s\n", config.GetRegistryURL())
		fmt.Print("Waiting for registry to be ready...")
	}

	// Wait for registry to be ready
	if err := WaitForRegistry(config.GetRegistryURL(), time.Duration(config.StartupTimeout)*time.Second); err != nil {
		return fmt.Errorf("registry failed to start: %w", err)
	}

	if !quiet {
		fmt.Println(" ✓")
		fmt.Println("Registry is running. Press Ctrl+C to stop.")
	}

	// Setup signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Wait for signal
	<-sigChan
	if !quiet {
		fmt.Println("\nShutting down registry...")
	}

	// Remove from process list
	RemoveRunningProcess(registryCmd.Process.Pid)

	// Kill the process
	shutdownTimeout, _ := cmd.Flags().GetInt("shutdown-timeout")
	if shutdownTimeout == 0 {
		shutdownTimeout = config.ShutdownTimeout
	}
	return KillProcess(registryCmd.Process.Pid, time.Duration(shutdownTimeout)*time.Second)
}

func startRegistryService(config *CLIConfig) (*exec.Cmd, error) {
	// Try to find registry binary in multiple locations
	localPaths := []string{
		"./bin/mcp-mesh-registry",   // Relative to current working directory
		"./mcp-mesh-registry",       // For compatibility with process_lifecycle.go
		"./build/mcp-mesh-registry", // Build directory
	}

	var registryBinary string
	var binaryFound bool

	// Check local paths first
	for _, path := range localPaths {
		if _, err := os.Stat(path); err == nil {
			registryBinary = path
			binaryFound = true
			break
		}
	}

	// If not found locally, check system PATH
	if !binaryFound {
		if path, err := exec.LookPath("mcp-mesh-registry"); err == nil {
			registryBinary = path
			binaryFound = true
		}
	}

	// Build possiblePaths for error message
	possiblePaths := append(localPaths, "mcp-mesh-registry (in PATH)")

	// If binary not found, try to build it
	if !binaryFound {
		// Use bin/ directory for consistency with Makefile
		registryBinary = "./bin/mcp-mesh-registry"

		// Check if we have the source to build from
		if _, err := os.Stat("./cmd/mcp-mesh-registry"); err == nil {
			fmt.Println("Registry binary not found, building from source...")

			// Ensure bin directory exists
			if err := os.MkdirAll("./bin", 0755); err != nil {
				return nil, fmt.Errorf("failed to create bin directory: %w", err)
			}

			buildCmd := exec.Command("go", "build", "-o", registryBinary, "./cmd/mcp-mesh-registry")

			// Ensure Go is in PATH
			env := os.Environ()
			pathFound := false
			for i, envVar := range env {
				if strings.HasPrefix(envVar, "PATH=") {
					env[i] = "PATH=/usr/local/go/bin:" + envVar[5:]
					pathFound = true
					break
				}
			}
			if !pathFound {
				env = append(env, "PATH=/usr/local/go/bin")
			}
			buildCmd.Env = env

			if err := buildCmd.Run(); err != nil {
				return nil, fmt.Errorf("failed to build registry from source: %w", err)
			}
			fmt.Println("Registry built successfully")
		} else {
			// No source available, cannot build
			return nil, fmt.Errorf("registry binary not found at any of these locations: %v. Please ensure the binary is built or run 'make build' to compile it", possiblePaths)
		}
	}

	// Create registry command
	cmd := exec.Command(registryBinary,
		"-host", config.RegistryHost,
		"-port", fmt.Sprintf("%d", config.RegistryPort),
	)

	// Set up environment
	cmd.Env = append(os.Environ(), config.GetRegistryEnvironmentVariables()...)

	// Add TLS auto env vars if enabled
	if config.TLSAuto && config.TLSAutoConfigRef != nil {
		cmd.Env = append(cmd.Env, config.TLSAutoConfigRef.GetRegistryTLSEnv()...)
	}

	// Set up process group for proper signal handling (Unix only)
	platformManager := NewPlatformProcessManager()
	platformManager.setProcessGroup(cmd)

	// Set up stdio
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	return cmd, nil
}

// determineStartRegistryURL resolves the registry URL for start command based on flags and config
func determineStartRegistryURL(cmd *cobra.Command, config *CLIConfig) string {
	// Check if registry-url flag is provided
	if registryURL, _ := cmd.Flags().GetString("registry-url"); registryURL != "" {
		return registryURL
	}

	// Build URL from individual flags or config
	host := config.RegistryHost
	port := config.RegistryPort

	// Override with flags if provided
	if cmd.Flags().Changed("registry-host") {
		if flagHost, _ := cmd.Flags().GetString("registry-host"); flagHost != "" {
			host = flagHost
		}
	}
	if cmd.Flags().Changed("registry-port") {
		if flagPort, _ := cmd.Flags().GetInt("registry-port"); flagPort > 0 {
			port = flagPort
		}
	}

	scheme := "http"
	if config.TLSAuto {
		scheme = "https"
	}
	return fmt.Sprintf("%s://%s:%d", scheme, host, port)
}

// getRegistryHostFromURL extracts the host from a registry URL, fallback to config host
func getRegistryHostFromURL(registryURL, fallbackHost string) string {
	if parsed, err := url.Parse(registryURL); err == nil {
		if host := parsed.Hostname(); host != "" {
			return host
		}
	}
	return fallbackHost
}

// getRegistryPortFromURL extracts the port from a registry URL, fallback to config port
func getRegistryPortFromURL(registryURL string, fallbackPort int) int {
	if parsed, err := url.Parse(registryURL); err == nil {
		if portStr := parsed.Port(); portStr != "" {
			if port, err := strconv.Atoi(portStr); err == nil {
				return port
			}
		}
	}
	return fallbackPort
}
