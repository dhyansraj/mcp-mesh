package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// PIDManager handles PID file operations for detached processes.
//
// As of the lifecycle refactor, PIDManager is a thin compatibility shim
// over <root>/pids/. Authoritative writes go through
// `mcp-mesh/src/core/cli/lifecycle` (WriteAgent, WriteService, etc.) so the
// .group-file + deps-file bookkeeping stays consistent. PIDManager remains
// because:
//   - it owns sanitizeName, which is also used by log file naming
//   - a few callers (e.g. status checks, --clean) need a directory handle
//   - tests reference newPIDManagerWithDir
//
// New code should import the lifecycle package directly. Watch-mode
// per-parent-PID file namespacing has been retired in favor of group-id
// dependency tracking.
type PIDManager struct {
	pidsDir string
}

// NewPIDManager creates a new PID manager with the default pids directory
// (~/.mcp-mesh/pids).
func NewPIDManager() (*PIDManager, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, fmt.Errorf("failed to get home directory: %w", err)
	}

	pidsDir := filepath.Join(homeDir, ".mcp-mesh", "pids")

	if err := os.MkdirAll(pidsDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create pids directory: %w", err)
	}

	return &PIDManager{pidsDir: pidsDir}, nil
}

// newPIDManagerWithDir creates a PIDManager rooted at a specific directory.
// Used primarily for testing.
func newPIDManagerWithDir(pidsDir string) (*PIDManager, error) {
	if err := os.MkdirAll(pidsDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create pids directory: %w", err)
	}
	return &PIDManager{pidsDir: pidsDir}, nil
}

// GetPIDsDir returns the pids directory path.
func (pm *PIDManager) GetPIDsDir() string {
	return pm.pidsDir
}

// GetPIDFile returns the path to the PID file for a given name.
func (pm *PIDManager) GetPIDFile(name string) string {
	return filepath.Join(pm.pidsDir, sanitizeName(name)+".pid")
}

// WritePID writes a PID to the appropriate PID file. Prefer
// lifecycle.WriteAgent / lifecycle.WriteService in new code.
func (pm *PIDManager) WritePID(name string, pid int) error {
	pidFile := pm.GetPIDFile(name)
	if err := os.WriteFile(pidFile, []byte(fmt.Sprintf("%d", pid)), 0644); err != nil {
		return fmt.Errorf("failed to write PID file %s: %w", pidFile, err)
	}
	return nil
}

// ReadPID reads the PID from a PID file for a given name.
func (pm *PIDManager) ReadPID(name string) (int, error) {
	pidFile := pm.GetPIDFile(name)
	return pm.ReadPIDFromFile(pidFile)
}

// ReadPIDFromFile reads the PID from a specific PID file.
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

// RemovePID removes the PID file for a given name.
func (pm *PIDManager) RemovePID(name string) error {
	return pm.RemovePIDFile(pm.GetPIDFile(name))
}

// RemovePIDFile removes a specific PID file.
func (pm *PIDManager) RemovePIDFile(pidFile string) error {
	if err := os.Remove(pidFile); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove PID file %s: %w", pidFile, err)
	}
	return nil
}

// IsProcessRunning checks if a process with the given name is running.
func (pm *PIDManager) IsProcessRunning(name string) bool {
	pid, err := pm.ReadPID(name)
	if err != nil {
		return false
	}
	return IsProcessAlive(pid)
}

// sanitizeName converts a name to a filesystem-safe string. Used by
// PID file naming AND by log file naming, so it stays here even though
// most PID writes now go via lifecycle.
func sanitizeName(name string) string {
	name = filepath.Base(name)
	name = strings.TrimSuffix(name, ".py")

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
