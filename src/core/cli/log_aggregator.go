package cli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// AggregatedLogEntry represents a single log entry in the aggregator
type AggregatedLogEntry struct {
	Timestamp time.Time `json:"timestamp"`
	Level     string    `json:"level"`
	Source    string    `json:"source"`
	Message   string    `json:"message"`
	Raw       string    `json:"raw"`
}

// LogAggregator handles aggregation and filtering of logs from multiple sources
type LogAggregator struct {
	processManager *ProcessManager
	logSources     map[string]string // process name -> log file path
	logPattern     *regexp.Regexp
	levelOrder     map[string]int
}

// NewLogAggregator creates a new log aggregator
func NewLogAggregator(pm *ProcessManager) *LogAggregator {
	// Common log pattern for parsing timestamps and levels
	logPattern := regexp.MustCompile(`^(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*(\w+)?\s*(.*)$`)

	levelOrder := map[string]int{
		"DEBUG":   0,
		"INFO":    1,
		"WARNING": 2,
		"WARN":    2,
		"ERROR":   3,
		"CRITICAL": 4,
		"FATAL":   4,
	}

	return &LogAggregator{
		processManager: pm,
		logSources:     make(map[string]string),
		logPattern:     logPattern,
		levelOrder:     levelOrder,
	}
}

// NewLogsAggregatorDetailedCommand creates the detailed logs command
func NewLogsAggregatorDetailedCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs [process-name]",
		Short: "Display and aggregate logs from processes",
		Long:  "Display logs from managed processes with filtering and aggregation capabilities",
		RunE:  runLogs,
	}

	cmd.Flags().Bool("follow", false, "Follow log output in real-time")
	cmd.Flags().String("filter", "", "Filter logs by keyword")
	cmd.Flags().String("level", "INFO", "Minimum log level (DEBUG, INFO, WARNING, ERROR)")
	cmd.Flags().Int("lines", 100, "Number of recent lines to show")
	cmd.Flags().Bool("aggregate", false, "Aggregate logs from all processes")
	cmd.Flags().String("since", "", "Show logs since timestamp (RFC3339 format)")
	cmd.Flags().String("until", "", "Show logs until timestamp (RFC3339 format)")
	cmd.Flags().Bool("json", false, "Output logs in JSON format")

	return cmd
}

// runLogs executes the logs command
func runLogs(cmd *cobra.Command, args []string) error {
	follow, _ := cmd.Flags().GetBool("follow")
	filter, _ := cmd.Flags().GetString("filter")
	level, _ := cmd.Flags().GetString("level")
	lines, _ := cmd.Flags().GetInt("lines")
	aggregate, _ := cmd.Flags().GetBool("aggregate")
	since, _ := cmd.Flags().GetString("since")
	until, _ := cmd.Flags().GetString("until")
	jsonOutput, _ := cmd.Flags().GetBool("json")

	pm := GetGlobalProcessManager()
	aggregator := NewLogAggregator(pm)

	// Discover log sources
	if err := aggregator.discoverLogSources(); err != nil {
		return fmt.Errorf("failed to discover log sources: %w", err)
	}

	var processName string
	if len(args) > 0 {
		processName = args[0]
		// Validate process exists
		if _, exists := pm.GetProcess(processName); !exists {
			return fmt.Errorf("process %s not found", processName)
		}
	} else if !aggregate {
		// Default to aggregated view if no specific process requested
		aggregate = true
	}

	// Parse time filters
	var sinceTime, untilTime time.Time
	var err error

	if since != "" {
		if sinceTime, err = time.Parse(time.RFC3339, since); err != nil {
			return fmt.Errorf("invalid since time format: %w", err)
		}
	}

	if until != "" {
		if untilTime, err = time.Parse(time.RFC3339, until); err != nil {
			return fmt.Errorf("invalid until time format: %w", err)
		}
	}

	if follow {
		return aggregator.followLogs(processName, aggregate, filter, level, jsonOutput)
	}

	return aggregator.displayHistoricalLogs(processName, aggregate, filter, level, lines, sinceTime, untilTime, jsonOutput)
}

