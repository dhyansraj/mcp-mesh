# Task 3: Go CLI Implementation (2 hours)

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

**MANDATORY**: This Go implementation must preserve 100% of existing Python CLI functionality.

**Reference Preservation**:

- Keep ALL Python CLI code as reference during migration
- Test EVERY existing CLI command, flag, and option
- Maintain IDENTICAL behavior, output format, and error messages
- Preserve ALL configuration handling and environment variables

**Implementation Validation**:

- Each Go CLI command must pass Python CLI behavior tests
- Environment variable handling must be identical
- Configuration precedence must match Python implementation
- Process management behavior must be preserved exactly

## Development Workflow Architecture

The Go CLI must support the standard 3-shell development workflow:

- **Shell 1**: `mcp_mesh_dev start --registry-only` (registry service only)
- **Shell 2**: `mcp_mesh_dev start examples/hello_world.py` (connects to existing registry)
- **Shell 3**: `mcp_mesh_dev start examples/system_agent.py` (connects to existing registry)
- **Auto-start**: If no registry running, agents auto-start embedded registry

## Objective

Replace Python Click CLI with Go Cobra CLI maintaining identical command behavior

## Reference

`packages/mcp_mesh_runtime/src/mcp_mesh_runtime/cli/` directory

## Implementation Requirements

```go
// cmd/mcp-mesh-dev/main.go
package main

import (
    "github.com/spf13/cobra"
    "mcp-mesh/internal/cli"
)

var rootCmd = &cobra.Command{
    Use:   "mcp-mesh-dev",
    Short: "MCP Mesh Development CLI - Go implementation",
    Long:  "Development CLI for MCP Mesh with identical functionality to Python version",
}

func main() {
    rootCmd.AddCommand(cli.NewStartCommand())
    rootCmd.AddCommand(cli.NewListCommand())
    rootCmd.AddCommand(cli.NewStopCommand())
    rootCmd.AddCommand(cli.NewStatusCommand())

    rootCmd.Execute()
}
```

## Detailed Sub-tasks

### 3.1: Implement `start` command with exact Python behavior

```go
// internal/cli/start.go
func NewStartCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "start [agent.py]",
        Short: "Start MCP agent with mesh runtime",
        Args:  cobra.MaximumNArgs(1),
        RunE:  startAgent,
    }

    // EXACT same flags as Python CLI
    cmd.Flags().Bool("registry-only", false, "Start registry only")
    cmd.Flags().String("registry-url", "", "External registry URL")
    cmd.Flags().Bool("connect-only", false, "Connect to external registry")
    cmd.Flags().Bool("debug", false, "Enable debug mode")

    return cmd
}

func startAgent(cmd *cobra.Command, args []string) error {
    registryOnly, _ := cmd.Flags().GetBool("registry-only")

    if registryOnly {
        // Start Go registry service
        return startRegistryService()
    }

    // Same logic as Python: check if registry running, start if needed
    if !isRegistryRunning("localhost:8080") {
        log.Info("Registry not found, starting local registry...")
        go startRegistryService()

        // Wait for registry to be ready
        waitForRegistry("localhost:8080", 30*time.Second)
    }

    // Start Python agent process (CRITICAL: preserves all Python decorator functionality)
    return startPythonAgent(args[0])
}
```

### 3.2: Implement Python agent process management

```go
func startPythonAgent(agentPath string) error {
    // Same environment variable injection as Python CLI
    cmd := exec.Command("python", agentPath)
    cmd.Env = append(os.Environ(),
        "MCP_MESH_REGISTRY_URL=http://localhost:8080",
        "MCP_MESH_REGISTRY_HOST=localhost",
        "MCP_MESH_REGISTRY_PORT=8080",
        "MCP_MESH_DATABASE_URL=sqlite:///mcp_mesh.db",
    )

    // Same stdio handling
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr
    cmd.Stdin = os.Stdin

    return cmd.Run()
}
```

### 3.3: Implement `list` command (CRITICAL: fix the issue mentioned in ISSUES_TO_TACKLE.md)

```go
func NewListCommand() *cobra.Command {
    cmd := &cobra.Command{
        Use:   "list",
        Short: "List running agents and registry status",
        RunE:  listRunningServices,
    }

    // Complete flag coverage matching Python CLI
    cmd.Flags().Bool("agents", false, "Show only agents")
    cmd.Flags().Bool("services", false, "Show only services")
    cmd.Flags().String("filter", "", "Filter by name pattern")
    cmd.Flags().Bool("json", false, "Output in JSON format")

    return cmd
}

func listRunningServices(cmd *cobra.Command, args []string) error {
    // CRITICAL: This should be READ-ONLY, not kill processes
    // Query registry for agents (don't kill anything!)
    resp, err := http.Get("http://localhost:8080/agents")
    if err != nil {
        fmt.Println("Registry: Not running")
        return nil
    }

    var result struct {
        Agents []Agent `json:"agents"`
    }
    json.NewDecoder(resp.Body).Decode(&result)

    // Handle JSON output flag
    jsonOutput, _ := cmd.Flags().GetBool("json")
    if jsonOutput {
        jsonData, _ := json.MarshalIndent(result, "", "  ")
        fmt.Println(string(jsonData))
        return nil
    }

    fmt.Printf("Registry: Running on port 8080\n")
    fmt.Printf("Agents:\n")
    for _, agent := range result.Agents {
        fmt.Printf("  - %s: %s (%s)\n", agent.Name, agent.Status, strings.Join(agent.Capabilities, ", "))
    }

    return nil // EXIT without killing processes!
}
```

## Success Criteria

- [ ] Go CLI accepts core commands (`start`, `list`) from Python version
- [ ] `start` command with registry embedding functionality works identically
- [ ] `list` command is READ-ONLY and doesn't kill processes (fixes known issue)
- [ ] Python agent processes start with correct environment variables
- [ ] Development workflow (3-shell scenario) foundation implemented
- [ ] Registry auto-start logic works identically to Python implementation
- [ ] Core CLI behavior matches Python implementation exactly
