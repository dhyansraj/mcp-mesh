//go:build !windows
// +build !windows

package cli

import (
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/fsnotify/fsnotify"

	"mcp-mesh/src/core/cli/lifecycle"
)

// WatchConfig holds configuration for the AgentWatcher.
type WatchConfig struct {
	ProjectRoot   string        // project root (for logging)
	WatchDir      string        // directory to watch recursively (e.g., projectRoot/src)
	Extensions    []string      // file extensions to watch: ".java", ".yml", ".yaml", ".properties", ".xml"
	ExcludeDirs   []string      // directories to skip: "target", ".git", ".idea", "node_modules", ".mvn"
	DebounceDelay time.Duration // default 500ms, configurable via MCP_MESH_RELOAD_DEBOUNCE env var
	PortDelay     time.Duration // delay after kill for port release, default 500ms, configurable via MCP_MESH_RELOAD_PORT_DELAY
	StopTimeout   time.Duration // SIGTERM -> SIGKILL timeout, default 3s
	AgentName         string        // for logging
	LogFileFactory    func() (*os.File, error) // returns fresh log file (with rotation); nil = use os.Stdout
	PreRestartCheck   func() error  // optional: validate before killing agent (e.g., compile check)
	PIDUpdateCallback func(pid int) // Called after agent starts/restarts with new PID
}

// AgentWatcher provides event-driven file watching with process restart capability.
type AgentWatcher struct {
	config     WatchConfig
	cmdFactory func() *exec.Cmd
	watcher    *fsnotify.Watcher
	currentCmd *exec.Cmd
	mu         sync.Mutex
	stopChan   chan struct{}
	doneChan   chan struct{}
	stopOnce       sync.Once
	quiet          bool
	currentLogFile *os.File
}

// NewAgentWatcher creates a new AgentWatcher with the given config, command factory, and quiet flag.
func NewAgentWatcher(config WatchConfig, cmdFactory func() *exec.Cmd, quiet bool) *AgentWatcher {
	return &AgentWatcher{
		config:     config,
		cmdFactory: cmdFactory,
		stopChan:   make(chan struct{}),
		doneChan:   make(chan struct{}),
		quiet:      quiet,
	}
}

// Start begins watching for file changes and managing the agent process. It blocks until Stop is called.
func (aw *AgentWatcher) Start() error {
	var err error
	aw.watcher, err = fsnotify.NewWatcher()
	if err != nil {
		return fmt.Errorf("failed to create file watcher: %w", err)
	}

	// Walk the watch directory recursively, adding each qualifying subdirectory
	err = filepath.WalkDir(aw.config.WatchDir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil // skip directories we can't read
		}
		if !d.IsDir() {
			return nil
		}

		basename := filepath.Base(path)

		// Skip hidden directories
		if strings.HasPrefix(basename, ".") && path != aw.config.WatchDir {
			return filepath.SkipDir
		}

		// Skip excluded directories
		for _, excl := range aw.config.ExcludeDirs {
			if basename == excl {
				return filepath.SkipDir
			}
		}

		if addErr := aw.watcher.Add(path); addErr != nil {
			// Non-fatal: log and continue
			if !aw.quiet {
				fmt.Printf("Warning: could not watch %s: %v\n", path, addErr)
			}
		}
		return nil
	})
	if err != nil {
		aw.watcher.Close()
		return fmt.Errorf("failed to walk watch directory %s: %w", aw.config.WatchDir, err)
	}

	// Start initial process. We deliberately do NOT inject MCP_MESH_HTTP_PORT=0
	// here: the configured port is honored on initial start. On reload,
	// restartAgent calls lifecycle.KillVerifyAndCleanup which polls until the
	// previous PID is dead before the new process binds, so the same port is
	// always free again — no random-port workaround needed.
	aw.mu.Lock()
	cmd := aw.cmdFactory()
	if aw.config.LogFileFactory != nil {
		if logFile, err := aw.config.LogFileFactory(); err == nil {
			cmd.Stdout = logFile
			cmd.Stderr = logFile
			aw.currentLogFile = logFile
		} else if !aw.quiet {
			fmt.Printf("Warning: failed to create log file for %s: %v\n", aw.config.AgentName, err)
		}
	}
	if err := cmd.Start(); err != nil {
		aw.mu.Unlock()
		aw.watcher.Close()
		return fmt.Errorf("failed to start initial agent process: %w", err)
	}
	aw.currentCmd = cmd
	aw.mu.Unlock()

	if aw.config.PIDUpdateCallback != nil {
		aw.config.PIDUpdateCallback(cmd.Process.Pid)
	}

	if !aw.quiet {
		fmt.Printf("Watch mode: watching %s for changes\n", aw.config.WatchDir)
	}

	// Debounce setup
	var debounceTimer *time.Timer
	restartCh := make(chan struct{}, 1)

	// Process exit monitoring for the initial process
	exitCh := make(chan struct{}, 1)
	go func() {
		cmd.Wait()
		select {
		case exitCh <- struct{}{}:
		default:
		}
	}()

	defer func() {
		aw.watcher.Close()
		if aw.currentLogFile != nil {
			aw.currentLogFile.Close()
		}
		close(aw.doneChan)
	}()

	for {
		select {
		case event, ok := <-aw.watcher.Events:
			if !ok {
				return nil
			}
			if aw.shouldWatch(event) {
				if debounceTimer != nil {
					debounceTimer.Stop()
				}
				debounceTimer = time.AfterFunc(aw.config.DebounceDelay, func() {
					select {
					case restartCh <- struct{}{}:
					default:
					}
				})
			}

		case err, ok := <-aw.watcher.Errors:
			if !ok {
				return nil
			}
			if !aw.quiet {
				fmt.Printf("Watch error: %v\n", err)
			}

		case <-restartCh:
			aw.restartAgent(&exitCh)

		case <-exitCh:
			if !aw.quiet {
				fmt.Println("Agent process exited")
			}
			// Do NOT auto-restart; wait for a file change

		case <-aw.stopChan:
			if debounceTimer != nil {
				debounceTimer.Stop()
			}
			aw.terminateAgent()
			return nil
		}
	}
}