// discoverLogSources discovers log files for all managed processes
func (la *LogAggregator) discoverLogSources() error {
	processes := la.processManager.GetAllProcesses()

	for name, info := range processes {
		// Try to find log files based on common patterns
		logPaths := la.findLogFiles(name, info)

		if len(logPaths) > 0 {
			// Use the first found log file
			la.logSources[name] = logPaths[0]
		}
	}

	return nil
}

// findLogFiles finds potential log files for a process
func (la *LogAggregator) findLogFiles(processName string, info *ProcessInfo) []string {
	var logPaths []string

	// Common log file patterns and locations
	patterns := []string{
		fmt.Sprintf("%s.log", processName),
		fmt.Sprintf("%s*.log", processName),
		"*.log",
	}

	searchDirs := []string{
		info.WorkingDir,
		filepath.Join(info.WorkingDir, "logs"),
		"/tmp",
		"/var/log",
		os.TempDir(),
	}

	for _, dir := range searchDirs {
		for _, pattern := range patterns {
			matches, err := filepath.Glob(filepath.Join(dir, pattern))
			if err == nil {
				logPaths = append(logPaths, matches...)
			}
		}
	}

	// Remove duplicates and filter by modification time
	uniquePaths := make(map[string]bool)
	var filteredPaths []string

	for _, path := range logPaths {
		if !uniquePaths[path] {
			uniquePaths[path] = true

			// Check if file exists and was modified recently
			if info, err := os.Stat(path); err == nil {
				if time.Since(info.ModTime()) < 24*time.Hour {
					filteredPaths = append(filteredPaths, path)
				}
			}
		}
	}

	return filteredPaths
}

// displayHistoricalLogs displays historical logs with filtering
func (la *LogAggregator) displayHistoricalLogs(processName string, aggregate bool, filter, level string, lines int, sinceTime, untilTime time.Time, jsonOutput bool) error {
	var allEntries []AggregatedLogEntry

	if aggregate {
		// Collect logs from all processes
		for name, logPath := range la.logSources {
			entries, err := la.readLogFile(logPath, name, filter, level, sinceTime, untilTime)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Warning: Could not read logs for %s: %v\n", name, err)
				continue
			}
			allEntries = append(allEntries, entries...)
		}
	} else {
		// Single process logs
		logPath, exists := la.logSources[processName]
		if !exists {
			return fmt.Errorf("no log file found for process %s", processName)
		}

		var err error
		allEntries, err = la.readLogFile(logPath, processName, filter, level, sinceTime, untilTime)
		if err != nil {
			return fmt.Errorf("failed to read log file: %w", err)
		}
	}

	// Sort by timestamp
	sort.Slice(allEntries, func(i, j int) bool {
		return allEntries[i].Timestamp.Before(allEntries[j].Timestamp)
	})

	// Limit to requested number of lines
	if lines > 0 && len(allEntries) > lines {
		allEntries = allEntries[len(allEntries)-lines:]
	}

	// Display logs
	if jsonOutput {
		return la.displayLogsJSON(allEntries)
	}

	return la.displayLogsText(allEntries)
}

// followLogs follows logs in real-time
func (la *LogAggregator) followLogs(processName string, aggregate bool, filter, level string, jsonOutput bool) error {
	// This is a simplified implementation
	// A full implementation would use file system watching (inotify/fsevents)

	fmt.Println("Following logs... (Press Ctrl+C to exit)")

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	signalHandler := GetGlobalSignalHandler()

	for {
		select {
		case <-ticker.C:
			// Read recent logs
			entries, err := la.getRecentLogEntries(processName, aggregate, filter, level, 10)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error reading logs: %v\n", err)
				continue
			}

			// Display new entries
			if jsonOutput {
				la.displayLogsJSON(entries)
			} else {
				la.displayLogsText(entries)
			}

		case <-time.After(time.Hour):
			return nil

		default:
			if signalHandler.IsShuttingDown() {
				return nil
			}
		}
	}
}

