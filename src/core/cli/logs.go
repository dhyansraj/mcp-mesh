package cli

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/cobra"
)

// NewLogsCommand creates the logs command
func NewLogsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "logs <agent-name>",
		Short: "View agent logs",
		Long: `View logs for agents running in detached mode.

Logs are stored in ~/.mcp-mesh/logs/ with automatic rotation (keeps 5 logs per agent).

Examples:
  meshctl logs my-agent              # Last 100 lines (default)
  meshctl logs my-agent -f           # Follow log output
  meshctl logs my-agent -p           # Previous log (before last restart)
  meshctl logs my-agent -p 2         # Log from 2 restarts ago
  meshctl logs my-agent --tail 50    # Last 50 lines
  meshctl logs my-agent --tail 0 -f  # No history, only new lines
  meshctl logs my-agent --since 10m  # Last 10 minutes
  meshctl logs my-agent --since 1h   # Last 1 hour
  meshctl logs my-agent --list       # List available agent logs`,
		Args: cobra.MaximumNArgs(1),
		RunE: runLogsCommand,
	}

	cmd.Flags().BoolP("follow", "f", false, "Follow log output (like tail -f)")
	cmd.Flags().IntP("previous", "p", 0, "Show previous log (1 = last restart, 2 = 2 restarts ago)")
	cmd.Flags().Int("tail", 100, "Number of lines to show from end of log (0 = no limit)")
	cmd.Flags().String("since", "", "Show logs since duration (e.g., 5m, 1h, 2h30m) or timestamp")
	cmd.Flags().String("until", "", "Show logs until duration ago (e.g., 5m) or timestamp")
	cmd.Flags().Bool("list", false, "List available agent logs")
	cmd.Flags().Bool("timestamps", false, "Show timestamps (if not already in log format)")

	return cmd
}

func runLogsCommand(cmd *cobra.Command, args []string) error {
	listLogs, _ := cmd.Flags().GetBool("list")

	lm, err := NewLogManager()
	if err != nil {
		return fmt.Errorf("failed to initialize log manager: %w", err)
	}

	// Handle --list flag
	if listLogs {
		return listAgentLogs(lm)
	}

	// Require agent name for other operations
	if len(args) == 0 {
		return fmt.Errorf("agent name required. Use 'meshctl logs --list' to see available logs")
	}

	agentName := args[0]
	follow, _ := cmd.Flags().GetBool("follow")
	previous, _ := cmd.Flags().GetInt("previous")
	tail, _ := cmd.Flags().GetInt("tail")
	since, _ := cmd.Flags().GetString("since")
	until, _ := cmd.Flags().GetString("until")

	// Parse time filters
	var sinceTime, untilTime *time.Time
	if since != "" {
		t, err := parseTimeSpec(since)
		if err != nil {
			return fmt.Errorf("invalid --since value: %w", err)
		}
		sinceTime = &t
	}
	if until != "" {
		t, err := parseTimeSpec(until)
		if err != nil {
			return fmt.Errorf("invalid --until value: %w", err)
		}
		untilTime = &t
	}

	// Open log file
	file, err := lm.OpenLogFile(agentName, previous)
	if err != nil {
		return err
	}
	defer file.Close()

	// If following, we need to handle this specially
	if follow {
		return followLog(file, lm.GetLogFile(agentName), tail, sinceTime, untilTime)
	}

	// Read and filter log
	return readLog(file, tail, sinceTime, untilTime)
}

func listAgentLogs(lm *LogManager) error {
	agents, err := lm.ListAgentLogs()
	if err != nil {
		return err
	}

	if len(agents) == 0 {
		fmt.Println("No agent logs found.")
		fmt.Println("Logs are created when agents run with 'meshctl start --detach'")
		return nil
	}

	fmt.Println("Available agent logs:")
	for _, agent := range agents {
		info, err := lm.GetLogInfo(agent)
		if err != nil {
			continue
		}

		status := ""
		if info.HasCurrent {
			status = fmt.Sprintf("(current: %s)", formatBytes(info.CurrentSize))
		}
		prevCount := len(info.PreviousLogs)
		if prevCount > 0 {
			if status != "" {
				status += ", "
			}
			status += fmt.Sprintf("%d previous", prevCount)
		}

		fmt.Printf("  %s %s\n", agent, status)
	}

	return nil
}

func readLog(file *os.File, tailLines int, sinceTime, untilTime *time.Time) error {
	// If we need to filter by time or tail, read all lines first
	var lines []string
	scanner := bufio.NewScanner(file)

	// Increase buffer size for long lines
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()

		// Apply time filters if specified
		if sinceTime != nil || untilTime != nil {
			lineTime := parseLogTimestamp(line)
			if lineTime != nil {
				if sinceTime != nil && lineTime.Before(*sinceTime) {
					continue
				}
				if untilTime != nil && lineTime.After(*untilTime) {
					continue
				}
			}
		}

		lines = append(lines, line)
	}

	if err := scanner.Err(); err != nil {
		return fmt.Errorf("error reading log: %w", err)
	}

	// Apply tail limit
	startIdx := 0
	if tailLines > 0 && len(lines) > tailLines {
		startIdx = len(lines) - tailLines
	}

	// Print lines
	for i := startIdx; i < len(lines); i++ {
		fmt.Println(lines[i])
	}

	return nil
}

