package cli

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"
)

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

	// Use platform-specific graceful process group termination
	platformManager := NewPlatformProcessManager()
	if err := platformManager.terminateProcessGroup(info.PID, timeout); err != nil {
		pm.logger.Printf("Process group termination failed for %s, falling back to single process signal: %v", name, err)
		// Fallback to signaling just the main process
		if err := info.Process.Signal(os.Interrupt); err != nil {
			return fmt.Errorf("failed to send SIGTERM to process %s: %w", name, err)
		}
	}

	// Wait for graceful shutdown
	done := make(chan error, 1)
	go func() {
		_, err := info.Process.Wait()
		done <- err
	}()

	select {
	case err := <-done:
		info.Status = "stopped"
		info.HealthCheck = "stopped"
		pm.logger.Printf("Process %s stopped gracefully", name)
		pm.saveState()
		return err
	case <-time.After(timeout):
		// Force kill if timeout exceeded
		pm.logger.Printf("Process %s timeout, forcing kill", name)
		if err := info.Process.Kill(); err != nil {
			return fmt.Errorf("failed to kill process %s: %w", name, err)
		}
		info.Status = "killed"
		info.HealthCheck = "killed"
		pm.saveState()
		return nil
	}
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
		if err := info.Process.Signal(os.Interrupt); err == nil {
			// Wait for graceful shutdown with timeout
			done := make(chan bool, 1)
			go func() {
				info.Process.Wait()
				done <- true
			}()

			select {
			case <-done:
				pm.logger.Printf("Process %s stopped gracefully for restart", name)
			case <-time.After(timeout):
				pm.logger.Printf("Process %s timeout during restart, forcing kill", name)
				info.Process.Kill()
			}
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

	// Use platform-specific process group termination
	platformManager := NewPlatformProcessManager()
	if err := platformManager.terminateProcessGroup(info.PID, timeout); err != nil {
		pm.logger.Printf("Process group termination failed for %s, falling back to single process kill: %v", name, err)
		// Fallback to killing just the main process
		if err := info.Process.Kill(); err != nil {
			return fmt.Errorf("failed to kill process %s: %w", name, err)
		}
	}

	// Wait for process to die
	done := make(chan error, 1)
	go func() {
		_, err := info.Process.Wait()
		done <- err
	}()

	select {
	case err := <-done:
		info.Status = "killed"
		info.HealthCheck = "killed"
		pm.logger.Printf("Process %s terminated", name)
		pm.saveState()
		return err
	case <-time.After(timeout):
		return fmt.Errorf("process %s did not terminate within timeout", name)
	}
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

	// Stop agents first, then registry
	for name, info := range processes {
		if info.ServiceType == "agent" {
			if err := pm.StopProcess(name, timeout); err != nil {
				errors = append(errors, fmt.Errorf("failed to stop agent %s: %w", name, err))
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

	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		resp, err := http.Get(registryURL + "/health")
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

	resp, err := http.Get(registryURL + "/agents")
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
