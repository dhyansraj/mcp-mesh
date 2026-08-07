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

## Declaring Your Own Health Check

Annotate one no-argument method with `@MeshHealthCheck` to tell the mesh what "able to serve" means for this agent:

```java
@Component
public class VendorHealth {

    @MeshHealthCheck(ttlSeconds = 30)
    public MeshHealth healthCheck() {
        if (!vendorReachable()) {
            return MeshHealth.unhealthy("vendor API unreachable")
                .withCheck("vendor_api_reachable", false);
        }
        return MeshHealth.healthy().withCheck("vendor_api_reachable", true);
    }
}
```

One check per agent, on any Spring bean. Return `MeshHealth` for full detail, or `boolean` for the terse form (`true` healthy, `false` unhealthy). `ttlSeconds` is how often it re-runs (default 15); `MCP_MESH_HEALTH_CHECK_TTL` overrides it.

### What a Failing Check Does

While the check reports unhealthy the agent **stops heartbeating**. The registry marks it unhealthy after the staleness window, dependency resolution stops selecting it, and consumers move to another provider. When the check passes again the heartbeat resumes and the registry restores the agent through the `410 Gone` re-register path - no restart. The TTL is the cadence, not the end-to-end latency: it only bounds how long until the next check runs. Withdrawal costs that plus the registry's staleness window once heartbeats stop, and recovery costs it plus the heartbeat resume and re-register round trip.

The verdict drives `/health`, which answers 503 while unhealthy and carries the `checks` and `errors` the method returned. It does not drive `/ready`, which reports whether the mesh runtime is up, on every agent type: pausing the heartbeat already withdraws the agent, and a 503 on `/ready` would additionally empty the Kubernetes Service that mesh traffic arrives on. `/livez` never consults it either - a restart cannot fix a vendor outage.

### Only an Explicit Unhealthy Withdraws the Agent

A check that **throws** is recorded as `degraded`, not unhealthy, and keeps heartbeating. A bug in a health check must not be able to remove a working agent from the mesh. Return `false` or `MeshHealth.unhealthy(...)` to actually withdraw.

`degraded` shows on the diagnostic surface only, the same way it does on Python: the agent keeps heartbeating and stays in dependency resolution, and `/health` answers 503 while `/ready` is unmoved. Nothing probes `/health`, so its status code is free to carry the verdict; readiness reports the mesh runtime and nothing else.

### Route and A2A Agents

A route-only (`api`) or A2A agent runs the check exactly as a provider does, and a failing one **pauses its heartbeat** too, so the registry stops advertising the gateway. Nothing else changes for it: the heartbeat is registry traffic, so the servlet container keeps serving, the dependencies it already resolved stay wired, and `/ready` still answers 200 - the pod keeps its Service endpoints and keeps taking ingress. A withdrawn gateway stops being discovered; it does not go dark.

Declare it the same way you would on a provider: one `@MeshHealthCheck` method on any Spring bean. No agent type is a carve-out any more, on any endpoint or on the heartbeat. `@MeshStartupCheck` works on a gateway too, and it is the one that matters more there - a gateway with a broken config should never come up.

The starter mounts `/startupz`, `/livez`, `/ready` and `/health` from one controller on every agent type, so those four paths are taken. A `@GetMapping` of your own for any of them is an ambiguous mapping and the application fails to start; put your own diagnostics on a path of your own.

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

## Spring Boot Actuator

Actuator is not a starter dependency, and mesh registers no `HealthIndicator` - deliberately. Actuator aggregates every registered indicator (datasource, disk, mail), while mesh gates traffic only on what `@MeshHealthCheck` says gates it. If your application adds Actuator itself, `/actuator/health` reports that application's indicators and says nothing about mesh; nothing mesh does appears there.

The mesh verdict is on the endpoints above - `/health` is the one to curl:

```bash
curl http://localhost:8080/health
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
