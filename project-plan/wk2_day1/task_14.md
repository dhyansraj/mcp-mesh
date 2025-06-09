# Task 14: Process Management and Monitoring (30 minutes)

## Overview: Critical Architecture Preservation
**⚠️ IMPORTANT**: This migration only replaces the registry service and CLI with Go. ALL Python decorator functionality must remain unchanged:
- `@mesh_agent` decorator analysis and metadata extraction (Python)
- Dependency injection and resolution (Python) 
- Service discovery and proxy creation (Python)
- Auto-registration and heartbeat mechanisms (Python)

**Reference Documents**:
- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/decorators/mesh_agent.py` - Core decorator implementation
- `packages/mcp_mesh_runtime/src/mcp_mesh_runtime/server/registry_server.py` - Current registry API

## CRITICAL PRESERVATION REQUIREMENT
**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI process management and monitoring functionality.

**Reference Preservation**:
- Keep ALL Python CLI process management code as reference during migration
- Test EVERY existing process monitoring and lifecycle management feature
- Maintain IDENTICAL behavior for all process management operations
- Preserve ALL health monitoring and status reporting functionality

**Implementation Validation**:
- Each Go process management feature must pass Python CLI behavior tests
- Process lifecycle management must work identically to Python version
- Health monitoring must match Python implementation exactly

## Objective
Implement complete process management and monitoring system maintaining identical behavior to Python

## Reference
`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/` directory

## Detailed Implementation

### 8.1: Complete process management system
```go
// Process tracking and management
type ProcessManager struct {
    processes map[string]*ProcessInfo
    mutex     sync.RWMutex
    logger    *log.Logger
}

type ProcessInfo struct {
    PID         int       `json:"pid"`
    Name        string    `json:"name"`
    Command     string    `json:"command"`
    StartTime   time.Time `json:"start_time"`
    Status      string    `json:"status"`
    HealthCheck string    `json:"health_check"`
    LastSeen    time.Time `json:"last_seen"`
    Restarts    int       `json:"restarts"`
    Process     *os.Process
}

func NewProcessManager() *ProcessManager {
    return &ProcessManager{
        processes: make(map[string]*ProcessInfo),
        logger:    log.New(os.Stdout, "[ProcessManager] ", log.LstdFlags),
    }
}

func (pm *ProcessManager) RegisterProcess(name, command string, process *os.Process) {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()
    
    pm.processes[name] = &ProcessInfo{
        PID:         process.Pid,
        Name:        name,
        Command:     command,
        StartTime:   time.Now(),
        Status:      "running",
        HealthCheck: "unknown",
        LastSeen:    time.Now(),
        Restarts:    0,
        Process:     process,
    }
    
    pm.logger.Printf("Registered process: %s (PID: %d)", name, process.Pid)
}

func (pm *ProcessManager) GetProcessStatus(name string) (*ProcessInfo, bool) {
    pm.mutex.RLock()
    defer pm.mutex.RUnlock()
    
    info, exists := pm.processes[name]
    if !exists {
        return nil, false
    }
    
    // Update process status
    if info.Process != nil {
        if err := info.Process.Signal(syscall.Signal(0)); err != nil {
            info.Status = "stopped"
        } else {
            info.Status = "running"
        }
    }
    
    return info, true
}

func (pm *ProcessManager) StopProcess(name string, timeout time.Duration) error {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()
    
    info, exists := pm.processes[name]
    if !exists {
        return fmt.Errorf("process %s not found", name)
    }
    
    if info.Process == nil {
        return fmt.Errorf("process %s has no associated OS process", name)
    }
    
    pm.logger.Printf("Stopping process: %s (PID: %d)", name, info.PID)
    
    // Send SIGTERM for graceful shutdown
    if err := info.Process.Signal(os.Interrupt); err != nil {
        return fmt.Errorf("failed to send SIGTERM to process %s: %w", name, err)
    }
    
    // Wait for graceful shutdown
    done := make(chan error, 1)
    go func() {
        _, err := info.Process.Wait()
        done <- err
    }()
    
    select {
    case err := <-done:
        info.Status = "stopped"
        pm.logger.Printf("Process %s stopped gracefully", name)
        return err
    case <-time.After(timeout):
        // Force kill if timeout exceeded
        pm.logger.Printf("Process %s timeout, forcing kill", name)
        if err := info.Process.Kill(); err != nil {
            return fmt.Errorf("failed to kill process %s: %w", name, err)
        }
        info.Status = "killed"
        return nil
    }
}

