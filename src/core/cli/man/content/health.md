# Health Monitoring & Auto-Rewiring

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
# Heartbeat cadence to registry (overrides @mesh.agent heartbeat_interval, default 5)
export MCP_MESH_HEALTH_INTERVAL=5

# Auto-run loop interval (overrides @mesh.agent auto_run_interval, default 10)
export MCP_MESH_AUTO_RUN_INTERVAL=10
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

## Declaring Your Own Health Check

Pass a `health_check` to `@mesh.agent` to tell the mesh what "able to serve" means for this agent:

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

One check per agent. Return a `{"status", "checks", "errors"}` dict for full detail, or a `bool` for the terse form (`True` healthy, `False` unhealthy). `health_check_ttl` is how often it re-runs (default 15); `MCP_MESH_HEALTH_CHECK_TTL` overrides it.

### What a Failing Check Does

While the check reports unhealthy the agent **stops heartbeating**. The registry marks it unhealthy after the staleness window, dependency resolution stops selecting it, and consumers move to another provider. When the check passes again the heartbeat resumes and the registry restores the agent - no restart, no redeploy. The TTL is the cadence, not the end-to-end latency: it only bounds how long until the next check runs, and withdrawal costs that plus the registry's staleness window once heartbeats stop.

The check that runs during startup is deliberately exempt: it seeds `/health` but is never reported to the core, so an agent registers and becomes visible first. The first refresh, one TTL later, is the earliest a check can withdraw it.

The verdict drives `/health`, which answers 200 only while the check reports `healthy` and carries the `checks` and `errors` it returned. It does not drive `/ready`, which reports whether the mesh runtime is up: pausing the heartbeat already withdraws the agent, and a 503 on `/ready` would additionally empty the Service that mesh traffic arrives on. `/livez` never consults it either - a restart cannot fix a vendor outage.

### Only an Explicit Unhealthy Withdraws the Agent

A check that **raises** is recorded as `degraded`, not unhealthy, and keeps heartbeating. So is one that returns something other than a dict, a `bool` or a `HealthStatus`. A bug in a health check must not be able to remove a working agent from the mesh. Return `False` or `{"status": "unhealthy"}` to actually withdraw.

`degraded` shows on the diagnostic surface only: the agent keeps heartbeating and stays in dependency resolution, and `/health` answers 503 while `/ready` is unmoved. Nothing probes `/health`, so its status code is free to carry the verdict; readiness reports the mesh runtime and nothing else.

### Route and A2A Agents

`@mesh.route` and `@mesh.a2a` agents never run the check at all - their startup pipelines have no health-refresh loop, so there is no verdict to suppress a heartbeat or to show anywhere. A gateway is a fan-out point that many requests enter through: withdrawing a provider is correct, withdrawing the gateway takes the application down. Declare the check on the agents behind the gateway instead.

They still serve all three probe endpoints, on your own FastAPI app: `/livez` answers 200 for as long as the process serves, `/ready` reports only whether the mesh runtime is running, and `/health` is a diagnostic view that never answers 503. If your app already defines one of those paths, yours is left alone and the other two are still added.

## Graceful Failure

The mesh handles failures gracefully:

- **Registry down**: Already-resolved dependency proxies cache their endpoint and continue functioning — but topology changes (new agents joining, dependencies re-resolving, deregistrations) and new client→agent proxy calls all require the registry to be back up.
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