// readLogFile reads and parses a log file
func (la *LogAggregator) readLogFile(logPath, source, filter, level string, sinceTime, untilTime time.Time) ([]AggregatedLogEntry, error) {
	file, err := os.Open(logPath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var entries []AggregatedLogEntry
	scanner := bufio.NewScanner(file)

	minLevel := la.levelOrder[strings.ToUpper(level)]

	for scanner.Scan() {
		line := scanner.Text()

		// Skip empty lines
		if strings.TrimSpace(line) == "" {
			continue
		}

		entry := la.parseLogLine(line, source)

		// Apply filters
		if filter != "" && !strings.Contains(strings.ToLower(entry.Message), strings.ToLower(filter)) {
			continue
		}

		if entryLevel, exists := la.levelOrder[strings.ToUpper(entry.Level)]; exists {
			if entryLevel < minLevel {
				continue
			}
		}

		if !sinceTime.IsZero() && entry.Timestamp.Before(sinceTime) {
			continue
		}

		if !untilTime.IsZero() && entry.Timestamp.After(untilTime) {
			continue
		}

		entries = append(entries, entry)
	}

	return entries, scanner.Err()
}

// parseLogLine parses a single log line
func (la *LogAggregator) parseLogLine(line, source string) AggregatedLogEntry {
	entry := AggregatedLogEntry{
		Source: source,
		Raw:    line,
	}

	matches := la.logPattern.FindStringSubmatch(line)
	if len(matches) >= 4 {
		// Parse timestamp
		if timestamp, err := time.Parse("2006-01-02 15:04:05", matches[1]); err == nil {
			entry.Timestamp = timestamp
		} else if timestamp, err := time.Parse(time.RFC3339, matches[1]); err == nil {
			entry.Timestamp = timestamp
		} else {
			entry.Timestamp = time.Now()
		}

		// Extract level
		if matches[2] != "" {
			entry.Level = strings.ToUpper(matches[2])
		} else {
			entry.Level = "INFO"
		}

		// Extract message
		entry.Message = matches[3]
	} else {
		// Fallback for unparseable lines
		entry.Timestamp = time.Now()
		entry.Level = "INFO"
		entry.Message = line
	}

	return entry
}

// getRecentLogEntries gets recent log entries for following mode
func (la *LogAggregator) getRecentLogEntries(processName string, aggregate bool, filter, level string, limit int) ([]AggregatedLogEntry, error) {
	// This is a simplified implementation
	// A real implementation would track file positions and only read new content

	var allEntries []AggregatedLogEntry

	if aggregate {
		for name, logPath := range la.logSources {
			entries, err := la.readLogFile(logPath, name, filter, level, time.Now().Add(-1*time.Minute), time.Time{})
			if err != nil {
				continue
			}
			allEntries = append(allEntries, entries...)
		}
	} else {
		logPath, exists := la.logSources[processName]
		if !exists {
			return nil, fmt.Errorf("no log file found for process %s", processName)
		}

		var err error
		allEntries, err = la.readLogFile(logPath, processName, filter, level, time.Now().Add(-1*time.Minute), time.Time{})
		if err != nil {
			return nil, err
		}
	}

	// Sort and limit
	sort.Slice(allEntries, func(i, j int) bool {
		return allEntries[i].Timestamp.After(allEntries[j].Timestamp)
	})

	if len(allEntries) > limit {
		allEntries = allEntries[:limit]
	}

	// Reverse to show chronological order
	for i := len(allEntries)/2 - 1; i >= 0; i-- {
		opp := len(allEntries) - 1 - i
		allEntries[i], allEntries[opp] = allEntries[opp], allEntries[i]
	}

	return allEntries, nil
}

// displayLogsText displays logs in text format
func (la *LogAggregator) displayLogsText(entries []AggregatedLogEntry) error {
	for _, entry := range entries {
		timestamp := entry.Timestamp.Format("2006-01-02 15:04:05")

		// Color code by level
		levelColor := la.getLevelColor(entry.Level)
		sourceColor := "\033[36m" // Cyan for source
		resetColor := "\033[0m"

		fmt.Printf("%s [%s%s%s] [%s%s%s] %s\n",
			timestamp,
			levelColor, entry.Level, resetColor,
			sourceColor, entry.Source, resetColor,
			entry.Message)
	}

	return nil
}

// displayLogsJSON displays logs in JSON format
func (la *LogAggregator) displayLogsJSON(entries []AggregatedLogEntry) error {
	for _, entry := range entries {
		data, err := json.Marshal(entry)
		if err != nil {
			return err
		}
		fmt.Println(string(data))
	}

	return nil
}

// getLevelColor returns ANSI color code for log level
func (la *LogAggregator) getLevelColor(level string) string {
	switch strings.ToUpper(level) {
	case "DEBUG":
		return "\033[37m" // White
	case "INFO":
		return "\033[32m" // Green
	case "WARNING", "WARN":
		return "\033[33m" // Yellow
	case "ERROR":
		return "\033[31m" // Red
	case "CRITICAL", "FATAL":
		return "\033[35m" // Magenta
	default:
		return "\033[0m" // Reset
	}
}

// NewLogAggregatorCommand creates the log aggregator command
func NewLogAggregatorCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs-aggregator",
		Short: "Advanced log aggregation and analysis",
		Long:  "Aggregate and analyze logs from all managed processes with advanced filtering",
		RunE:  runLogsAggregator,
	}

	cmd.Flags().Bool("follow", false, "Follow log output in real-time")
	cmd.Flags().String("filter", "", "Filter logs by keyword")
	cmd.Flags().String("level", "INFO", "Minimum log level")
	cmd.Flags().Int("lines", 100, "Number of recent lines to show")
	cmd.Flags().Bool("stats", false, "Show log statistics")
	cmd.Flags().String("format", "text", "Output format (text, json, csv)")

	return cmd
}

