package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
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

// RestartProcess restarts a managed process with optional new configuration
func (pm *ProcessManager) RestartProcess(name string, newCommand string, newMetadata map[string]interface{}, timeout time.Duration) (*ProcessInfo, error) {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	info, exists := pm.processes[name]
	if !exists {
		return nil, fmt.Errorf("process %s not found", name)
	}

	pm.logger.Printf("Restarting process: %s", name)

	// Update command and metadata if provided
	if newCommand != "" {
		info.Command = newCommand
	}
	if newMetadata != nil {
		info.Metadata = newMetadata
	}

	// Stop existing process if running
	if info.Process != nil && pm.isProcessRunning(info) {
		if err := pm.terminateAndWait(info, name, os.Interrupt, timeout); err != nil {
			pm.logger.Printf("Process %s timeout during restart, forcing kill", name)
			if killErr := info.Process.Kill(); killErr != nil {
				return nil, fmt.Errorf("failed to kill process %s during restart: %w", name, killErr)
			}
		} else {
			pm.logger.Printf("Process %s stopped gracefully for restart", name)
		}
	}

	// Start new process
	if err := pm.startProcessInternal(name, info); err != nil {
		return nil, fmt.Errorf("failed to restart process %s: %w", name, err)
	}

	// Update restart tracking
	info.Restarts++
	info.LastRestart = time.Now()
	info.ConsecutiveFails = 0

	pm.saveState()
	pm.logger.Printf("Process %s restarted successfully (PID: %d, Total restarts: %d)", name, info.PID, info.Restarts)

	return info, nil
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

// StartAgentProcess starts a new agent process
func (pm *ProcessManager) StartAgentProcess(agentFile string, metadata map[string]interface{}) (*ProcessInfo, error) {
	// Validate agent file exists
	if _, err := os.Stat(agentFile); err != nil {
		return nil, fmt.Errorf("agent file %s does not exist: %w", agentFile, err)
	}

	// Generate process name from file
	name := pm.generateProcessName(agentFile)

	// Check if process already exists
	if _, exists := pm.GetProcess(name); exists {
		return nil, fmt.Errorf("process %s already exists", name)
	}

	// Ensure registry is running
	if err := pm.ensureRegistryRunning(); err != nil {
		pm.logger.Printf("Warning: Could not ensure registry is running: %v", err)
	}

	// Start the process
	cmd := exec.Command("python", agentFile)

	// Set working directory
	workingDir, _ := os.Getwd()
	cmd.Dir = workingDir

	// Set environment variables
	env := os.Environ()

	// Add registry environment variables
	if pm.config.GetRegistryURL() != "" {
		env = append(env, "MCP_MESH_REGISTRY_URL="+pm.config.GetRegistryURL())
	}
	if pm.config.RegistryHost != "" {
		env = append(env, "MCP_MESH_REGISTRY_HOST="+pm.config.RegistryHost)
	}
	if pm.config.RegistryPort > 0 {
		env = append(env, fmt.Sprintf("MCP_MESH_REGISTRY_PORT=%d", pm.config.RegistryPort))
	}
	if pm.config.DBPath != "" {
		env = append(env, "MCP_MESH_DB_PATH="+pm.config.DBPath)
	}

	cmd.Env = env
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("failed to start agent process: %w", err)
	}

	// Track the process
	if metadata == nil {
		metadata = make(map[string]interface{})
	}
	metadata["agent_file"] = agentFile

	processInfo := pm.TrackProcess(name, agentFile, "agent", cmd.Process, metadata)

	pm.logger.Printf("Started agent process: %s (PID: %d)", name, cmd.Process.Pid)

	return processInfo, nil
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
			port = 8080
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

	args := []string{
		"-port", fmt.Sprintf("%d", port),
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
	if err := pm.waitForRegistryReady(10 * time.Second); err != nil {
		pm.logger.Printf("Warning: Registry may not be fully ready: %v", err)
	}

	return processInfo, nil
}

// StopAllProcesses stops all managed processes
func (pm *ProcessManager) StopAllProcesses(timeout time.Duration) []error {
	processes := pm.GetAllProcesses()
	var errors []error

	pm.logger.Printf("Stopping all %d processes", len(processes))

	// Stop agents first
	for name, info := range processes {
		if info.ServiceType == "agent" {
			if err := pm.StopProcess(name, timeout); err != nil {
				errors = append(errors, fmt.Errorf("failed to stop agent %s: %w", name, err))
			}
		}
	}

	// Stop UI server before registry (UI depends on registry)
	for name, info := range processes {
		if info.ServiceType == "ui" {
			if err := pm.StopProcess(name, timeout); err != nil {
				errors = append(errors, fmt.Errorf("failed to stop UI server %s: %w", name, err))
			}
		}
	}

	// Stop registry last
	for name, info := range processes {
		if info.ServiceType == "registry" {
			if err := pm.StopProcess(name, timeout); err != nil {
				errors = append(errors, fmt.Errorf("failed to stop registry %s: %w", name, err))
			}
		}
	}

	pm.logger.Printf("Stopped all processes (errors: %d)", len(errors))
	return errors
}

// GetProcessStatus returns detailed status for a process
func (pm *ProcessManager) GetProcessStatus(name string) (map[string]interface{}, error) {
	info, exists := pm.GetProcess(name)
	if !exists {
		return nil, fmt.Errorf("process %s not found", name)
	}

	status := map[string]interface{}{
		"name":              info.Name,
		"pid":               info.PID,
		"status":            info.Status,
		"health_check":      info.HealthCheck,
		"service_type":      info.ServiceType,
		"start_time":        info.StartTime,
		"last_seen":         info.LastSeen,
		"uptime":            time.Since(info.StartTime).Truncate(time.Second),
		"restarts":          info.Restarts,
		"consecutive_fails": info.ConsecutiveFails,
		"command":           info.Command,
		"working_dir":       info.WorkingDir,
		"registry_url":      info.RegistryURL,
		"metadata":          info.Metadata,
	}

	// Add registry-specific information for agents
	if info.ServiceType == "agent" {
		registryStatus := pm.checkAgentRegistryStatus(name)
		status["registry_status"] = registryStatus
	}

	return status, nil
}

// startProcessInternal handles internal process starting logic
func (pm *ProcessManager) startProcessInternal(name string, info *ProcessInfo) error {
	var cmd *exec.Cmd

	if info.ServiceType == "registry" {
		// Find registry binary
		registryBinary, err := pm.findRegistryBinary()
		if err != nil {
			return err
		}

		port := 8080
		if portVal, ok := info.Metadata["port"].(int); ok {
			port = portVal
		}

		args := []string{"-port", fmt.Sprintf("%d", port)}
		// Database path is passed via environment variable, not as an argument

		cmd = exec.Command(registryBinary, args...)
	} else {
		// Start agent process
		cmd = exec.Command("python", info.Command)
	}

	cmd.Dir = info.WorkingDir

	// Set environment variables
	env := os.Environ()
	for key, value := range info.Environment {
		env = append(env, fmt.Sprintf("%s=%s", key, value))
	}
	cmd.Env = env

	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return err
	}

	// Update process info
	info.Process = cmd.Process
	info.PID = cmd.Process.Pid
	info.StartTime = time.Now()
	info.Status = "running"
	info.LastSeen = time.Now()

	return nil
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

	for _, path := range localPaths {
		if _, err := os.Stat(path); err == nil {
			return path, nil
		}
	}

	// If not found locally, check PATH
	if path, err := exec.LookPath("mcp-mesh-registry"); err == nil {
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
			port = 3080
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
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("failed to start UI server process: %w", err)
	}

	metadata := map[string]interface{}{
		"port":         port,
		"registry_url": registryURL,
	}

	processInfo := pm.TrackProcess(name, uiBinary, "ui", cmd.Process, metadata)

	pm.logger.Printf("Started UI server: %s (PID: %d, Port: %d)", name, cmd.Process.Pid, port)

	// Wait for UI to be ready
	if err := pm.waitForUIReady(port, 5*time.Second); err != nil {
		pm.logger.Printf("Warning: UI server may not be fully ready: %v", err)
	}

	return processInfo, nil
}

