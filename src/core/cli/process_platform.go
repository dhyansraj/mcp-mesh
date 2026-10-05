//go:build !windows
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

	// Wait for processes to terminate with frequent checks for FastAPI agents
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		// Check if process group still exists
		if err := syscall.Kill(-pgid, 0); err != nil {
			// Process group no longer exists
			return nil
		}
		time.Sleep(50 * time.Millisecond) // Optimized for FastAPI agents that terminate quickly
	}

	// Force kill the process group
	return syscall.Kill(-pgid, syscall.SIGKILL)
}