func followLog(file *os.File, logPath string, tailLines int, sinceTime, untilTime *time.Time) error {
	// First, print existing content (respecting tail)
	if tailLines != 0 {
		if err := readLog(file, tailLines, sinceTime, untilTime); err != nil {
			return err
		}
	}

	// Seek to end for following
	if _, err := file.Seek(0, io.SeekEnd); err != nil {
		return fmt.Errorf("failed to seek to end of log: %w", err)
	}

	// Set up file watcher
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("failed to create file watcher: %w", err)
	}
	defer watcher.Close()

	if err := watcher.Add(logPath); err != nil {
		return fmt.Errorf("failed to watch log file: %w", err)
	}

	reader := bufio.NewReader(file)

	// Watch for changes
	for {
		select {
		case event, ok := <-watcher.Events:
			if !ok {
				return nil
			}
			if event.Op&fsnotify.Write == fsnotify.Write {
				// Read new content
				for {
					line, err := reader.ReadString('\n')
					if err != nil {
						break
					}
					line = strings.TrimSuffix(line, "\n")

					// Apply time filters
					if sinceTime != nil || untilTime != nil {
						lineTime := parseLogTimestamp(line)
						if lineTime != nil {
							if sinceTime != nil && lineTime.Before(*sinceTime) {
								continue
							}
							if untilTime != nil && lineTime.After(*untilTime) {
								continue
							}
						}
					}

					fmt.Println(line)
				}
			}
		case err, ok := <-watcher.Errors:
			if !ok {
				return nil
			}
			return fmt.Errorf("watcher error: %w", err)
		}
	}
}

// parseTimeSpec parses a time specification like "5m", "1h", "2h30m" or a timestamp
func parseTimeSpec(spec string) (time.Time, error) {
	// Try parsing as duration first
	duration, err := parseDuration(spec)
	if err == nil {
		return time.Now().Add(-duration), nil
	}

	// Try parsing as timestamp
	formats := []string{
		"2006-01-02 15:04:05",
		"2006-01-02T15:04:05",
		"2006-01-02 15:04",
		"2006-01-02",
		"15:04:05",
		"15:04",
	}

	for _, format := range formats {
		if t, err := time.Parse(format, spec); err == nil {
			// If only time was parsed, use today's date
			if format == "15:04:05" || format == "15:04" {
				now := time.Now()
				t = time.Date(now.Year(), now.Month(), now.Day(), t.Hour(), t.Minute(), t.Second(), 0, time.Local)
			}
			return t, nil
		}
	}

	return time.Time{}, fmt.Errorf("cannot parse '%s' as duration or timestamp", spec)
}

// parseDuration parses duration strings like "5m", "1h", "2h30m"
func parseDuration(s string) (time.Duration, error) {
	// Try standard Go duration parsing
	if d, err := time.ParseDuration(s); err == nil {
		return d, nil
	}

	// Try parsing simple formats like "5m", "1h"
	s = strings.ToLower(strings.TrimSpace(s))

	// Extract number and unit
	re := regexp.MustCompile(`^(\d+)([smhd])$`)
	matches := re.FindStringSubmatch(s)
	if matches == nil {
		return 0, fmt.Errorf("invalid duration format")
	}

	value, _ := strconv.Atoi(matches[1])
	unit := matches[2]

	switch unit {
	case "s":
		return time.Duration(value) * time.Second, nil
	case "m":
		return time.Duration(value) * time.Minute, nil
	case "h":
		return time.Duration(value) * time.Hour, nil
	case "d":
		return time.Duration(value) * 24 * time.Hour, nil
	default:
		return 0, fmt.Errorf("unknown duration unit: %s", unit)
	}
}

// parseLogTimestamp extracts timestamp from a log line
// Expected format: "2025-01-05 10:23:45 INFO ..."
func parseLogTimestamp(line string) *time.Time {
	// Try to match common timestamp formats at the start of the line
	patterns := []struct {
		regex  *regexp.Regexp
		format string
	}{
		{regexp.MustCompile(`^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})`), "2006-01-02 15:04:05"},
		{regexp.MustCompile(`^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})`), "2006-01-02T15:04:05"},
		{regexp.MustCompile(`^(\d{2}:\d{2}:\d{2})`), "15:04:05"},
	}

	for _, p := range patterns {
		if matches := p.regex.FindStringSubmatch(line); matches != nil {
			if t, err := time.Parse(p.format, matches[1]); err == nil {
				// If only time was parsed, use today's date
				if p.format == "15:04:05" {
					now := time.Now()
					t = time.Date(now.Year(), now.Month(), now.Day(), t.Hour(), t.Minute(), t.Second(), 0, time.Local)
				}
				return &t
			}
		}
	}

	return nil
}

// formatBytes formats bytes as human-readable string
func formatBytes(bytes int64) string {
	const unit = 1024
	if bytes < unit {
		return fmt.Sprintf("%d B", bytes)
	}
	div, exp := int64(unit), 0
	for n := bytes / unit; n >= unit; n /= unit {
		div *= unit
		exp++
	}
	return fmt.Sprintf("%.1f %cB", float64(bytes)/float64(div), "KMGTPE"[exp])
}