// shouldWatch determines whether a file system event should trigger a rebuild.
func (aw *AgentWatcher) shouldWatch(event fsnotify.Event) bool {
	// If a new directory was created, add it to the watcher
	if event.Has(fsnotify.Create) {
		info, err := os.Stat(event.Name)
		if err == nil && info.IsDir() {
			basename := filepath.Base(event.Name)
			// Don't watch hidden or excluded dirs
			if !strings.HasPrefix(basename, ".") {
				excluded := false
				for _, excl := range aw.config.ExcludeDirs {
					if basename == excl {
						excluded = true
						break
					}
				}
				if !excluded {
					aw.watcher.Add(event.Name)
				}
			}
			return false
		}
	}

	// Only pass Write, Create, Rename operations
	if !event.Has(fsnotify.Write) && !event.Has(fsnotify.Create) && !event.Has(fsnotify.Rename) {
		return false
	}

	basename := filepath.Base(event.Name)

	// Skip hidden files
	if strings.HasPrefix(basename, ".") {
		return false
	}

	// Skip editor temp files
	if strings.HasSuffix(basename, "~") ||
		strings.HasSuffix(basename, ".swp") ||
		strings.HasSuffix(basename, ".tmp") ||
		strings.HasSuffix(basename, ".bak") {
		return false
	}

	// Check if any path component matches an excluded directory
	parts := strings.Split(event.Name, string(os.PathSeparator))
	for _, part := range parts {
		for _, excl := range aw.config.ExcludeDirs {
			if part == excl {
				return false
			}
		}
	}

	// Check file extension
	ext := filepath.Ext(event.Name)
	for _, watchExt := range aw.config.Extensions {
		if ext == watchExt {
			return true
		}
	}

	return false
}

// terminateAgent sends SIGTERM to the current agent's process group, then SIGKILL if it doesn't exit in time.
func (aw *AgentWatcher) terminateAgent() {
	aw.mu.Lock()
	defer aw.mu.Unlock()

	if aw.currentCmd == nil || aw.currentCmd.Process == nil {
		return
	}

	pid := aw.currentCmd.Process.Pid
	// Process group ID equals PID since we set Setpgid
	pgid := pid

	// Send SIGTERM to the process group
	if err := syscall.Kill(-pgid, syscall.SIGTERM); err != nil {
		// Process may already be dead
		aw.currentCmd = nil
		return
	}

	// Poll every 50ms until StopTimeout
	deadline := time.Now().Add(aw.config.StopTimeout)
	for time.Now().Before(deadline) {
		if err := syscall.Kill(-pgid, 0); err != nil {
			// Process group no longer exists
			aw.currentCmd = nil
			return
		}
		time.Sleep(50 * time.Millisecond)
	}

	// Force kill
	syscall.Kill(-pgid, syscall.SIGKILL)
	aw.currentCmd = nil
}

