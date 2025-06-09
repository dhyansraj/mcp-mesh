# Task 4: Advanced CLI Commands Implementation (30 minutes)

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
**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI advanced command functionality.

**Reference Preservation**:
- Keep ALL Python CLI code as reference during migration
- Test EVERY existing advanced CLI command, flag, and option
- Maintain IDENTICAL behavior for advanced commands (`stop`, `restart`, `status`, `logs`)
- Preserve ALL command-line argument parsing and validation

**Implementation Validation**:
- Each Go CLI command must pass Python CLI behavior tests
- Command outputs must match Python implementation exactly
- Error handling must be identical to Python version

## Objective
Implement advanced CLI commands (`stop`, `restart`, `restart-agent`, `status`, `logs`) maintaining identical behavior to Python

## Reference
`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/` directory

## Detailed Implementation

### 4.1: Implement advanced CLI commands
```go
// Complete command coverage matching Python CLI
func NewStopCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "stop",
        Short: "Stop MCP Mesh services",
        RunE:  stopServices,
    }
    
    cmd.Flags().Bool("force", false, "Force stop services without graceful shutdown")
    cmd.Flags().Int("timeout", 30, "Timeout for graceful shutdown")
    cmd.Flags().String("agent", "", "Stop only the specified agent")
    
    return cmd
}

func NewRestartCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "restart",
        Short: "Restart MCP Mesh registry service",
        RunE:  restartRegistry,
    }
    
    cmd.Flags().Int("timeout", 30, "Timeout for graceful shutdown")
    cmd.Flags().Bool("reset-config", false, "Reset to default configuration")
    
    return cmd
}

func NewRestartAgentCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "restart-agent [agent_name]",
        Short: "Restart a specific agent",
        Args:  cobra.ExactArgs(1),
        RunE:  restartAgent,
    }
    
    cmd.Flags().Int("timeout", 30, "Timeout for graceful shutdown")
    
    return cmd
}

func NewStatusCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "status",
        Short: "Display status of MCP Mesh services",
        RunE:  showStatus,
    }
    
    cmd.Flags().Bool("verbose", false, "Show detailed status information")
    cmd.Flags().Bool("json", false, "Output status in JSON format")
    
    return cmd
}

func NewLogsCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "logs",
        Short: "Show logs for MCP Mesh services",
        RunE:  showLogs,
    }
    
    cmd.Flags().Bool("follow", false, "Follow log output in real-time")
    cmd.Flags().String("agent", "", "Show logs for specific agent")
    cmd.Flags().String("level", "INFO", "Minimum log level to display")
    cmd.Flags().Int("lines", 50, "Number of recent log lines to show")
    
    return cmd
}

// Implementation functions
func stopServices(cmd *cobra.Command, args []string) error {
    force, _ := cmd.Flags().GetBool("force")
    timeout, _ := cmd.Flags().GetInt("timeout")
    agent, _ := cmd.Flags().GetString("agent")
    
    if agent != "" {
        // Stop specific agent
        return stopSpecificAgent(agent, force, timeout)
    }
    
    // Stop all services
    return stopAllServices(force, timeout)
}

func restartRegistry(cmd *cobra.Command, args []string) error {
    timeout, _ := cmd.Flags().GetInt("timeout")
    resetConfig, _ := cmd.Flags().GetBool("reset-config")
    
    // Implementation matching Python CLI behavior
    return performRegistryRestart(timeout, resetConfig)
}

func restartAgent(cmd *cobra.Command, args []string) error {
    agentName := args[0]
    timeout, _ := cmd.Flags().GetInt("timeout")
    
    return performAgentRestart(agentName, timeout)
}

func showStatus(cmd *cobra.Command, args []string) error {
    verbose, _ := cmd.Flags().GetBool("verbose")
    jsonOutput, _ := cmd.Flags().GetBool("json")
    
    status := collectSystemStatus(verbose)
    
    if jsonOutput {
        return outputStatusAsJSON(status)
    }
    
    return outputStatusAsText(status, verbose)
}

func showLogs(cmd *cobra.Command, args []string) error {
    follow, _ := cmd.Flags().GetBool("follow")
    agent, _ := cmd.Flags().GetString("agent")
    level, _ := cmd.Flags().GetString("level")
    lines, _ := cmd.Flags().GetInt("lines")
    
    return streamLogs(follow, agent, level, lines)
}
```

## Success Criteria
- [ ] **CRITICAL**: ALL advanced CLI commands implemented (`stop`, `restart`, `restart-agent`, `status`, `logs`)
- [ ] **CRITICAL**: All command flags and options work identically to Python CLI
- [ ] **CRITICAL**: Command outputs match Python implementation exactly
- [ ] **CRITICAL**: Error handling and validation identical to Python version
- [ ] **CRITICAL**: Help text and usage information matches Python CLI
- [ ] **CRITICAL**: Cross-platform compatibility for all commands