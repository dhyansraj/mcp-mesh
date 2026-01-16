# FastAPI Integration

> Use mesh dependency injection in FastAPI backends with @mesh.route

**Note:** This page covers Python/FastAPI integration. For TypeScript/Express, use `mesh.route()` middleware. See `meshctl man express` for Express examples.

## Overview

MCP Mesh provides the `@mesh.route` decorator for FastAPI applications that need to consume mesh capabilities without being MCP agents themselves. This enables traditional REST APIs to leverage the mesh service layer.

**Important**: This is for integrating MCP Mesh into your EXISTING FastAPI app. There is no `meshctl scaffold` command for FastAPI. To create a new MCP agent, use `meshctl scaffold` instead.

> **TypeScript/Express**: A similar `mesh.route()` middleware exists for Express applications. See `meshctl man express` for details.

## Installation

```bash
pip install mcp-mesh
```

## Two Architectures

| Pattern         | Decorator                    | Use Case                              |
| --------------- | ---------------------------- | ------------------------------------- |
| MCP Agent       | `@mesh.tool` + `@mesh.agent` | Service that _provides_ capabilities  |
| FastAPI Backend | `@mesh.route`                | REST API that _consumes_ capabilities |

```
[Frontend] → [FastAPI Backend] → [MCP Mesh] → [Agents]
                   ↑
            @mesh.route
```

## @mesh.route Decorator

```python
from fastapi import APIRouter, Request
import mesh
from mesh.types import McpMeshAgent

router = APIRouter()

@router.post("/chat")
@mesh.route(dependencies=["avatar_chat"])
async def chat(
    request: Request,
    message: str,
    avatar_agent: McpMeshAgent = None,  # Injected by mesh
):
    result = await avatar_agent(
        message=message,
        user_email="user@example.com",
    )
    return {"response": result.get("message")}
```

## Dependency Declaration

### Simple (by capability name)

```python
@mesh.route(dependencies=["user_service", "notification_service"])
async def handler(
    user_svc: McpMeshAgent = None,
    notif_svc: McpMeshAgent = None,
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
    llm_agent: McpMeshAgent = None,
    storage_agent: McpMeshAgent = None,
):
    ...
```

## Complete Example

```python
from fastapi import FastAPI, APIRouter, Request, HTTPException
import mesh
from mesh.types import McpMeshAgent
from pydantic import BaseModel

app = FastAPI(title="My Backend")
router = APIRouter(prefix="/api", tags=["api"])

class ChatRequest(BaseModel):
    message: str
    avatar_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    avatar_id: str

@router.post("/chat", response_model=ChatResponse)
@mesh.route(dependencies=["avatar_chat"])
async def chat_endpoint(
    request: Request,
    chat_req: ChatRequest,
    avatar_agent: McpMeshAgent = None,
):
    """Chat endpoint that delegates to mesh avatar agent."""
    if avatar_agent is None:
        raise HTTPException(503, "Avatar service unavailable")

    result = await avatar_agent(
        message=chat_req.message,
        avatar_id=chat_req.avatar_id,
        user_email="user@example.com",
    )

    return ChatResponse(
        response=result.get("message", ""),
        avatar_id=chat_req.avatar_id,
    )

@router.get("/history")
@mesh.route(dependencies=["conversation_history_get"])
async def get_history(
    request: Request,
    avatar_id: str = "default",
    limit: int = 50,
    history_agent: McpMeshAgent = None,
):
    """Get conversation history from mesh agent."""
    result = await history_agent(
        avatar_id=avatar_id,
        limit=limit,
    )
    return {"messages": result.get("messages", [])}

app.include_router(router)
```

## Running Your FastAPI App

Run your existing FastAPI application as you normally would:

```bash
export MCP_MESH_REGISTRY_URL=http://localhost:8000
uvicorn main:app --host 0.0.0.0 --port 8080
```

**Note**: Unlike MCP agents, FastAPI backends are NOT started with `meshctl start`.

The backend will:

1. Connect to the mesh registry on startup
2. Resolve dependencies declared in `@mesh.route`
3. Inject `McpMeshAgent` proxies into route handlers
4. Re-resolve on topology changes (auto-rewiring)

## Key Differences from @mesh.tool

| Aspect                | @mesh.tool   | @mesh.route                     |
| --------------------- | ------------ | ------------------------------- |
| Registers with mesh   | Yes          | No                              |
| Provides capabilities | Yes          | No                              |
| Consumes capabilities | Yes          | Yes                             |
| Has heartbeat         | Yes          | Yes (for dependency resolution) |
| Protocol              | MCP JSON-RPC | REST/HTTP                       |
| Use case              | Microservice | API Gateway/Backend             |

## When to Use @mesh.route

- Building a REST API that fronts mesh services
- API gateway pattern
- Backend-for-Frontend (BFF) services
- Adding REST endpoints to existing FastAPI apps
- When you need traditional HTTP semantics (REST, OpenAPI docs)

## When to Use @mesh.tool Instead

- Building reusable mesh capabilities
- Service-to-service communication
- LLM tool providers
- When other agents need to discover and call your service

## See Also

- `meshctl man express` - TypeScript/Express equivalent
- `meshctl man decorators` - All mesh decorators
- `meshctl man dependency-injection` - How DI works
- `meshctl man proxies` - Proxy configuration
