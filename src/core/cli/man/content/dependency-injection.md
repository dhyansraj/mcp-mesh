# Dependency Injection

> Automatic wiring of capabilities between agents

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
async def greet(name: str, date_service: mesh.McpMeshAgent = None) -> str:
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
    data_svc: mesh.McpMeshAgent = None,
    formatter: mesh.McpMeshAgent = None,
) -> str:
    data = await data_svc(query="sales")
    return await formatter(data=data)
```

## Injection Types

### mesh.McpMeshAgent

Callable proxy for tool invocations:

```python
async def my_tool(helper: mesh.McpMeshAgent = None):
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
async def my_tool(helper: mesh.McpMeshAgent = None):
    if helper is None:
        return "Service temporarily unavailable"
    return await helper()
```

Or use default values:

```python
async def get_time(date_service: mesh.McpMeshAgent = None):
    if date_service:
        return await date_service()
    return datetime.now().isoformat()  # Fallback
```

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
async def my_tool(slow_service: mesh.McpMeshAgent = None):
    result = await slow_service(data="large_payload")
    ...
```

## Proxy Types (Auto-Selected)

The mesh automatically selects the appropriate proxy:

| Proxy Type               | Use Case                 |
| ------------------------ | ------------------------ |
| `SelfDependencyProxy`    | Same agent (direct call) |
| `MCPClientProxy`         | Simple tool calls        |
| `EnhancedMCPClientProxy` | Timeout/retry config     |
| `EnhancedFullMCPProxy`   | Streaming/sessions       |

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
- `meshctl man health` - Health monitoring
- `meshctl man proxies` - Proxy details
