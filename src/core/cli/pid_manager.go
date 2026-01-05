package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// PIDManager handles PID file operations for detached processes
type PIDManager struct {
	pidsDir string
}

// PIDInfo represents information about a tracked process
type PIDInfo struct {
	Name     string
	PID      int
	PIDFile  string
	Running  bool
	Type     string // "agent" or "registry"
}

// NewPIDManager creates a new PID manager with the default pids directory
func NewPIDManager() (*PIDManager, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, fmt.Errorf("failed to get home directory: %w", err)
	}

	pidsDir := filepath.Join(homeDir, ".mcp-mesh", "pids")

	// Ensure pids directory exists
	if err := os.MkdirAll(pidsDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create pids directory: %w", err)
	}

	return &PIDManager{pidsDir: pidsDir}, nil
}

// GetPIDsDir returns the pids directory path
func (pm *PIDManager) GetPIDsDir() string {
	return pm.pidsDir
}

// GetPIDFile returns the path to the PID file for a given name
func (pm *PIDManager) GetPIDFile(name string) string {
	// Sanitize name to be filesystem safe
	safeName := sanitizeName(name)
	return filepath.Join(pm.pidsDir, safeName+".pid")
}

// WritePID writes a PID to the appropriate PID file
func (pm *PIDManager) WritePID(name string, pid int) error {
	pidFile := pm.GetPIDFile(name)
	if err := os.WriteFile(pidFile, []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		return fmt.Errorf("failed to write PID file %s: %w", pidFile, err)
	}
	return nil
}

// ReadPID reads the PID from a PID file for a given name
func (pm *PIDManager) ReadPID(name string) (int, error) {
	pidFile := pm.GetPIDFile(name)
	return pm.ReadPIDFromFile(pidFile)
}

// ReadPIDFromFile reads the PID from a specific PID file
func (pm *PIDManager) ReadPIDFromFile(pidFile string) (int, error) {
	data, err := os.ReadFile(pidFile)
	if err != nil {
		return 0, err
	}

	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return 0, fmt.Errorf("invalid PID in file %s: %w", pidFile, err)
	}

	return pid, nil
}

// RemovePID removes the PID file for a given name
func (pm *PIDManager) RemovePID(name string) error {
	pidFile := pm.GetPIDFile(name)
	return pm.RemovePIDFile(pidFile)
}

// RemovePIDFile removes a specific PID file
func (pm *PIDManager) RemovePIDFile(pidFile string) error {
	if err := os.Remove(pidFile); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove PID file %s: %w", pidFile, err)
	}
	return nil
}

// IsProcessRunning checks if a process with the given name is running
func (pm *PIDManager) IsProcessRunning(name string) bool {
	pid, err := pm.ReadPID(name)
	if err != nil {
		return false
	}
	return IsProcessAlive(pid)
}

// Note: IsProcessAlive is defined in utils.go

// ListRunningProcesses returns all running processes tracked by PID files
func (pm *PIDManager) ListRunningProcesses() ([]PIDInfo, error) {
	entries, err := os.ReadDir(pm.pidsDir)
	if err != nil {
		if os.IsNotExist(err) {
			return []PIDInfo{}, nil
		}
		return nil, fmt.Errorf("failed to read pids directory: %w", err)
	}

	var processes []PIDInfo
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".pid") {
			continue
		}

		name := strings.TrimSuffix(entry.Name(), ".pid")
		pidFile := filepath.Join(pm.pidsDir, entry.Name())

		pid, err := pm.ReadPIDFromFile(pidFile)
		if err != nil {
			continue
		}

		running := IsProcessAlive(pid)
		procType := "agent"
		if name == "registry" {
			procType = "registry"
		}

		processes = append(processes, PIDInfo{
			Name:    name,
			PID:     pid,
			PIDFile: pidFile,
			Running: running,
			Type:    procType,
		})
	}

	return processes, nil
}

// ListAllPIDFiles returns all PID files (including stale ones)
func (pm *PIDManager) ListAllPIDFiles() ([]PIDInfo, error) {
	return pm.ListRunningProcesses() // Same implementation, includes running status
}

// CleanStalePIDFiles removes PID files for processes that are no longer running
func (pm *PIDManager) CleanStalePIDFiles() ([]string, error) {
	processes, err := pm.ListAllPIDFiles()
	if err != nil {
		return nil, err
	}

	var cleaned []string
	for _, proc := range processes {
		if !proc.Running {
			if err := pm.RemovePIDFile(proc.PIDFile); err == nil {
				cleaned = append(cleaned, proc.Name)
			}
		}
	}

	return cleaned, nil
}

// GetRunningAgents returns only running agent processes (excludes registry)
func (pm *PIDManager) GetRunningAgents() ([]PIDInfo, error) {
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		return nil, err
	}

	var agents []PIDInfo
	for _, proc := range processes {
		if proc.Running && proc.Type == "agent" {
			agents = append(agents, proc)
		}
	}

	return agents, nil
}

// GetRegistry returns the registry process info if running
func (pm *PIDManager) GetRegistry() (*PIDInfo, error) {
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		return nil, err
	}

	for _, proc := range processes {
		if proc.Name == "registry" && proc.Running {
			return &proc, nil
		}
	}

	return nil, nil
}

// sanitizeName converts a name to a filesystem-safe string
func sanitizeName(name string) string {
	// Remove path components, keep only the base name
	name = filepath.Base(name)

	// Remove .py extension if present
	name = strings.TrimSuffix(name, ".py")

	// Replace any remaining problematic characters
	name = strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '-' || r == '_' {
			return r
		}
		return '_'
	}, name)

	if name == "" {
		name = "unknown"
	}

	return name
}
