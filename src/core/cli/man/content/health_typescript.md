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
  execute: async ({}, { date_service }) => {
    // If date_service agent restarts or is replaced,
    // the proxy automatically points to new instance
    if (date_service) {
      return await date_service({});
    }
    return "Service unavailable";
  },
});
```

## Health Endpoints

TypeScript agents automatically expose health endpoints:

```typescript
// Automatic health check at /health
// Returns: { status: "healthy", agentId: "my-agent-abc123" }
```

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
  execute: async ({ data }, { primary_service, backup_service }) => {
    // Try primary first
    if (primary_service) {
      try {
        return await primary_service({ data });
      } catch (error) {
        console.log("Primary failed, trying backup");
      }
    }

    // Fall back to backup
    if (backup_service) {
      return await backup_service({ data });
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
  execute: async ({ request, priority }, { fast_processor, reliable_processor }) => {
    // High priority: prefer fast if available
    if (priority === "high" && fast_processor) {
      try {
        return await fast_processor({ request });
      } catch {
        console.log("Fast processor failed, falling back");
      }
    }

    // Normal/Low priority or fast failed: use reliable
    if (reliable_processor) {
      return await reliable_processor({ request });
    }

    // Last resort: try fast
    if (fast_processor) {
      return await fast_processor({ request });
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
