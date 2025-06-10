package cli

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
	"time"
)


// RegistryAgent represents an agent in the registry
type RegistryAgent struct {
	ID           string    `json:"id"`
	Name         string    `json:"name"`
	Status       string    `json:"status"`
	Capabilities []string  `json:"capabilities"`
	LastSeen     time.Time `json:"last_seen"`
	Version      string    `json:"version,omitempty"`
	Description  string    `json:"description,omitempty"`
}

// RegistryResponse represents the response from the registry agents endpoint
type RegistryResponse struct {
	Agents []RegistryAgent `json:"agents"`
	Count  int             `json:"count"`
}

// IsPortAvailable checks if a port is available for use
func IsPortAvailable(host string, port int) bool {
	address := fmt.Sprintf("%s:%d", host, port)
	conn, err := net.DialTimeout("tcp", address, 1*time.Second)
	if err != nil {
		return true // Port is available
	}
	conn.Close()
	return false // Port is in use
}

// WaitForRegistry waits for the registry to become available
func WaitForRegistry(registryURL string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	healthURL := registryURL + "/health"

	for time.Now().Before(deadline) {
		resp, err := http.Get(healthURL)
		if err == nil && resp.StatusCode == http.StatusOK {
			resp.Body.Close()
			return nil
		}
		if resp != nil {
			resp.Body.Close()
		}
		time.Sleep(500 * time.Millisecond)
	}

	return fmt.Errorf("registry did not become available within %v", timeout)
}

// IsRegistryRunning checks if the registry is currently running
func IsRegistryRunning(registryURL string) bool {
	healthURL := registryURL + "/health"
	resp, err := http.Get(healthURL)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// PythonProcessFile represents the Python CLI process file format
type PythonProcessFile struct {
	Processes     map[string]interface{} `json:"processes"`
	RegistryState interface{}            `json:"registry_state"`
	LastUpdated   string                 `json:"last_updated"`
}

// GetRunningProcesses returns information about running MCP Mesh processes
func GetRunningProcesses() ([]ProcessInfo, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}

	processFile := filepath.Join(homeDir, ".mcp_mesh", "processes.json")
	data, err := os.ReadFile(processFile)
	if err != nil {
		if os.IsNotExist(err) {
			return []ProcessInfo{}, nil
		}
		return nil, err
	}

	// Try to parse as Go format first (simple array)
	var processes []ProcessInfo
	if err := json.Unmarshal(data, &processes); err == nil {
		// Filter out dead processes
		var alive []ProcessInfo
		for _, proc := range processes {
			if IsProcessAlive(proc.PID) {
				alive = append(alive, proc)
			}
		}

		// Save the filtered list back
		if len(alive) != len(processes) {
			SaveRunningProcesses(alive)
		}

		return alive, nil
	}

	// Try to parse as Python format (complex structure)
	var pythonFile PythonProcessFile
	if err := json.Unmarshal(data, &pythonFile); err == nil {
		// For now, return empty list when using Python format
		// The Python processes are managed differently and we don't want to interfere
		return []ProcessInfo{}, nil
	}

	// If both formats fail, return empty list
	return []ProcessInfo{}, nil
}

// SaveRunningProcesses saves the list of running processes
func SaveRunningProcesses(processes []ProcessInfo) error {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return err
	}

	mcpDir := filepath.Join(homeDir, ".mcp_mesh")
	if err := os.MkdirAll(mcpDir, 0755); err != nil {
		return err
	}

	processFile := filepath.Join(mcpDir, "processes.json")
	data, err := json.MarshalIndent(processes, "", "  ")
	if err != nil {
		return err
	}

	return os.WriteFile(processFile, data, 0644)
}

// AddRunningProcess adds a process to the running processes list
func AddRunningProcess(proc ProcessInfo) error {
	processes, err := GetRunningProcesses()
	if err != nil {
		return err
	}

	// Remove any existing entry with the same PID
	var filtered []ProcessInfo
	for _, p := range processes {
		if p.PID != proc.PID {
			filtered = append(filtered, p)
		}
	}

	filtered = append(filtered, proc)
	return SaveRunningProcesses(filtered)
}

// RemoveRunningProcess removes a process from the running processes list
func RemoveRunningProcess(pid int) error {
	processes, err := GetRunningProcesses()
	if err != nil {
		return err
	}

	var filtered []ProcessInfo
	for _, p := range processes {
		if p.PID != pid {
			filtered = append(filtered, p)
		}
	}

	return SaveRunningProcesses(filtered)
}

// IsProcessAlive checks if a process is still running
func IsProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}

	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}

	// On Unix-like systems, we can send signal 0 to check if process exists
	err = process.Signal(syscall.Signal(0))
	return err == nil
}

// KillProcess attempts to gracefully kill a process
func KillProcess(pid int, timeout time.Duration) error {
	if !IsProcessAlive(pid) {
		return nil // Already dead
	}

	process, err := os.FindProcess(pid)
	if err != nil {
		return err
	}

	// Try graceful shutdown first (SIGTERM)
	if err := process.Signal(syscall.SIGTERM); err != nil {
		return err
	}

	// Wait for graceful shutdown
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !IsProcessAlive(pid) {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Force kill if graceful shutdown failed
	return process.Signal(syscall.SIGKILL)
}

// StartPythonAgent starts a Python agent process
func StartPythonAgent(agentPath string, config *CLIConfig) (*exec.Cmd, error) {
	// Check if the agent file exists
	if _, err := os.Stat(agentPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("agent file not found: %s", agentPath)
	}

	// Create the command
	cmd := exec.Command("python", agentPath)

	// Set environment variables
	cmd.Env = append(os.Environ(), config.GetEnvironmentVariables()...)

	// Set up stdio
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin

	return cmd, nil
}

// GetRegistryAgents retrieves the list of agents from the registry
func GetRegistryAgents(registryURL string) ([]RegistryAgent, error) {
	agentsURL := registryURL + "/agents"
	resp, err := http.Get(agentsURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to registry: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("registry returned status %d", resp.StatusCode)
	}

	var response RegistryResponse
	if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
		return nil, fmt.Errorf("failed to decode registry response: %w", err)
	}

	return response.Agents, nil
}

// FindAvailablePort finds an available port starting from the given port
func FindAvailablePort(host string, startPort int) (int, error) {
	for port := startPort; port < startPort+100; port++ {
		if IsPortAvailable(host, port) {
			return port, nil
		}
	}
	return 0, fmt.Errorf("no available port found starting from %d", startPort)
}

// AbsolutePath converts a relative path to an absolute path
func AbsolutePath(path string) (string, error) {
	if filepath.IsAbs(path) {
		return path, nil
	}
	return filepath.Abs(path)
}


// ValidateLogLevel checks if a log level is valid
func ValidateLogLevel(level string) bool {
	validLevels := []string{"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
	for _, valid := range validLevels {
		if level == valid {
			return true
		}
	}
	return false
}

// ParsePort parses a port string and validates it
func ParsePort(portStr string) (int, error) {
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return 0, fmt.Errorf("invalid port number: %s", portStr)
	}
	if port < 1 || port > 65535 {
		return 0, fmt.Errorf("port must be between 1 and 65535, got %d", port)
	}
	return port, nil
}
