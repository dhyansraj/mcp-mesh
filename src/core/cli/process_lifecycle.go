package cli

import (
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"time"
)

const (
	defaultRegistryPort  = 8080
	defaultUIPort        = 3080
	registryReadyTimeout = 10 * time.Second
	uiReadyTimeout       = 5 * time.Second
	readyPollInterval    = 250 * time.Millisecond
)

// terminateAndWait sends a termination signal to the process group and waits for exit.
// fallbackSignal is sent to the main process if group termination fails.
// Returns nil if the process exits within timeout, or an error on timeout.
// The caller must hold pm.mutex.
func (pm *ProcessManager) terminateAndWait(info *ProcessInfo, name string, fallbackSignal os.Signal, timeout time.Duration) error {
	platformManager := NewPlatformProcessManager()
	if err := platformManager.terminateProcessGroup(info.PID, timeout); err != nil {
		pm.logger.Printf("Process group termination failed for %s, falling back to signal: %v", name, err)
		if err := info.Process.Signal(fallbackSignal); err != nil {
			// If signal fails too, try kill as last resort
			info.Process.Kill()
		}
	}

	done := make(chan error, 1)
	go func() {
		_, err := info.Process.Wait()
		done <- err
	}()

	select {
	case err := <-done:
		return err
	case <-time.After(timeout):
		// Kill process to ensure the Wait() goroutine can complete
		info.Process.Kill()
		<-done // drain the goroutine
		return fmt.Errorf("process %s did not exit within %v", name, timeout)
	}
}

// StopProcess gracefully stops a managed process
func (pm *ProcessManager) StopProcess(name string, timeout time.Duration) error {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	info, exists := pm.processes[name]
	if !exists {
		return fmt.Errorf("process %s not found", name)
	}

	if info.Process == nil {
		return fmt.Errorf("process %s has no associated OS process", name)
	}

	pm.logger.Printf("Stopping process group: %s (PID: %d)", name, info.PID)

	err := pm.terminateAndWait(info, name, os.Interrupt, timeout)
	if err != nil {
		// Timeout — force kill
		pm.logger.Printf("Process %s timeout, forcing kill", name)
		if killErr := info.Process.Kill(); killErr != nil {
			pm.logger.Printf("Failed to kill process %s: %v", name, killErr)
		}
		info.Status = "killed"
		info.HealthCheck = "killed"
		pm.saveState()
		return err
	}

	info.Status = "stopped"
	info.HealthCheck = "stopped"
	pm.logger.Printf("Process %s stopped gracefully", name)
	pm.saveState()
	return nil
}

// TerminateProcess forcefully terminates a process and its entire process group
func (pm *ProcessManager) TerminateProcess(name string, timeout time.Duration) error {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	info, exists := pm.processes[name]
	if !exists {
		return fmt.Errorf("process %s not found", name)
	}

	if info.Process == nil {
		return fmt.Errorf("process %s has no associated OS process", name)
	}

	pm.logger.Printf("Terminating process group: %s (PID: %d)", name, info.PID)

	err := pm.terminateAndWait(info, name, os.Kill, timeout)
	if err != nil {
		return err
	}

	info.Status = "killed"
	info.HealthCheck = "killed"
	pm.logger.Printf("Process %s terminated", name)
	pm.saveState()
	return nil
}

