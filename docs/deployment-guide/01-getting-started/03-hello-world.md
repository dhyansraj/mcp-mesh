# Running Hello World Example

> The simplest way to see MCP Mesh in action - as easy as running a Python script!

## Overview

Running MCP Mesh agents is as simple as running Python scripts. The mesh handles all the complexity of service discovery and dependency injection automatically.

## Quick Start (3 Commands!)

```bash
# 1. Start the first agent (provides system functions)
meshctl start examples/system_agent.py

# 2. Start the Hello World agent (uses system functions)
meshctl start examples/hello_world.py

# 3. Test it!
curl http://localhost:8888/greet_from_mcp_mesh_dependency
```

That's it! You've just run a distributed MCP system with automatic dependency injection. 🎉

## What Just Happened?

The Hello World example demonstrates the power of MCP Mesh:

1. **system_agent.py** provides functions like `getDate()` and `getTime()`
2. **hello_world.py** automatically discovers and uses these functions
3. No configuration files, no service URLs, no boilerplate - just decorators!

## Understanding the Code

Here's the key part of `hello_world.py`:

```python
@server.tool()
@mesh_agent(
    capability="greeting",
    dependencies=["SystemAgent_getDate"],  # ← Declares what it needs
    enable_http=True,
    http_port=8888
)
def greet_from_mcp_mesh_dependency(
    name: str = "World",
    SystemAgent_getDate=None  # ← Automatically injected!
):
    """This shows MCP Mesh dependency injection"""
    if SystemAgent_getDate:
        date_str = SystemAgent_getDate()
        return f"Hello {name} from MCP Mesh Dependency Injection! Today is {date_str}"
    else:
        return f"Hello {name} from MCP Mesh (SystemAgent not available)"
```

Compare this to a regular MCP function in the same file:

```python
@server.tool()
def greet_from_mcp(name: str = "World"):
    """This is a regular MCP function - no mesh features"""
    return f"Hello {name} from regular MCP!"
```

The only difference? The `@mesh_agent()` decorator and the dependency parameter!

## Behind the Scenes

When you run `meshctl start`, it automatically:

1. **Starts the Registry** (if not already running) - A Go service that tracks all agents
2. **Registers your agent** - Tells the registry what functions it provides
3. **Resolves dependencies** - Finds and connects to required services
4. **Injects functions** - Makes remote functions callable as if they were local
5. **Monitors health** - Keeps everything running smoothly

## Step-by-Step Breakdown

### What `system_agent.py` provides:

```python
@server.tool()
@mesh_agent(
    capability="SystemAgent",
    enable_http=True
)
async def getDate() -> str:
    """Get the current date"""
    return datetime.now().strftime("%Y-%m-%d")
```

### How `hello_world.py` uses it:

```python
# The function parameter name must match: capability_functionName
def greet_from_mcp_mesh_dependency(
    name: str = "World",
    SystemAgent_getDate=None  # ← This gets injected automatically!
):
    if SystemAgent_getDate:
        date_str = SystemAgent_getDate()  # ← Call it like a local function
        return f"Hello {name}! Today is {date_str}"
```

## Try More Examples

```bash
# Test different endpoints
curl http://localhost:8888/greet_from_mcp       # Regular MCP (no injection)
curl http://localhost:8888/greet_from_mcp_mesh  # With injection (fixed in code)
curl http://localhost:8888/greet_from_mcp_mesh_dependency  # With injection (dynamic)

# See all available functions
curl http://localhost:8080/docs  # System agent docs
curl http://localhost:8888/docs  # Hello world docs

# Check what's running
meshctl status

# View logs
meshctl logs hello_world
```

## Understanding the Architecture

```
Your Agent Code                    MCP Mesh (Installed via pip)              Registry (Go)
┌─────────────────┐               ┌──────────────────────────┐            ┌─────────────┐
│ @mesh_agent()   │──registers───▶│ • Service discovery      │◀──tracks──│ • Agent list │
│ def my_func():  │               │ • Dependency injection   │            │ • Health     │
│   ...           │◀──injects─────│ • HTTP transport         │            │ • Routing    │
└─────────────────┘               └──────────────────────────┘            └─────────────┘
     You write                          Handles complexity                   Runs automatically
```

## What's Next?

Congratulations! You've successfully:

- ✅ Run distributed MCP agents with one command
- ✅ Seen automatic dependency injection in action
- ✅ Tested cross-service communication

The beauty of MCP Mesh is that **this is all you need to know** to start building distributed MCP systems!

### Try This Yourself

Create a new file `my_agent.py`:

```python
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="my-agent")

@server.tool()
@mesh_agent(
    capability="weather",
    dependencies=["SystemAgent_getTime"],
    enable_http=True,
    http_port=9000
)
def get_weather(city: str = "London", SystemAgent_getTime=None):
    time = SystemAgent_getTime() if SystemAgent_getTime else "unknown"
    return f"Weather in {city} at {time}: Sunny, 22°C"

if __name__ == "__main__":
    import asyncio
    from mcp_mesh.server.runner import run_server
    asyncio.run(run_server(server))
```

Run it:

```bash
meshctl start my_agent.py
curl http://localhost:9000/weather_get_weather
```

Next, let's understand how this magic works:

[Understanding Dependency Injection](./04-dependency-injection.md) →

---

💡 **Remember**: MCP Mesh is just a pip package. You write agents, it handles the mesh!

📚 **Exercise**: Try modifying hello_world.py to use SystemAgent_getTime as well. What changes are needed?

## 🔧 Troubleshooting

### Common Issues

1. **"Connection refused" errors** - Ensure registry is running on port 8000
2. **"Dependency not found"** - Start System Agent before Hello World
3. **"Port already in use"** - Kill existing processes or use different ports
4. **"Import error: mcp_mesh"** - Activate virtual environment
5. **Slow dependency resolution** - Check network connectivity to registry

For detailed solutions, see our [Troubleshooting Guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **Single registry**: Examples assume single registry instance
- **Local only**: Examples use localhost; remote deployment requires configuration
- **No persistence**: Registry uses in-memory storage by default
- **HTTP only**: Examples don't include HTTPS/TLS configuration
- **Basic auth**: No authentication in example setup

## 📝 TODO

- [ ] Add WebSocket transport example
- [ ] Include gRPC transport option
- [ ] Add multi-registry example
- [ ] Create interactive web UI for testing
- [ ] Add distributed tracing example
- [ ] Include metrics visualization