// shutdownCurrentForRestart stops the current agent process and waits for the
// kernel to confirm it's gone, removing the on-disk PID file as a side
// effect. Returns an error if the process refuses to die within the kill
// budget — caller MUST treat this as "do not restart".
//
// This is the deterministic synchronization point for watch-mode reload: by
// the time it returns nil, the previous PID is dead AND its <agent>.pid file
// is gone, so the new process can safely bind to the same configured port.
//
// Implementation: clears aw.currentCmd up front (so the local exit reaper
// doesn't race with our explicit kill), then routes through
// lifecycle.KillVerifyAndCleanup which polls until dead and removes the .pid
// file. Falls back to a direct process-group SIGTERM if the lifecycle layer
// has no PID file (e.g., agent name lookup failed at startup).
func (aw *AgentWatcher) shutdownCurrentForRestart() error {
	aw.mu.Lock()
	cmd := aw.currentCmd
	aw.currentCmd = nil
	aw.mu.Unlock()

	if cmd == nil || cmd.Process == nil {
		return nil
	}

	name := aw.config.AgentName
	if name != "" {
		if _, err := lifecycle.KillVerifyAndCleanup(name, aw.config.StopTimeout); err == nil {
			return nil
		} else if !aw.quiet {
			// Non-fatal — fall through to the direct-PID fallback so we still
			// try to stop the process even if the .pid file lookup misfired.
			fmt.Printf("[watch] lifecycle kill for %s reported: %v (falling back to direct signal)\n", name, err)
		}
	}

	pid := cmd.Process.Pid
	pgid := pid
	_ = syscall.Kill(-pgid, syscall.SIGTERM)
	deadline := time.Now().Add(aw.config.StopTimeout)
	for time.Now().Before(deadline) {
		if err := syscall.Kill(-pgid, 0); err != nil {
			return nil
		}
		time.Sleep(50 * time.Millisecond)
	}
	_ = syscall.Kill(-pgid, syscall.SIGKILL)
	deadline = time.Now().Add(1 * time.Second)
	for time.Now().Before(deadline) {
		if err := syscall.Kill(-pgid, 0); err != nil {
			return nil
		}
		time.Sleep(50 * time.Millisecond)
	}
	if err := syscall.Kill(-pgid, 0); err == nil {
		return fmt.Errorf("process %d still alive after SIGKILL", pid)
	}
	return nil
}