// StartRegistryProcess starts the registry service
func (pm *ProcessManager) StartRegistryProcess(port int, dbPath string, metadata map[string]interface{}) (*ProcessInfo, error) {
	name := "registry"

	// Check if registry already exists
	if info, exists := pm.GetProcess(name); exists && pm.isProcessRunning(info) {
		return info, fmt.Errorf("registry process already running (PID: %d)", info.PID)
	}

	// Find available port if not specified
	if port == 0 {
		port = pm.config.RegistryPort
		if port == 0 {
			port = defaultRegistryPort
		}
	}

	// Use configured database path if not specified
	if dbPath == "" {
		dbPath = pm.config.DBPath
	}

	// Find registry binary
	registryBinary, err := pm.findRegistryBinary()
	if err != nil {
		return nil, fmt.Errorf("failed to start registry: %w", err)
	}

	host := pm.config.RegistryHost
	if host == "" {
		host = "localhost"
	}

	args := []string{
		"--host", host,
		"--port", fmt.Sprintf("%d", port),
	}

	// Database path is passed via environment variable, not as an argument

	cmd := exec.Command(registryBinary, args...)

	// Set up environment variables
	cmd.Env = append(os.Environ(), pm.config.GetRegistryEnvironmentVariables()...)

	// Add TLS auto env vars if enabled
	if pm.config.TLSAuto && pm.config.TLSAutoConfigRef != nil {
		cmd.Env = append(cmd.Env, pm.config.TLSAutoConfigRef.GetRegistryTLSEnv()...)
	}

	// Set working directory
	workingDir, _ := os.Getwd()
	cmd.Dir = workingDir

	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("failed to start registry process: %w", err)
	}

	// Track the process
	if metadata == nil {
		metadata = make(map[string]interface{})
	}
	metadata["host"] = host
	metadata["port"] = port
	metadata["db_path"] = dbPath

	processInfo := pm.TrackProcess(name, registryBinary, "registry", cmd.Process, metadata)

	// Update config with registry information
	pm.config.RegistryPort = port
	if dbPath != "" {
		pm.config.DBPath = dbPath
	}

	pm.logger.Printf("Started registry process: %s (PID: %d, Port: %d)", name, cmd.Process.Pid, port)

	// Wait for registry to be ready (reduced timeout for FastAPI registry)
	if err := pm.waitForRegistryReady(registryReadyTimeout); err != nil {
		pm.logger.Printf("Warning: Registry may not be fully ready: %v", err)
	}

	return processInfo, nil
}

// findBinary searches localPaths in order, then falls back to PATH for each
// name in pathNames. A local path matches only if it is a regular, executable
// file. Returns the first match or an empty string if none found.
func findBinary(localPaths []string, pathNames ...string) string {
	for _, path := range localPaths {
		if fi, err := os.Stat(path); err == nil && fi.Mode().IsRegular() && fi.Mode().Perm()&0111 != 0 {
			return path
		}
	}

	for _, name := range pathNames {
		if path, err := exec.LookPath(name); err == nil {
			return path
		}
	}

	return ""
}

// findRegistryBinary finds the registry binary in local paths or PATH
func (pm *ProcessManager) findRegistryBinary() (string, error) {
	// First check local paths
	localPaths := []string{
		"./bin/mcp-mesh-registry",
		"./mcp-mesh-registry",
		"./build/mcp-mesh-registry",
		"cmd/mcp-mesh-registry/mcp-mesh-registry",
	}

	if path := findBinary(localPaths, "mcp-mesh-registry"); path != "" {
		return path, nil
	}

	// Return error with all attempted paths
	allPaths := append(localPaths, "mcp-mesh-registry (in PATH)")
	return "", fmt.Errorf("registry binary not found at any of these locations: %v. Please ensure the binary is built or run 'make build' to compile it", allPaths)
}

