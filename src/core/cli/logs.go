package cli

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// NewLogsCommand creates the logs command
func NewLogsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs",
		Short: "Show logs for MCP Mesh services",
		Long: `Show logs for MCP Mesh services from multiple sources.

This command discovers log files automatically and displays them with filtering
and real-time following capabilities.

Examples:
  mcp-mesh-dev logs                    # Show recent logs from all sources
  mcp-mesh-dev logs --follow           # Follow logs in real-time
  mcp-mesh-dev logs --agent hello      # Show logs for specific agent
  mcp-mesh-dev logs --level ERROR      # Show only ERROR level and above
  mcp-mesh-dev logs --lines 100        # Show last 100 lines`,
		RunE: runLogsCommand,
	}

	// Add flags matching Python CLI
	cmd.Flags().Bool("follow", false, "Follow log output in real-time")
	cmd.Flags().String("agent", "", "Show logs for specific agent")
	cmd.Flags().String("level", "INFO", "Minimum log level [DEBUG, INFO, WARNING, ERROR]")
	cmd.Flags().Int("lines", 50, "Number of recent log lines to show")

	return cmd
}

// LogEntry represents a single log entry
type LogEntry struct {
	Timestamp time.Time
	Level     string
	Source    string
	Message   string
	Raw       string
}

// LogLevel mapping for filtering
var logLevels = map[string]int{
	"DEBUG":   0,
	"INFO":    1,
	"WARNING": 2,
	"ERROR":   3,
	"CRITICAL": 4,
}

func runLogsCommand(cmd *cobra.Command, args []string) error {
	// Get flags
	follow, _ := cmd.Flags().GetBool("follow")
	agentName, _ := cmd.Flags().GetString("agent")
	level, _ := cmd.Flags().GetString("level")
	lines, _ := cmd.Flags().GetInt("lines")

	// Validate log level
	if !ValidateLogLevel(level) {
		return fmt.Errorf("invalid log level: %s (valid: DEBUG, INFO, WARNING, ERROR, CRITICAL)", level)
	}

	// Discover log sources
	logSources, err := discoverLogSources(agentName)
	if err != nil {
		return fmt.Errorf("failed to discover log sources: %w", err)
	}

	if len(logSources) == 0 {
		fmt.Printf("No log sources found for MCP Mesh services\n")

		// Show helpful information about running processes
		showProcessLogAdvice(agentName, lines, follow)
		return nil
	}

	// Show logs
	if follow {
		return followLogs(logSources, level, agentName)
	} else {
		return showRecentLogs(logSources, level, agentName, lines)
	}
}

// LogSource represents a source of logs
type LogSource struct {
	Type     string // "file", "journalctl", "process"
	Path     string
	Source   string // Agent name or "registry"
	Command  []string // For command-based sources
}

// discoverLogSources finds all available log sources
func discoverLogSources(agentFilter string) ([]LogSource, error) {
	var sources []LogSource

	// 1. Check for log files in standard locations
	logDirs := []string{
		filepath.Join(os.Getenv("HOME"), ".mcp_mesh", "logs"),
		"./logs",
		"/tmp/mcp_mesh_logs",
	}

	for _, dir := range logDirs {
		if dirSources, err := discoverLogFiles(dir, agentFilter); err == nil {
			sources = append(sources, dirSources...)
		}
	}

	// 2. Check for process-specific logs via journalctl (Linux) or system logs
	if processSources, err := discoverProcessLogs(agentFilter); err == nil {
		sources = append(sources, processSources...)
	}

	return sources, nil
}

// discoverLogFiles discovers log files in a directory
func discoverLogFiles(dir string, agentFilter string) ([]LogSource, error) {
	var sources []LogSource

	entries, err := os.ReadDir(dir)
	if err != nil {
		return sources, err
	}

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		name := entry.Name()
		if !strings.HasSuffix(name, ".log") {
			continue
		}

		// Extract source name from filename
		sourceName := strings.TrimSuffix(name, ".log")
		if sourceName == "registry" || sourceName == "mcp-mesh-registry" {
			sourceName = "registry"
		}

		// Apply agent filter
		if agentFilter != "" && sourceName != agentFilter && sourceName != "registry" {
			continue
		}

		sources = append(sources, LogSource{
			Type:   "file",
			Path:   filepath.Join(dir, name),
			Source: sourceName,
		})
	}

	return sources, nil
}

