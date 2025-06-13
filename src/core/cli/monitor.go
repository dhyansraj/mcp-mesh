package cli

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"
)

// MonitorCommand creates the monitor command
func NewMonitorCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "monitor",
		Short: "Monitor process health and status",
		Long:  "Continuously monitor MCP Mesh processes and display real-time status",
		RunE:  runMonitor,
	}

	cmd.Flags().Int("interval", 5, "Status update interval in seconds")
	cmd.Flags().Bool("json", false, "Output status in JSON format")
	cmd.Flags().Bool("continuous", false, "Continuous monitoring mode")
	cmd.Flags().Bool("verbose", false, "Show detailed process information")
	cmd.Flags().String("filter", "", "Filter processes by name pattern")

	return cmd
}

// runMonitor executes the monitor command
func runMonitor(cmd *cobra.Command, args []string) error {
	interval, _ := cmd.Flags().GetInt("interval")
	jsonOutput, _ := cmd.Flags().GetBool("json")
	continuous, _ := cmd.Flags().GetBool("continuous")
	verbose, _ := cmd.Flags().GetBool("verbose")
	filter, _ := cmd.Flags().GetString("filter")

	pm := GetGlobalProcessManager()

	if continuous {
		return runContinuousMonitoring(pm, time.Duration(interval)*time.Second, jsonOutput, verbose, filter)
	}

	return displayCurrentStatus(pm, jsonOutput, verbose, filter)
}

// runContinuousMonitoring runs the monitoring loop
func runContinuousMonitoring(pm *ProcessManager, interval time.Duration, jsonOutput, verbose bool, filter string) error {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	// Set up signal handling for graceful exit
	signalHandler := GetGlobalSignalHandler()

	for {
		if !jsonOutput {
			// Clear screen for terminal display
			fmt.Print("\033[2J\033[H")
			fmt.Printf("MCP Mesh Process Monitor - %s\n", time.Now().Format("2006-01-02 15:04:05"))
			fmt.Println(strings.Repeat("=", 100))
		}

		if err := displayCurrentStatus(pm, jsonOutput, verbose, filter); err != nil {
			return err
		}

		if !jsonOutput {
			fmt.Printf("\nRefreshing every %v seconds. Press Ctrl+C to exit.\n", interval)
		}

		select {
		case <-ticker.C:
			// Check if we're shutting down
			if signalHandler.IsShuttingDown() {
				return nil
			}
			continue
		case <-time.After(time.Hour): // Safety timeout
			return nil
		}
	}
}

// displayCurrentStatus displays the current status of all processes
func displayCurrentStatus(pm *ProcessManager, jsonOutput, verbose bool, filter string) error {
	processes := pm.GetAllProcesses()

	// Filter processes if filter is provided
	if filter != "" {
		filteredProcesses := make(map[string]*ProcessInfo)
		for name, info := range processes {
			if strings.Contains(strings.ToLower(name), strings.ToLower(filter)) {
				filteredProcesses[name] = info
			}
		}
		processes = filteredProcesses
	}

	if jsonOutput {
		return displayJSONStatus(processes, verbose)
	}

	return displayTextStatus(processes, verbose)
}

// displayJSONStatus displays status in JSON format
func displayJSONStatus(processes map[string]*ProcessInfo, verbose bool) error {
	if verbose {
		// Include all fields
		data, err := json.MarshalIndent(processes, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(data))
	} else {
		// Include only essential fields
		simplified := make(map[string]interface{})
		for name, info := range processes {
			simplified[name] = map[string]interface{}{
				"pid":          info.PID,
				"status":       info.Status,
				"health_check": info.HealthCheck,
				"service_type": info.ServiceType,
				"uptime":       time.Since(info.StartTime).Truncate(time.Second),
				"restarts":     info.Restarts,
			}
		}

		data, err := json.MarshalIndent(simplified, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(data))
	}

	return nil
}

// displayTextStatus displays status in human-readable text format
func displayTextStatus(processes map[string]*ProcessInfo, verbose bool) error {
	if len(processes) == 0 {
		fmt.Println("No managed processes found.")
		return nil
	}

	// Summary header
	fmt.Printf("Total Processes: %d\n", len(processes))

	// Count by status
	statusCounts := make(map[string]int)
	healthCounts := make(map[string]int)

	for _, info := range processes {
		statusCounts[info.Status]++
		healthCounts[info.HealthCheck]++
	}

	fmt.Printf("Status Summary: ")
	for status, count := range statusCounts {
		fmt.Printf("%s: %d  ", status, count)
	}
	fmt.Println()

	fmt.Printf("Health Summary: ")
	for health, count := range healthCounts {
		fmt.Printf("%s: %d  ", health, count)
	}
	fmt.Println()
	fmt.Println()

	if verbose {
		return displayVerboseTextStatus(processes)
	}

	return displayCompactTextStatus(processes)
}

