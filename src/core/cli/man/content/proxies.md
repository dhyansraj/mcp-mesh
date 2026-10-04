# Proxy System & Communication

> Inter-agent communication and proxy configuration

## Overview

MCP Mesh uses proxy objects to enable seamless communication between agents. When you call an injected dependency, you're actually calling a proxy that routes to the remote agent via MCP JSON-RPC.

## How Proxies Work

```
┌─────────────┐     Proxy Call      ┌─────────────┐
│   Agent A   │ ────────────────►   │   Agent B   │
│             │   MCP JSON-RPC      │             │
│  date_svc() │ ◄────────────────   │ get_time()  │
└─────────────┘     Response        └─────────────┘
```

1. Agent A calls `date_svc()` (the proxy)
2. Proxy serializes call to MCP JSON-RPC
3. HTTP POST to Agent B's `/mcp` endpoint
4. Agent B executes `get_time()` function
5. Response returned to Agent A

## Proxy Types

MCP Mesh uses a unified proxy system:

| Proxy                     | Use Case    | Features                                   |
| ------------------------- | ----------- | ------------------------------------------ |
| `SelfDependencyProxy`     | Same agent  | Direct function call (no network overhead) |
| `EnhancedUnifiedMCPProxy` | Cross-agent | All features (auto-configured from kwargs) |

## Using Proxies

**Important**: All proxy calls are async and require `await`.

### Simple Call

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper:
        result = await helper()  # Call default tool
```

### Named Tool Call

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper:
        result = await helper.call_tool("specific_tool", {"arg": "value"})
```

### With Arguments

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper:
        result = await helper(city="London", units="metric")
```

## Proxy Configuration

The Python runtime has no per-dependency proxy settings. Every outgoing call runs on one budget: `MCP_MESH_CALL_TIMEOUT` (default 300 seconds), replaced by an inbound `X-Mesh-Timeout` when the current call carries one. See `meshctl man environment`.

Per-dependency options (`dependencyKwargs`) are TypeScript-only; see `meshctl man proxies --typescript`. A `dependency_kwargs` argument to `@mesh.tool` is ignored with a warning.

## Streaming

`proxy.stream(...)` returns an async iterator of text chunks when the provider's tool returns `mesh.Stream[str]` (see `meshctl man streaming`):

```python
@mesh.tool(dependencies=["stream_service"])
async def process_stream(stream_svc: mesh.McpMeshTool = None):
    async for chunk in stream_svc.stream(prompt="data"):
        process(chunk)
```

## Session Affinity

A Python provider pins every call that carries a `session_id` argument to the replica that served that session's first call, and forwards later calls for the session there. Assignments live in Redis (`REDIS_URL`) so every replica sees them, and expire after `MCP_MESH_SESSION_TTL` seconds (default 3600). Without Redis each replica only knows its own assignments.

```python
@mesh.tool(dependencies=["stateful_service"])
async def stateful_operation(session_id: str, svc: mesh.McpMeshTool = None):
    # Every call with this session_id lands on the same provider replica
    await svc(session_id=session_id, action="start")
    return await svc(session_id=session_id, action="process")
```

## Error Handling

Proxies handle errors gracefully:

```python
async def my_tool(helper: mesh.McpMeshTool = None):
    if helper is None:
        return "Service unavailable"

    try:
        return await helper()
    except TimeoutError:
        return "Service timed out"
    except ConnectionError:
        return "Cannot reach service"
```

## Direct Communication

Agents communicate directly - no proxy server:

- Registry provides endpoint information
- Agents call each other via HTTP
- Minimal latency (no intermediary)
- Already-resolved dependency proxies cache their endpoint and continue functioning during registry outages — but topology changes (new agents joining, dependencies re-resolving, deregistrations) and new client→agent proxy calls all require the registry to be back up.

## See Also

- `meshctl man dependency-injection` - DI overview
- `meshctl man health` - Auto-rewiring on failure
- `meshctl man testing` - Testing agent communication