// waitForUIReady waits for the UI server to respond to health checks
func (pm *ProcessManager) waitForUIReady(port int, timeout time.Duration) error {
	healthURL := fmt.Sprintf("http://localhost:%d/api/ui-health", port)
	client := newTLSSkipVerifyClient()
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		resp, err := client.Get(healthURL)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				return nil
			}
		}
		time.Sleep(250 * time.Millisecond)
	}

	return fmt.Errorf("UI server did not become ready within timeout")
}

// findUIBinary finds the UI server binary in local paths or PATH
func (pm *ProcessManager) findUIBinary() (string, error) {
	localPaths := []string{
		"./bin/mcp-mesh-ui",
		"./mcp-mesh-ui",
		"./build/mcp-mesh-ui",
		"cmd/mcp-mesh-ui/mcp-mesh-ui",
	}

	for _, path := range localPaths {
		if _, err := os.Stat(path); err == nil {
			return path, nil
		}
	}

	if path, err := exec.LookPath("mcp-mesh-ui"); err == nil {
		return path, nil
	}

	allPaths := append(localPaths, "mcp-mesh-ui (in PATH)")
	return "", fmt.Errorf("UI server binary not found at any of these locations: %v. Please ensure the binary is built or run 'make build' to compile it", allPaths)
}