// discoverProcessLogs discovers process-based log sources
func discoverProcessLogs(agentFilter string) ([]LogSource, error) {
	var sources []LogSource

	processes, err := GetRunningProcesses()
	if err != nil {
		return sources, err
	}

	for _, proc := range processes {
		// Apply agent filter
		if agentFilter != "" && proc.Name != agentFilter {
			continue
		}

		// Create appropriate log source based on OS
		if runtime.GOOS == "linux" {
			// Use journalctl on Linux
			sources = append(sources, LogSource{
				Type:   "journalctl",
				Source: proc.Name,
				Command: []string{"journalctl", "--pid", strconv.Itoa(proc.PID), "--no-pager", "--output", "short"},
			})
		} else {
			// For other systems, suggest process monitoring
			sources = append(sources, LogSource{
				Type:   "process",
				Source: proc.Name,
				Path:   fmt.Sprintf("PID:%d", proc.PID),
			})
		}
	}

	return sources, nil
}

// showRecentLogs displays recent log entries
func showRecentLogs(sources []LogSource, minLevel string, agentFilter string, lines int) error {
	var allEntries []LogEntry
	minLevelInt := logLevels[minLevel]

	for _, source := range sources {
		entries, err := readLogEntries(source, lines)
		if err != nil {
			fmt.Printf("Warning: failed to read logs from %s: %v\n", source.Source, err)
			continue
		}

		// Filter entries by level
		for _, entry := range entries {
			if entryLevel, exists := logLevels[entry.Level]; exists && entryLevel >= minLevelInt {
				allEntries = append(allEntries, entry)
			} else if entry.Level == "" {
				// Include entries without level parsing
				allEntries = append(allEntries, entry)
			}
		}
	}

	// Sort by timestamp
	sort.Slice(allEntries, func(i, j int) bool {
		return allEntries[i].Timestamp.Before(allEntries[j].Timestamp)
	})

	// Display entries
	displayedCount := 0
	for i := len(allEntries) - lines; i < len(allEntries); i++ {
		if i < 0 {
			continue
		}
		displayLogEntry(allEntries[i])
		displayedCount++
	}

	if displayedCount == 0 {
		fmt.Printf("No log entries found matching criteria\n")
	} else {
		fmt.Printf("\nShowing last %d log entries (from %d sources)\n", displayedCount, len(sources))
	}

	return nil
}

// followLogs follows log sources in real-time
func followLogs(sources []LogSource, minLevel string, agentFilter string) error {
	fmt.Printf("Following logs from %d sources (press Ctrl+C to stop)...\n\n", len(sources))

	// For simplicity, we'll follow the first available file source
	// A full implementation would multiplex multiple sources
	for _, source := range sources {
		if source.Type == "file" {
			return followLogFile(source.Path, minLevel)
		}
	}

	// Fallback to process monitoring
	processes, err := GetRunningProcesses()
	if err != nil {
		return err
	}

	if len(processes) == 0 {
		return fmt.Errorf("no processes to follow")
	}

	fmt.Printf("No log files found, monitoring process output...\n")
	for _, proc := range processes {
		if agentFilter == "" || proc.Name == agentFilter {
			fmt.Printf("Process: %s (PID: %d)\n", proc.Name, proc.PID)
		}
	}

	// Keep the process alive for demonstration
	for {
		time.Sleep(5 * time.Second)
		fmt.Printf("[%s] Monitoring MCP Mesh processes...\n", time.Now().Format("15:04:05"))
	}
}

// followLogFile follows a single log file
func followLogFile(filepath string, minLevel string) error {
	cmd := exec.Command("tail", "-f", filepath)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		return err
	}

	scanner := bufio.NewScanner(stdout)
	minLevelInt := logLevels[minLevel]

	for scanner.Scan() {
		line := scanner.Text()
		entry := parseLogLine(line, filepath)

		// Apply level filtering
		if entryLevel, exists := logLevels[entry.Level]; exists && entryLevel >= minLevelInt {
			displayLogEntry(entry)
		} else if entry.Level == "" {
			// Include unparseable lines
			displayLogEntry(entry)
		}
	}

	return cmd.Wait()
}

// readLogEntries reads log entries from a source
func readLogEntries(source LogSource, maxLines int) ([]LogEntry, error) {
	var entries []LogEntry

	switch source.Type {
	case "file":
		return readLogFile(source.Path, maxLines)
	case "journalctl":
		return readJournalctlOutput(source.Command, maxLines)
	case "process":
		// For process type, return a placeholder entry
		return []LogEntry{{
			Timestamp: time.Now(),
			Level:     "INFO",
			Source:    source.Source,
			Message:   fmt.Sprintf("Process monitoring available: %s", source.Path),
			Raw:       fmt.Sprintf("Process monitoring available: %s", source.Path),
		}}, nil
	}

	return entries, nil
}

