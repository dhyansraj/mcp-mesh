# MCP Mesh Decorators

> Core decorators for building distributed agent systems

## Overview

MCP Mesh provides decorators (Python), annotations (Java), and function wrappers (TypeScript) that transform regular functions into mesh-aware distributed services. These APIs handle registration, dependency injection, and communication automatically.

| Decorator            | Purpose                         |
| -------------------- | ------------------------------- |
| `@mesh.agent`        | Configure agent server settings |
| `@mesh.tool`         | Register capability with DI     |
| `@mesh.llm`          | Enable LLM-powered tools        |
| `@mesh.llm_provider` | Create LLM provider (zero-code) |
| `@mesh.route`        | FastAPI route with mesh DI      |
| `@mesh.a2a`          | Expose mesh tools as A2A v1.0 skills (producer, Python only) |
| `@mesh.a2a_consumer` | Bridge an external A2A skill into the mesh as a capability   |

## Decorator Order (Critical!)

When using multiple decorators, order matters:

```python
@app.tool()                  # 1. FastMCP protocol handler (outermost)
@mesh.llm(...)               # 2. LLM integration (if using)
@mesh.a2a_consumer(...)      # 2. OR A2A bridge (mutually exclusive with @mesh.llm)
@mesh.tool(...)              # 3. Mesh capability registration (innermost)
def my_function():
    pass
```

## @mesh.agent

Configures the agent server settings. Applied to a class.

```python
@mesh.agent(
    name="my-service",           # Required: unique agent identifier
    version="1.0.0",             # Semantic version
    description="Service desc",  # Human-readable description
    http_host="localhost",       # Host announced to registry
    http_port=8080,              # HTTP server port (0 = auto-assign)
    enable_http=True,            # Bind HTTP server (default True)
    namespace="default",         # Namespace for isolation
    heartbeat_interval=5,        # Heartbeat cadence in seconds (env: MCP_MESH_HEALTH_INTERVAL)
    health_check=health_fn,      # Optional health check function
    health_check_ttl=15,         # Health check cache TTL (seconds)
    auto_run=True,               # Start automatically (no main() needed)
    auto_run_interval=10,        # Auto-run loop interval (env: MCP_MESH_AUTO_RUN_INTERVAL)
)
class MyAgent:
    pass
```

## @mesh.tool

Registers a function as a mesh capability with dependency injection.

```python
@app.tool()
@mesh.tool(
    capability="greeting",              # Capability name for discovery
    description="Greets users",         # Human-readable description
    version="1.0.0",                    # Capability version
    tags=["greeting", "utility"],       # Tags for filtering
    dependencies=["date_service"],      # Required capabilities
)
async def greet(name: str, date_svc: mesh.McpMeshTool = None) -> str:
    if date_svc:
        today = await date_svc()  # Must use await for proxy calls!
        return f"Hello {name}! Today is {today}"
    return f"Hello {name}!"  # Graceful degradation
```

**Note**: Functions with dependencies must be `async def` and proxy calls require `await`.

### Dependency Injection Types

| Type                | Use Case                               |
| ------------------- | -------------------------------------- |
| `mesh.McpMeshTool`  | Tool calls via proxy                   |
| `mesh.MeshLlmAgent` | LLM agent injection (with `@mesh.llm`) |

### Schema-aware capabilities (issue #547)

The mesh can match producers and consumers by their canonical response schemas, not just by capability name. This is opt-in per dependency.

**Producer side** — the output schema is inferred from the function's return type annotation. Use a Pydantic model for highest fidelity:

```python
from pydantic import BaseModel

class Employee(BaseModel):
    id: int
    name: str
    department: str

@mesh.tool(capability="lookup_employee")
def lookup_employee(id: int) -> Employee:
    ...
```

**Consumer side** — add `expected_type` (and optionally `match_mode`) to the dependency dict:

```python
@mesh.tool(
    capability="hr_report",
    dependencies=[
        {
            "capability": "lookup_employee",
            "expected_type": Employee,
            "match_mode": "subset",  # or "strict"; defaults to "subset" if expected_type is set
        },
    ],
)
async def hr_report(employee_lookup: mesh.McpMeshTool = None): ...
```

Producer tools can opt out of strict schema verdicts via `output_schema_strict=False`. See `meshctl man schema-matching` for verdict tiers and policy. See `meshctl man dependency-injection` for the full filter pipeline.

## @mesh.service

Aggregates capabilities behind a typed view, or — with a prefix — publishes a class's methods as tools (RFC #1280).

**Consumer view** — a class of `async` `@mesh.selector` stubs, injected as a `@mesh.tool` parameter:

```python
@mesh.service                       # or @mesh.service(min_available=2)
class MediaService:
    @mesh.selector("media.caption", required=True)
    async def caption(self, args: dict) -> dict: ...
    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...

@mesh.tool(capability="process_media")
async def process_media(req: dict, media: MediaService = None):
    return await media.caption({"text": req["text"]})
```

**Producer** — a prefixed class whose real methods publish as `prefix.<method>`:

```python
@mesh.service("media")              # publishes media.caption, media.thumbnail
class MediaTools:
    async def caption(self, args: dict) -> dict: ...
    async def thumbnail(self, args: dict) -> dict: ...
```

Each view method is an ordinary dependency edge and each producer method an ordinary tool — both show as `N` entries in `meshctl list`. `required` view edges get the pre-invoke `dependency_unavailable` refusal; `min_available` (consumer-only) adds a floor. For the full semantics see `meshctl man dependency-injection`.

## @mesh.llm

Enables LLM-powered tools with automatic tool discovery.

```python
@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},  # LLM provider selector
    max_iterations=5,                    # Max agentic loop iterations
    system_prompt="file://prompts/agent.jinja2",  # Jinja2 template
    response_model=AssistResponse,       # Pydantic model the LLM must emit (optional)
    context_param="ctx",                 # Parameter name for context
    filter=[{"tags": ["tools"]}],        # Tool filter for discovery
    filter_mode="all",                   # "all", "best_match", or "*"
)
@mesh.tool(
    capability="smart_assistant",
    description="LLM-powered assistant",
)
def assist(ctx: AssistContext, llm: mesh.MeshLlmAgent = None) -> AssistResponse:
    return llm("Help the user with their request")
```

**Note**: Response format is determined by return type: `-> str` for text, `-> PydanticModel` for JSON. Use `response_model` to make the LLM emit a focused subset (validated against that model) while the return annotation still drives the tool's `outputSchema`; when omitted, the LLM schema falls back to the return annotation.

### Filter Modes

| Mode         | Description                              |
| ------------ | ---------------------------------------- |
| `all`        | Include all tools matching any filter    |
| `best_match` | One tool per capability (best tag match) |
| `*`          | All available tools (wildcard)           |

## @mesh.llm_provider

Creates a zero-code LLM provider wrapping LiteLLM.

```python
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",  # LiteLLM model string
    capability="llm",                      # Capability name
    tags=["llm", "claude", "provider"],    # Discovery tags
    version="1.0.0",                       # Provider version
)
def claude_provider():
    pass  # No implementation needed
```

## @mesh.route

Enables mesh dependency injection in FastAPI route handlers. Use this when building REST APIs that consume mesh capabilities.

```python
from fastapi import APIRouter, Request
import mesh
from mesh.types import McpMeshTool

router = APIRouter()

@router.post("/chat")
@mesh.route(dependencies=["avatar_chat"])
async def chat_endpoint(
    request: Request,
    message: str,
    avatar_agent: McpMeshTool = None,  # Injected by mesh
):
    result = await avatar_agent(message=message, user_email="user@example.com")
    return {"response": result.get("message")}
```

