<div class="runtime-crossref">
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../java/dependency-injection/">Java Dependency Injection</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/dependency-injection/">TypeScript Dependency Injection</a></span>
</div>

# Dependency Injection

> Automatic wiring of capabilities between agents

MCP Mesh implements **[Distributed Dynamic Dependency Injection (DDDI)](../concepts/dddi.md)** — dependencies are discovered and injected at runtime across the mesh, not at compile time.

**Note:** This page shows Python examples. See `meshctl man dependency-injection --typescript` for TypeScript or `meshctl man dependency-injection --java` for Java/Spring Boot examples.

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a function declares a dependency, the mesh automatically creates a callable proxy that routes to the providing agent.

## How It Works

1. **Declaration**: Function declares dependencies via `@mesh.tool` decorator
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh creates proxy objects for each dependency
5. **Invocation**: Calling the proxy routes to the remote agent

## Declaring Dependencies

### Simple Dependencies

```python
@app.tool()
@mesh.tool(
    capability="greeting",
    dependencies=["date_service"],  # Request by capability name
)
async def greet(name: str, date_service: mesh.McpMeshTool = None) -> str:
    if date_service:
        today = await date_service()  # Must use await!
        return f"Hello {name}! Today is {today}"
    return f"Hello {name}!"
```

**Important**: Functions with dependencies must be `async def` and calls must use `await`.

### Dependencies with Filters

Use the capability selector syntax (see `meshctl man capabilities`) to filter by tags or version:

```python
@app.tool()
@mesh.tool(
    capability="report",
    dependencies=[
        {"capability": "data_service", "tags": ["+fast"]},
        {"capability": "formatter", "tags": ["-deprecated"]},
    ],
)
async def generate_report(
    data_svc: mesh.McpMeshTool = None,
    formatter: mesh.McpMeshTool = None,
) -> str:
    data = await data_svc(query="sales")
    return await formatter(data=data)
```

### OR Alternatives (Tag-Level)

Use nested arrays in tags to specify fallback providers:

```python
@app.tool()
@mesh.tool(
    capability="calculator",
    dependencies=[
        # Prefer python provider, fallback to typescript
        {"capability": "math", "tags": ["addition", ["python", "typescript"]]},
    ],
)
async def calculate(a: int, b: int, math: mesh.McpMeshTool = None):
    result = await math(a=a, b=b)
    return result
```

Resolution order:

1. Try to find provider with `addition` AND `python` tags
2. If not found, try provider with `addition` AND `typescript` tags
3. If neither found, dependency is unresolved (injected as `None`)

This is useful when you have multiple implementations of the same capability
and want to prefer one but fallback to another if unavailable.

## Injection Types

### mesh.McpMeshTool

Callable proxy for tool invocations:

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    result = await helper(arg1="value")  # Direct call
    result = await helper.call_tool("tool_name", {"arg": "value"})  # Named tool
```

### mesh.MeshLlmAgent

For LLM agent injection in `@mesh.llm` decorated functions:

```python
@mesh.llm(...)
def smart_tool(ctx: Context, llm: mesh.MeshLlmAgent = None):
    response = llm("Process this request")
```

## Graceful Degradation

Dependencies may be unavailable. Always handle `None`:

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper is None:
        return "Service temporarily unavailable"
    return await helper()
```

Or use default values:

```python
async def get_time(date_service: mesh.McpMeshTool = None):
    if date_service:
        return await date_service()
    return datetime.now().isoformat()  # Fallback
```

## Proxy Configuration

Configure proxy behavior via `dependency_kwargs`:

```python
@mesh.tool(
    dependencies=["slow_service"],
    dependency_kwargs={
        "slow_service": {
            "timeout": 60,           # Request timeout (seconds)
            "retry_count": 3,        # Retry attempts
            "streaming": True,       # Enable streaming
            "session_required": True, # Require session affinity
        }
    },
)
async def my_tool(slow_service: mesh.McpMeshTool = None):
    result = await slow_service(data="large_payload")
    ...
```

## Proxy Types (Auto-Selected)

The mesh uses a unified proxy system:

| Proxy Type                | Use Case                                        |
| ------------------------- | ----------------------------------------------- |
| `SelfDependencyProxy`     | Same agent (direct call, no network overhead)   |
| `EnhancedUnifiedMCPProxy` | Cross-agent calls (auto-configured from kwargs) |

## Function vs Capability Names

- **Capability name**: Used for dependency resolution (`date_service`)
- **Function name**: Used in MCP tool calls (`get_current_time`)

The mesh maps capabilities to their implementing functions automatically.

