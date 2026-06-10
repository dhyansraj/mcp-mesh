package cli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

// ProcessInfo represents detailed information about a managed process
type ProcessInfo struct {
	PID              int                    `json:"pid"`
	Name             string                 `json:"name"`
	Command          string                 `json:"command"`
	StartTime        time.Time              `json:"start_time"`
	Status           string                 `json:"status"`
	HealthCheck      string                 `json:"health_check"`
	LastSeen         time.Time              `json:"last_seen"`
	Restarts         int                    `json:"restarts"`
	ServiceType      string                 `json:"service_type"`
	Type             string                 `json:"type"` // Alias for ServiceType for backward compatibility
	WorkingDir       string                 `json:"working_dir"`
	RegistryURL      string                 `json:"registry_url"`
	Environment      map[string]string      `json:"environment"`
	Metadata         map[string]interface{} `json:"metadata"`
	ConsecutiveFails int                    `json:"consecutive_fails"`
	LastRestart      time.Time              `json:"last_restart"`
	FilePath         string                 `json:"file_path,omitempty"` // Added for backward compatibility
	Process          *os.Process            `json:"-"`
}

// ProcessState represents the persistent state of all processes
type ProcessState struct {
	Processes     map[string]*ProcessInfo `json:"processes"`
	LastUpdated   time.Time               `json:"last_updated"`
	RegistryState *RegistryState          `json:"registry_state"`
	ConfigVersion int                     `json:"config_version"`
}

// RegistryState tracks registry connection information
type RegistryState struct {
	Running     bool              `json:"running"`
	URL         string            `json:"url"`
	Port        int               `json:"port"`
	DBPath      string            `json:"db_path"`
	Environment map[string]string `json:"environment"`
	LastCheck   time.Time         `json:"last_check"`
}

// MonitoringPolicy defines health monitoring configuration
type MonitoringPolicy struct {
	Enabled            bool          `json:"enabled"`
	CheckInterval      time.Duration `json:"check_interval"`
	RestartOnFailure   bool          `json:"restart_on_failure"`
	MaxRestartAttempts int           `json:"max_restart_attempts"`
	RestartCooldown    time.Duration `json:"restart_cooldown"`
}

// ProcessManager handles lifecycle management of MCP Mesh processes
type ProcessManager struct {
	processes        map[string]*ProcessInfo
	mutex            sync.RWMutex
	logger           *CLILogger
	stateFile        string
	monitoringTicker *time.Ticker
	monitorPolicy    *MonitoringPolicy
	shutdownChan     chan struct{}
	config           *CLIConfig
}

// Global process manager instance
var globalProcessManager *ProcessManager
var pmMutex sync.Mutex

// NewProcessManager creates a new process manager instance
func NewProcessManager(config *CLIConfig) *ProcessManager {
	stateFile := filepath.Join(config.StateDir, "processes.json")

	pm := &ProcessManager{
		processes:    make(map[string]*ProcessInfo),
		logger:       NewCLILogger("PROCMGR"),
		stateFile:    stateFile,
		shutdownChan: make(chan struct{}),
		config:       config,
		monitorPolicy: &MonitoringPolicy{
			Enabled:            true,
			CheckInterval:      30 * time.Second,
			RestartOnFailure:   true,
			MaxRestartAttempts: 3,
			RestartCooldown:    5 * time.Minute,
		},
	}

	// Load existing state if available
	if err := pm.loadState(); err != nil {
		pm.logger.Printf("Warning: Could not load process state: %v", err)
	}

	// Clean up dead processes on startup
	pm.cleanupDeadProcesses()

	return pm
}

// GetGlobalProcessManager returns the global process manager instance
func GetGlobalProcessManager() *ProcessManager {
	pmMutex.Lock()
	defer pmMutex.Unlock()

	if globalProcessManager == nil {
		config := GetCLIConfig()
		globalProcessManager = NewProcessManager(config)
	}

	return globalProcessManager
}

// TrackProcess registers a new process for management
func (pm *ProcessManager) TrackProcess(name, command, serviceType string, process *os.Process, metadata map[string]interface{}) *ProcessInfo {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	workingDir, _ := os.Getwd()

	processInfo := &ProcessInfo{
		PID:              process.Pid,
		Name:             name,
		Command:          command,
		StartTime:        time.Now(),
		Status:           "running",
		HealthCheck:      "unknown",
		LastSeen:         time.Now(),
		Restarts:         0,
		ServiceType:      serviceType,
		Type:             serviceType, // Set alias for backward compatibility
		WorkingDir:       workingDir,
		RegistryURL:      pm.config.GetRegistryURL(),
		Environment:      make(map[string]string),
		Metadata:         metadata,
		ConsecutiveFails: 0,
		LastRestart:      time.Time{},
		FilePath:         command, // Set filepath for agents
		Process:          process,
	}

	// Copy relevant environment variables
	for _, env := range os.Environ() {
		if strings.HasPrefix(env, "MCP_MESH_") {
			parts := strings.SplitN(env, "=", 2)
			if len(parts) == 2 {
				processInfo.Environment[parts[0]] = parts[1]
			}
		}
	}

	pm.processes[name] = processInfo

	// Save state immediately
	if err := pm.saveState(); err != nil {
		pm.logger.Printf("Warning: Could not save process state: %v", err)
	}

	pm.logger.Printf("Tracked process: %s (PID: %d, Type: %s)", name, process.Pid, serviceType)
	return processInfo
}

