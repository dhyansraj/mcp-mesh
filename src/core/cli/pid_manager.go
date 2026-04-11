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
	Name      string
	PID       int
	PIDFile   string
	Running   bool
	Type      string // "agent", "registry", "ui", "watcher-parent"
	ParentPID int    // 0 for flat/non-watch entries; otherwise the watcher parent meshctl PID that owns this entry
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

// newPIDManagerWithDir creates a PIDManager rooted at a specific directory.
// Used primarily for testing to avoid touching ~/.mcp-mesh/pids.
func newPIDManagerWithDir(pidsDir string) (*PIDManager, error) {
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

// GetWatchAgentPIDFile returns <name>.<parentPID>.pid
func (pm *PIDManager) GetWatchAgentPIDFile(name string, parentPID int) string {
	safeName := sanitizeName(name)
	return filepath.Join(pm.pidsDir, fmt.Sprintf("%s.%d.pid", safeName, parentPID))
}

// GetWatchParentPIDFile returns <name>.<parentPID>.watcher-parent.pid
func (pm *PIDManager) GetWatchParentPIDFile(name string, parentPID int) string {
	safeName := sanitizeName(name)
	return filepath.Join(pm.pidsDir, fmt.Sprintf("%s.%d.watcher-parent.pid", safeName, parentPID))
}

// WriteWatchAgentPID writes the agent process PID to <name>.<parentPID>.pid
func (pm *PIDManager) WriteWatchAgentPID(name string, parentPID int, agentPID int) error {
	pidFile := pm.GetWatchAgentPIDFile(name, parentPID)
	if err := os.WriteFile(pidFile, []byte(fmt.Sprintf("%d", agentPID)), 0644); err != nil {
		return fmt.Errorf("failed to write watch agent PID file %s: %w", pidFile, err)
	}
	return nil
}

// WriteWatchParentPID writes the parent meshctl PID to <name>.<parentPID>.watcher-parent.pid
func (pm *PIDManager) WriteWatchParentPID(name string, parentPID int) error {
	pidFile := pm.GetWatchParentPIDFile(name, parentPID)
	if err := os.WriteFile(pidFile, []byte(fmt.Sprintf("%d", parentPID)), 0644); err != nil {
		return fmt.Errorf("failed to write watch parent PID file %s: %w", pidFile, err)
	}
	return nil
}

// RemoveWatchAgentPID removes <name>.<parentPID>.pid
func (pm *PIDManager) RemoveWatchAgentPID(name string, parentPID int) error {
	return pm.RemovePIDFile(pm.GetWatchAgentPIDFile(name, parentPID))
}

// RemoveWatchParentPID removes <name>.<parentPID>.watcher-parent.pid
func (pm *PIDManager) RemoveWatchParentPID(name string, parentPID int) error {
	return pm.RemovePIDFile(pm.GetWatchParentPIDFile(name, parentPID))
}

// FindWatchAgentsByName returns all watch-mode agent entries for a given name
// (one per distinct parent_pid). Returns only entries whose agent process is alive.
//
// The lookup name is normalized via sanitizeName before comparison, matching the
// normalization applied by the write path (GetWatchAgentPIDFile). This means
// callers can pass the original unsanitized agent name (e.g., "my agent") and
// it will match the on-disk sanitized form ("my_agent"). Passing an already
// sanitized name also works, because sanitizeName is idempotent for names that
// only contain characters it allows.
func (pm *PIDManager) FindWatchAgentsByName(name string) ([]PIDInfo, error) {
	all, err := pm.ListRunningProcesses()
	if err != nil {
		return nil, err
	}
	sanitized := sanitizeName(name)
	var matches []PIDInfo
	for _, p := range all {
		if p.Type == "agent" && p.Name == sanitized && p.ParentPID > 0 && p.Running {
			matches = append(matches, p)
		}
	}
	return matches, nil
}

// FindWatchAgentsByParent returns all watch-mode agent entries under a given parent meshctl PID.
// Returns only entries whose agent process is alive.
//
// parentPID must be > 0. Passing 0 or negative returns nil (no matches) — the
// method's semantic is "agents under a watch-mode parent", and parent 0 is
// not a valid watch-mode parent (flat entries also have ParentPID == 0, and
// they are not watch-mode agents).
func (pm *PIDManager) FindWatchAgentsByParent(parentPID int) ([]PIDInfo, error) {
	if parentPID <= 0 {
		return nil, nil
	}
	all, err := pm.ListRunningProcesses()
	if err != nil {
		return nil, err
	}
	var matches []PIDInfo
	for _, p := range all {
		if p.Type == "agent" && p.ParentPID == parentPID && p.Running {
			matches = append(matches, p)
		}
	}
	return matches, nil
}

// FindWatchParentsByPID returns all watcher-parent tracking entries whose
// parent meshctl PID matches. Unlike FindWatchAgentsByParent, this returns
// tracking file metadata regardless of whether the parent process itself
// is still alive — used by stop to clean up stale tracking files when the
// parent has already exited.
//
// parentPID must be > 0; passing 0 or negative returns nil.
func (pm *PIDManager) FindWatchParentsByPID(parentPID int) ([]PIDInfo, error) {
	if parentPID <= 0 {
		return nil, nil
	}
	all, err := pm.ListRunningProcesses()
	if err != nil {
		return nil, err
	}
	var matches []PIDInfo
	for _, p := range all {
		if p.Type == "watcher-parent" && p.ParentPID == parentPID {
			matches = append(matches, p)
		}
	}
	return matches, nil
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

// ListRunningProcesses returns all running processes tracked by PID files.
//
// Supported filename layouts (base = filename without the ".pid" suffix):
//  1. Flat/legacy: "<name>"                        -> Type=agent|registry|ui, ParentPID=0
//  2. Watch-mode agent: "<name>.<parent_pid>"      -> Type=agent, ParentPID=<parent_pid>
//  3. Watch-mode parent: "<name>.<parent_pid>.watcher-parent" -> Type=watcher-parent, ParentPID=<parent_pid>
//
// Note: older meshctl versions wrote watcher-parent files as "<name>_watcher-parent.pid".
// Those files won't match any of the cases above and will be silently ignored by this
// parser. Use `meshctl stop --clean` or delete them by hand after upgrading.
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

		base := strings.TrimSuffix(entry.Name(), ".pid")

		// Skip empty base (filename was just ".pid").
		if base == "" {
			continue
		}

		// Legacy watcher-parent format: "<name>_watcher-parent.pid" (underscore separator).
		// Pre-namespacing versions of meshctl wrote these; they're unparseable in the
		// current scheme and would otherwise be mis-parsed as flat agents. Skip them.
		// Users can clean them up with `meshctl stop --clean`.
		if strings.HasSuffix(base, "_watcher-parent") {
			continue
		}

		pidFile := filepath.Join(pm.pidsDir, entry.Name())

		pid, err := pm.ReadPIDFromFile(pidFile)
		if err != nil {
			continue
		}

		var (
			name      string
			parentPID int
			procType  string
		)

		// Case 1: watcher-parent file — <name>.<parent_pid>.watcher-parent
		if strings.HasSuffix(base, ".watcher-parent") {
			rest := strings.TrimSuffix(base, ".watcher-parent")
			idx := strings.LastIndex(rest, ".")
			if idx <= 0 {
				// Malformed — skip
				continue
			}
			parsedPID, perr := strconv.Atoi(rest[idx+1:])
			if perr != nil || parsedPID <= 0 {
				continue
			}
			name = rest[:idx]
			parentPID = parsedPID
			procType = "watcher-parent"
		} else {
			// Case 2 or 3: has a trailing .<parent_pid> (watch-mode agent) or not (flat/legacy).
			//
			// Invariant: sanitizeName strips dots from legitimate agent names, so any
			// dot in the base must come from one of the documented <name>.<parent_pid>
			// or <name>.<parent_pid>.watcher-parent patterns. If a dot is present but
			// the trailing segment isn't a positive integer parent PID, the file was
			// not written by a current meshctl version — skip rather than fall back to
			// flat, because "flat fallback with a dotted name" would yield a name that
			// no other code path can ever re-derive (sanitizeName would never produce
			// it), leaving a permanent stale entry.
			idx := strings.LastIndex(base, ".")
			if idx > 0 {
				parsedPID, perr := strconv.Atoi(base[idx+1:])
				if perr != nil || parsedPID <= 0 {
					// Dotted but unparseable — skip.
					continue
				}
				name = base[:idx]
				parentPID = parsedPID
				procType = "agent"
			} else {
				// No dot: flat — <name>.pid
				name = base
				parentPID = 0
				switch name {
				case "registry":
					procType = "registry"
				case "ui":
					procType = "ui"
				default:
					procType = "agent"
				}
			}
		}

		processes = append(processes, PIDInfo{
			Name:      name,
			PID:       pid,
			PIDFile:   pidFile,
			Running:   IsProcessAlive(pid),
			Type:      procType,
			ParentPID: parentPID,
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

// GetRegistry returns the registry process info if running.
//
// Matches on BOTH Name=="registry" and Type=="registry" to avoid confusing a
// watch-mode agent named "registry" (e.g. "registry.12345.pid") with the real
// flat registry.pid. Under the current parser, only the flat "registry.pid"
// file produces Type="registry"; any dotted "registry.<ppid>.pid" file is
// parsed as Type="agent".
func (pm *PIDManager) GetRegistry() (*PIDInfo, error) {
	processes, err := pm.ListRunningProcesses()
	if err != nil {
		return nil, err
	}

	for _, proc := range processes {
		if proc.Name == "registry" && proc.Type == "registry" && proc.Running {
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