## Auto-Rewiring

When topology changes (agents join/leave), the mesh:

1. Detects change via heartbeat response
2. Refreshes dependency proxies
3. Routes to new providers automatically

No code changes needed - happens transparently.

## Single-worker mode for shared loop-bound resources

Some Python async libraries hand back objects that are bound to the
specific asyncio loop they were created on — `asyncpg.Pool`,
`redis.asyncio.Redis`, `motor.motor_asyncio.AsyncIOMotorClient`,
`aiohttp.ClientSession`, and many others. The library caches internal
`Future` objects against the creating loop; awaiting any of them from a
different loop throws:

```
RuntimeError: Task <...> got Future <...> attached to a different loop
```

The mesh Python runtime dispatches `async def` `@mesh.tool` functions
across a small pool of worker loops (default `min(8, max(2, cpu_count()))`,
always ≥ 2). The pool keeps `/health`, `/livez`, registry heartbeats,
and other concurrent tool calls responsive even when one tool blocks the
loop. The full topology is documented in `meshctl man dependency-injection`.

The interaction: if you cache a pool at module level on default workers,
the lazy initializer runs on whichever worker loop happened to receive
the first call. Subsequent calls round-robin to a different worker, the
pool's internal Futures fail the cross-loop check, and every call after
the first raises.

### The flag: `MCP_MESH_TOOL_WORKERS=1`

Pin the agent to a single worker loop. The pool gets created on that
loop, every subsequent tool call lands on that same loop, no cross-loop
sharing happens. Module-level resource caching works the way you'd
expect from a non-mesh FastAPI agent.

### Trade-offs

| Property | Default (N≥2) | `WORKERS=1` |
|---|---|---|
| Health/livez endpoint stays responsive when a tool blocks | ✓ | ✓ |
| Module-level loop-bound resource shared across tools | ✗ | ✓ |
| Parallel execution when a tool does blocking sync work | ✓ | ✗ (serialized) |
| Async cooperative concurrency within a tool body | ✓ | ✓ |

The `/health` and `/livez` endpoints run on their own thread regardless
of `WORKERS`, so infra signals stay responsive in both modes. The
asymmetry is in parallel execution of tool bodies that block the loop:
on default workers, two blocking tools run concurrently on two
workers; on `WORKERS=1`, the second waits for the first.

### When to use it

Good fit:

- **Single-tenant CRUD agents** with one shared asyncpg pool or one
  shared Redis client.
- **State agents** in the [stateful-agents pattern](../concepts/stateful-agents.md) —
  pure read/write tools over durable storage, no long-running work in
  the agent itself.
- Any agent where the shared resource cost (creating per-tool pools)
  outweighs the parallel-execution gain.

Bad fit:

- **Agents that do blocking sync work** (sync DB drivers, CPU-bound
  computation) and need true parallelism. Keep default workers and use
  `await asyncio.to_thread(blocking_fn, ...)` inside the handler — that
  offloads to the runtime's thread pool without freezing the worker
  loop.
- **CPU-bound workloads** that need to use multiple cores in parallel.
  `WORKERS=1` serializes; default workers parallelize only across
  loops, not across CPU cores (use process-level parallelism for that).
- **Agents that hold genuinely long-lived state in process memory**
  beyond a connection pool. See
  [In-Process State (Escape Hatch)](../concepts/in-process-state.md)
  for the narrower cases where `WORKERS=1` isn't enough.

### How to set it

Docker compose:

```yaml
services:
  state-agent:
    environment:
      MCP_MESH_TOOL_WORKERS: "1"
```

Helm values:

```yaml
env:
  MCP_MESH_TOOL_WORKERS: "1"
```

Kubernetes deployment spec:

```yaml
spec:
  containers:
    - name: state-agent
      env:
        - name: MCP_MESH_TOOL_WORKERS
          value: "1"
```

For the bigger-picture decomposition (state agent + MeshJob orchestrator
+ client surface) that motivates this flag, see
[Stateful Agents](../concepts/stateful-agents.md). For the narrower
cases where even single-worker isn't enough (sub-10ms latency budgets,
unportable loop-bound resources, true background daemons), see
[In-Process State](../concepts/in-process-state.md).

## See Also

- `meshctl man capabilities` - Declaring capabilities
- `meshctl man tags` - Tag-based selection
- `meshctl man health` - Health monitoring
- `meshctl man proxies` - Proxy details
- [Stateful Agents](../concepts/stateful-agents.md) - State agents +
  MeshJob orchestrators
- [In-Process State](../concepts/in-process-state.md) - Escape hatch
  for narrow cases