// UntrackProcess removes a process from management
func (pm *ProcessManager) UntrackProcess(name string) bool {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	if _, exists := pm.processes[name]; exists {
		delete(pm.processes, name)
		pm.saveState()
		pm.logger.Printf("Untracked process: %s", name)
		return true
	}

	return false
}

// clone returns a deep copy of the ProcessInfo so callers can't mutate (or
// race on) the manager's shared state through the returned pointer. The
// Process handle is intentionally shared: *os.Process is safe for concurrent
// Signal/Kill calls and cloning it is not meaningful.
func (info *ProcessInfo) clone() *ProcessInfo {
	c := *info
	if info.Environment != nil {
		c.Environment = make(map[string]string, len(info.Environment))
		for k, v := range info.Environment {
			c.Environment[k] = v
		}
	}
	if info.Metadata != nil {
		c.Metadata = make(map[string]interface{}, len(info.Metadata))
		for k, v := range info.Metadata {
			c.Metadata[k] = v
		}
	}
	return &c
}

// GetProcess returns a deep copy of a managed process's info. The write lock
// is required (not RLock) because updateProcessStatus mutates the shared
// struct (Status/LastSeen/HealthCheck/Process).
func (pm *ProcessManager) GetProcess(name string) (*ProcessInfo, bool) {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	info, exists := pm.processes[name]
	if !exists {
		return nil, false
	}

	// Update process status
	pm.updateProcessStatus(info)

	return info.clone(), true
}

// GetAllProcesses returns deep copies of all managed processes. The write
// lock is required (not RLock) because updateProcessStatus mutates the shared
// structs; the copies mean concurrent callers never alias manager state.
func (pm *ProcessManager) GetAllProcesses() map[string]*ProcessInfo {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	result := make(map[string]*ProcessInfo, len(pm.processes))
	for name, info := range pm.processes {
		pm.updateProcessStatus(info)
		result[name] = info.clone()
	}

	return result
}

// cleanupDeadProcesses removes processes that are no longer running
func (pm *ProcessManager) cleanupDeadProcesses() []string {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	var removed []string

	for name, info := range pm.processes {
		if !pm.isProcessRunning(info) {
			pm.logger.Printf("Cleaning up dead process: %s (PID: %d)", name, info.PID)
			delete(pm.processes, name)
			removed = append(removed, name)
		}
	}

	if len(removed) > 0 {
		pm.saveState()
	}

	return removed
}

// updateProcessStatus updates the status of a process.
// Caller must hold pm.mutex (write lock) — this mutates the shared struct.
func (pm *ProcessManager) updateProcessStatus(info *ProcessInfo) {
	if info.Process == nil {
		// Try to find process by PID if we don't have a handle
		if process, err := os.FindProcess(info.PID); err == nil {
			info.Process = process
		}
	}

	if pm.isProcessRunning(info) {
		info.Status = "running"
		info.LastSeen = time.Now()
	} else {
		info.Status = "stopped"
		info.HealthCheck = "failed"
	}
}

// isProcessRunning checks if a process is still running
func (pm *ProcessManager) isProcessRunning(info *ProcessInfo) bool {
	if info.Process == nil {
		return false
	}

	// Send signal 0 to check if process exists
	if err := info.Process.Signal(syscall.Signal(0)); err != nil {
		return false
	}

	return true
}

// StopHealthMonitoring stops background health monitoring
func (pm *ProcessManager) StopHealthMonitoring() {
	if pm.monitoringTicker != nil {
		pm.monitoringTicker.Stop()
		pm.monitoringTicker = nil
	}

	close(pm.shutdownChan)
	pm.logger.Println("Stopped health monitoring")
}

// saveState persists the current process state to disk
func (pm *ProcessManager) saveState() error {
	state := &ProcessState{
		Processes:     pm.processes,
		LastUpdated:   time.Now(),
		ConfigVersion: 1,
	}

	// Ensure state directory exists
	if err := os.MkdirAll(filepath.Dir(pm.stateFile), 0755); err != nil {
		return fmt.Errorf("failed to create state directory: %w", err)
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	if err := os.WriteFile(pm.stateFile, data, 0644); err != nil {
		return fmt.Errorf("failed to write state file: %w", err)
	}

	return nil
}

// loadState loads process state from disk
func (pm *ProcessManager) loadState() error {
	data, err := os.ReadFile(pm.stateFile)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // No state file exists yet
		}
		return fmt.Errorf("failed to read state file: %w", err)
	}

	var state ProcessState
	if err := json.Unmarshal(data, &state); err != nil {
		return fmt.Errorf("failed to unmarshal state: %w", err)
	}

	pm.processes = state.Processes
	if pm.processes == nil {
		pm.processes = make(map[string]*ProcessInfo)
	}

	// Clear process handles as they're not serializable
	for _, info := range pm.processes {
		info.Process = nil
	}

	pm.logger.Printf("Loaded state for %d processes", len(pm.processes))
	return nil
}
