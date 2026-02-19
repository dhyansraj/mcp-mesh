# HTTP Header Propagation (Python)

> Forward custom HTTP headers across agent-to-agent calls

## Overview

MCP Mesh can propagate user-defined HTTP headers through the call chain.
When Agent A calls Agent B, configured headers from the incoming request
are automatically forwarded. This enables auth token forwarding, correlation
IDs, tenant context, and any custom metadata — without coupling agents to
a specific auth or observability framework.

## Configuration

Set the allowlist via environment variable on every agent in the chain:

```bash
export MCP_MESH_PROPAGATE_HEADERS=authorization,x-request-id,x-tenant-id
```

- Comma-separated header name **prefixes**
- Case-insensitive (normalized to lowercase internally)
- Prefix matching: `x-audit` matches `x-audit-id`, `x-audit-source`, etc.
- Whitespace around names is trimmed
- Parsed once at startup — restart to change
- Must be set on **every agent** in the chain that should participate

With no value set, no custom headers are propagated. Trace headers
(`X-Trace-ID`, `X-Parent-Span`) are always propagated independently.

## How It Works

```
Client                Agent A              Agent B              Agent C
  |                     |                     |                    |
  | Authorization: Bxxx |                     |                    |
  |-------------------->|                     |                    |
  |                     | captures "authorization" from allowlist  |
  |                     |                     |                    |
  |                     | Authorization: Bxxx |                    |
  |                     |-------------------->|                    |
  |                     |                     | Authorization: Bxxx|
  |                     |                     |------------------>|
```

1. Incoming request arrives with headers
2. Agent captures headers matching the allowlist into request-scoped context
3. When the agent calls another agent, captured headers are injected
   into the outgoing HTTP request automatically
4. The downstream agent repeats the process — headers flow end-to-end

Python uses `contextvars.ContextVar` for async-safe, request-scoped storage
so concurrent requests are fully isolated.

## Reading Headers in Tool Handlers

Headers are captured and forwarded automatically. You can also read them
explicitly in your tool code:

```python
from _mcp_mesh.tracing.context import TraceContext

@mesh.tool(capability="my_tool")
async def my_tool(name: str) -> dict:
    headers = TraceContext.get_propagated_headers()
    tenant = headers.get("x-tenant-id", "unknown")
    return {"user": name, "tenant": tenant}
```

## Per-Call Header Injection

Agents can inject headers when calling other tools. This enables use cases
like audit correlation where an orchestrating agent stamps metadata on
downstream calls.

```python
from _mcp_mesh.tracing.context import TraceContext
from mesh.types import McpMeshTool

@mesh.tool(capability="relay", dependencies=["echo_headers"])
async def relay(echo_svc: McpMeshTool = None) -> str:
    # Check what's already propagated
    propagated = TraceContext.get_propagated_headers()

    if "x-audit-id" not in propagated:
        # Inject a new header on this specific call
        result = await echo_svc(headers={"x-audit-id": "audit-12345"})
    else:
        result = await echo_svc()

    return str(result)
```

**API:** `await tool(headers={"header-name": "value"})`

The `headers` keyword argument is available on `__call__`:

```python
# Positional args style
result = await tool(headers={"x-audit-id": "abc"})

# With tool arguments
result = await tool(query="test", headers={"x-audit-id": "abc"})
```

### Merge Semantics

Per-call headers merge on top of session-level propagated headers:

```
Session propagated headers (from incoming request)
  + Per-call headers (from headers= argument)
  = Merged headers sent downstream
```

Per-call headers **win** on conflict. All headers (session and per-call)
are filtered by the `MCP_MESH_PROPAGATE_HEADERS` prefix allowlist — agents
cannot inject arbitrary headers unless the operator explicitly allows them.

## Example: Auth Token Forwarding

Forward bearer tokens through the mesh so each agent can enforce its own
authorization:

```bash
# Set on all agents in the chain:
export MCP_MESH_PROPAGATE_HEADERS=authorization

# API gateway or client sends a token:
curl -H "Authorization: Bearer tok_abc123" \
  http://localhost:8080/api/process
```

The `Authorization` header flows automatically through every agent call.
Each agent can enforce auth using FastAPI dependencies:

```python
from fastapi import Depends, HTTPException
from _mcp_mesh.tracing.context import TraceContext

def require_auth():
    headers = TraceContext.get_propagated_headers()
    token = headers.get("authorization", "")
    if not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    return token

@mesh.tool(capability="secure_tool")
async def secure_tool(data: str, auth: str = Depends(require_auth)) -> dict:
    return {"result": "ok", "authenticated": True}
```

## Cross-Language Behavior

All three SDKs inject headers via two mechanisms simultaneously:

1. **HTTP headers** on outgoing requests — works for Python and Java receivers
2. **`_mesh_headers` argument** tunneled in JSON-RPC args — works for
   TypeScript receivers (where FastMCP doesn't expose HTTP headers)

The `_mesh_headers` argument is stripped before user code sees it. This
dual mechanism is transparent — headers flow correctly regardless of which
SDK combination is in the chain.

## Environment Variables

| Variable                     | Description                                       | Default  |
| ---------------------------- | ------------------------------------------------- | -------- |
| `MCP_MESH_PROPAGATE_HEADERS` | Comma-separated header name prefixes to forward   | _(none)_ |

## See Also

- `meshctl man observability` — Distributed tracing with X-Trace-ID
- `meshctl man environment` — All configuration variables
- `meshctl man proxies` — Inter-agent communication mechanics
- `meshctl man api` — Adding mesh to existing web frameworks
