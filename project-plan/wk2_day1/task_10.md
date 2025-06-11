# Task 10: Python Environment Integration and Hybrid Agent Support (2 hours)

## Overview: Smart Python Agent Execution

**⚠️ IMPORTANT**: This task implements the critical bridge between Go CLI process management and Python MCP agent execution. The Go CLI must intelligently detect and manage Python environments while preserving all Python decorator functionality.

**Reference Documents**:

- `ARCHITECTURAL_CONCEPTS_AND_DEVELOPER_RULES.md` - Complete architecture overview
- `TASK_10_PYTHON_BRIDGE_VALIDATION_REPORT.md` - Python-Go bridge validation results
- `examples/hello_world.py` - Reference Python MCP agent implementation

## CRITICAL INTEGRATION REQUIREMENT

**MANDATORY**: This Go CLI implementation must seamlessly execute Python MCP agents with full mesh functionality.

**Integration Preservation**:

- Detect and use appropriate Python environments (.venv vs system Python)
- Set correct environment variables for Go registry connection
- Support both simple `.py` files and advanced `.yaml` configurations
- Provide intelligent package management and installation assistance
- Maintain identical Python agent behavior and performance

**Implementation Validation**:

- Python agents must register successfully with Go registry
- All `@mesh_agent` decorator functionality must work unchanged
- Environment detection must work across Windows/Linux/Mac
- Interactive package installation must be user-friendly

## Agent File Type Architecture

The Go CLI will support hybrid agent execution patterns:

- ✅ **Simple Mode**: Direct `.py` file execution with automatic registry connection
- ✅ **Advanced Mode**: YAML configuration files for complex deployment scenarios
- ✅ **Environment Detection**: Intelligent Python environment discovery and management
- ✅ **Package Management**: Interactive installation of missing dependencies

## Objective

Implement comprehensive Python agent execution with intelligent environment management and hybrid configuration support

## Implementation Requirements

### Core Python Environment Detection

```go
// internal/cli/python_env.go
package cli

import (
    "bufio"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "runtime"
    "strings"
)

type PythonEnvironment struct {
    PythonExecutable string
    IsVirtualEnv     bool
    Version          string
    HasMcpMeshRuntime bool
}

// DetectPythonEnvironment finds the best Python environment to use
func DetectPythonEnvironment() (*PythonEnvironment, error) {
    env := &PythonEnvironment{}

    // 1. Check for .venv in current directory first (highest priority)
    if venvPython := detectVirtualEnv(); venvPython != "" {
        env.PythonExecutable = venvPython
        env.IsVirtualEnv = true
        fmt.Printf("🐍 Using virtual environment: %s\n", venvPython)
    } else {
        // 2. Fall back to system Python
        systemPython, err := findSystemPython()
        if err != nil {
            return nil, fmt.Errorf("Python not found: %w", err)
        }
        env.PythonExecutable = systemPython
        env.IsVirtualEnv = false
        fmt.Printf("🐍 Using system Python: %s\n", systemPython)
    }

    // 3. Verify Python version (require >= 3.7)
    version, err := getPythonVersion(env.PythonExecutable)
    if err != nil {
        return nil, fmt.Errorf("failed to get Python version: %w", err)
    }
    env.Version = version

    if !isValidPythonVersion(version) {
        return nil, fmt.Errorf("Python %s detected. MCP Mesh requires Python 3.7+", version)
    }

    // 4. Check for mcp-mesh-runtime availability
    env.HasMcpMeshRuntime = checkMcpMeshRuntime(env.PythonExecutable)

    return env, nil
}

func detectVirtualEnv() string {
    venvPath := ".venv"
    if !dirExists(venvPath) {
        return ""
    }

    var pythonPath string
    if runtime.GOOS == "windows" {
        pythonPath = filepath.Join(venvPath, "Scripts", "python.exe")
    } else {
        pythonPath = filepath.Join(venvPath, "bin", "python")
    }

    if fileExists(pythonPath) {
        return pythonPath
    }
    return ""
}

func findSystemPython() (string, error) {
    // Try common Python executable names in order of preference
    candidates := []string{"python3", "python"}

    for _, candidate := range candidates {
        if path, err := exec.LookPath(candidate); err == nil {
            return path, nil
        }
    }

    return "", fmt.Errorf("no Python executable found in PATH")
}

func getPythonVersion(pythonExec string) (string, error) {
    cmd := exec.Command(pythonExec, "--version")
    output, err := cmd.Output()
    if err != nil {
        return "", err
    }

    // Parse "Python 3.9.7" -> "3.9.7"
    versionStr := strings.TrimPrefix(strings.TrimSpace(string(output)), "Python ")
    return versionStr, nil
}

func isValidPythonVersion(version string) bool {
    // Simple version check - require 3.7+
    parts := strings.Split(version, ".")
    if len(parts) < 2 {
        return false
    }

    major := parts[0]
    minor := parts[1]

    return major == "3" && minor >= "7"
}

func checkMcpMeshRuntime(pythonExec string) bool {
    cmd := exec.Command(pythonExec, "-c", "import mcp_mesh_runtime")
    return cmd.Run() == nil
}
```