// restartAgent terminates the current agent and starts a new one.
//
// Termination is delegated to lifecycle.KillVerifyAndCleanup which polls until
// the kernel confirms the previous PID is dead (treating zombies as dead) and
// removes <agent>.pid + <agent>.group bookkeeping. This is what makes
// watch-mode reload deterministic: the new process never tries to bind to a
// port that the old process is still holding. If the old process refuses to
// die within the 3s timeout, we SKIP the restart with a loud error rather
// than blindly racing — the next file-change event can retry once the user
// notices.
func (aw *AgentWatcher) restartAgent(exitCh *chan struct{}) {
	// Pre-restart validation (compile check)
	if aw.config.PreRestartCheck != nil {
		if !aw.quiet {
			fmt.Printf("[watch] Running pre-restart check for %s...\n", aw.config.AgentName)
		}
		if err := aw.config.PreRestartCheck(); err != nil {
			if !aw.quiet {
				fmt.Printf("[watch] Pre-restart check failed, keeping current agent running:\n%v\n", err)
			}
			return // Don't kill the agent — wait for next file change
		}
	}

	if !aw.quiet {
		fmt.Println("Restarting agent...")
	}

	// Terminate by routing through the lifecycle layer. KillVerifyAndCleanup
	// reads <agent>.pid (kept in sync by PIDUpdateCallback), sends SIGTERM to
	// the process group, polls until dead, escalates to SIGKILL, and removes
	// the .pid + .group files on confirmed death. On timeout it returns an
	// error WITHOUT removing files, so we know the old process is still
	// holding the port and skip the restart.
	if err := aw.shutdownCurrentForRestart(); err != nil {
		if !aw.quiet {
			fmt.Printf("[watch] ERROR: failed to stop %s for restart, skipping this reload: %v\n", aw.config.AgentName, err)
			fmt.Printf("[watch] The agent may be stuck. Save the file again to retry, or run 'meshctl stop %s' manually.\n", aw.config.AgentName)
		}
		return
	}

	aw.mu.Lock()
	// Close old log file before starting new one
	if aw.currentLogFile != nil {
		aw.currentLogFile.Close()
		aw.currentLogFile = nil
	}
	cmd := aw.cmdFactory()
	if aw.config.LogFileFactory != nil {
		if logFile, err := aw.config.LogFileFactory(); err == nil {
			cmd.Stdout = logFile
			cmd.Stderr = logFile
			aw.currentLogFile = logFile
		} else if !aw.quiet {
			fmt.Printf("Warning: failed to create log file for %s: %v\n", aw.config.AgentName, err)
		}
	}
	if err := cmd.Start(); err != nil {
		aw.mu.Unlock()
		if !aw.quiet {
			fmt.Printf("Failed to restart agent: %v\n", err)
		}
		return
	}
	aw.currentCmd = cmd
	aw.mu.Unlock()

	if aw.config.PIDUpdateCallback != nil {
		aw.config.PIDUpdateCallback(cmd.Process.Pid)
	}

	if !aw.quiet {
		fmt.Printf("Agent restarted (PID: %d)\n", cmd.Process.Pid)
	}

	// Start new exit monitoring goroutine with a fresh channel
	newExitCh := make(chan struct{}, 1)
	*exitCh = newExitCh
	go func() {
		cmd.Wait()
		select {
		case newExitCh <- struct{}{}:
		default:
		}
	}()
}

// Stop signals the watcher to shut down. Safe to call multiple times.
func (aw *AgentWatcher) Stop() {
	aw.stopOnce.Do(func() {
		close(aw.stopChan)
	})
}

// Wait blocks until the watcher has fully stopped.
func (aw *AgentWatcher) Wait() {
	<-aw.doneChan
}

// GetPID returns the PID of the currently running agent process, or 0 if none.
func (aw *AgentWatcher) GetPID() int {
	aw.mu.Lock()
	defer aw.mu.Unlock()

	if aw.currentCmd != nil && aw.currentCmd.Process != nil {
		return aw.currentCmd.Process.Pid
	}
	return 0
}

// getWatchDebounceDelay reads the MCP_MESH_RELOAD_DEBOUNCE env var and returns the debounce delay.
// Falls back to 500ms if not set or invalid.
func getWatchDebounceDelay() time.Duration {
	val := os.Getenv("MCP_MESH_RELOAD_DEBOUNCE")
	if val == "" {
		return 500 * time.Millisecond
	}
	seconds, err := strconv.ParseFloat(val, 64)
	if err != nil || seconds <= 0 {
		return 500 * time.Millisecond
	}
	return time.Duration(seconds * float64(time.Second))
}

// getWatchPortDelay reads the MCP_MESH_RELOAD_PORT_DELAY env var and returns the port release delay.
// Falls back to 500ms if not set or invalid.
func getWatchPortDelay() time.Duration {
	val := os.Getenv("MCP_MESH_RELOAD_PORT_DELAY")
	if val == "" {
		return 500 * time.Millisecond
	}
	seconds, err := strconv.ParseFloat(val, 64)
	if err != nil || seconds <= 0 {
		return 500 * time.Millisecond
	}
	return time.Duration(seconds * float64(time.Second))
}

// getWatchPrecheckEnabled reads the MCP_MESH_RELOAD_PRECHECK env var and returns whether pre-restart checks are enabled.
// Defaults to true (enabled) if not set.
func getWatchPrecheckEnabled() bool {
	val := os.Getenv("MCP_MESH_RELOAD_PRECHECK")
	if val == "" {
		return true // enabled by default
	}
	return parseBoolEnv(val) // parseBoolEnv is in config.go (same package)
}
