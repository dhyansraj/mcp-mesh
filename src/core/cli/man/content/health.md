# Health Monitoring & Auto-Rewiring

> Fast heartbeat system and automatic topology updates

**Note:** This page shows Python examples. See `meshctl man health --typescript` for TypeScript or `meshctl man health --java` for Java/Spring Boot examples.

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

```python
@mesh.tool(dependencies=["date_service"])
def my_tool(date_svc: mesh.McpMeshTool = None):
    # If date_service agent restarts or is replaced,
    # the proxy automatically points to new instance
    return date_svc()
```

## Custom Health Checks

Add custom health checks to your agent:

```python
async def my_health_check() -> dict:
    # Check your dependencies
    db_ok = await check_database()
    api_ok = await check_external_api()

    return {
        "status": "healthy" if (db_ok and api_ok) else "unhealthy",
        "checks": {
            "database": db_ok,
            "external_api": api_ok,
        },
        "errors": [] if (db_ok and api_ok) else ["Some checks failed"],
    }

@mesh.agent(
    name="my-service",
    health_check=my_health_check,
    health_check_ttl=30,  # Cache health for 30 seconds
)
class MyAgent:
    pass
```

## Graceful Failure

The mesh handles failures gracefully:

- **Registry down**: Existing agent-to-agent communication continues
- **Agent down**: Dependencies return `None`, code handles gracefully
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
- `meshctl man dependency-injection` - How DI handles failures
- `meshctl man environment` - Configuration options