### Interactive Package Management

```go
// internal/cli/package_manager.go
func EnsureMcpMeshRuntime(env *PythonEnvironment) error {
    if env.HasMcpMeshRuntime {
        fmt.Printf("✅ mcp-mesh-runtime found and ready\n")
        return nil
    }

    // Interactive installation prompt
    fmt.Printf("⚠️  mcp-mesh-runtime not found in Python environment\n")
    fmt.Printf("📦 Required packages: mcp, mcp-mesh, mcp-mesh-runtime\n")
    fmt.Printf("📍 Python environment: %s\n", env.PythonExecutable)

    if env.IsVirtualEnv {
        fmt.Printf("🔧 Virtual environment detected - packages will be installed locally\n")
    } else {
        fmt.Printf("🌐 System Python detected - packages will be installed globally\n")
    }

    fmt.Printf("\nOptions:\n")
    fmt.Printf("  i - Install packages automatically\n")
    fmt.Printf("  c - Continue without packages (agent may not connect to registry)\n")
    fmt.Printf("  q - Quit\n")
    fmt.Printf("Choice [i/c/q]: ")

    reader := bufio.NewReader(os.Stdin)
    input, _ := reader.ReadString('\n')
    choice := strings.TrimSpace(strings.ToLower(input))

    switch choice {
    case "i", "":  // Default to install
        return installMcpMeshRuntime(env.PythonExecutable)
    case "c":
        fmt.Printf("⚠️  Continuing without mcp-mesh-runtime - agent may not connect to registry\n")
        return nil
    case "q":
        return fmt.Errorf("installation cancelled by user")
    default:
        fmt.Printf("Invalid choice. Continuing without installation.\n")
        return nil
    }
}

func installMcpMeshRuntime(pythonExec string) error {
    fmt.Printf("📦 Installing mcp-mesh-runtime and dependencies...\n")

    packages := []string{"mcp", "mcp-mesh", "mcp-mesh-runtime"}

    for i, pkg := range packages {
        fmt.Printf("Installing %s (%d/%d)...\n", pkg, i+1, len(packages))

        cmd := exec.Command(pythonExec, "-m", "pip", "install", pkg)
        cmd.Stdout = os.Stdout
        cmd.Stderr = os.Stderr

        if err := cmd.Run(); err != nil {
            return fmt.Errorf("failed to install %s: %w", pkg, err)
        }
    }

    fmt.Printf("✅ Installation complete! All packages ready.\n")
    return nil
}
```

### Hybrid Agent Configuration Support

