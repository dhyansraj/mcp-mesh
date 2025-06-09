// +build windows

package cli

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// Windows API constants
const (
	PROCESS_TERMINATE = 0x0001
	PROCESS_QUERY_INFORMATION = 0x0400
)

// PlatformProcessManager provides Windows-specific process management functionality
type PlatformProcessManager struct {
	logger *log.Logger
}

// NewPlatformProcessManager creates a platform-specific process manager
func NewPlatformProcessManager() *PlatformProcessManager {
	return &PlatformProcessManager{
		logger: log.New(os.Stdout, "[PlatformProcess] ", log.LstdFlags),
	}
}

// terminateProcessGracefully terminates a process gracefully on Windows
func (ppm *PlatformProcessManager) terminateProcessGracefully(process *os.Process, timeout time.Duration) error {
	// On Windows, try to terminate gracefully first
	if err := ppm.sendCtrlBreak(process.Pid); err != nil {
		// If Ctrl+Break fails, try regular termination
		return process.Kill()
	}

	// Wait for graceful shutdown
	done := make(chan error, 1)
	go func() {
		_, err := process.Wait()
		done <- err
	}()

	select {
	case err := <-done:
		return err
	case <-time.After(timeout):
		// Force kill if timeout exceeded
		return process.Kill()
	}
}

// killProcessForcefully kills a process immediately on Windows
func (ppm *PlatformProcessManager) killProcessForcefully(process *os.Process) error {
	return process.Kill()
}

// isProcessRunning checks if a process is running on Windows
func (ppm *PlatformProcessManager) isProcessRunning(pid int) bool {
	// Use Windows-specific process checking
	handle, err := syscall.OpenProcess(PROCESS_QUERY_INFORMATION, false, uint32(pid))
	if err != nil {
		return false
	}
	defer syscall.CloseHandle(handle)

	var exitCode uint32
	err = syscall.GetExitCodeProcess(handle, &exitCode)
	if err != nil {
		return false
	}

	// STILL_ACTIVE = 259
	return exitCode == 259
}

// setProcessGroup sets process group (limited functionality on Windows)
func (ppm *PlatformProcessManager) setProcessGroup(cmd *exec.Cmd) {
	// Windows doesn't have process groups like Unix
	// Instead, we can create processes in a new console
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP,
	}
}

// terminateProcessGroup terminates a process group on Windows
func (ppm *PlatformProcessManager) terminateProcessGroup(pgid int, timeout time.Duration) error {
	// Windows implementation using taskkill
	cmd := exec.Command("taskkill", "/F", "/T", "/PID", strconv.Itoa(pgid))
	return cmd.Run()
}

// getProcessDetails gets detailed process information on Windows
func (ppm *PlatformProcessManager) getProcessDetails(pid int) (map[string]interface{}, error) {
	details := make(map[string]interface{})

	// Use wmic or tasklist to get process information
	if procInfo, err := ppm.getWindowsProcessInfo(pid); err == nil {
		details["process_info"] = procInfo
	}

	details["platform"] = "windows"
	return details, nil
}

// getWindowsProcessInfo gets process information using Windows tools
func (ppm *PlatformProcessManager) getWindowsProcessInfo(pid int) (map[string]interface{}, error) {
	info := make(map[string]interface{})

	// Use tasklist to get process information
	cmd := exec.Command("tasklist", "/FI", fmt.Sprintf("PID eq %d", pid), "/FO", "CSV", "/NH")
	output, err := cmd.Output()
	if err != nil {
		return info, err
	}

	// Parse CSV output
	lines := strings.Split(string(output), "\n")
	if len(lines) > 0 && lines[0] != "" {
		// Remove quotes and split by comma
		fields := strings.Split(strings.Trim(lines[0], "\""), "\",\"")
		if len(fields) >= 5 {
			info["image_name"] = fields[0]
			info["pid"] = fields[1]
			info["session_name"] = fields[2]
			info["session_number"] = fields[3]
			info["mem_usage"] = fields[4]
		}
	}

	return info, nil
}

// setupSignalHandling sets up Windows-specific signal handling
func (ppm *PlatformProcessManager) setupSignalHandling() []os.Signal {
	return []os.Signal{
		os.Interrupt, // Ctrl+C
		syscall.SIGTERM,
	}
}

// getUserCredentials gets user credentials (Windows-specific)
func (ppm *PlatformProcessManager) getUserCredentials() (map[string]interface{}, error) {
	creds := make(map[string]interface{})

	// Get current user information
	if username := os.Getenv("USERNAME"); username != "" {
		creds["username"] = username
	}
	if domain := os.Getenv("USERDOMAIN"); domain != "" {
		creds["domain"] = domain
	}

	return creds, nil
}

// setProcessCredentials sets process credentials (limited on Windows)
func (ppm *PlatformProcessManager) setProcessCredentials(cmd *exec.Cmd, uid, gid int) {
	// Windows doesn't use UID/GID like Unix
	// This would require more complex Windows API calls for user impersonation
	ppm.logger.Println("Warning: Process credential setting not fully implemented on Windows")
}

