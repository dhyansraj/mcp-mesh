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

## Required Dependencies

Graceful degradation is the default — an unresolved dependency injects `None` and your agent keeps serving. When a capability is useless without a particular dependency, mark that edge `required` instead of null-checking it everywhere:

```python
@app.tool()
@mesh.tool(
    capability="report",
    dependencies=[
        {"capability": "data_service", "required": True},
        {"capability": "formatter"},  # optional (default)
    ],
)
async def generate_report(
    data_svc: mesh.McpMeshTool = None,
    formatter: mesh.McpMeshTool = None,
) -> str:
    data = await data_svc(query="sales")  # data_svc is guaranteed live
    if formatter:
        return await formatter(data=data)
    return str(data)
```

`required` defaults to `False` and combines with the other selector fields (`tags`, `version`, `expected_type`).

**What it changes.** The registry now computes a capability as **available** only when its owning agent is healthy *and* every one of its `required` dependencies resolves to an available provider. This is transitive — in a chain `A → B → C`, if `C` goes down then `B` becomes unavailable and `A` becomes unavailable in turn. An unavailable capability drops out of resolution exactly like an unhealthy provider, so any consumer's proxy for it flips to `None` automatically, with no code change. Optional edges never propagate, so soft-fail stays the default everywhere you don't opt in.

**HTTP routes get an automatic 503.** External callers to a `@mesh.route` don't go through proxies, so when a route declares a required dependency that is unavailable at request time, the framework returns `503` before your handler runs (after the settle window):

```json
{ "error": "dependency_unavailable", "capability": "data_service" }
```

Streaming routes can't carry a pre-body 503, so they bypass the perimeter and keep soft-fail semantics — check `None` there.

**Cycles are rejected.** A cycle of required edges could never converge (both ends stay unavailable forever), so the registry rejects the registration that closes one and logs, on the rejected agent, `Agent registration failed: required dependency cycle: analyst → enricher → analyst`. Cycles that route through an optional edge remain legal — that's the bootstrapping path.

**Inspecting availability.** Each capability in the agents/capabilities API carries `available` (boolean) and, when false, `unavailable_reason` naming the first broken edge — e.g. `required dep 'data_service' unavailable (provider agent-7 unhealthy)` or `required dep 'weather-api' unresolved (no provider matches tags=[+prod])`. The capability stays visible in the registry, UI, and `meshctl`; availability is distinct from presence.

## Service Views (RFC #1280)

A **service view** aggregates several capability dependencies behind one typed class. Decorate a class with `@mesh.service`; every public method is an **`async` stub** carrying `@mesh.selector("cap", ...)` that binds one capability. Pass the view class as a `@mesh.tool` parameter (detected by type, like `MeshJob`) and the framework injects a facade whose methods each delegate to their capability's own resolved proxy — so different methods can resolve to different provider agents and rebind independently.

```python
@mesh.service                       # or @mesh.service(min_available=2)
class MediaService:
    @mesh.selector("media.caption", required=True, tags=["+fast"])
    async def caption(self, args: dict) -> dict: ...
    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...
    @mesh.selector("media.transcribe")
    async def transcribe(self, args: dict) -> dict: ...


@app.tool()
@mesh.tool(capability="process_media", dependencies=["audit_log"])
async def process_media(
    req: dict,
    audit: mesh.McpMeshTool = None,
    media: MediaService = None,
):
    caption = await media.caption({"text": req["text"]})   # dict → the target tool's named args
    try:
        thumb = await media.thumbnail({"asset_id": req["id"]})
    except ToolError as e:
        # swallow ONLY the unresolved-optional refusal, not provider-side errors
        if "dependency_unavailable" not in str(e):
            raise
        thumb = None
    return {"caption": caption, "thumbnail": thumb}
```