```go
// internal/cli/agent_config.go
type AgentConfig struct {
    Script           string            `yaml:"script"`
    WorkingDirectory string            `yaml:"working_directory,omitempty"`
    PythonInterpreter string           `yaml:"python_interpreter,omitempty"`
    Environment      map[string]string `yaml:"environment,omitempty"`
    Metadata         AgentMetadata     `yaml:"metadata,omitempty"`
    Resources        ResourceLimits    `yaml:"resources,omitempty"`
}

type AgentMetadata struct {
    Name        string   `yaml:"name,omitempty"`
    Version     string   `yaml:"version,omitempty"`
    Description string   `yaml:"description,omitempty"`
    Tags        []string `yaml:"tags,omitempty"`
}

type ResourceLimits struct {
    Timeout     int    `yaml:"timeout,omitempty"`
    MemoryLimit string `yaml:"memory_limit,omitempty"`
    CPULimit    string `yaml:"cpu_limit,omitempty"`
}

func LoadAgentConfig(configPath string) (*AgentConfig, error) {
    data, err := os.ReadFile(configPath)
    if err != nil {
        return nil, fmt.Errorf("failed to read config file: %w", err)
    }

    var config AgentConfig
    if err := yaml.Unmarshal(data, &config); err != nil {
        return nil, fmt.Errorf("failed to parse config YAML: %w", err)
    }

    // Validate required fields
    if config.Script == "" {
        return nil, fmt.Errorf("config must specify 'script' field")
    }

    return &config, nil
}
```

### Process Lifecycle Management