func (pm *ProcessManager) RestartProcess(name string, command string, env []string) error {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()
    
    info, exists := pm.processes[name]
    if !exists {
        return fmt.Errorf("process %s not found", name)
    }
    
    pm.logger.Printf("Restarting process: %s", name)
    
    // Stop existing process
    if info.Process != nil {
        info.Process.Signal(os.Interrupt)
        info.Process.Wait()
    }
    
    // Start new process
    cmd := exec.Command("python", command)
    cmd.Env = env
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr
    
    if err := cmd.Start(); err != nil {
        return fmt.Errorf("failed to restart process %s: %w", name, err)
    }
    
    // Update process info
    info.Process = cmd.Process
    info.PID = cmd.Process.Pid
    info.StartTime = time.Now()
    info.Status = "running"
    info.Restarts++
    info.LastSeen = time.Now()
    
    pm.logger.Printf("Process %s restarted (PID: %d, Restarts: %d)", name, info.PID, info.Restarts)
    return nil
}

func (pm *ProcessManager) GetAllProcesses() map[string]*ProcessInfo {
    pm.mutex.RLock()
    defer pm.mutex.RUnlock()
    
    // Create a copy to avoid race conditions
    result := make(map[string]*ProcessInfo)
    for name, info := range pm.processes {
        // Update status before returning
        if info.Process != nil {
            if err := info.Process.Signal(syscall.Signal(0)); err != nil {
                info.Status = "stopped"
            } else {
                info.Status = "running"
            }
        }
        result[name] = info
    }
    
    return result
}

func (pm *ProcessManager) StartHealthMonitoring(interval time.Duration) {
    ticker := time.NewTicker(interval)
    go func() {
        for range ticker.C {
            pm.performHealthChecks()
        }
    }()
}

func (pm *ProcessManager) performHealthChecks() {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()
    
    for name, info := range pm.processes {
        if info.Process == nil {
            continue
        }
        
        // Check if process is still running
        if err := info.Process.Signal(syscall.Signal(0)); err != nil {
            pm.logger.Printf("Process %s is no longer running", name)
            info.Status = "stopped"
            info.HealthCheck = "failed"
            continue
        }
        
        // Perform registry health check for agents
        if strings.Contains(info.Command, ".py") {
            if pm.checkAgentHealth(name) {
                info.HealthCheck = "healthy"
                info.LastSeen = time.Now()
            } else {
                info.HealthCheck = "unhealthy"
                pm.logger.Printf("Agent %s failed health check", name)
            }
        }
    }
}

func (pm *ProcessManager) checkAgentHealth(agentName string) bool {
    // Query registry for agent status
    resp, err := http.Get("http://localhost:8080/agents")
    if err != nil {
        return false
    }
    defer resp.Body.Close()
    
    var result struct {
        Agents []struct {
            Name      string    `json:"name"`
            Status    string    `json:"status"`
            LastSeen  time.Time `json:"last_seen"`
        } `json:"agents"`
    }
    
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return false
    }
    
    // Check if agent is registered and recently active
    for _, agent := range result.Agents {
        if agent.Name == agentName {
            return agent.Status == "active" && 
                   time.Since(agent.LastSeen) < 2*time.Minute
        }
    }
    
    return false
}