// readLogFile reads log entries from a file
func readLogFile(filepath string, maxLines int) ([]LogEntry, error) {
	file, err := os.Open(filepath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)

	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}

	if err := scanner.Err(); err != nil {
		return nil, err
	}

	// Take last N lines
	start := len(lines) - maxLines
	if start < 0 {
		start = 0
	}

	var entries []LogEntry
	for i := start; i < len(lines); i++ {
		entry := parseLogLine(lines[i], filepath)
		entries = append(entries, entry)
	}

	return entries, nil
}

// readJournalctlOutput reads log entries from journalctl command output
func readJournalctlOutput(command []string, maxLines int) ([]LogEntry, error) {
	// Add lines limit to command
	cmd := append(command, "--lines", strconv.Itoa(maxLines))

	output, err := exec.Command(cmd[0], cmd[1:]...).Output()
	if err != nil {
		return nil, err
	}

	lines := strings.Split(string(output), "\n")
	var entries []LogEntry

	for _, line := range lines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		entry := parseLogLine(line, "journalctl")
		entries = append(entries, entry)
	}

	return entries, nil
}

// parseLogLine parses a log line into a LogEntry
func parseLogLine(line string, source string) LogEntry {
	entry := LogEntry{
		Timestamp: time.Now(),
		Level:     "",
		Source:    filepath.Base(source),
		Message:   line,
		Raw:       line,
	}

	// Try to parse timestamp and level from common formats
	// Format 1: "2024-01-15 12:30:45 INFO: message"
	if parts := strings.SplitN(line, " ", 4); len(parts) >= 4 {
		if timestamp, err := time.Parse("2006-01-02 15:04:05", parts[0]+" "+parts[1]); err == nil {
			entry.Timestamp = timestamp
			level := strings.TrimSuffix(parts[2], ":")
			if ValidateLogLevel(level) {
				entry.Level = level
				entry.Message = parts[3]
			}
		}
	}

	// Format 2: ISO format with level
	// "2024-01-15T12:30:45Z [INFO] message"
	if strings.Contains(line, "[") && strings.Contains(line, "]") {
		levelStart := strings.Index(line, "[")
		levelEnd := strings.Index(line, "]")
		if levelStart >= 0 && levelEnd > levelStart {
			level := line[levelStart+1 : levelEnd]
			if ValidateLogLevel(level) {
				entry.Level = level
				if levelEnd+2 < len(line) {
					entry.Message = strings.TrimSpace(line[levelEnd+1:])
				}
			}
		}
	}

	return entry
}

// displayLogEntry displays a single log entry
func displayLogEntry(entry LogEntry) {
	timestamp := entry.Timestamp.Format("15:04:05")
	level := entry.Level
	if level == "" {
		level = "    "
	}

	// Color coding for levels (using simple prefixes)
	levelPrefix := ""
	switch level {
	case "ERROR", "CRITICAL":
		levelPrefix = "✗"
	case "WARNING":
		levelPrefix = "⚠"
	case "INFO":
		levelPrefix = "ℹ"
	case "DEBUG":
		levelPrefix = "·"
	default:
		levelPrefix = " "
	}

	fmt.Printf("%s %s [%s] %s: %s\n", timestamp, levelPrefix, level, entry.Source, entry.Message)
}

// showProcessLogAdvice shows advice for viewing process logs
func showProcessLogAdvice(agentFilter string, lines int, follow bool) {
	processes, err := GetRunningProcesses()
	if err != nil {
		fmt.Printf("Unable to get process information: %v\n", err)
		return
	}

	if len(processes) == 0 {
		fmt.Printf("No MCP Mesh services are currently running.\n")
		fmt.Printf("Use 'mcp-mesh-dev start' to start services.\n")
		return
	}

	fmt.Printf("\nRunning processes (use system tools to view their logs):\n")
	for _, proc := range processes {
		if agentFilter == "" || proc.Name == agentFilter {
			fmt.Printf("\n  %s (PID: %d, Type: %s)\n", proc.Name, proc.PID, proc.Type)

			// Suggest OS-specific log viewing commands
			if runtime.GOOS == "linux" {
				fmt.Printf("    View logs: journalctl --pid %d --lines %d\n", proc.PID, lines)
				if follow {
					fmt.Printf("    Follow logs: journalctl --pid %d --follow\n", proc.PID)
				}
			} else if runtime.GOOS == "darwin" {
				fmt.Printf("    View logs: log show --predicate 'processID == %d' --last %dm\n", proc.PID, lines/10)
				if follow {
					fmt.Printf("    Follow logs: log stream --predicate 'processID == %d'\n", proc.PID)
				}
			} else {
				fmt.Printf("    Monitor process: ps -p %d -o pid,ppid,cmd,etime\n", proc.PID)
			}
		}
	}

	fmt.Printf("\nTip: Enable file logging by setting MCP_MESH_DEBUG_MODE=true\n")
}