**Note**: `@mesh.route` is for FastAPI backends that _consume_ mesh capabilities. Use `@mesh.tool` for MCP agents that _provide_ capabilities.

**Note**: Both `@mesh.tool` and `@mesh.route` inject dependencies POSITIONALLY into `McpMeshTool`-typed parameters — pairing the order of `McpMeshTool` parameters in the function signature against the order of `dependencies=[...]` (the runtime takes `mesh_positions[: len(dependencies)]`). Parameter names like `date_service` in examples are reader-friendly only — they don't match against the dependency capability name. The same rule applies in TypeScript (`addTool({ dependencies: [...] })`, injected positionally) and Java (`@MeshTool(dependencies = @Selector(...))`, parameter order). A `MeshJob` slot (one per tool) is detected by parameter type but counts as an eligible position in this same positional pairing — it pairs with its own `dependencies=[...]` entry, and that dependency is bound as the job's submitter — see `meshctl man jobs`.

See `meshctl man api` for complete FastAPI integration guide.

## @mesh.a2a (Producer — Python only)

Expose mesh tools as A2A v1.0 skills via the `mesh.a2a.mount(...)` style. The user owns the FastAPI app AND the uvicorn lifecycle — no `@mesh.agent` decorator. The mount auto-generates the `/.well-known/agent.json` card and the JSON-RPC entry route.

```python
import mesh
from fastapi import FastAPI
from mesh.types import McpMeshTool

app = FastAPI(title="Date A2A Agent")


@mesh.a2a.mount(
    app,
    path="/agents/date",
    dependencies=["date_service"],
    skill_id="get-date",
    skill_name="Get Date",
)
async def date_a2a(payload: dict, date_service: McpMeshTool = None):
    if date_service is None:
        return {"error": "date_service not yet resolved"}
    return {"date": await date_service()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
```

The mount attaches both:
- `GET  /agents/date/.well-known/agent.json` — auto-generated card
- `POST /agents/date` — JSON-RPC entry for `tasks/*` methods

**Note**: A single Python process may NOT host both `@mesh.tool` capabilities and a `mesh.a2a.mount(...)` surface — the framework rejects mixed-mode at boot. Split into two agents (one provider, one A2A surface that depends on it).

Java and TypeScript producer support is future work.

See `meshctl man a2a` for the full producer + bearer auth + skill-card guide.

## @mesh.a2a_consumer

Bridge an external A2A v1.0 skill into the mesh as an ordinary mesh capability. Downstream callers consume it with no awareness of A2A.

```python
import json
import mesh
from fastmcp import FastMCP

app = FastMCP("Date Consumer Bridge")


@app.tool()
@mesh.a2a_consumer(
    capability="current-date",
    a2a_url="http://localhost:9090/agents/date",
    a2a_skill_id="get-date",
)
async def current_date(_a2a: mesh.A2AClient = None) -> dict:
    response = await _a2a.send(
        message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
    )
    return json.loads(response.artifact_text)


@mesh.agent(name="date-consumer", http_port=9201)
class DateConsumer:
    pass
```

The injected `_a2a: mesh.A2AClient` parameter exposes `.send(...)`. Bearer auth (`A2A_BEARER_TOKEN` env var by default) is wired automatically when the upstream card declares it.

See `meshctl man a2a` for cross-language consumer parity (Python/TypeScript/Java) and offline-card scaffolding via `meshctl scaffold a2a-consumer`.

## Environment Variable Overrides

All decorator parameters can be overridden via environment variables:

```bash
export MCP_MESH_AGENT_NAME=custom-name
export MCP_MESH_HTTP_PORT=9090
export MCP_MESH_NAMESPACE=production
export MCP_MESH_AUTO_RUN=false
```

## See Also

- `meshctl man dependency-injection` - DI details
- `meshctl man llm` - LLM integration guide
- `meshctl man tags` - Tag matching system
- `meshctl man capabilities` - Capabilities system
- `meshctl man api` - FastAPI integration with @mesh.route
