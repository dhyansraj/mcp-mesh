# Dependency Injection

> Automatic wiring of capabilities between agents

**Note:** This page shows Python examples. See `meshctl man dependency-injection --typescript` for TypeScript or `meshctl man dependency-injection --java` for Java/Spring Boot examples.

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
async def greet(name: str, date_service: mesh.McpMeshTool = None) -> str:
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
    data_svc: mesh.McpMeshTool = None,
    formatter: mesh.McpMeshTool = None,
) -> str:
    data = await data_svc(query="sales")
    return await formatter(data=data)
```

### OR Alternatives (Tag-Level)

Use nested arrays in tags to specify fallback providers:

```python
@app.tool()
@mesh.tool(
    capability="calculator",
    dependencies=[
        # Prefer python provider, fallback to typescript
        {"capability": "math", "tags": ["addition", ["python", "typescript"]]},
    ],
)
async def calculate(a: int, b: int, math: mesh.McpMeshTool = None):
    result = await math(a=a, b=b)
    return result
```

Resolution order:

1. Try to find provider with `addition` AND `python` tags
2. If not found, try provider with `addition` AND `typescript` tags
3. If neither found, dependency is unresolved (injected as `None`)

This is useful when you have multiple implementations of the same capability
and want to prefer one but fallback to another if unavailable.

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

Dependencies may be unavailable. Always handle `None`:

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
- `meshctl man health` - Health monitoring
- `meshctl man proxies` - Proxy details