```go
// internal/cli/process_lifecycle.go
type AgentProcess struct {
    ID          string
    ScriptPath  string
    ConfigPath  string
    PID         int
    Cmd         *exec.Cmd
    StartTime   time.Time
    Status      string // starting, running, stopping, stopped, failed
    Environment map[string]string
    Metadata    AgentMetadata
}

type ProcessManager struct {
    processes map[string]*AgentProcess
    mutex     sync.RWMutex
    logger    *log.Logger
}

func NewProcessManager() *ProcessManager {
    return &ProcessManager{
        processes: make(map[string]*AgentProcess),
        logger:    log.New(os.Stdout, "[ProcessManager] ", log.LstdFlags),
    }
}

func (pm *ProcessManager) StartAgent(agentPath string, config *AgentConfig, env []string) (*AgentProcess, error) {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()

    // Generate unique agent ID
    agentID := generateAgentID(agentPath)

    // Check if agent already running
    if existing, exists := pm.processes[agentID]; exists && existing.Status == "running" {
        return nil, fmt.Errorf("agent %s is already running (PID: %d)", agentID, existing.PID)
    }

    // Create agent process
    process := &AgentProcess{
        ID:         agentID,
        ScriptPath: agentPath,
        StartTime:  time.Now(),
        Status:     "starting",
        Environment: envMapFromSlice(env),
    }

    if config != nil {
        process.ConfigPath = config.Script
        process.Metadata = config.Metadata
    }

    // Store process for tracking
    pm.processes[agentID] = process

    // Start process in goroutine for non-blocking execution
    go pm.runAgentProcess(process, config, env)

    return process, nil
}

func (pm *ProcessManager) runAgentProcess(process *AgentProcess, config *AgentConfig, env []string) {
    var pythonExec string
    var scriptPath string
    var workingDir string

    if config != nil {
        // YAML config mode
        if config.PythonInterpreter != "" {
            pythonExec = config.PythonInterpreter
        } else {
            pythonEnv, err := DetectPythonEnvironment()
            if err != nil {
                pm.markProcessFailed(process, fmt.Errorf("Python detection failed: %w", err))
                return
            }
            pythonExec = pythonEnv.PythonExecutable
        }
        scriptPath = config.Script
        workingDir = config.WorkingDirectory
        if workingDir == "" {
            workingDir = filepath.Dir(scriptPath)
        }
    } else {
        // Simple .py mode
        pythonEnv, err := DetectPythonEnvironment()
        if err != nil {
            pm.markProcessFailed(process, fmt.Errorf("Python detection failed: %w", err))
            return
        }
        pythonExec = pythonEnv.PythonExecutable
        scriptPath = process.ScriptPath
        workingDir = filepath.Dir(scriptPath)
    }

    // Create command
    cmd := exec.Command(pythonExec, scriptPath)
    cmd.Env = env
    cmd.Dir = workingDir
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr

    // Store command for process control
    process.Cmd = cmd

    pm.logger.Printf("Starting agent %s: %s %s", process.ID, pythonExec, scriptPath)

    // Start the process
    if err := cmd.Start(); err != nil {
        pm.markProcessFailed(process, fmt.Errorf("failed to start process: %w", err))
        return
    }

    // Update process info
    pm.mutex.Lock()
    process.PID = cmd.Process.Pid
    process.Status = "running"
    pm.mutex.Unlock()

    pm.logger.Printf("Agent %s started successfully (PID: %d)", process.ID, process.PID)

    // Wait for process completion
    err := cmd.Wait()

    // Update final status
    pm.mutex.Lock()
    if err != nil {
        process.Status = "failed"
        pm.logger.Printf("Agent %s failed: %v", process.ID, err)
    } else {
        process.Status = "stopped"
        pm.logger.Printf("Agent %s stopped normally", process.ID)
    }
    pm.mutex.Unlock()
}

func (pm *ProcessManager) StopAgent(agentID string) error {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()

    process, exists := pm.processes[agentID]
    if !exists {
        return fmt.Errorf("agent %s not found", agentID)
    }

    if process.Status != "running" {
        return fmt.Errorf("agent %s is not running (status: %s)", agentID, process.Status)
    }

    if process.Cmd == nil || process.Cmd.Process == nil {
        return fmt.Errorf("agent %s has no process to stop", agentID)
    }

    pm.logger.Printf("Stopping agent %s (PID: %d)", agentID, process.PID)
    process.Status = "stopping"

    return pm.gracefulShutdown(process)
}

func (pm *ProcessManager) gracefulShutdown(process *AgentProcess) error {
    // 1. Send SIGTERM for graceful shutdown
    if err := process.Cmd.Process.Signal(os.Interrupt); err != nil {
        pm.logger.Printf("Failed to send SIGTERM to agent %s: %v", process.ID, err)
    } else {
        pm.logger.Printf("Sent SIGTERM to agent %s", process.ID)
    }

    // 2. Wait for graceful shutdown (with timeout)
    gracefulTimeout := 10 * time.Second
    done := make(chan error, 1)

    go func() {
        done <- process.Cmd.Wait()
    }()

    select {
    case err := <-done:
        // Process exited gracefully
        if err != nil {
            pm.logger.Printf("Agent %s exited with error: %v", process.ID, err)
        } else {
            pm.logger.Printf("Agent %s stopped gracefully", process.ID)
        }
        process.Status = "stopped"
        return nil

    case <-time.After(gracefulTimeout):
        // Graceful shutdown timed out, force kill
        pm.logger.Printf("Graceful shutdown timeout for agent %s, forcing termination", process.ID)

        if err := process.Cmd.Process.Kill(); err != nil {
            pm.logger.Printf("Failed to kill agent %s: %v", process.ID, err)
            return fmt.Errorf("failed to force stop agent %s: %w", process.ID, err)
        }

        // Wait for force kill to complete
        process.Cmd.Wait()
        process.Status = "stopped"
        pm.logger.Printf("Agent %s force stopped", process.ID)
        return nil
    }
}

func (pm *ProcessManager) StopAllAgents() error {
    pm.mutex.RLock()
    runningAgents := make([]*AgentProcess, 0)
    for _, process := range pm.processes {
        if process.Status == "running" {
            runningAgents = append(runningAgents, process)
        }
    }
    pm.mutex.RUnlock()

    if len(runningAgents) == 0 {
        pm.logger.Printf("No running agents to stop")
        return nil
    }

    pm.logger.Printf("Stopping %d running agents...", len(runningAgents))

    // Stop all agents concurrently
    var wg sync.WaitGroup
    errors := make(chan error, len(runningAgents))

    for _, process := range runningAgents {
        wg.Add(1)
        go func(p *AgentProcess) {
            defer wg.Done()
            if err := pm.StopAgent(p.ID); err != nil {
                errors <- fmt.Errorf("failed to stop agent %s: %w", p.ID, err)
            }
        }(process)
    }

    wg.Wait()
    close(errors)

    // Collect any errors
    var stopErrors []error
    for err := range errors {
        stopErrors = append(stopErrors, err)
    }

    if len(stopErrors) > 0 {
        return fmt.Errorf("errors stopping agents: %v", stopErrors)
    }

    pm.logger.Printf("All agents stopped successfully")
    return nil
}

func (pm *ProcessManager) ListAgents() []*AgentProcess {
    pm.mutex.RLock()
    defer pm.mutex.RUnlock()

    agents := make([]*AgentProcess, 0, len(pm.processes))
    for _, process := range pm.processes {
        agents = append(agents, process)
    }

    return agents
}

func (pm *ProcessManager) GetAgent(agentID string) (*AgentProcess, bool) {
    pm.mutex.RLock()
    defer pm.mutex.RUnlock()

    process, exists := pm.processes[agentID]
    return process, exists
}

func (pm *ProcessManager) markProcessFailed(process *AgentProcess, err error) {
    pm.mutex.Lock()
    defer pm.mutex.Unlock()

    process.Status = "failed"
    pm.logger.Printf("Agent %s failed to start: %v", process.ID, err)
}

func generateAgentID(agentPath string) string {
    // Generate unique ID from agent path and timestamp
    basename := filepath.Base(agentPath)
    name := strings.TrimSuffix(basename, filepath.Ext(basename))
    return fmt.Sprintf("%s-%d", name, time.Now().Unix())
}

func envMapFromSlice(envSlice []string) map[string]string {
    envMap := make(map[string]string)
    for _, env := range envSlice {
        parts := strings.SplitN(env, "=", 2)
        if len(parts) == 2 {
            envMap[parts[0]] = parts[1]
        }
    }
    return envMap
}
```

