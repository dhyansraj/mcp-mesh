# API Integration (Python/FastAPI)

> Add mesh capabilities to your FastAPI routes with @mesh.route

## Why Use This

- You have a FastAPI app (or are building one) and want your routes to call mesh agent capabilities (LLMs, data services, etc.)
- `@mesh.route` gives you automatic dependency injection -- declare what you need, mesh provides it
- Your API registers as a consumer (Type: API) -- no MCP protocol needed on your side
- Dependencies auto-rewire when agents come and go

## Install

```bash
pip install mcp-mesh
```

## Quick Start (Add to Existing App)

**Before** -- a normal FastAPI endpoint:

```python
@router.post("/chat")
async def chat(request: Request, message: str):
    # How do I call the LLM agent from here?
    return {"response": "..."}
```

**After** -- same endpoint with mesh dependency injection:

```python
import mesh
from mesh.types import McpMeshTool

@router.post("/chat")
@mesh.route(dependencies=["avatar_chat"])
async def chat(
    request: Request,
    message: str,
    avatar_agent: McpMeshTool = None,  # Injected by mesh
):
    result = await avatar_agent(
        message=message,
        user_email="user@example.com",
    )
    return {"response": result.get("message")}
```

The `McpMeshTool` proxy is injected at request time. Call it like a function -- mesh handles routing to the actual agent.

**Note**: Dependencies are resolved by **position**, not by parameter name. The first `McpMeshTool` parameter receives the first dependency, the second receives the second, and so on. Parameter names (like `avatar_agent` above) can be anything -- use whatever is readable.

## Starting Fresh

A minimal complete app:

```python
from fastapi import FastAPI, Request
import mesh
from mesh.types import McpMeshTool

app = FastAPI()

@app.post("/greet")
@mesh.route(dependencies=["greeting"])
async def greet(
    request: Request,
    name: str,
    greeting: McpMeshTool = None,
):
    result = await greeting(name=name)
    return {"message": result.get("text", "")}
```

## Dependency Declaration

### Simple (by capability name)

```python
@mesh.route(dependencies=["user_service", "notification_service"])
async def handler(
    user_svc: McpMeshTool = None,
    notif_svc: McpMeshTool = None,
):
    ...
```

### With Tag Filtering

```python
@mesh.route(dependencies=[
    {"capability": "llm", "tags": ["+claude"]},
    {"capability": "storage", "tags": ["-deprecated"]},
])
async def handler(
    llm_agent: McpMeshTool = None,
    storage_agent: McpMeshTool = None,
):
    ...
```

## Running

```bash
# 1. Start the mesh registry
meshctl start --registry-only

# 2. Start your FastAPI app (not through meshctl)
export MCP_MESH_REGISTRY_URL=http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8080
```

**Note**: FastAPI backends are NOT started with `meshctl start` -- run them your normal way. The registry must be running so `@mesh.route` can resolve dependencies.

## How It Works

1. App connects to the mesh registry on startup
2. `@mesh.route` resolves dependencies at request time
3. `McpMeshTool` proxies are injected into your handler parameters
4. If an agent goes down, mesh auto-rewires to an available replacement

## Graceful Degradation

If a dependency might not be available, check for `None`:

```python
from fastapi import HTTPException

@mesh.route(dependencies=["greeting"])
async def greet(request: Request, greeting: McpMeshTool = None):
    if greeting is None:
        raise HTTPException(status_code=503, detail="Service unavailable")
    result = await greeting(name="World")
    return {"message": result.get("text")}
```

## See Also

- `meshctl man decorators` - All mesh decorators
- `meshctl man dependency-injection` - How DI works
- `meshctl man proxies` - Proxy configuration
