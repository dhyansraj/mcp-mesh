# Health Monitoring & Auto-Rewiring (Java/Spring Boot)

> Fast heartbeat system and automatic topology updates

## Overview

MCP Mesh uses a dual-heartbeat system for fast failure detection and automatic topology updates. Java/Spring Boot agents participate in the same health monitoring system as Python and TypeScript agents. The Spring Boot starter handles heartbeat, registration, and auto-rewiring automatically.

## Heartbeat System

### Dual-Heartbeat Design

| Type | Frequency  | Size  | Purpose                  |
| ---- | ---------- | ----- | ------------------------ |
| HEAD | ~5 seconds | ~200B | Lightweight keep-alive   |
| POST | On change  | ~2KB  | Full registration update |

### How It Works

1. Agent sends HEAD request every 5 seconds
2. Registry responds with status:
   - `200 OK`: No changes
   - `202 Accepted`: Topology changed, refresh needed
   - `410 Gone`: Agent unknown, re-register
3. On `202`, agent sends POST with full registration
4. Registry returns updated dependency topology

### Failure Detection

- Registry marks agents unhealthy after missed heartbeats
- Default threshold: 20 seconds (4 missed 5-second heartbeats)
- Configurable via environment variables

## Checking Dependency Health

Use `isAvailable()` on `McpMeshTool` to check if a dependency is reachable:

```java
@MeshTool(
    capability = "smart_greeting",
    description = "Greet with current date from mesh",
    dependencies = @Selector(capability = "date_service")
)
public GreetingResponse smartGreet(
    @Param(value = "name", description = "Name to greet") String name,
    McpMeshTool<String> dateService
) {
    if (dateService != null && dateService.isAvailable()) {
        String date = dateService.call();
        return new GreetingResponse("Hello, " + name + "! Today is " + date, "mesh");
    }
    // Graceful degradation
    return new GreetingResponse("Hello, " + name + "!", "fallback");
}
```

## The agent_status Tool Pattern

Expose a tool that reports dependency health to the mesh:

```java
@MeshTool(
    capability = "agent_status",
    description = "Get agent status with dependency info",
    tags = {"status", "info", "java"},
    dependencies = @Selector(capability = "date_service")
)
public AgentStatus getStatus(McpMeshTool<String> dateService) {
    boolean dateServiceAvailable = dateService != null && dateService.isAvailable();
    String dateServiceEndpoint = dateServiceAvailable ? dateService.getEndpoint() : null;

    return new AgentStatus(
        "assistant",
        "1.0.0",
        "Java " + System.getProperty("java.version"),
        dateServiceAvailable,
        dateServiceEndpoint
    );
}

public record AgentStatus(
    String name,
    String version,
    String runtime,
    boolean dateServiceAvailable,
    String dateServiceEndpoint
) {}
```

This pattern lets other agents (or operators) query dependency health programmatically via `meshctl call agent_status`.

## Auto-Rewiring

When topology changes, the mesh automatically:

1. **Detects change**: Via heartbeat response (`202`)
2. **Fetches new topology**: Registry returns updated dependencies
3. **Compares hashes**: Prevents unnecessary updates
4. **Refreshes proxies**: McpMeshTool proxies update automatically
5. **Routes traffic**: New calls go to updated providers

### Code Impact

None! Auto-rewiring is transparent:

```java
@MeshTool(
    capability = "my_tool",
    dependencies = @Selector(capability = "date_service")
)
public String myTool(McpMeshTool<String> dateService) {
    // If date_service agent restarts or is replaced,
    // the proxy automatically points to the new instance
    if (dateService != null && dateService.isAvailable()) {
        return dateService.call();
    }
    return "Service unavailable";
}
```

## Spring Boot Health Actuator

The MCP Mesh Spring Boot starter automatically integrates with Spring Boot's health actuator. The `/actuator/health` endpoint includes mesh status:

```bash
curl http://localhost:9000/actuator/health
```

## Configuration

### Agent Settings

```bash
# Heartbeat interval (seconds)
export MCP_MESH_AUTO_RUN_INTERVAL=30

# Health check interval (seconds)
export MCP_MESH_HEALTH_INTERVAL=30
```

### Registry Settings

```bash
# When to mark agents unhealthy (seconds)
export DEFAULT_TIMEOUT_THRESHOLD=20

# How often to scan for unhealthy agents (seconds)
export HEALTH_CHECK_INTERVAL=10

# When to evict stale agents (seconds)
export DEFAULT_EVICTION_THRESHOLD=60
```

## Graceful Failure

The mesh handles failures gracefully:

- **Registry down**: Existing agent-to-agent communication continues
- **Agent down**: Dependencies are `null`, code handles gracefully
- **Network partition**: Agents continue with cached topology
- **Recovery**: Automatic reconnection and topology refresh

## Monitoring

```bash
# Check overall mesh health
meshctl status

# Verbose status with heartbeat info
meshctl status --verbose

# List agents with health status
meshctl list

# JSON output for automation
meshctl status --json
```

## See Also

- `meshctl man registry` - Registry operations
- `meshctl man dependency-injection --java` - How DI handles failures
- `meshctl man environment` - Configuration options