### Signal Handling and Cleanup

```go
// internal/cli/signal_handler.go
type SignalHandler struct {
    processManager *ProcessManager
    cleanup        []func() error
    logger         *log.Logger
}

func NewSignalHandler(pm *ProcessManager) *SignalHandler {
    return &SignalHandler{
        processManager: pm,
        cleanup:        make([]func() error, 0),
        logger:         log.New(os.Stdout, "[SignalHandler] ", log.LstdFlags),
    }
}

func (sh *SignalHandler) SetupSignalHandling() {
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

    go sh.handleSignals(sigChan)
}

func (sh *SignalHandler) handleSignals(sigChan chan os.Signal) {
    for sig := range sigChan {
        sh.logger.Printf("Received signal: %v", sig)
        sh.logger.Printf("Initiating graceful shutdown...")

        // Stop all running agents
        if err := sh.processManager.StopAllAgents(); err != nil {
            sh.logger.Printf("Error stopping agents: %v", err)
        }

        // Run cleanup functions
        for _, cleanupFunc := range sh.cleanup {
            if err := cleanupFunc(); err != nil {
                sh.logger.Printf("Cleanup error: %v", err)
            }
        }

        sh.logger.Printf("Graceful shutdown complete")
        os.Exit(0)
    }
}

func (sh *SignalHandler) AddCleanupFunction(cleanup func() error) {
    sh.cleanup = append(sh.cleanup, cleanup)
}
```

### Enhanced Start Command Implementation

