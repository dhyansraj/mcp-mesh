// +build !windows

package cli

import (
	"log"
	"os"
	"os/exec"
	"syscall"
	"time"
)

// PlatformProcessManager provides Unix-specific process management functionality
type PlatformProcessManager struct {
	logger *log.Logger
}

// NewPlatformProcessManager creates a platform-specific process manager
func NewPlatformProcessManager() *PlatformProcessManager {
	return &PlatformProcessManager{
		logger: log.New(os.Stdout, "[PlatformProcess] ", log.LstdFlags),
	}
}

// terminateProcessGracefully terminates a process gracefully using Unix signals
func (ppm *PlatformProcessManager) terminateProcessGracefully(process *os.Process, timeout time.Duration) error {
	// Send SIGTERM for graceful shutdown
	if err := process.Signal(syscall.SIGTERM); err != nil {
		return err
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
		// Force kill with SIGKILL
		return process.Signal(syscall.SIGKILL)
	}
}

// killProcessForcefully kills a process immediately
func (ppm *PlatformProcessManager) killProcessForcefully(process *os.Process) error {
	return process.Signal(syscall.SIGKILL)
}

// isProcessRunning checks if a process is running using Unix signal 0
func (ppm *PlatformProcessManager) isProcessRunning(pid int) bool {
	process, err := os.FindProcess(pid)
	if err != nil {
		return false
	}

	// Send signal 0 to check if process exists
	err = process.Signal(syscall.Signal(0))
	return err == nil
}

// setProcessGroup sets the process group for a command (Unix-specific)
func (ppm *PlatformProcessManager) setProcessGroup(cmd *exec.Cmd) {
	// Set process group ID to enable group termination
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
	}
}

// terminateProcessGroup terminates an entire process group
func (ppm *PlatformProcessManager) terminateProcessGroup(pgid int, timeout time.Duration) error {
	// Send SIGTERM to the process group
	if err := syscall.Kill(-pgid, syscall.SIGTERM); err != nil {
		return err
	}

	// Wait for processes to terminate
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		// Check if process group still exists
		if err := syscall.Kill(-pgid, 0); err != nil {
			// Process group no longer exists
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Force kill the process group
	return syscall.Kill(-pgid, syscall.SIGKILL)
}

// getProcessDetails gets detailed process information (Unix-specific)
func (ppm *PlatformProcessManager) getProcessDetails(pid int) (map[string]interface{}, error) {
	details := make(map[string]interface{})

	// Read from /proc filesystem
	if procInfo, err := ppm.readProcInfo(pid); err == nil {
		details["proc_info"] = procInfo
	}

	details["platform"] = "unix"
	return details, nil
}

// readProcInfo reads process information from /proc filesystem
func (ppm *PlatformProcessManager) readProcInfo(pid int) (map[string]interface{}, error) {
	// This is a simplified implementation
	// A full implementation would parse /proc/[pid]/stat, /proc/[pid]/status, etc.
	
	info := make(map[string]interface{})
	info["available"] = true
	
	return info, nil
}

// setupSignalHandling sets up Unix-specific signal handling
func (ppm *PlatformProcessManager) setupSignalHandling() []os.Signal {
	return []os.Signal{
		os.Interrupt,    // SIGINT (Ctrl+C)
		syscall.SIGTERM, // SIGTERM
		syscall.SIGHUP,  // SIGHUP
		syscall.SIGQUIT, // SIGQUIT
	}
}

// getUserCredentials gets user credentials for process management
func (ppm *PlatformProcessManager) getUserCredentials() (map[string]interface{}, error) {
	creds := make(map[string]interface{})
	
	// Get user and group IDs
	creds["uid"] = os.Getuid()
	creds["gid"] = os.Getgid()
	creds["euid"] = os.Geteuid()
	creds["egid"] = os.Getegid()
	
	return creds, nil
}

// setProcessCredentials sets process credentials (Unix-specific)
func (ppm *PlatformProcessManager) setProcessCredentials(cmd *exec.Cmd, uid, gid int) {
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	
	cmd.SysProcAttr.Credential = &syscall.Credential{
		Uid: uint32(uid),
		Gid: uint32(gid),
	}
}

// findProcessesByName finds processes by name pattern (Unix-specific)
func (ppm *PlatformProcessManager) findProcessesByName(pattern string) ([]int, error) {
	// This would typically use ps or scan /proc
	// Simplified implementation
	var pids []int
	
	// In a real implementation, we would:
	// 1. Execute: ps -eo pid,comm
	// 2. Filter by pattern
	// 3. Return matching PIDs
	
	return pids, nil
}

// getSystemResourceUsage gets system resource usage information
func (ppm *PlatformProcessManager) getSystemResourceUsage() (map[string]interface{}, error) {
	usage := make(map[string]interface{})
	
	// This would typically read from /proc/loadavg, /proc/meminfo, etc.
	// Simplified implementation
	usage["load_avg"] = []float64{0.0, 0.0, 0.0}
	usage["memory_total"] = 0
	usage["memory_free"] = 0
	usage["cpu_count"] = 1
	
	return usage, nil
}

// createDaemonProcess creates a daemon process (Unix-specific)
func (ppm *PlatformProcessManager) createDaemonProcess(cmd *exec.Cmd) error {
	// Set up daemon process attributes
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	
	// Create new session and process group
	cmd.SysProcAttr.Setsid = true
	cmd.SysProcAttr.Setpgid = true
	
	// Redirect standard file descriptors to /dev/null
	devNull, err := os.OpenFile(os.DevNull, os.O_RDWR, 0)
	if err != nil {
		return err
	}
	
	cmd.Stdin = devNull
	cmd.Stdout = devNull
	cmd.Stderr = devNull
	
	return nil
}

// monitorProcessMemory monitors memory usage of a process
func (ppm *PlatformProcessManager) monitorProcessMemory(pid int) (map[string]interface{}, error) {
	memory := make(map[string]interface{})
	
	// Read from /proc/[pid]/status or /proc/[pid]/statm
	// Simplified implementation
	memory["rss"] = 0    // Resident set size
	memory["vms"] = 0    // Virtual memory size
	memory["shared"] = 0 // Shared memory
	
	return memory, nil
}

// getPlatformSpecificInfo returns platform-specific process information
func (ppm *PlatformProcessManager) getPlatformSpecificInfo() map[string]interface{} {
	info := make(map[string]interface{})
	
	info["platform"] = "unix"
	info["has_proc_fs"] = true
	info["supports_process_groups"] = true
	info["supports_signals"] = true
	info["supports_credentials"] = true
	
	return info
}