// findProcessesByName finds processes by name pattern on Windows
func (ppm *PlatformProcessManager) findProcessesByName(pattern string) ([]int, error) {
	var pids []int

	// Use tasklist to find processes
	cmd := exec.Command("tasklist", "/FO", "CSV", "/NH")
	output, err := cmd.Output()
	if err != nil {
		return pids, err
	}

	// Parse output and find matching processes
	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		if strings.Contains(strings.ToLower(line), strings.ToLower(pattern)) {
			fields := strings.Split(strings.Trim(line, "\""), "\",\"")
			if len(fields) >= 2 {
				if pid, err := strconv.Atoi(fields[1]); err == nil {
					pids = append(pids, pid)
				}
			}
		}
	}

	return pids, nil
}

// getSystemResourceUsage gets system resource usage on Windows
func (ppm *PlatformProcessManager) getSystemResourceUsage() (map[string]interface{}, error) {
	usage := make(map[string]interface{})

	// Use wmic or performance counters
	// Simplified implementation
	usage["cpu_count"] = ppm.getCPUCount()

	if memInfo, err := ppm.getMemoryInfo(); err == nil {
		usage["memory_total"] = memInfo["total"]
		usage["memory_free"] = memInfo["free"]
	}

	return usage, nil
}

// getCPUCount gets the number of CPUs on Windows
func (ppm *PlatformProcessManager) getCPUCount() int {
	cmd := exec.Command("wmic", "cpu", "get", "NumberOfCores", "/value")
	output, err := cmd.Output()
	if err != nil {
		return 1
	}

	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "NumberOfCores=") {
			if count, err := strconv.Atoi(strings.TrimSpace(strings.Split(line, "=")[1])); err == nil {
				return count
			}
		}
	}

	return 1
}

// getMemoryInfo gets memory information on Windows
func (ppm *PlatformProcessManager) getMemoryInfo() (map[string]interface{}, error) {
	info := make(map[string]interface{})

	// Use wmic to get memory information
	cmd := exec.Command("wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/value")
	output, err := cmd.Output()
	if err != nil {
		return info, err
	}

	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "TotalVisibleMemorySize=") {
			if size, err := strconv.ParseInt(strings.Split(line, "=")[1], 10, 64); err == nil {
				info["total"] = size * 1024 // Convert from KB to bytes
			}
		} else if strings.HasPrefix(line, "FreePhysicalMemory=") {
			if size, err := strconv.ParseInt(strings.Split(line, "=")[1], 10, 64); err == nil {
				info["free"] = size * 1024 // Convert from KB to bytes
			}
		}
	}

	return info, nil
}

// createDaemonProcess creates a background process on Windows
func (ppm *PlatformProcessManager) createDaemonProcess(cmd *exec.Cmd) error {
	// On Windows, create a detached process
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP | syscall.DETACHED_PROCESS,
	}

	// Redirect standard handles to NUL
	if nulFile, err := os.OpenFile("NUL", os.O_RDWR, 0); err == nil {
		cmd.Stdin = nulFile
		cmd.Stdout = nulFile
		cmd.Stderr = nulFile
	}

	return nil
}

// monitorProcessMemory monitors memory usage of a process on Windows
func (ppm *PlatformProcessManager) monitorProcessMemory(pid int) (map[string]interface{}, error) {
	memory := make(map[string]interface{})

	// Use tasklist to get memory information
	cmd := exec.Command("tasklist", "/FI", fmt.Sprintf("PID eq %d", pid), "/FO", "CSV", "/NH")
	output, err := cmd.Output()
	if err != nil {
		return memory, err
	}

	lines := strings.Split(string(output), "\n")
	if len(lines) > 0 && lines[0] != "" {
		fields := strings.Split(strings.Trim(lines[0], "\""), "\",\"")
		if len(fields) >= 5 {
			// Parse memory usage (format: "1,234 K")
			memStr := strings.ReplaceAll(fields[4], ",", "")
			memStr = strings.ReplaceAll(memStr, " K", "")
			if memKB, err := strconv.ParseInt(memStr, 10, 64); err == nil {
				memory["working_set"] = memKB * 1024 // Convert to bytes
			}
		}
	}

	return memory, nil
}

// sendCtrlBreak sends Ctrl+Break signal to a process on Windows
func (ppm *PlatformProcessManager) sendCtrlBreak(pid int) error {
	// This is a simplified implementation
	// A full implementation would use GenerateConsoleCtrlEvent Windows API
	return fmt.Errorf("Ctrl+Break not implemented")
}

// getPlatformSpecificInfo returns Windows-specific process information
func (ppm *PlatformProcessManager) getPlatformSpecificInfo() map[string]interface{} {
	info := make(map[string]interface{})

	info["platform"] = "windows"
	info["has_proc_fs"] = false
	info["supports_process_groups"] = false
	info["supports_signals"] = false
	info["supports_credentials"] = false
	info["has_tasklist"] = true
	info["has_wmic"] = true

	return info
}

// Helper function to check if a Windows service/tool is available
func (ppm *PlatformProcessManager) checkToolAvailability(tool string) bool {
	cmd := exec.Command(tool, "/?")
	err := cmd.Run()
	return err == nil
}