```go
// internal/cli/start.go - Enhanced startAgent function
func startAgent(agentPath string, cmd *cobra.Command) error {
    // Get registry configuration
    registryHost, _ := cmd.Flags().GetString("registry-host")
    registryPort, _ := cmd.Flags().GetInt("registry-port")
    registryURL := fmt.Sprintf("http://%s:%d", registryHost, registryPort)

    // Detect file type and handle accordingly
    switch filepath.Ext(agentPath) {
    case ".py":
        return startPythonAgentSimple(agentPath, registryURL)
    case ".yaml", ".yml":
        return startPythonAgentWithConfig(agentPath, registryURL)
    default:
        return fmt.Errorf("unsupported agent type: %s (supported: .py, .yaml)", agentPath)
    }
}

func startPythonAgentSimple(scriptPath, registryURL string) error {
    fmt.Printf("🚀 Starting Python agent: %s\n", scriptPath)

    // 1. Detect Python environment
    env, err := DetectPythonEnvironment()
    if err != nil {
        return fmt.Errorf("Python environment detection failed: %w", err)
    }

    // 2. Ensure mcp-mesh-runtime is available
    if err := EnsureMcpMeshRuntime(env); err != nil {
        return fmt.Errorf("package management failed: %w", err)
    }

    // 3. Set up environment variables for Go registry connection
    envVars := os.Environ()
    envVars = append(envVars,
        fmt.Sprintf("MCP_MESH_REGISTRY_URL=%s", registryURL),
        "MCP_MESH_LOG_LEVEL=INFO",
    )

    // 4. Execute Python agent
    cmd := exec.Command(env.PythonExecutable, scriptPath)
    cmd.Env = envVars
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr
    cmd.Dir = filepath.Dir(scriptPath)

    fmt.Printf("🔗 Registry URL: %s\n", registryURL)
    fmt.Printf("🐍 Python: %s (version %s)\n", env.PythonExecutable, env.Version)
    fmt.Printf("📝 Agent script: %s\n", scriptPath)
    fmt.Printf("▶️  Starting agent...\n")

    return cmd.Start()
}

func startPythonAgentWithConfig(configPath, registryURL string) error {
    fmt.Printf("🚀 Starting Python agent with config: %s\n", configPath)

    // 1. Load configuration
    config, err := LoadAgentConfig(configPath)
    if err != nil {
        return fmt.Errorf("failed to load agent config: %w", err)
    }

    // 2. Detect Python environment (or use specified interpreter)
    var env *PythonEnvironment
    if config.PythonInterpreter != "" {
        // Use specified Python interpreter
        env = &PythonEnvironment{
            PythonExecutable: config.PythonInterpreter,
            IsVirtualEnv:     false,
        }
        // Still need to check version and packages
        version, err := getPythonVersion(env.PythonExecutable)
        if err != nil {
            return fmt.Errorf("failed to verify specified Python interpreter: %w", err)
        }
        env.Version = version
        env.HasMcpMeshRuntime = checkMcpMeshRuntime(env.PythonExecutable)
    } else {
        // Auto-detect Python environment
        env, err = DetectPythonEnvironment()
        if err != nil {
            return fmt.Errorf("Python environment detection failed: %w", err)
        }
    }

    // 3. Ensure mcp-mesh-runtime is available
    if err := EnsureMcpMeshRuntime(env); err != nil {
        return fmt.Errorf("package management failed: %w", err)
    }

    // 4. Set up environment variables
    envVars := os.Environ()

    // Add registry connection
    envVars = append(envVars, fmt.Sprintf("MCP_MESH_REGISTRY_URL=%s", registryURL))

    // Add custom environment variables from config
    for key, value := range config.Environment {
        // Support environment variable expansion
        expandedValue := os.ExpandEnv(value)
        envVars = append(envVars, fmt.Sprintf("%s=%s", key, expandedValue))
    }

    // 5. Set working directory
    scriptDir := filepath.Dir(config.Script)
    if config.WorkingDirectory != "" {
        scriptDir = config.WorkingDirectory
    }

    // 6. Execute Python agent
    cmd := exec.Command(env.PythonExecutable, config.Script)
    cmd.Env = envVars
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr
    cmd.Dir = scriptDir

    fmt.Printf("🔗 Registry URL: %s\n", registryURL)
    fmt.Printf("🐍 Python: %s (version %s)\n", env.PythonExecutable, env.Version)
    fmt.Printf("📝 Agent script: %s\n", config.Script)
    fmt.Printf("📁 Working directory: %s\n", scriptDir)
    fmt.Printf("🔧 Environment variables: %d custom vars\n", len(config.Environment))
    fmt.Printf("▶️  Starting agent...\n")

    return cmd.Start()
}
```

## Example Usage Patterns

### Simple Python Agent

```bash
# Developer workflow - just works
./mcp-mesh-dev start examples/hello_world.py

# Output:
# 🐍 Using virtual environment: .venv/bin/python
# ✅ mcp-mesh-runtime found and ready
# 🚀 Starting Python agent: examples/hello_world.py
# 🔗 Registry URL: http://localhost:8080
# 🐍 Python: .venv/bin/python (version 3.9.7)
# ▶️  Starting agent...
```

### Advanced YAML Configuration

```yaml
# examples/production_agent.yaml
agent:
  script: "src/advanced_agent.py"
  working_directory: "/opt/myapp"
  python_interpreter: "/usr/bin/python3.9"

environment:
  MCP_MESH_LOG_LEVEL: "DEBUG"
  DATABASE_URL: "postgresql://localhost:5432/agents"
  API_TOKEN: "${PRODUCTION_API_TOKEN}"
  CUSTOM_CONFIG: "production"

metadata:
  name: "production-agent"
  version: "2.1.0"
  description: "Production agent with advanced configuration"
  tags: ["production", "database", "api"]

resources:
  timeout: 300
  memory_limit: "1GB"
  cpu_limit: "2"
```

