# HTTP Header Propagation

> Forward custom HTTP headers across agent-to-agent calls

## Overview

MCP Mesh can propagate user-defined HTTP headers through the call chain.
When Agent A calls Agent B, configured headers from the incoming request
are automatically forwarded. This enables auth token forwarding, correlation
IDs, tenant context, and any custom metadata — without coupling agents to
a specific auth or observability framework.

This is the foundation for authentication in MCP Mesh: you bring your own
auth framework, and the mesh ensures tokens flow through the call chain.

## Configuration

Set the allowlist via environment variable on every agent in the chain:

```bash
export MCP_MESH_PROPAGATE_HEADERS=authorization,x-request-id,x-tenant-id
```

- Comma-separated header names
- Case-insensitive (normalized to lowercase internally)
- Whitespace around names is trimmed
- Parsed once at startup — restart to change
- Must be set on **every agent** in the chain that should participate

With no value set, no custom headers are propagated. Trace headers
(`X-Trace-ID`, `X-Parent-Span`) are always propagated independently.

## How It Works

```
Client                Agent A              Agent B              Agent C
  │                     │                     │                    │
  │ Authorization: Bxxx │                     │                    │
  │────────────────────>│                     │                    │
  │                     │ captures "authorization" from allowlist  │
  │                     │                     │                    │
  │                     │ Authorization: Bxxx │                    │
  │                     │────────────────────>│                    │
  │                     │                     │ Authorization: Bxxx│
  │                     │                     │───────────────────>│
```

1. Incoming request arrives with headers
2. Agent captures headers matching the allowlist into request-scoped context
3. When the agent calls another agent, captured headers are injected
   into the outgoing HTTP request automatically
4. The downstream agent repeats the process — headers flow end-to-end

Each SDK uses async-safe, request-scoped storage so concurrent requests
are fully isolated:

| SDK        | Storage mechanism        |
| ---------- | ------------------------ |
| Python     | `contextvars.ContextVar` |
| TypeScript | `AsyncLocalStorage`      |
| Java       | `InheritableThreadLocal` |

## Reading Headers in Tool Handlers

Headers are captured and forwarded automatically. You can also read them
explicitly in your tool code:

**Python:**

```python
from _mcp_mesh.tracing.context import TraceContext

@mesh.tool(capability="my_tool")
async def my_tool(name: str) -> dict:
    headers = TraceContext.get_propagated_headers()
    tenant = headers.get("x-tenant-id", "unknown")
    return {"user": name, "tenant": tenant}
```

**TypeScript:**

```typescript
import { getCurrentPropagatedHeaders } from "@mcpmesh/sdk";

mesh.tool("my_tool", async ({ name }) => {
  const headers = getCurrentPropagatedHeaders();
  const tenant = headers["x-tenant-id"] ?? "unknown";
  return { user: name, tenant };
});
```

**Java:**

```java
import io.mcpmesh.spring.tracing.TraceContext;

@MeshTool(capability = "my_tool")
public Map<String, Object> myTool(@Param("name") String name) {
    Map<String, String> headers = TraceContext.getPropagatedHeaders();
    String tenant = headers.getOrDefault("x-tenant-id", "unknown");
    return Map.of("user", name, "tenant", tenant);
}
```

## Example: Auth Token Forwarding

The most common use case — forward bearer tokens through the mesh so each
agent can enforce its own authorization:

```bash
# Set on all agents in the chain:
export MCP_MESH_PROPAGATE_HEADERS=authorization

# API gateway or client sends a token:
curl -H "Authorization: Bearer tok_abc123" \
  http://localhost:8080/api/process
```

The `Authorization` header flows automatically through every agent call.
Each agent can then enforce auth using its framework's native tools:

**Python (FastAPI dependency):**

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

**Java (Spring Security annotation):**

```java
import org.springframework.security.access.prepost.PreAuthorize;

@MeshTool(capability = "secure_tool")
@PreAuthorize("hasRole('ADMIN')")
public Map<String, Object> secureTool(@Param("data") String data) {
    return Map.of("result", "ok", "authenticated", true);
}
```

Spring Security reads the `Authorization` header from the HTTP request
automatically — no extra wiring needed when headers are propagated.

## Cross-Language Behavior

All three SDKs inject headers via two mechanisms simultaneously:

1. **HTTP headers** on outgoing requests — works for Python and Java receivers
2. **`_mesh_headers` argument** tunneled in JSON-RPC args — works for
   TypeScript receivers (where FastMCP doesn't expose HTTP headers)

The `_mesh_headers` argument is stripped before user code sees it. This
dual mechanism is transparent — headers flow correctly regardless of which
SDK combination is in the chain.

**TypeScript limitation:** TypeScript agents cannot capture headers from
direct external HTTP callers (curl, API gateways) due to FastMCP not
exposing HTTP headers. Headers are only received from other mesh agents
that tunnel them via `_mesh_headers`. Agent-to-agent calls work correctly
across all SDK combinations.

## Environment Variables

| Variable                     | Description                             | Default  |
| ---------------------------- | --------------------------------------- | -------- |
| `MCP_MESH_PROPAGATE_HEADERS` | Comma-separated header names to forward | _(none)_ |

## See Also

- `meshctl man observability` — Distributed tracing with X-Trace-ID
- `meshctl man environment` — All configuration variables
- `meshctl man proxies` — Inter-agent communication mechanics
- `meshctl man api` — Adding mesh to existing web frameworks