// runLogsAggregator executes the advanced log aggregator
func runLogsAggregator(cmd *cobra.Command, args []string) error {
	follow, _ := cmd.Flags().GetBool("follow")
	filter, _ := cmd.Flags().GetString("filter")
	level, _ := cmd.Flags().GetString("level")
	lines, _ := cmd.Flags().GetInt("lines")
	showStats, _ := cmd.Flags().GetBool("stats")
	format, _ := cmd.Flags().GetString("format")

	pm := GetGlobalProcessManager()
	aggregator := NewLogAggregator(pm)

	if err := aggregator.discoverLogSources(); err != nil {
		return fmt.Errorf("failed to discover log sources: %w", err)
	}

	if showStats {
		return aggregator.displayLogStatistics()
	}

	if follow {
		return aggregator.followLogs("", true, filter, level, format == "json")
	}

	return aggregator.displayHistoricalLogs("", true, filter, level, lines, time.Time{}, time.Time{}, format == "json")
}

// displayLogStatistics displays statistics about the logs
func (la *LogAggregator) displayLogStatistics() error {
	fmt.Println("Log Sources Statistics")
	fmt.Println(strings.Repeat("=", 40))

	for processName, logPath := range la.logSources {
		info, err := os.Stat(logPath)
		if err != nil {
			continue
		}

		fmt.Printf("Process: %s\n", processName)
		fmt.Printf("  Log File: %s\n", logPath)
		fmt.Printf("  Size: %d bytes\n", info.Size())
		fmt.Printf("  Modified: %s\n", info.ModTime().Format("2006-01-02 15:04:05"))

		// Count lines
		if lineCount, err := la.countLines(logPath); err == nil {
			fmt.Printf("  Lines: %d\n", lineCount)
		}

		fmt.Println()
	}

	return nil
}

// countLines counts the number of lines in a file
func (la *LogAggregator) countLines(filePath string) (int, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return 0, err
	}
	defer file.Close()

	count := 0
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		count++
	}

	return count, scanner.Err()
}