```bash
./mcp-mesh-dev start examples/production_agent.yaml

# Output:
# 🚀 Starting Python agent with config: examples/production_agent.yaml
# 🐍 Using specified Python: /usr/bin/python3.9 (version 3.9.16)
# ✅ mcp-mesh-runtime found and ready
# 🔗 Registry URL: http://localhost:8080
# 📝 Agent script: src/advanced_agent.py
# 📁 Working directory: /opt/myapp
# 🔧 Environment variables: 4 custom vars
# ▶️  Starting agent...
```

### Interactive Package Installation

```bash
./mcp-mesh-dev start examples/hello_world.py

# Output:
# 🐍 Using system Python: /usr/bin/python3
# ⚠️  mcp-mesh-runtime not found in Python environment
# 📦 Required packages: mcp, mcp-mesh, mcp-mesh-runtime
# 📍 Python environment: /usr/bin/python3
# 🌐 System Python detected - packages will be installed globally
#
# Options:
#   i - Install packages automatically
#   c - Continue without packages (agent may not connect to registry)
#   q - Quit
# Choice [i/c/q]: i
#
# 📦 Installing mcp-mesh-runtime and dependencies...
# Installing mcp (1/3)...
# Installing mcp-mesh (2/3)...
# Installing mcp-mesh-runtime (3/3)...
# ✅ Installation complete! All packages ready.
```

### Complete Lifecycle Example

```bash
# Start multiple agents
./mcp-mesh-dev start examples/hello_world.py
# [ProcessManager] Starting agent hello_world-1699123456: /usr/bin/python3 examples/hello_world.py
# [ProcessManager] Agent hello_world-1699123456 started successfully (PID: 12345)

./mcp-mesh-dev start examples/system_agent.py
# [ProcessManager] Starting agent system_agent-1699123460: /usr/bin/python3 examples/system_agent.py
# [ProcessManager] Agent system_agent-1699123460 started successfully (PID: 12350)

# Check status
./mcp-mesh-dev status
# Agent Status Report:
# ─────────────────────────────────────────────────────────────
# hello_world-1699123456    RUNNING    PID: 12345    Runtime: 2m30s
# system_agent-1699123460   RUNNING    PID: 12350    Runtime: 45s
# ─────────────────────────────────────────────────────────────
# Total: 2 agents running

# Stop specific agent
./mcp-mesh-dev stop hello_world-1699123456
# [ProcessManager] Stopping agent hello_world-1699123456 (PID: 12345)
# [ProcessManager] Sent SIGTERM to agent hello_world-1699123456
# [ProcessManager] Agent hello_world-1699123456 stopped gracefully

# Graceful shutdown (Ctrl+C)
^C
# [SignalHandler] Received signal: interrupt
# [SignalHandler] Initiating graceful shutdown...
# [ProcessManager] Stopping 1 running agents...
# [ProcessManager] Stopping agent system_agent-1699123460 (PID: 12350)
# [ProcessManager] Sent SIGTERM to agent system_agent-1699123460
# [ProcessManager] Agent system_agent-1699123460 stopped gracefully
# [ProcessManager] All agents stopped successfully
# [SignalHandler] Graceful shutdown complete
```

## Detailed Sub-tasks

### 15.1: Implement Python environment detection system

- [ ] Create `internal/cli/python_env.go` with environment detection logic
- [ ] Support .venv virtual environment detection (Windows/Linux/Mac paths)
- [ ] Implement system Python discovery with version validation
- [ ] Add Python version checking (require >= 3.7)
- [ ] Implement mcp-mesh-runtime package detection

### 15.2: Build interactive package management

- [ ] Create `internal/cli/package_manager.go` with installation logic
- [ ] Implement interactive prompts for missing packages
- [ ] Add pip-based installation with progress reporting
- [ ] Handle installation errors gracefully
- [ ] Support both virtual environment and system-wide installation

### 15.3: Add YAML configuration support

- [ ] Create `internal/cli/agent_config.go` with configuration structures
- [ ] Implement YAML parsing for agent configurations
- [ ] Add environment variable expansion support
- [ ] Validate configuration fields and provide helpful errors
- [ ] Support custom working directories and Python interpreters