// displayCompactTextStatus displays compact text status
func displayCompactTextStatus(processes map[string]*ProcessInfo) error {
	// Column headers
	fmt.Printf("%-25s %-8s %-10s %-12s %-12s %-10s %-8s\n",
		"NAME", "PID", "STATUS", "HEALTH", "TYPE", "UPTIME", "RESTARTS")
	fmt.Println(strings.Repeat("-", 100))

	// Process rows
	for name, info := range processes {
		uptime := time.Since(info.StartTime).Truncate(time.Second)

		// Add status indicators
		statusIndicator := getStatusIndicator(info.Status)
		healthIndicator := getHealthIndicator(info.HealthCheck)

		fmt.Printf("%-25s %-8d %s%-9s %s%-11s %-12s %-10s %-8d\n",
			truncateString(name, 25),
			info.PID,
			statusIndicator, info.Status,
			healthIndicator, info.HealthCheck,
			info.ServiceType,
			uptime,
			info.Restarts)
	}

	return nil
}

// displayVerboseTextStatus displays detailed text status
func displayVerboseTextStatus(processes map[string]*ProcessInfo) error {
	for name, info := range processes {
		fmt.Printf("━━━ Process: %s ━━━\n", name)
		fmt.Printf("  PID:               %d\n", info.PID)
		fmt.Printf("  Status:            %s %s\n", getStatusIndicator(info.Status), info.Status)
		fmt.Printf("  Health:            %s %s\n", getHealthIndicator(info.HealthCheck), info.HealthCheck)
		fmt.Printf("  Service Type:      %s\n", info.ServiceType)
		fmt.Printf("  Command:           %s\n", info.Command)
		fmt.Printf("  Working Directory: %s\n", info.WorkingDir)
		fmt.Printf("  Start Time:        %s\n", info.StartTime.Format("2006-01-02 15:04:05"))
		fmt.Printf("  Uptime:            %s\n", time.Since(info.StartTime).Truncate(time.Second))
		fmt.Printf("  Last Seen:         %s\n", info.LastSeen.Format("2006-01-02 15:04:05"))
		fmt.Printf("  Restarts:          %d\n", info.Restarts)
		fmt.Printf("  Consecutive Fails: %d\n", info.ConsecutiveFails)
		fmt.Printf("  Auto Restart:      %t\n", info.AutoRestart)

		if info.RegistryURL != "" {
			fmt.Printf("  Registry URL:      %s\n", info.RegistryURL)
		}

		// Show environment variables
		if len(info.Environment) > 0 {
			fmt.Printf("  Environment:\n")
			for key, value := range info.Environment {
				fmt.Printf("    %s=%s\n", key, value)
			}
		}

		// Show metadata
		if len(info.Metadata) > 0 {
			fmt.Printf("  Metadata:\n")
			for key, value := range info.Metadata {
				fmt.Printf("    %s=%v\n", key, value)
			}
		}

		// Show registry status for agents
		if info.ServiceType == "agent" {
			pm := GetGlobalProcessManager()
			registryStatus := pm.checkAgentRegistryStatus(name)
			fmt.Printf("  Registry Status:\n")
			fmt.Printf("    Connected:       %t\n", registryStatus["connected"])
			fmt.Printf("    Registered:      %t\n", registryStatus["registered"])
			if lastHeartbeat, ok := registryStatus["last_heartbeat"].(time.Time); ok && !lastHeartbeat.IsZero() {
				fmt.Printf("    Last Heartbeat:  %s\n", lastHeartbeat.Format("2006-01-02 15:04:05"))
			}
			if regStatus, ok := registryStatus["registry_status"].(string); ok {
				fmt.Printf("    Registry Health: %s\n", regStatus)
			}
		}

		fmt.Println()
	}

	return nil
}

// getStatusIndicator returns a visual indicator for process status
func getStatusIndicator(status string) string {
	switch status {
	case "running":
		return "🟢"
	case "stopped":
		return "🔴"
	case "killed":
		return "💀"
	default:
		return "⚪"
	}
}

// getHealthIndicator returns a visual indicator for health status
func getHealthIndicator(health string) string {
	switch health {
	case "healthy":
		return "✅"
	case "unhealthy":
		return "❌"
	case "failed":
		return "💥"
	case "unknown":
		return "❓"
	default:
		return "⚪"
	}
}

