<div class="runtime-crossref">
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../java/annotations/">Java Decorators</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../typescript/mesh-functions/">TypeScript Decorators</a></span>
</div>

# MCP Mesh Decorators

> Core decorators for building distributed agent systems

**Note:** This page shows Python examples. See `meshctl man decorators --typescript` for TypeScript or `meshctl man decorators --java` for Java/Spring Boot examples.

## Overview

MCP Mesh provides decorators (Python), annotations (Java), and function wrappers (TypeScript) that transform regular functions into mesh-aware distributed services. These APIs handle registration, dependency injection, and communication automatically.

| Decorator            | Purpose                         |
| -------------------- | ------------------------------- |
| `@mesh.agent`        | Configure agent server settings |
| `@mesh.tool`         | Register capability with DI     |
| `@mesh.llm`          | Enable LLM-powered tools        |
| `@mesh.llm_provider` | Create LLM provider (zero-code) |
| `@mesh.route`        | FastAPI route with mesh DI      |

## Decorator Order (Critical!)

When using multiple decorators, order matters:

```python
@app.tool()           # 1. FastMCP protocol handler (outermost)
@mesh.llm(...)        # 2. LLM integration (if using)
@mesh.tool(...)       # 3. Mesh capability registration (innermost)
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
    http_port=8080,              # HTTP server port (0 = auto-assign)
    http_host="localhost",       # Host announced to registry
    namespace="default",         # Namespace for isolation
    auto_run=True,               # Start automatically (no main() needed)
    auto_run_interval=30,        # Heartbeat interval in seconds
    health_check=health_fn,      # Optional health check function
    health_check_ttl=30,         # Health check cache TTL
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

## @mesh.llm

Enables LLM-powered tools with automatic tool discovery.

```python
@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},  # LLM provider selector
    max_iterations=5,                    # Max agentic loop iterations
    system_prompt="file://prompts/agent.jinja2",  # Jinja2 template
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

**Note**: Response format is determined by return type: `-> str` for text, `-> PydanticModel` for JSON.

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

See `meshctl man fastapi` for complete FastAPI integration guide.

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
- `meshctl man fastapi` - FastAPI integration with @mesh.route