### 15.4: Enhance start command with hybrid support

- [ ] Modify `internal/cli/start.go` to detect file types (.py vs .yaml)
- [ ] Implement `startPythonAgentSimple()` for direct .py execution
- [ ] Implement `startPythonAgentWithConfig()` for YAML-based execution
- [ ] Add environment variable injection for registry connection
- [ ] Integrate process tracking and management

### 15.5: Add comprehensive error handling and user feedback

- [ ] Provide clear error messages for missing Python/packages
- [ ] Add helpful suggestions for environment setup
- [ ] Implement logging for debugging Python agent startup issues
- [ ] Add validation for agent file existence and permissions
- [ ] Support graceful fallback when packages are unavailable

### 15.6: Implement process lifecycle management

- [ ] Create `internal/cli/process_lifecycle.go` with AgentProcess and ProcessManager types
- [ ] Implement process tracking with unique agent IDs and status monitoring
- [ ] Add graceful shutdown with SIGTERM followed by SIGKILL timeout
- [ ] Implement concurrent agent stopping with proper error collection
- [ ] Add process listing and individual agent management

### 15.7: Add signal handling and cleanup

- [ ] Create `internal/cli/signal_handler.go` with SignalHandler type
- [ ] Implement SIGINT/SIGTERM signal catching for graceful shutdown
- [ ] Add automatic cleanup of all running agents on shutdown
- [ ] Support additional cleanup functions for registry and other resources
- [ ] Ensure proper exit codes and logging during shutdown

### 15.8: Integrate process management with CLI commands

- [ ] Modify start command to use ProcessManager for agent tracking
- [ ] Update stop command to use graceful shutdown mechanisms
- [ ] Enhance status command to show detailed process information
- [ ] Add restart command functionality with proper process lifecycle
- [ ] Integrate signal handling into main CLI application

### 15.9: Cross-platform compatibility testing

- [ ] Test virtual environment detection on Windows, Linux, and Mac
- [ ] Verify Python executable path handling across platforms
- [ ] Test pip installation on different operating systems
- [ ] Validate environment variable handling and expansion
- [ ] Ensure proper working directory and path resolution
- [ ] Test signal handling and process termination across platforms

## Success Criteria

### Core Python Integration

- [ ] **CRITICAL**: Python agents register successfully with Go registry using environment variables
- [ ] **CRITICAL**: Virtual environment detection works across Windows/Linux/Mac platforms
- [ ] **CRITICAL**: Interactive package installation provides smooth user experience
- [ ] **CRITICAL**: YAML configuration support enables advanced deployment scenarios
- [ ] **CRITICAL**: All existing Python MCP agent examples work unchanged
- [ ] **CRITICAL**: Environment variable injection enables Python-Go registry bridge functionality

### Process Lifecycle Management

- [ ] **CRITICAL**: Graceful shutdown works reliably across all platforms (SIGTERM → SIGKILL)
- [ ] **CRITICAL**: Signal handlers (Ctrl+C, SIGTERM) stop all running agents cleanly
- [ ] **CRITICAL**: Process tracking prevents duplicate agents and enables proper management
- [ ] **CRITICAL**: Concurrent agent shutdown completes within reasonable timeouts
- [ ] **CRITICAL**: Process status monitoring accurately reflects agent lifecycle states
- [ ] **CRITICAL**: Error handling during shutdown preserves system stability

### CLI Integration

- [ ] **CRITICAL**: Both `.py` and `.yaml` agent types integrate seamlessly with process management
- [ ] **CRITICAL**: Stop command gracefully terminates specific agents by ID
- [ ] **CRITICAL**: Status command shows detailed process information (PID, status, runtime)
- [ ] **CRITICAL**: Restart command handles full process lifecycle correctly
- [ ] **CRITICAL**: Error messages are clear and actionable for users

### Reliability and Safety

- [ ] **CRITICAL**: No orphaned Python processes remain after CLI shutdown
- [ ] **CRITICAL**: Process cleanup completes successfully even when agents are unresponsive
- [ ] **CRITICAL**: Memory and resource leaks are prevented during long-running operations
- [ ] **CRITICAL**: Cross-platform signal handling works identically on Windows/Linux/Mac