A facade call takes one `dict` that becomes the target tool's named arguments, and accepts a `headers=` kwarg for header propagation. Each view method expands into an ordinary dependency edge appended **after** the tool's explicit `dependencies` — name-sorted within a view, in parameter order across multiple views — so a view over N capabilities shows as **N dependencies** in `meshctl list`. Capability names are dot-namespaced (see the [naming rules](capabilities-tags.md#capability-naming-conventions)).

- Every method must be `async def` with `@mesh.selector`; a **sync** stub or a selector-less public method **boot-fails** (make helpers private with a leading underscore).
- A `required=True` method joins the tool's pre-invoke guard: an unresolved required edge makes the tool return the structured `dependency_unavailable` refusal before the handler runs (direct and claim paths). An unresolved **optional** method raises `ToolError` (`fastmcp.exceptions.ToolError`) carrying that same `dependency_unavailable` payload on its own call only — catch it to degrade gracefully.
- When a `@mesh.selector` sets `match_mode`, its `expected_type` defaults to the stub method's **return annotation** (mirroring Java's `schemaMode` deriving the type from the method return type); pass `expected_type=` to override. Only **structured** return types derive a schema — a Pydantic model, dataclass, or `TypedDict`, including `list[Model]` and `Optional[Model]`. Bare containers (`dict`, `list`), scalars, `Any`, `-> None`, and unannotated stubs derive nothing (no schema, no provider filtering) — a deliberate, conservative divergence from Java.
- `@mesh.service(min_available=N)` adds a consumer-local floor: below `N` resolved methods every facade call raises `mesh.MeshServiceUnavailableError` (settle-aware). Default `0` = no floor.
- **Testing:** passing your own facade object for the view parameter skips the pre-invoke refusal and settle wait for that view — mock the facade directly in unit tests.
- Views are a **tool-parameter** surface only: a view in `@mesh.route` boot-fails, and an undecorated subclass of a view is not a view (decorate the class directly).

### Publishing the dotted capabilities a view binds

A view is consumer-side only — it aggregates capabilities, it does not publish them. The dotted capabilities it binds are ordinary tools, each declared explicitly on its provider with a dot-namespaced `capability`:

```python
@app.tool()
@mesh.tool(capability="media.caption")
async def caption(args: dict) -> dict:
    return {"caption": f"a scene: {args['text']}"}


@app.tool()
@mesh.tool(capability="media.thumbnail")
async def thumbnail(args: dict) -> dict:
    return {"uri": f"thumb://{args['asset_id']}"}
```

Each dotted `capability` is segment-validated against the dotted-capability grammar and resolves independently, so `media.caption` and `media.thumbnail` can live on the same agent or on separate ones. `meshctl list --services` groups them for display by the segments before the last dot (see the [naming rules](capabilities-tags.md#capability-naming-conventions)).

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

## Loop topology (v2.2.4+)

mcp-mesh runs your agent across two event loops:

- **Framework loop** (uvicorn main): serves `/health`, `/ready`,
  `/livez`, and routes MCP protocol traffic. Always responsive.
- **User loop** (single, dedicated): runs your FastMCP/FastAPI
  `lifespan` startup, all `@mesh.tool` and `@app.tool` bodies, and
  `lifespan` exit. One loop for everything you write.

A long-running tool body holds the user loop, but never the framework
loop — K8s liveness/readiness probes stay responsive.

### Default `MCP_MESH_TOOL_WORKERS=1`

Since v3.2.2, default tool dispatch runs on a single-user loop (was
`min(8, max(2, cpu_count()))`). The canonical pattern for loop-bound
resources works as expected — `lifespan` startup creates the resource
on the user loop; every tool body uses it on the same loop; `lifespan`
exit closes it on the same loop. Note that FastMCP's `lifespan`
receives a FastMCP server instance, not a FastAPI app, so there is no
`.state` namespace to attach the resource to — the canonical Python
pattern is a module-level global.

```python
from contextlib import asynccontextmanager
import asyncpg
import mesh
from fastmcp import FastMCP

# Module-level — FastMCP's lifespan param is a FastMCP server instance,
# not a FastAPI app, so .state isn't available. The canonical Python
# pattern is a module-level global.
_pool = None


@asynccontextmanager
async def _lifespan(server):
    global _pool
    _pool = await asyncpg.create_pool(...)
    try:
        yield
    finally:
        if _pool is not None:
            await _pool.close()


app = FastMCP("my-agent", lifespan=_lifespan)


@app.tool()
@mesh.tool(capability="query")
async def query() -> dict:
    async with _pool.acquire() as conn:
        return await conn.fetchrow("SELECT ...")
```

No per-loop dict workarounds, no `WORKERS=1` ceremony. Loop-affine
libraries (`asyncpg.Pool`, `redis.asyncio.Redis`, `aiohttp.ClientSession`)
just work.

### Opt-in `MCP_MESH_TOOL_WORKERS=N` (N>1)

If a tool body does sync blocking work (`time.sleep`, `requests.get`,
CPU-bound number crunching) and you need concurrent calls to absorb it
rather than serializing on one loop, set `MCP_MESH_TOOL_WORKERS=N`.
You get N worker loops, dispatched round-robin.

Loop-affinity caveat: resources created in `lifespan` bind to worker-0
only. Tools dispatched to worker-1..N-1 cannot share them. For
cross-worker access, use a per-loop dict cache — each worker lazily
builds its own resource on first access. See
`src/runtime/python/_mcp_mesh/engine/unified_mcp_proxy.py` for the SDK's
own internal use of this pattern for httpx clients.

**Better escape for sync-blocking**: prefer
`await asyncio.to_thread(blocking_call)` over N>1. The blocking call
runs on Python's default thread pool; the user loop stays free; no
cross-worker resource problem.

### Trade-offs

| Concern | N=1 (default) | `MCP_MESH_TOOL_WORKERS=N` (N>1) |
|---|---|---|
| FastMCP/FastAPI `lifespan` + loop-bound resource (asyncpg, redis, aiohttp) | Works | Resource bound to worker-0 only — use per-loop dict for cross-worker access |
| Parallel `asyncio.gather` fan-out within one tool body | Full parallelism via async I/O | Same |
| Sync blocking in tool body (`time.sleep`, `requests.get`) | Serializes — use `asyncio.to_thread` instead | Absorbed across N worker loops |
| `/health`, `/ready` during long tool calls | Always responsive (framework loop separate) | Same |

### How to set it

Docker compose:

```yaml
services:
  my-agent:
    environment:
      MCP_MESH_TOOL_WORKERS: "4"
```

Helm values:

```yaml
env:
  MCP_MESH_TOOL_WORKERS: "4"
```

Kubernetes deployment spec:

```yaml
spec:
  containers:
    - name: my-agent
      env:
        - name: MCP_MESH_TOOL_WORKERS
          value: "4"
```

For the bigger-picture decomposition (state agent + MeshJob orchestrator
+ client surface), see [Stateful Agents](../concepts/stateful-agents.md).
For the narrow cases where neither default nor N>1 fits (sub-10ms
latency budgets, unportable loop-bound resources, true background
daemons), see [In-Process State](../concepts/in-process-state.md).

## See Also

- `meshctl man capabilities` - Declaring capabilities
- `meshctl man tags` - Tag-based selection
- `meshctl man health` - Health monitoring
- `meshctl man proxies` - Proxy details
- [Stateful Agents](../concepts/stateful-agents.md) - State agents +
  MeshJob orchestrators
- [In-Process State](../concepts/in-process-state.md) - Escape hatch
  for narrow cases
