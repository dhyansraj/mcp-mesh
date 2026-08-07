# Health Monitoring & Auto-Rewiring (TypeScript)

> Fast heartbeat system and automatic topology updates

## Overview

MCP Mesh uses a dual-heartbeat system for fast failure detection and automatic topology updates. Agents maintain connectivity with the registry, and the mesh automatically rewires dependencies when agents join or leave.

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

Pass a `healthCheck` to `mesh()` to tell the mesh what "able to serve" means for this agent:

```typescript
const agent = mesh(server, {
  name: "claude-provider",
  httpPort: 9001,
  healthCheckTtl: 30,
  healthCheck: async () => {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      return {
        status: "unhealthy",
        checks: { vendor_api_key_present: false },
        errors: ["ANTHROPIC_API_KEY not set"],
      };
    }
    const response = await fetch("https://api.anthropic.com/v1/models", {
      headers: { "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
      signal: AbortSignal.timeout(5_000),
    });
    return response.status === 200
      ? { status: "healthy", checks: { vendor_api_reachable: true } }
      : {
          status: "unhealthy",
          checks: { vendor_api_reachable: false },
          errors: [`vendor returned ${response.status}`],
        };
  },
});
```

One check per agent. Return `{ status, checks, errors }` for full detail, or a `boolean` for the terse form (`true` healthy, `false` unhealthy). `healthCheckTtl` is how often it re-runs (default 15); `MCP_MESH_HEALTH_CHECK_TTL` overrides it.

The verdict drives `/health`, which answers 200 only while the check reports `healthy` and carries the `checks` and `errors` it returned. It does not drive `/ready`, which reports whether the mesh runtime is up: pausing the heartbeat already withdraws the agent, and a 503 on `/ready` would additionally empty the Service that mesh traffic arrives on. `/livez` never consults it either - a restart cannot fix a vendor outage.

### What a Failing Check Does

While the check reports unhealthy the agent **stops heartbeating**. The registry marks it unhealthy after the staleness window, dependency resolution stops selecting it, and consumers move to another provider. When the check passes again the heartbeat resumes and the registry restores the agent through the `410 Gone` re-register path - no restart. The TTL is the cadence, not the end-to-end latency: it only bounds how long until the next check runs. Withdrawal costs that plus the registry's staleness window once heartbeats stop, and recovery costs it plus the heartbeat resume and re-register round trip.

Report `unhealthy` only for conditions the mesh should route around: the upstream this agent needs is genuinely not serving. A check that **throws**, or that could not reach a conclusion, is recorded as `degraded` and keeps heartbeating - a broken probe says nothing about the upstream, and withdrawing a working agent over one is the worse failure.

`degraded` shows on the diagnostic surface only, the same way it does on Python and Java: the agent keeps heartbeating and stays in dependency resolution, and `/health` answers 503 while `/ready` is unmoved. Nothing probes `/health`, so its status code is free to carry the verdict; readiness reports the mesh runtime and nothing else.

A `mesh.route` or A2A gateway runs the check exactly as an MCP agent does, and a failing one pauses its heartbeat too, so the registry stops advertising it. Nothing else changes: the Express server keeps listening, the dependencies it already resolved stay wired, and `/ready` still answers 200 - the pod keeps its Service endpoints and keeps taking ingress. A withdrawn gateway stops being discovered; it does not go dark.

Declare it on the gateway itself, in the `meshExpress` config:

```typescript
const meshApp = meshExpress(app, {
  name: "my-gateway",
  httpPort: 3000,
  healthCheckTtl: 30,
  healthCheck: async () => (await upstreamReachable()) || { status: "unhealthy", errors: ["upstream down"] },
});
```

