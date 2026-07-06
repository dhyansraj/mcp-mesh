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
| `version`          | Semver constraint (bare `4.6.0` = exact; `>=2.0.0`, `^1.4`, ...)            |
| `schema`           | Opt-in schema check (issue #547) — see below                                |
| `tiebreaker`       | Highest tag-match score, then **highest version**, then agent ID            |

Every decision the registry makes is recorded as a `dependency_resolved` (or `dependency_unresolved`) event. Use `meshctl audit <agent>` to read them back — see `meshctl man audit`.

## Loop topology (v2.2.4+)

mcp-mesh runs your agent across two event loops:

- **Framework loop** (uvicorn main): serves `/health`, `/ready`, `/livez`, and routes MCP protocol traffic. Always responsive.
- **User loop** (single, dedicated): runs FastMCP/FastAPI `lifespan` startup, all `@mesh.tool` and `@app.tool` bodies, and `lifespan` exit.

A long-running tool body holds the user loop, but never the framework loop — K8s probes stay responsive during long tool calls.

**Default `MCP_MESH_TOOL_WORKERS=1`** (since v2.2.4; previously `min(8, max(2, cpu_count()))`). Loop-affine resources (`asyncpg.Pool`, `redis.asyncio.Redis`, `motor.motor_asyncio.AsyncIOMotorClient`, `aiohttp.ClientSession`) created in `lifespan` startup bind to the single-user loop and are reused by every tool body on the same loop. FastMCP's `lifespan` parameter receives a FastMCP server instance (not a FastAPI app), so there is no `.state` namespace — the canonical Python pattern is a module-level global:

```python
from contextlib import asynccontextmanager
import asyncpg
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
```

**Opt-in `MCP_MESH_TOOL_WORKERS=N` (N>1)** for tool bodies that do sync blocking work and need concurrent calls to absorb it. Loop-affinity caveat: resources created in `lifespan` bind to worker-0 only. For cross-worker access, use a per-loop dict cache (each worker lazily builds its own resource on first access). Better escape: `await asyncio.to_thread(blocking_call)` keeps the user loop free without N>1 workers.

For long-running stateful work, use MeshJob (`@mesh.tool(task=True)`) with state externalized to a separate state agent — see `meshctl man jobs` and the Stateful Agents concept doc.

For the narrow case where neither fits (sub-10ms state-mutation latency, unportable loop-bound resources like GPU contexts, true background daemons), see the In-Process State escape hatch. The default answer should still be MeshJob.

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

**Note**: Both `@mesh.tool` and `@mesh.route` inject dependencies POSITIONALLY into `McpMeshTool`-typed parameters — pairing the order of `McpMeshTool` parameters in the function signature against the order of `dependencies=[...]` (the runtime takes `mesh_positions[: len(dependencies)]`). Parameter names like `date_service` in examples are reader-friendly only — they don't match against the dependency capability name. The same rule applies in TypeScript (`addTool({ dependencies: [...] })`, injected positionally) and Java (`@MeshTool(dependencies = @Selector(...))`, parameter order). A `MeshJob` slot (one per tool) is detected by parameter type but counts as an eligible position in this same positional pairing — it pairs with its own `dependencies=[...]` entry, and that dependency is bound as the job's submitter — see `meshctl man jobs`.

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

Dependencies may be unavailable. During agent startup, calls on a declared-but-unresolved dependency first wait — bounded by the settle window (`MCP_MESH_SETTLE_TIMEOUT`, default 20s; the window starts when the agent's first dependency is declared) — for the resolution to land before degrading; once the agent settles, unresolved dependencies inject `None` immediately. Always handle `None`:

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

By default a dependency is optional: an unresolved dependency injects `None`, and the agent still starts, registers, and serves (soft-fail). Mark an edge `required` to opt that single edge into strictness:

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
) -> str: ...
```

`required` defaults to `False` and combines with the other selector fields (`tags`, `version`, `expected_type`). It is carried on the wire only when `True`.

### Availability Semantics

The registry computes a capability-availability predicate:

> a capability is **available** ⇔ its owning agent is healthy **AND** every one of its `required` dependencies resolves to an available provider (full tag / version / schema matching)

The predicate is **transitive**: in a required chain `A → B → C`, if `C` goes down then `B` becomes unavailable and `A` becomes unavailable in turn. Optional edges never propagate — strictness flows only along edges you mark `required`, so the soft-fail default is preserved everywhere else.

An unavailable capability is excluded from resolution exactly like an unhealthy provider — it drops out at the resolver's `health` stage. Consumers holding a proxy to it see the proxy flip to `None` through the same background dependency-update channel that already delivers topology changes — no code changes, no SDK upgrade required.

### Route Perimeter (503)

Mesh-internal calls go through proxies; external HTTP callers to a `@mesh.route` do not. When a route declares a required dependency that is unavailable at call time, the framework's own wrapper returns **503** — before your handler runs, after the settle window — with the body:

```json
{ "error": "dependency_unavailable", "capability": "data_service" }
```

503 rather than 404 so monitoring alarms on 5xx, load-balancer health checks eject the instance, and clients see a retryable "unavailable" instead of a permanent "missing". A caller that supplies its own value for the slot (a test override) is honored and skips the check.

**Streaming routes** (`is_stream=True`) bypass the 503 perimeter by design — an in-flight stream cannot carry a pre-body 503 — so a streaming route's required deps stay soft-fail (`None` injected). The framework logs a warning at registration so the author knows enforcement is off for that route.

### Cycle Rule

A cycle among `required` edges can never converge (both ends stay unavailable forever), so the registry rejects the registration/heartbeat that would close one, loudly naming the loop:

```
required dependency cycle: analyst → enricher → analyst
```

The rejected agent logs `Agent registration failed: required dependency cycle: …` and keeps retrying on each heartbeat until the loop is broken. Cycles routed through an **optional** edge remain legal — that is the bootstrapping path.

### Observing Availability

The agents/capabilities API carries two derived fields per capability:

- `available` — the predicate above (boolean)
- `unavailable_reason` — set when `available` is false; names the first broken edge with its constraint detail, e.g. `required dep 'weather-api' unresolved (no provider matches tags=[+prod])`, `required dep 'data_service' unavailable (provider agent-7 unhealthy)`, or `agent unhealthy` when the owning agent is itself down.

The capability stays visible in the registry, UI, and `meshctl` (availability is distinct from presence), so the reason chain is a diagnostic upgrade, not a disappearance.

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

A facade call takes one `dict` that becomes the target tool's named arguments, and accepts a `headers=` kwarg for header propagation. Each view method expands into an ordinary dependency edge appended **after** the tool's explicit `dependencies` — name-sorted within a view, in parameter order across multiple views — so a view over N capabilities shows as **N dependencies** in `meshctl list`. Capability names are dot-namespaced (see the naming rules in `meshctl man capabilities`).

- Every method must be `async def` with `@mesh.selector`; a **sync** stub or a selector-less public method **boot-fails** (make helpers private with a leading underscore).
- A `required=True` method joins the tool's pre-invoke guard: an unresolved required edge makes the tool return the structured `dependency_unavailable` refusal before the handler runs (direct and claim paths). An unresolved **optional** method raises `ToolError` (`fastmcp.exceptions.ToolError`) carrying that same `dependency_unavailable` payload on its own call only — catch it to degrade gracefully.
- When a `@mesh.selector` sets `match_mode`, its `expected_type` defaults to the stub method's **return annotation** (mirroring Java's `schemaMode` deriving the type from the method return type); pass `expected_type=` to override. Only **structured** return types derive a schema — a Pydantic model, dataclass, or `TypedDict`, including `list[Model]` and `Optional[Model]`. Bare containers (`dict`, `list`), scalars, `Any`, `-> None`, and unannotated stubs derive nothing (no schema, no provider filtering) — a deliberate, conservative divergence from Java.
- `@mesh.service(min_available=N)` adds a consumer-local floor: below `N` resolved methods every facade call raises `mesh.MeshServiceUnavailableError` (settle-aware). Default `0` = no floor.
- **Testing:** passing your own facade object for the view parameter skips the pre-invoke refusal and settle wait for that view — mock the facade directly in unit tests.
- Views are a **tool-parameter** surface only: a view in `@mesh.route` boot-fails, and an undecorated subclass of a view is not a view (decorate the class directly).

### Publishing a service (producer side)

Give `@mesh.service` a **prefix** and the class becomes a producer: each public method (a real `async` implementation) publishes as an ordinary tool with capability `prefix.<method>`.

```python
@mesh.service("media")              # publishes media.caption, media.thumbnail
class MediaTools:
    async def caption(self, args: dict) -> dict:
        return {"caption": f"a scene: {args['text']}"}
    async def thumbnail(self, args: dict) -> dict:
        return {"uri": f"thumb://{args['asset_id']}"}
```

- Methods publish **name-sorted** under dotted tool names; underscore-prefixed methods are skipped.
- A method carrying its own `@mesh.tool` **wins** (keeps its declared capability/tags/version).
- The class must be **zero-arg constructible** (instantiated once at decoration time to publish bound methods); the `prefix` is segment-validated against the dotted-capability grammar. A `@mesh.selector` inside a prefixed class is a **mixed-roles boot-fail**, and `min_available` is consumer-only.

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
- In-Process State concept doc - Escape hatch for narrow cases where neither MeshJob nor the standard FastAPI `lifespan` pattern fits
