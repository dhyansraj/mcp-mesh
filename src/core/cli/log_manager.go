package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

const (
	// MaxLogFiles is the number of log files to keep per agent
	MaxLogFiles = 5
)

// LogManager handles log file operations for agents
type LogManager struct {
	logsDir string
}

// NewLogManager creates a new log manager with the default logs directory
func NewLogManager() (*LogManager, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, fmt.Errorf("failed to get home directory: %w", err)
	}

	logsDir := filepath.Join(homeDir, ".mcp-mesh", "logs")

	// Ensure logs directory exists
	if err := os.MkdirAll(logsDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create logs directory: %w", err)
	}

	return &LogManager{logsDir: logsDir}, nil
}

// GetLogsDir returns the logs directory path
func (lm *LogManager) GetLogsDir() string {
	return lm.logsDir
}

// GetLogFile returns the path to the current log file for a given agent
func (lm *LogManager) GetLogFile(agentName string) string {
	safeName := sanitizeLogName(agentName)
	return filepath.Join(lm.logsDir, safeName+".log")
}

// GetPreviousLogFile returns the path to a previous log file
// generation 1 = most recent previous, 2 = 2 restarts ago, etc.
func (lm *LogManager) GetPreviousLogFile(agentName string, generation int) string {
	if generation < 1 || generation > MaxLogFiles-1 {
		return ""
	}
	safeName := sanitizeLogName(agentName)
	return filepath.Join(lm.logsDir, fmt.Sprintf("%s.%d.log", safeName, generation))
}

// RotateLogs rotates log files for an agent before starting
// Keeps up to MaxLogFiles logs per agent
func (lm *LogManager) RotateLogs(agentName string) error {
	safeName := sanitizeLogName(agentName)

	// Delete oldest log if it exists
	oldestLog := filepath.Join(lm.logsDir, fmt.Sprintf("%s.%d.log", safeName, MaxLogFiles-1))
	if err := os.Remove(oldestLog); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove oldest log: %w", err)
	}

	// Rotate existing logs: .3.log -> .4.log, .2.log -> .3.log, etc.
	for i := MaxLogFiles - 2; i >= 1; i-- {
		oldPath := filepath.Join(lm.logsDir, fmt.Sprintf("%s.%d.log", safeName, i))
		newPath := filepath.Join(lm.logsDir, fmt.Sprintf("%s.%d.log", safeName, i+1))
		if _, err := os.Stat(oldPath); err == nil {
			if err := os.Rename(oldPath, newPath); err != nil {
				return fmt.Errorf("failed to rotate log %s: %w", oldPath, err)
			}
		}
	}

	// Rotate current log to .1.log
	currentLog := lm.GetLogFile(agentName)
	if _, err := os.Stat(currentLog); err == nil {
		firstPrevLog := filepath.Join(lm.logsDir, fmt.Sprintf("%s.1.log", safeName))
		if err := os.Rename(currentLog, firstPrevLog); err != nil {
			return fmt.Errorf("failed to rotate current log: %w", err)
		}
	}

	return nil
}

// CreateLogFile creates a new log file for writing and returns the file handle
func (lm *LogManager) CreateLogFile(agentName string) (*os.File, error) {
	logPath := lm.GetLogFile(agentName)
	file, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to create log file %s: %w", logPath, err)
	}
	return file, nil
}

// OpenLogFile opens an existing log file for reading
func (lm *LogManager) OpenLogFile(agentName string, generation int) (*os.File, error) {
	var logPath string
	if generation == 0 {
		logPath = lm.GetLogFile(agentName)
	} else {
		logPath = lm.GetPreviousLogFile(agentName, generation)
	}

	if logPath == "" {
		return nil, fmt.Errorf("invalid log generation: %d", generation)
	}

	file, err := os.Open(logPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("log file not found for agent '%s'", agentName)
		}
		return nil, fmt.Errorf("failed to open log file: %w", err)
	}
	return file, nil
}

// ListAgentLogs returns a list of agents that have log files
func (lm *LogManager) ListAgentLogs() ([]string, error) {
	entries, err := os.ReadDir(lm.logsDir)
	if err != nil {
		if os.IsNotExist(err) {
			return []string{}, nil
		}
		return nil, fmt.Errorf("failed to read logs directory: %w", err)
	}

	agentSet := make(map[string]bool)
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".log") {
			continue
		}

		name := entry.Name()
		// Remove .log suffix
		name = strings.TrimSuffix(name, ".log")
		// Remove .N suffix if present (e.g., agent.1, agent.2)
		if idx := strings.LastIndex(name, "."); idx != -1 {
			if _, err := strconv.Atoi(name[idx+1:]); err == nil {
				name = name[:idx]
			}
		}
		agentSet[name] = true
	}

	var agents []string
	for agent := range agentSet {
		agents = append(agents, agent)
	}
	return agents, nil
}

// GetLogInfo returns information about available logs for an agent
type LogInfo struct {
	AgentName   string
	CurrentLog  string
	CurrentSize int64
	HasCurrent  bool
	PreviousLogs []struct {
		Generation int
		Path       string
		Size       int64
	}
}

func (lm *LogManager) GetLogInfo(agentName string) (*LogInfo, error) {
	info := &LogInfo{
		AgentName: agentName,
	}

	// Check current log
	currentPath := lm.GetLogFile(agentName)
	if stat, err := os.Stat(currentPath); err == nil {
		info.HasCurrent = true
		info.CurrentLog = currentPath
		info.CurrentSize = stat.Size()
	}

	// Check previous logs
	for i := 1; i < MaxLogFiles; i++ {
		prevPath := lm.GetPreviousLogFile(agentName, i)
		if stat, err := os.Stat(prevPath); err == nil {
			info.PreviousLogs = append(info.PreviousLogs, struct {
				Generation int
				Path       string
				Size       int64
			}{
				Generation: i,
				Path:       prevPath,
				Size:       stat.Size(),
			})
		}
	}

	if !info.HasCurrent && len(info.PreviousLogs) == 0 {
		return nil, fmt.Errorf("no logs found for agent '%s'", agentName)
	}

	return info, nil
}

// CleanAgentLogs removes all log files for an agent
func (lm *LogManager) CleanAgentLogs(agentName string) error {
	safeName := sanitizeLogName(agentName)

	// Remove current log
	currentLog := lm.GetLogFile(agentName)
	if err := os.Remove(currentLog); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove current log: %w", err)
	}

	// Remove previous logs
	for i := 1; i < MaxLogFiles; i++ {
		prevLog := filepath.Join(lm.logsDir, fmt.Sprintf("%s.%d.log", safeName, i))
		if err := os.Remove(prevLog); err != nil && !os.IsNotExist(err) {
			return fmt.Errorf("failed to remove log %s: %w", prevLog, err)
		}
	}

	return nil
}

// sanitizeLogName converts an agent name to a filesystem-safe log name
func sanitizeLogName(name string) string {
	// Remove path components, keep only the base name
	name = filepath.Base(name)

	// Remove .py extension if present
	name = strings.TrimSuffix(name, ".py")

	// Replace any problematic characters
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