`mesh.route()` on its own auto-initializes a gateway with no config object, so there is nowhere to declare a check on that path - use `meshExpress` when you want one, and use it INSTEAD of `mesh.route()`, not alongside it: `mesh.route()` starts the API runtime itself, so a process doing both registers two agents. That is not a gap awaiting a fix (issue #1506, for the equivalent on Python). Mesh gives a gateway dependency injection, not lifecycle management: a `mesh.route()` app is an ordinary Express application, so validate its configuration at boot and `process.exit(1)`, and Kubernetes reports `CrashLoopBackOff` with the cause in the logs.

## Registry Health Monitor

Background process that:

- Scans for agents past timeout threshold
- Marks unhealthy agents in database
- Generates audit events for topology changes
- Triggers `202` responses to notify other agents

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

### Performance Profiles

**Development (fast feedback)**:

```bash
DEFAULT_TIMEOUT_THRESHOLD=10
HEALTH_CHECK_INTERVAL=5
```

**Production (balanced)**:

```bash
DEFAULT_TIMEOUT_THRESHOLD=20
HEALTH_CHECK_INTERVAL=10
```

**High-Performance (sub-5s detection)**:

```bash
DEFAULT_TIMEOUT_THRESHOLD=5
HEALTH_CHECK_INTERVAL=2
```

## Auto-Rewiring

When topology changes, the mesh automatically:

1. **Detects change**: Via heartbeat response (`202`)
2. **Fetches new topology**: Registry returns updated dependencies
3. **Compares hashes**: Prevents unnecessary updates
4. **Refreshes proxies**: Creates new proxy objects
5. **Routes traffic**: New calls go to updated providers

### Code Impact

None! Auto-rewiring is transparent:

```typescript
agent.addTool({
  name: "my_tool",
  capability: "my_capability",
  dependencies: ["date_service"],
  parameters: z.object({}),
  execute: async ({}, dateService: McpMeshTool | null = null) => {
    // If the date_service agent restarts or is replaced,
    // the proxy automatically points to the new instance
    if (dateService) {
      return await dateService({});
    }
    return "Service unavailable";
  },
});
```

## Health Endpoints

TypeScript agents automatically expose four endpoints, and Kubernetes probes must not share one:

- `/startupz` - `startupProbe`. Reports your `startupCheck`; an agent that declares none passes.
- `/livez` - `livenessProbe`. 200 for as long as the process is serving; consults nothing else.
- `/ready` - `readinessProbe`. 200 once the mesh runtime is up; 503 before that and while shutting down. Your `healthCheck` does not reach it.
- `/health` - no probe. The check's verdict plus the `checks` and `errors` it returned; 200 only while it reports `healthy`. An agent with no `healthCheck` is healthy.

```typescript
// GET /health
// { status: "healthy", agent: "my-agent", checks: { vendor_api_reachable: true }, errors: [], timestamp: "..." }

// GET /ready
// { ready: true, agent: "my-agent", runtime: "up", mcp_wrappers: 1, timestamp: "..." }
```

A gateway wrapped in `meshExpress` serves the same four URLs, and its `/health` carries the same verdict. A bare `mesh.route()` app does not: mesh never touches the Express server there, so nothing mounts the four and the chart's probes 404 until you define them yourself. `meshctl scaffold api --lang typescript` generates them.

## Graceful Shutdown

TypeScript SDK handles SIGINT/SIGTERM automatically:

```typescript
// No code needed - SDK installs handlers automatically
// Agents deregister cleanly on shutdown
```

## Graceful Failure

The mesh handles failures gracefully:

- **Registry down**: Existing agent-to-agent communication continues
- **Agent down**: Dependencies return `null`, code handles gracefully
- **Network partition**: Agents continue with cached topology
- **Recovery**: Automatic reconnection and topology refresh

## Handling Unavailable Dependencies

```typescript
agent.addTool({
  name: "resilient_tool",
  capability: "resilient",
  dependencies: ["primary_service", "backup_service"],
  parameters: z.object({ data: z.string() }),
  execute: async (
    { data },
    primaryService: McpMeshTool | null = null,  // dependencies[0]
    backupService: McpMeshTool | null = null,   // dependencies[1]
  ) => {
    // Try primary first
    if (primaryService) {
      try {
        return await primaryService({ data });
      } catch (error) {
        console.log("Primary failed, trying backup");
      }
    }

    // Fall back to backup
    if (backupService) {
      return await backupService({ data });
    }

    // Both unavailable
    return JSON.stringify({
      error: "All services unavailable",
      suggestion: "Check mesh status",
    });
  },
});
```

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

## Complete Example

```typescript
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Resilient Service", version: "1.0.0" });
const agent = mesh(server, {
  name: "resilient-service",
  httpPort: 8080,
  heartbeatInterval: 30,  // Custom heartbeat interval
});

// Tool with health-aware dependency handling
agent.addTool({
  name: "process_request",
  capability: "request_processor",
  description: "Process requests with fallback handling",
  dependencies: [
    { capability: "fast_processor", tags: ["+fast"] },
    { capability: "reliable_processor", tags: ["+reliable"] },
  ],
  parameters: z.object({
    request: z.string(),
    priority: z.enum(["high", "normal", "low"]).default("normal"),
  }),
  execute: async (
    { request, priority },
    fastProcessor: McpMeshTool | null = null,      // dependencies[0]
    reliableProcessor: McpMeshTool | null = null,  // dependencies[1]
  ) => {
    // High priority: prefer fast if available
    if (priority === "high" && fastProcessor) {
      try {
        return await fastProcessor({ request });
      } catch {
        console.log("Fast processor failed, falling back");
      }
    }

    // Normal/Low priority or fast failed: use reliable
    if (reliableProcessor) {
      return await reliableProcessor({ request });
    }

    // Last resort: try fast
    if (fastProcessor) {
      return await fastProcessor({ request });
    }

    return JSON.stringify({
      error: "No processors available",
      status: "service_degraded",
    });
  },
});

// The agent will automatically:
// - Send heartbeats to registry
// - Receive topology updates
// - Rewire proxies when services change
// - Handle graceful shutdown
```

## See Also

- `meshctl man registry` - Registry operations
- `meshctl man dependency-injection --typescript` - How DI handles failures
- `meshctl man environment` - Configuration options
