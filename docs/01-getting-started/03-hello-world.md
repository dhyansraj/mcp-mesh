# Running Hello World Example

> The simplest way to see MCP Mesh in action - dual decorators make it effortless!

## Overview

MCP Mesh 0.2.x introduces the **dual decorator pattern** that combines the familiar FastMCP development experience with powerful mesh orchestration. No main methods, no manual server setup - just add decorators and go!

## Quick Start (2 Commands!)

```bash
# 1. Start the system agent (provides date services) - registry starts automatically
meshctl start examples/simple/system_agent.py

# 2. Start the hello world agent (uses date services)
meshctl start examples/simple/hello_world.py

# 3. Test it with MCP JSON-RPC!
curl -s -X POST http://localhost:9090/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "hello_mesh_simple",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq '.result'
```

That's it! `meshctl` automatically starts the registry when needed, making it truly 2 commands for a distributed MCP system. 🎉

## What Just Happened?

The Hello World example demonstrates the **dual decorator pattern**:

1. **FastMCP decorators** (`@app.tool`) handle the MCP protocol
2. **Mesh decorators** (`@mesh.tool`) add dependency injection and orchestration
3. **Automatic discovery** - Mesh finds your FastMCP `app` instance and handles everything
4. **Zero boilerplate** - No main methods or manual server management needed

## Understanding the New Architecture

### The Dual Decorator Pattern

Here's the key part of `hello_world.py` using the new 0.2.x pattern:

```python
from typing import Any

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Hello World Service")

@app.tool()  # ← FastMCP decorator (familiar MCP development)
@mesh.tool(
    capability="greeting",
    dependencies=["date_service"]  # ← Mesh decorator (orchestration)
)
def hello_mesh_simple(date_service: Any = None) -> str:
    """MCP Mesh greeting with dependency injection."""
    if date_service is None:
        return "👋 Hello from MCP Mesh! (Date service not available yet)"

    current_date = date_service()  # Call injected function
    return f"👋 Hello from MCP Mesh! Today is {current_date}"

# Agent configuration - tells mesh how to run FastMCP
@mesh.agent(
    name="hello-world",
    http_port=9090,
    auto_run=True  # Mesh handles startup automatically
)
class HelloWorldAgent:
    pass

# No main method needed! Mesh discovers 'app' and handles everything.
```

### System Agent Architecture

And here's how `system_agent.py` provides the date service:

```python
import mesh
from fastmcp import FastMCP
from datetime import datetime

app = FastMCP("System Agent Service")

@app.tool()  # ← FastMCP handles MCP protocol
@mesh.tool(capability="date_service")  # ← What others can depend on
def get_current_time() -> str:
    """Get current system date and time."""
    return datetime.now().strftime("%B %d, %Y at %I:%M %p")

@mesh.agent(
    name="system-agent",
    http_port=8080,
    auto_run=True
)
class SystemAgent:
    pass
```

## Key Benefits of the New Pattern

### 1. **Familiar FastMCP Development**

- Keep using `@app.tool()`, `@app.prompt()`, `@app.resource()`
- Same function signatures and return types
- Full MCP protocol compatibility

### 2. **Enhanced with Mesh Orchestration**

- Add `@mesh.tool()` for dependency injection
- Automatic service discovery and registration
- Smart capability resolution with tags

### 3. **Zero Boilerplate**

- No main methods needed
- No manual server startup
- Mesh discovers your `app` instance automatically

### 4. **Automatic Service Discovery**

- No configuration files or service URLs needed
- Services find each other automatically through the registry

## Testing Your Setup

### List Available Tools

```bash
# Check what tools are available on hello world agent
curl -s -X POST http://localhost:9090/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'
```

### Test Different Functions

```bash
# Test simple greeting
curl -s -X POST http://localhost:9090/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "hello_mesh_simple", "arguments": {}}
  }' | jq '.result'

# Test smart tag-based greeting
curl -s -X POST http://localhost:9090/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "hello_mesh_typed", "arguments": {}}
  }' | jq '.result'
```

## What's Different from 0.1.x?

| Feature          | 0.1.x                            | 0.2.x                             |
| ---------------- | -------------------------------- | --------------------------------- |
| **Decorators**   | Only `@mesh.tool`, `@mesh.agent` | Dual: `@app.tool` + `@mesh.tool`  |
| **MCP Support**  | Limited mesh-only protocol       | Full FastMCP compatibility        |
| **Server Setup** | Manual configuration             | Automatic discovery               |
| **Types**        | Basic typing                     | Enhanced with `mesh.McpMeshAgent` |
| **Tags**         | Not supported                    | Smart tag-based resolution        |
| **Main Method**  | Required for some cases          | Never needed                      |

## Troubleshooting

### Service Not Starting

```bash
# Check if ports are available
lsof -i :9090  # Hello world agent port
lsof -i :8080  # System agent port
```

### Dependency Not Injected

```bash
# Check registry for available services
curl -s http://localhost:8000/agents | jq '.agents[] | {name: .name, capabilities: .capabilities}'
```

### Function Not Found

- Make sure you're using the correct **function name** (not capability name) in MCP calls
- Function name: `hello_mesh_simple`
- Capability name: `greeting`

## Next Steps

Now that you understand the dual decorator pattern, let's explore:

1. **[Dependency Injection](./04-dependency-injection.md)** - Deep dive into smart dependency resolution
2. **[Creating Your First Agent](./05-first-agent.md)** - Build a complete agent from scratch

---

💡 **Tip**: The dual decorator pattern gives you the best of both worlds - familiar FastMCP development with powerful mesh orchestration!

📚 **Note**: All examples use the new 0.2.x pattern - no more manual server management needed.
