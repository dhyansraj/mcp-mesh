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

Configure via `dependency_kwargs` in the decorator:

```python
@mesh.tool(
    dependencies=["slow_service"],
    dependency_kwargs={
        "slow_service": {
            "timeout": 60,              # Request timeout (seconds)
            "retry_count": 3,           # Retry attempts on failure
            "custom_headers": {         # Custom HTTP headers
                "X-Request-ID": "...",
            },
            "streaming": True,          # Enable streaming responses
            "session_required": True,   # Require session affinity
            "auth_required": True,      # Require authentication
            "stateful": True,           # Mark as stateful
            "auto_session_management": True,  # Auto session lifecycle
        }
    },
)
async def my_tool(slow_service: mesh.McpMeshTool = None):
    result = await slow_service(data="payload")
    ...
```

## Configuration Options

| Option                    | Type | Default | Description                 |
| ------------------------- | ---- | ------- | --------------------------- |
| `timeout`                 | int  | 30      | Request timeout in seconds  |
| `retry_count`             | int  | 0       | Number of retry attempts    |
| `streaming`               | bool | False   | Enable streaming responses  |
| `session_required`        | bool | False   | Require session affinity    |
| `auth_required`           | bool | False   | Require authentication      |
| `stateful`                | bool | False   | Mark capability as stateful |
| `auto_session_management` | bool | False   | Auto manage sessions        |
| `custom_headers`          | dict | {}      | Additional HTTP headers     |

## Streaming

Enable streaming for real-time data:

```python
@mesh.tool(
    dependencies=["stream_service"],
    dependency_kwargs={
        "stream_service": {"streaming": True}
    },
)
async def process_stream(stream_svc: mesh.McpMeshTool = None):
    async for chunk in stream_svc.stream("data"):
        process(chunk)
```

## Session Affinity

For stateful services, ensure requests go to the same instance:

```python
@mesh.tool(
    dependencies=["stateful_service"],
    dependency_kwargs={
        "stateful_service": {
            "session_required": True,
            "auto_session_management": True,
        }
    },
)
async def stateful_operation(svc: mesh.McpMeshTool = None):
    # All calls routed to same instance
    await svc.initialize()
    result = await svc.process()
    await svc.cleanup()
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
- Continues working if registry is down

## See Also

- `meshctl man dependency-injection` - DI overview
- `meshctl man health` - Auto-rewiring on failure
- `meshctl man testing` - Testing agent communication
