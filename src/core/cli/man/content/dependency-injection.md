# Dependency Injection (DDDI)

> Distributed Dynamic Dependency Injection — runtime discovery, proxy creation, and automatic wiring across the mesh

## Overview

MCP Mesh provides automatic dependency injection (DI) that connects agents based on their declared capabilities and dependencies. When a function declares a dependency, the mesh automatically creates a callable proxy that routes to the providing agent.

MCP Mesh implements **Distributed Dynamic Dependency Injection (DDDI)** — unlike traditional DI frameworks that wire dependencies at compile time on a single machine, DDDI discovers and injects dependencies at runtime across distributed agents, languages, and clouds.

## How It Works

1. **Declaration**: Function declares dependencies via `@mesh.tool` decorator
2. **Registration**: Agent registers with registry, advertising capabilities
3. **Resolution**: Registry matches dependencies to providers
4. **Injection**: Mesh creates proxy objects for each dependency
5. **Invocation**: Calling the proxy routes to the remote agent

## Resolution Pipeline

When the registry resolves one of your dependencies, candidate providers flow through a fixed sequence of filter stages:

```
health → capability_match → tags → version → schema → tiebreaker
```

| Stage              | What it filters on                                                          |
| ------------------ | --------------------------------------------------------------------------- |
| `health`           | Drops unhealthy / deregistering candidates first                            |
| `capability_match` | Indexed query on the capability name                                        |
| `tags`             | Required / preferred / excluded tag filter (with scoring)                   |
| `version`          | Semver constraint (`>=2.0.0`, `^1.4`, ...)                                  |
| `schema`           | Opt-in schema check (issue #547) — see below                                |
| `tiebreaker`       | `HighestScoreFirst` from the surviving set                                  |

Every decision the registry makes is recorded as a `dependency_resolved` (or `dependency_unresolved`) event. Use `meshctl audit <agent>` to read them back — see `meshctl man audit`.

## Loop topology

The Python runtime dispatches `async def` `@mesh.tool` functions across a pool of worker threads, each owning its own asyncio loop. Default pool size is `min(8, max(2, cpu_count()))` — always ≥ 2.

**Why a pool, not one loop.** A tool that blocks the asyncio loop (sync `time.sleep`, sync DB driver, CPU-bound work) shouldn't freeze `/health`, `/livez`, registry heartbeats, or other concurrent tool calls. Isolating tool dispatch onto a pool of worker loops keeps infra endpoints responsive even when a handler is misbehaving.

**The implication.** Module-level loop-bound resources bind to whatever loop created them and fail when reused from a different loop. The canonical examples are `asyncpg.Pool`, `redis.asyncio.Redis`, `motor.motor_asyncio.AsyncIOMotorClient`, and `aiohttp.ClientSession` — all of them cache internal `Future` objects against the creating loop. On default workers, the first call lazily creates the resource on worker A; the second call lands on worker B and throws:

```
RuntimeError: Task <...> got Future <...> attached to a different loop
```

This is a real footgun for the natural FastAPI-shaped pattern of "cache a pool at module level." Two clean answers, depending on what you need:

- **One shared loop-bound resource, CRUD-shape tools.** Set `MCP_MESH_TOOL_WORKERS=1` to collapse to a single worker loop. Module-level resource caching works as expected. Trade-off: lose parallel execution of blocking work (async still interleaves cooperatively within a single loop). Full trade-off table in `meshctl man dependency-injection` (Python doc) under "Single-worker mode for shared loop-bound resources".

- **Long-running stateful work.** Use MeshJob (`@mesh.tool(task=True)`) with state externalized to a separate state agent. The orchestrator stays stateless; the state agent owns the durable storage. See `meshctl man jobs` for the MeshJob primitive and the Stateful Agents concept doc for the full decomposition.

For the narrow case where neither answer fits (sub-10ms state-mutation latency budgets, unportable loop-bound resources like GPU contexts, true background daemons running between tool calls), see the In-Process State escape hatch in the concepts docs. The default answer should still be MeshJob.

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

**Note**: Both `@mesh.tool` and `@mesh.route` inject dependencies POSITIONALLY into `McpMeshTool`-typed parameters — pairing the order of `McpMeshTool` parameters in the function signature against the order of `dependencies=[...]` (the runtime takes `mesh_positions[: len(dependencies)]`). Parameter names like `date_service` in examples are reader-friendly only — they don't match against the dependency capability name. The same rule applies in TypeScript (`addTool({ dependencies: [...] })`, injected positionally) and Java (`@MeshTool(dependencies = @Selector(...))`, parameter order). `MeshJob` parameters use a separate type-based injection mechanism (one `MeshJob` slot per tool, detected by parameter type) — see `meshctl man jobs`.

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

### Schema-Aware Filtering (issue #547)

Add `expected_type` (and optionally `match_mode`) to opt the dependency into the schema stage of the pipeline. Producers whose published `outputSchema` doesn't satisfy your expected type are evicted with `SchemaIncompatible`.

```python
from pydantic import BaseModel

class Employee(BaseModel):
    id: int
    name: str
    department: str

@app.tool()
@mesh.tool(
    capability="hr_report",
    dependencies=[
        {
            "capability": "lookup_employee",
            "expected_type": Employee,
            "match_mode": "subset",   # default opt-in; or "strict"
        },
    ],
)
async def hr_report(employee_lookup: mesh.McpMeshTool = None): ...
```

`match_mode` defaults to `"subset"` when `expected_type` is provided. See `meshctl man schema-matching` for `subset` vs `strict` semantics, the cross-language convention table, and the `MCP_MESH_SCHEMA_STRICT` env knob.

### OR Alternatives (Tag-Level)

Tags also support nested-array OR alternatives for fallback semantics
(e.g., prefer `python`, fallback `typescript`). See the **Tag-Level OR**
section in `meshctl man capabilities` for the full pattern.

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

Per-dependency proxy options (timeout, retry, streaming, session affinity, auth, custom headers, etc.) are configured via `dependency_kwargs`. See `meshctl man proxies` for the full options table.

```python
@mesh.tool(
    dependencies=["slow_service"],
    dependency_kwargs={
        "slow_service": {"timeout": 60, "retry_count": 3},
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

## See Also

- `meshctl man capabilities` - Declaring capabilities
- `meshctl man tags` - Tag-based selection
- `meshctl man schema-matching` - Schema-aware capability filtering (#547)
- `meshctl man audit` - Inspecting resolution decisions
- `meshctl man health` - Health monitoring
- `meshctl man proxies` - Proxy details
- `meshctl man jobs` - MeshJob primitive for long-running stateful work
- Stateful Agents concept doc - State agent + MeshJob orchestrator decomposition
- In-Process State concept doc - Escape hatch for the narrow cases neither MeshJob nor `WORKERS=1` cover