// truncateString truncates a string to a maximum length
func truncateString(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	if maxLen <= 3 {
		return s[:maxLen]
	}
	return s[:maxLen-3] + "..."
}

// ProcessStats represents aggregated process statistics
type ProcessStats struct {
	TotalProcesses   int             `json:"total_processes"`
	StatusBreakdown  map[string]int  `json:"status_breakdown"`
	HealthBreakdown  map[string]int  `json:"health_breakdown"`
	ServiceBreakdown map[string]int  `json:"service_breakdown"`
	TotalRestarts    int             `json:"total_restarts"`
	AvgUptime        time.Duration   `json:"avg_uptime"`
	SystemLoad       *SystemLoadInfo `json:"system_load,omitempty"`
}

// SystemLoadInfo represents system resource information
type SystemLoadInfo struct {
	CPUUsage    float64 `json:"cpu_usage"`
	MemoryUsage float64 `json:"memory_usage"`
	LoadAvg     float64 `json:"load_avg"`
}

// GetProcessStats returns aggregated statistics for all processes
func (pm *ProcessManager) GetProcessStats() *ProcessStats {
	processes := pm.GetAllProcesses()

	stats := &ProcessStats{
		TotalProcesses:   len(processes),
		StatusBreakdown:  make(map[string]int),
		HealthBreakdown:  make(map[string]int),
		ServiceBreakdown: make(map[string]int),
		TotalRestarts:    0,
	}

	var totalUptime time.Duration

	for _, info := range processes {
		stats.StatusBreakdown[info.Status]++
		stats.HealthBreakdown[info.HealthCheck]++
		stats.ServiceBreakdown[info.ServiceType]++
		stats.TotalRestarts += info.Restarts
		totalUptime += time.Since(info.StartTime)
	}

	if len(processes) > 0 {
		stats.AvgUptime = totalUptime / time.Duration(len(processes))
	}

	return stats
}

// NewStatsCommand creates the stats command
func NewStatsCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "stats",
		Short: "Display process statistics",
		Long:  "Display aggregated statistics for all managed processes",
		RunE:  runStats,
	}

	cmd.Flags().Bool("json", false, "Output statistics in JSON format")
	cmd.Flags().Bool("system", false, "Include system resource information")

	return cmd
}

// runStats executes the stats command
func runStats(cmd *cobra.Command, args []string) error {
	jsonOutput, _ := cmd.Flags().GetBool("json")
	includeSystem, _ := cmd.Flags().GetBool("system")

	pm := GetGlobalProcessManager()
	stats := pm.GetProcessStats()

	// Add system information if requested
	if includeSystem {
		// This would be implemented with system-specific code
		// For now, we'll leave it as nil
		stats.SystemLoad = nil
	}

	if jsonOutput {
		data, err := json.MarshalIndent(stats, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(data))
	} else {
		displayTextStats(stats)
	}

	return nil
}

// displayTextStats displays statistics in text format
func displayTextStats(stats *ProcessStats) {
	fmt.Printf("MCP Mesh Process Statistics\n")
	fmt.Println(strings.Repeat("=", 40))
	fmt.Printf("Total Processes: %d\n", stats.TotalProcesses)
	fmt.Printf("Total Restarts:  %d\n", stats.TotalRestarts)
	fmt.Printf("Average Uptime:  %s\n", stats.AvgUptime.Truncate(time.Second))
	fmt.Println()

	fmt.Println("Status Breakdown:")
	for status, count := range stats.StatusBreakdown {
		fmt.Printf("  %s: %d\n", status, count)
	}
	fmt.Println()

	fmt.Println("Health Breakdown:")
	for health, count := range stats.HealthBreakdown {
		fmt.Printf("  %s: %d\n", health, count)
	}
	fmt.Println()

	fmt.Println("Service Type Breakdown:")
	for serviceType, count := range stats.ServiceBreakdown {
		fmt.Printf("  %s: %d\n", serviceType, count)
	}

	if stats.SystemLoad != nil {
		fmt.Println()
		fmt.Println("System Resources:")
		fmt.Printf("  CPU Usage:    %.1f%%\n", stats.SystemLoad.CPUUsage)
		fmt.Printf("  Memory Usage: %.1f%%\n", stats.SystemLoad.MemoryUsage)
		fmt.Printf("  Load Average: %.2f\n", stats.SystemLoad.LoadAvg)
	}
}