// Enhanced status monitoring
func NewStatusMonitorCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "monitor",
        Short: "Monitor process health and status",
        Long:  "Continuously monitor MCP Mesh processes and display real-time status",
        RunE:  runStatusMonitor,
    }
    
    cmd.Flags().Int("interval", 5, "Status update interval in seconds")
    cmd.Flags().Bool("json", false, "Output status in JSON format")
    cmd.Flags().Bool("continuous", false, "Continuous monitoring mode")
    
    return cmd
}

func runStatusMonitor(cmd *cobra.Command, args []string) error {
    interval, _ := cmd.Flags().GetInt("interval")
    jsonOutput, _ := cmd.Flags().GetBool("json")
    continuous, _ := cmd.Flags().GetBool("continuous")
    
    pm := GetGlobalProcessManager()
    
    if continuous {
        return runContinuousMonitoring(pm, time.Duration(interval)*time.Second, jsonOutput)
    }
    
    return displayCurrentStatus(pm, jsonOutput)
}

func runContinuousMonitoring(pm *ProcessManager, interval time.Duration, jsonOutput bool) error {
    ticker := time.NewTicker(interval)
    defer ticker.Stop()
    
    for {
        if !jsonOutput {
            // Clear screen for terminal display
            fmt.Print("\033[2J\033[H")
            fmt.Printf("MCP Mesh Process Monitor - %s\n", time.Now().Format("2006-01-02 15:04:05"))
            fmt.Println(strings.Repeat("=", 80))
        }
        
        if err := displayCurrentStatus(pm, jsonOutput); err != nil {
            return err
        }
        
        if !jsonOutput {
            fmt.Printf("\nRefreshing every %v seconds. Press Ctrl+C to exit.\n", interval)
        }
        
        select {
        case <-ticker.C:
            continue
        case <-time.After(time.Hour): // Safety timeout
            return nil
        }
    }
}

func displayCurrentStatus(pm *ProcessManager, jsonOutput bool) error {
    processes := pm.GetAllProcesses()
    
    if jsonOutput {
        data, err := json.MarshalIndent(processes, "", "  ")
        if err != nil {
            return err
        }
        fmt.Println(string(data))
        return nil
    }
    
    // Text format output
    fmt.Printf("%-20s %-8s %-10s %-12s %-10s %-8s\n", 
        "NAME", "PID", "STATUS", "HEALTH", "UPTIME", "RESTARTS")
    fmt.Println(strings.Repeat("-", 80))
    
    for name, info := range processes {
        uptime := time.Since(info.StartTime).Truncate(time.Second)
        fmt.Printf("%-20s %-8d %-10s %-12s %-10s %-8d\n",
            name, info.PID, info.Status, info.HealthCheck, uptime, info.Restarts)
    }
    
    return nil
}

// Log aggregation functionality
func NewLogsAggregatorCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "logs-aggregator",
        Short: "Aggregate and display logs from all processes",
        RunE:  runLogsAggregator,
    }
    
    cmd.Flags().Bool("follow", false, "Follow log output in real-time")
    cmd.Flags().String("filter", "", "Filter logs by keyword")
    cmd.Flags().String("level", "INFO", "Minimum log level")
    cmd.Flags().Int("lines", 100, "Number of recent lines to show")
    
    return cmd
}

func runLogsAggregator(cmd *cobra.Command, args []string) error {
    follow, _ := cmd.Flags().GetBool("follow")
    filter, _ := cmd.Flags().GetString("filter")
    level, _ := cmd.Flags().GetString("level")
    lines, _ := cmd.Flags().GetInt("lines")
    
    if follow {
        return followAggregatedLogs(filter, level)
    }
    
    return displayRecentLogs(filter, level, lines)
}
```

## Success Criteria
- [ ] **CRITICAL**: Complete process management system matching Python CLI exactly
- [ ] **CRITICAL**: Process lifecycle management works identically to Python version
- [ ] **CRITICAL**: Health monitoring functionality preserved with same behavior
- [ ] **CRITICAL**: Process status reporting matches Python implementation
- [ ] **CRITICAL**: Log aggregation works identically to Python CLI
- [ ] **CRITICAL**: Process restart and recovery mechanisms preserved