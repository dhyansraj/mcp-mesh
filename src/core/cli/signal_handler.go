package cli

import (
	"context"
	"log"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

// SignalHandler manages graceful shutdown and signal handling
type SignalHandler struct {
	shutdownCallbacks []func() error
	mutex             sync.RWMutex
	logger            *log.Logger
	shutdownTimeout   time.Duration
	shutdownChan      chan struct{}
	shutdownOnce      sync.Once
}

// ProcessCleanupManager handles cleanup operations during shutdown
type ProcessCleanupManager struct {
	processManager *ProcessManager
	logger         *log.Logger
	cleanupTimeout time.Duration
}

// NewSignalHandler creates a new signal handler
func NewSignalHandler() *SignalHandler {
	return &SignalHandler{
		shutdownCallbacks: make([]func() error, 0),
		logger:            log.New(os.Stdout, "[SignalHandler] ", log.LstdFlags),
		shutdownTimeout:   30 * time.Second,
		shutdownChan:      make(chan struct{}),
	}
}

// NewProcessCleanupManager creates a new process cleanup manager
func NewProcessCleanupManager(pm *ProcessManager) *ProcessCleanupManager {
	return &ProcessCleanupManager{
		processManager: pm,
		logger:         log.New(os.Stdout, "[ProcessCleanup] ", log.LstdFlags),
		cleanupTimeout: 30 * time.Second,
	}
}

// RegisterShutdownCallback adds a callback to be executed during shutdown
func (sh *SignalHandler) RegisterShutdownCallback(callback func() error) {
	sh.mutex.Lock()
	defer sh.mutex.Unlock()

	sh.shutdownCallbacks = append(sh.shutdownCallbacks, callback)
}

// SetShutdownTimeout sets the timeout for shutdown operations
func (sh *SignalHandler) SetShutdownTimeout(timeout time.Duration) {
	sh.shutdownTimeout = timeout
}

// StartSignalHandling starts listening for system signals
func (sh *SignalHandler) StartSignalHandling() {
	signalChan := make(chan os.Signal, 1)

	// Register for interrupt signals
	signal.Notify(signalChan,
		os.Interrupt,    // SIGINT (Ctrl+C)
		syscall.SIGTERM, // SIGTERM (termination request)
		syscall.SIGHUP,  // SIGHUP (hangup)
	)

	go sh.handleSignals(signalChan)
	sh.logger.Println("Started signal handling")
}

// handleSignals processes incoming signals
func (sh *SignalHandler) handleSignals(signalChan chan os.Signal) {
	for sig := range signalChan {
		sh.logger.Printf("Received signal: %v", sig)

		switch sig {
		case os.Interrupt, syscall.SIGTERM:
			sh.logger.Println("Initiating graceful shutdown...")
			sh.gracefulShutdown()
			return
		case syscall.SIGHUP:
			sh.logger.Println("Received SIGHUP, reloading configuration...")
			sh.handleReload()
		}
	}
}

// gracefulShutdown performs a graceful shutdown of all processes
func (sh *SignalHandler) gracefulShutdown() {
	sh.shutdownOnce.Do(func() {
		close(sh.shutdownChan)

		sh.logger.Println("Starting graceful shutdown sequence...")

		// Create context with timeout
		ctx, cancel := context.WithTimeout(context.Background(), sh.shutdownTimeout)
		defer cancel()

		// Execute shutdown callbacks in reverse order
		sh.mutex.RLock()
		callbacks := make([]func() error, len(sh.shutdownCallbacks))
		copy(callbacks, sh.shutdownCallbacks)
		sh.mutex.RUnlock()

		for i := len(callbacks) - 1; i >= 0; i-- {
			func() {
				defer func() {
					if r := recover(); r != nil {
						sh.logger.Printf("Panic during shutdown callback: %v", r)
					}
				}()

				callbackDone := make(chan error, 1)
				go func() {
					callbackDone <- callbacks[i]()
				}()

				select {
				case err := <-callbackDone:
					if err != nil {
						sh.logger.Printf("Error during shutdown callback: %v", err)
					}
				case <-ctx.Done():
					sh.logger.Printf("Shutdown callback timed out")
				}
			}()
		}

		sh.logger.Println("Graceful shutdown completed")
		os.Exit(0)
	})
}

// handleReload handles configuration reload signals
func (sh *SignalHandler) handleReload() {
	// Reload configuration
	config := GetCLIConfig()
	if err := config.Load(); err != nil {
		sh.logger.Printf("Error reloading configuration: %v", err)
		return
	}

	sh.logger.Println("Configuration reloaded successfully")
}

// IsShuttingDown returns true if shutdown has been initiated
func (sh *SignalHandler) IsShuttingDown() bool {
	select {
	case <-sh.shutdownChan:
		return true
	default:
		return false
	}
}

// WaitForShutdown blocks until shutdown is initiated
func (sh *SignalHandler) WaitForShutdown() {
	<-sh.shutdownChan
}

// PerformProcessCleanup performs comprehensive process cleanup
func (pcm *ProcessCleanupManager) PerformProcessCleanup() error {
	pcm.logger.Println("Starting process cleanup...")

	// Step 1: Stop health monitoring
	pcm.processManager.StopHealthMonitoring()

	// Step 2: Get all managed processes
	processes := pcm.processManager.GetAllProcesses()

	if len(processes) == 0 {
		pcm.logger.Println("No processes to clean up")
		return nil
	}

	// Step 3: Stop agents first (graceful)
	agentErrors := pcm.stopAgentProcesses(processes)

	// Step 4: Stop registry services (graceful)
	registryErrors := pcm.stopRegistryProcesses(processes)

	// Step 5: Force kill any remaining processes
	forceErrors := pcm.forceKillRemainingProcesses()

	// Step 6: Clean up orphaned processes
	orphanErrors := pcm.cleanupOrphanedProcesses()

	// Step 7: Clear process state
	pcm.processManager.clearAllProcesses()

	// Collect all errors
	var allErrors []error
	allErrors = append(allErrors, agentErrors...)
	allErrors = append(allErrors, registryErrors...)
	allErrors = append(allErrors, forceErrors...)
	allErrors = append(allErrors, orphanErrors...)

	if len(allErrors) > 0 {
		pcm.logger.Printf("Process cleanup completed with %d errors", len(allErrors))
		return allErrors[0] // Return first error
	}

	pcm.logger.Println("Process cleanup completed successfully")
	return nil
}

// stopAgentProcesses stops all agent processes gracefully
func (pcm *ProcessCleanupManager) stopAgentProcesses(processes map[string]*ProcessInfo) []error {
	var errors []error

	pcm.logger.Println("Stopping agent processes...")

	for name, info := range processes {
		if info.ServiceType == "agent" {
			pcm.logger.Printf("Stopping agent: %s", name)
			if err := pcm.processManager.StopProcess(name, 10*time.Second); err != nil {
				pcm.logger.Printf("Error stopping agent %s: %v", name, err)
				errors = append(errors, err)
			}
		}
	}

	return errors
}

// stopRegistryProcesses stops all registry processes gracefully
func (pcm *ProcessCleanupManager) stopRegistryProcesses(processes map[string]*ProcessInfo) []error {
	var errors []error

	pcm.logger.Println("Stopping registry processes...")

	for name, info := range processes {
		if info.ServiceType == "registry" {
			pcm.logger.Printf("Stopping registry: %s", name)
			if err := pcm.processManager.StopProcess(name, 15*time.Second); err != nil {
				pcm.logger.Printf("Error stopping registry %s: %v", name, err)
				errors = append(errors, err)
			}
		}
	}

	return errors
}

// forceKillRemainingProcesses force kills any processes that didn't stop gracefully
func (pcm *ProcessCleanupManager) forceKillRemainingProcesses() []error {
	var errors []error

	processes := pcm.processManager.GetAllProcesses()

	for name, info := range processes {
		if info.Status == "running" {
			pcm.logger.Printf("Force killing remaining process: %s", name)
			if err := pcm.processManager.TerminateProcess(name, 5*time.Second); err != nil {
				pcm.logger.Printf("Error force killing %s: %v", name, err)
				errors = append(errors, err)
			}
		}
	}

	return errors
}

// cleanupOrphanedProcesses finds and cleans up orphaned MCP processes
func (pcm *ProcessCleanupManager) cleanupOrphanedProcesses() []error {
	var errors []error

	pcm.logger.Println("Checking for orphaned MCP processes...")

	// This is a simplified implementation
	// In a full implementation, we would scan for processes matching MCP patterns
	// and clean them up if they're not in our process tracker

	return errors
}

// clearAllProcesses removes all processes from tracking
func (pm *ProcessManager) clearAllProcesses() {
	pm.mutex.Lock()
	defer pm.mutex.Unlock()

	pm.processes = make(map[string]*ProcessInfo)
	pm.saveState()
}

// SetupGracefulShutdown sets up signal handling and cleanup for the CLI
func SetupGracefulShutdown(pm *ProcessManager) *SignalHandler {
	signalHandler := NewSignalHandler()
	cleanupManager := NewProcessCleanupManager(pm)

	// Register process cleanup callback
	signalHandler.RegisterShutdownCallback(func() error {
		return cleanupManager.PerformProcessCleanup()
	})

	// Start signal handling
	signalHandler.StartSignalHandling()

	return signalHandler
}

// ProcessTree represents a hierarchical view of processes
type ProcessTree struct {
	logger *log.Logger
}

// NewProcessTree creates a new process tree manager
func NewProcessTree() *ProcessTree {
	return &ProcessTree{
		logger: log.New(os.Stdout, "[ProcessTree] ", log.LstdFlags),
	}
}

// TerminateProcessTree terminates an entire process tree (parent and all children)
func (pt *ProcessTree) TerminateProcessTree(pid int, timeout time.Duration) error {
	pt.logger.Printf("Terminating process tree for PID: %d", pid)

	// Find the process
	process, err := os.FindProcess(pid)
	if err != nil {
		return err
	}

	// On Unix systems, we can use process groups
	// First try to terminate the process group
	if err := pt.terminateProcessGroup(pid, timeout); err != nil {
		pt.logger.Printf("Process group termination failed, trying individual process: %v", err)
		// Fall back to terminating just the main process
		return pt.terminateIndividualProcess(process, timeout)
	}

	return nil
}

// terminateProcessGroup terminates a process group (Unix-specific)
func (pt *ProcessTree) terminateProcessGroup(pid int, timeout time.Duration) error {
	// Send SIGTERM to the process group
	if err := syscall.Kill(-pid, syscall.SIGTERM); err != nil {
		return err
	}

	// Wait for processes to terminate
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		// Check if process group still exists
		if err := syscall.Kill(-pid, 0); err != nil {
			// Process group no longer exists
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Force kill if timeout exceeded
	pt.logger.Printf("Process group %d timeout, sending SIGKILL", pid)
	return syscall.Kill(-pid, syscall.SIGKILL)
}

// terminateIndividualProcess terminates a single process
func (pt *ProcessTree) terminateIndividualProcess(process *os.Process, timeout time.Duration) error {
	// Send SIGTERM
	if err := process.Signal(os.Interrupt); err != nil {
		return err
	}

	// Wait for graceful termination
	done := make(chan error, 1)
	go func() {
		_, err := process.Wait()
		done <- err
	}()

	select {
	case err := <-done:
		return err
	case <-time.After(timeout):
		// Force kill
		return process.Kill()
	}
}

// FindOrphanedMCPProcesses finds MCP-related processes that might be orphaned
func (pt *ProcessTree) FindOrphanedMCPProcesses() ([]int, error) {
	// This is a simplified implementation
	// In a full implementation, we would:
	// 1. List all processes on the system
	// 2. Filter for MCP-related processes (by command line, executable name, etc.)
	// 3. Return PIDs of processes that aren't in our process tracker

	var orphanedPIDs []int

	// For now, return empty list
	// Real implementation would use system-specific process enumeration

	return orphanedPIDs, nil
}

// Global signal handler instance
var globalSignalHandler *SignalHandler
var shMutex sync.Mutex

// GetGlobalSignalHandler returns the global signal handler instance
func GetGlobalSignalHandler() *SignalHandler {
	shMutex.Lock()
	defer shMutex.Unlock()

	if globalSignalHandler == nil {
		pm := GetGlobalProcessManager()
		globalSignalHandler = SetupGracefulShutdown(pm)
	}

	return globalSignalHandler
}
