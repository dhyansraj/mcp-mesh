# Hello World Example

> The simplest way to see MCP Mesh in action

## Overview

This example demonstrates the **dual decorator pattern** - combining FastMCP's familiar development experience with MCP Mesh's powerful orchestration. No main methods, no manual server setup - just add decorators and go!

## Quick Start

```bash
# 1. Start system agent (provides date service) - registry starts automatically
meshctl start examples/simple/system_agent.py

# 2. Start hello world agent (uses date service)
meshctl start examples/simple/hello_world.py

# 3. Test it
curl -s -X POST http://localhost:9090/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"hello_mesh_simple","arguments":{}}}' \
  | grep "^data:" | sed 's/^data: //' | jq '.result.content[0].text'
```

**Expected response:**

```
"Hello from MCP Mesh! Today is December 10, 2025 at 03:30 PM"
```

## Understanding the Code

### Hello World Agent

```python
from typing import Any
import mesh
from fastmcp import FastMCP

app = FastMCP("Hello World Service")

@app.tool()  # FastMCP: Exposes as MCP tool
@mesh.tool(
    capability="greeting",
    dependencies=["date_service"]  # Mesh: Declares dependency
)
async def hello_mesh_simple(date_service: Any = None) -> str:
    """Greeting with dependency injection."""
    if date_service is None:
        return "Hello from MCP Mesh! (Date service not available)"

    current_date = await date_service()
    return f"Hello from MCP Mesh! Today is {current_date}"

@mesh.agent(name="hello-world", http_port=9090, auto_run=True)
class HelloWorldAgent:
    pass
```

### System Agent (Provider)

```python
import mesh
from fastmcp import FastMCP
from datetime import datetime

app = FastMCP("System Agent Service")

@app.tool()
@mesh.tool(capability="date_service")  # Other agents can depend on this
def get_current_time() -> str:
    """Get current system date and time."""
    return datetime.now().strftime("%B %d, %Y at %I:%M %p")

@mesh.agent(name="system-agent", http_port=8080, auto_run=True)
class SystemAgent:
    pass
```

## Key Concepts

### Dual Decorators

| Decorator      | Purpose                                            |
| -------------- | -------------------------------------------------- |
| `@app.tool()`  | FastMCP - Exposes function as MCP tool             |
| `@mesh.tool()` | MCP Mesh - Adds discovery and dependency injection |

### Capability vs Function Name

- **Function name** (`hello_mesh_simple`) - Used in MCP `tools/call`
- **Capability** (`greeting`) - What others depend on

### Dependency Injection

```python
@mesh.tool(dependencies=["date_service"])
async def my_tool(date_service: Any = None):
    result = await date_service()  # Calls system agent automatically
```

MCP Mesh automatically:

1. Finds an agent providing `date_service` capability
2. Injects a proxy function as `date_service` parameter
3. Routes calls to the remote agent

## Testing Your Setup

### List Available Tools

```bash
curl -s -X POST http://localhost:9090/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | grep "^data:" | sed 's/^data: //' | jq '.result.tools[].name'
```

### Check Agent Status

```bash
meshctl status
```

### View Registry

```bash
curl -s http://localhost:8000/agents | jq '.agents[] | {name, capabilities}'
```

## Troubleshooting

### Port Already in Use

```bash
lsof -i :9090  # Check hello world port
lsof -i :8080  # Check system agent port
```

### Dependency Not Injected

The dependency appears as `None` if:

- System agent isn't running
- Capability name doesn't match
- Registry isn't reachable

```bash
# Verify system agent is registered
curl -s http://localhost:8000/agents | jq '.agents[] | select(.name=="system-agent")'
```

## Next Steps

- [Dependency Injection](./04-dependency-injection.md) - Deep dive into smart resolution
- [Creating Your First Agent](./05-first-agent.md) - Build a complete agent
- [LLM Integration](./06-llm-integration.md) - Add AI capabilities