// generateProcessName generates a unique process name from a file path
func (pm *ProcessManager) generateProcessName(agentFile string) string {
	base := strings.TrimSuffix(agentFile, ".py")
	base = strings.ReplaceAll(base, "/", "_")
	base = strings.ReplaceAll(base, "\\", "_")
	base = strings.ReplaceAll(base, ".", "_")

	// Ensure uniqueness
	counter := 1
	name := base
	for {
		if _, exists := pm.processes[name]; !exists {
			break
		}
		name = fmt.Sprintf("%s_%d", base, counter)
		counter++
	}

	return name
}

// ensureRegistryRunning ensures the registry is running
func (pm *ProcessManager) ensureRegistryRunning() error {
	// Check if registry is already running
	if info, exists := pm.GetProcess("registry"); exists && pm.isProcessRunning(info) {
		return nil
	}

	// Start registry
	_, err := pm.StartRegistryProcess(0, "", nil)
	return err
}

// waitForRegistryReady waits for the registry to be ready to accept connections
func (pm *ProcessManager) waitForRegistryReady(timeout time.Duration) error {
	registryURL := pm.config.GetRegistryURL()
	if registryURL == "" {
		registryURL = "http://localhost:8080"
	}

	client := newTLSSkipVerifyClient()
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		resp, err := client.Get(registryURL + "/health")
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				return nil
			}
		}

		time.Sleep(250 * time.Millisecond) // More frequent checks for FastAPI registry startup
	}

	return fmt.Errorf("registry did not become ready within timeout")
}

// checkAgentRegistryStatus checks the registry status for an agent
func (pm *ProcessManager) checkAgentRegistryStatus(agentName string) map[string]interface{} {
	registryURL := pm.config.GetRegistryURL()
	if registryURL == "" {
		registryURL = "http://localhost:8080"
	}

	status := map[string]interface{}{
		"connected":      false,
		"registered":     false,
		"last_heartbeat": nil,
	}

	client := newTLSSkipVerifyClient()
	resp, err := client.Get(registryURL + "/agents")
	if err != nil {
		status["error"] = err.Error()
		return status
	}
	defer resp.Body.Close()

	var result struct {
		Agents []struct {
			Name          string    `json:"name"`
			Status        string    `json:"status"`
			LastHeartbeat time.Time `json:"last_heartbeat"`
		} `json:"agents"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		status["error"] = err.Error()
		return status
	}

	status["connected"] = true

	// Find the agent in the registry
	for _, agent := range result.Agents {
		if agent.Name == agentName {
			status["registered"] = true
			status["registry_status"] = agent.Status
			status["last_heartbeat"] = agent.LastHeartbeat
			break
		}
	}

	return status
}