// StartUIProcess starts the dashboard UI server
func (pm *ProcessManager) StartUIProcess(port int, registryURL string, dbPath string) (*ProcessInfo, error) {
	name := "ui"

	// Check if UI already running
	if info, exists := pm.GetProcess(name); exists && pm.isProcessRunning(info) {
		return info, nil
	}

	if port == 0 {
		if val := os.Getenv("MCP_MESH_UI_PORT"); val != "" {
			if parsed, err := strconv.Atoi(val); err == nil {
				port = parsed
			}
		}
		if port == 0 {
			port = defaultUIPort
		}
	}

	uiBinary, err := pm.findUIBinary()
	if err != nil {
		return nil, fmt.Errorf("failed to start UI server: %w", err)
	}

	args := []string{
		"--port", fmt.Sprintf("%d", port),
	}

	cmd := exec.Command(uiBinary, args...)

	// Set up environment
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("MCP_MESH_UI_PORT=%d", port),
		fmt.Sprintf("MCP_MESH_REGISTRY_URL=%s", registryURL),
	)
	if dbPath != "" {
		cmd.Env = append(cmd.Env, fmt.Sprintf("DATABASE_URL=%s", dbPath))
	}

	workingDir, _ := os.Getwd()
	cmd.Dir = workingDir

	// Set up log file for UI server
	lm, err := NewLogManager()
	if err != nil {
		return nil, fmt.Errorf("failed to initialize log manager: %w", err)
	}

	if err := lm.RotateLogs("meshui"); err != nil {
		pm.logger.Printf("Warning: failed to rotate logs for meshui: %v", err)
	}

	logFile, err := lm.CreateLogFile("meshui")
	if err != nil {
		return nil, fmt.Errorf("failed to create log file for meshui: %w", err)
	}
	cmd.Stdout = logFile
	cmd.Stderr = logFile

	if err := cmd.Start(); err != nil {
		logFile.Close()
		return nil, fmt.Errorf("failed to start UI server process: %w", err)
	}
	// Close parent's copy of log file — child process has its own file descriptor
	logFile.Close()

	metadata := map[string]interface{}{
		"port":         port,
		"registry_url": registryURL,
	}

	processInfo := pm.TrackProcess(name, uiBinary, "ui", cmd.Process, metadata)

	pm.logger.Printf("Started UI server: %s (PID: %d, Port: %d)", name, cmd.Process.Pid, port)

	// Wait for UI to be ready
	if err := pm.waitForUIReady(port, uiReadyTimeout); err != nil {
		pm.logger.Printf("Warning: UI server may not be fully ready: %v", err)
	}

	return processInfo, nil
}

// waitForHTTPReady polls url until it returns HTTP 200 or the timeout elapses.
func waitForHTTPReady(client *http.Client, url string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		resp, err := client.Get(url)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				return nil
			}
		}
		time.Sleep(readyPollInterval)
	}

	return fmt.Errorf("endpoint %s did not become ready within timeout", url)
}

// waitForUIReady waits for the UI server to respond to health checks
func (pm *ProcessManager) waitForUIReady(port int, timeout time.Duration) error {
	healthURL := fmt.Sprintf("http://localhost:%d/api/ui-health", port)
	if err := waitForHTTPReady(newTLSSkipVerifyClient(), healthURL, timeout); err != nil {
		return fmt.Errorf("UI server did not become ready within timeout")
	}
	return nil
}

// findUIBinary finds the UI server binary in local paths or PATH
func (pm *ProcessManager) findUIBinary() (string, error) {
	localPaths := []string{
		"./bin/meshui",
		"./bin/mcp-mesh-ui",
		"./meshui",
		"./mcp-mesh-ui",
		"./build/meshui",
		"./build/mcp-mesh-ui",
	}

	if path := findBinary(localPaths, "meshui", "mcp-mesh-ui"); path != "" {
		return path, nil
	}

	return "", fmt.Errorf("UI server binary not found. Run 'make build' to compile it")
}

// waitForRegistryReady waits for the registry to be ready to accept connections
func (pm *ProcessManager) waitForRegistryReady(timeout time.Duration) error {
	registryURL := pm.config.GetRegistryURL()
	if registryURL == "" {
		registryURL = fmt.Sprintf("http://localhost:%d", defaultRegistryPort)
	}

	if err := waitForHTTPReady(newTLSSkipVerifyClient(), registryURL+"/health", timeout); err != nil {
		return fmt.Errorf("registry did not become ready within timeout")
	}
	return nil
}
