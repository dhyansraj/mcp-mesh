# Getting Started with MCP Mesh

> From zero to distributed MCP services in 5 minutes

## Overview

MCP Mesh makes building distributed MCP services as easy as writing Python functions. Just add a decorator, and your functions can automatically discover and use other services across your network.

## What is MCP Mesh?

MCP Mesh is a **pip-installable package** that adds service mesh capabilities to your MCP agents:

- 🔌 **Just a decorator**: Add `@mesh_agent()` to any MCP function
- 🔍 **Automatic discovery**: Services find each other automatically
- 💉 **Dependency injection**: Use remote functions like local ones
- 🚀 **Zero configuration**: No service URLs, no config files
- 📦 **Batteries included**: Registry, CLI tools, and monitoring built-in

## The Simplest Example

```python
# Regular MCP function
@server.tool()
def greet(name: str = "World"):
    return f"Hello, {name}!"

# MCP Mesh function with dependency injection
@server.tool()
@mesh_agent(
    capability="greeting",
    dependencies=["SystemAgent_getDate"],  # ← Uses another service
    enable_http=True
)
def greet_with_date(name: str = "World", SystemAgent_getDate=None):
    date = SystemAgent_getDate() if SystemAgent_getDate else "unknown"
    return f"Hello, {name}! Today is {date}"
```

That's it! The second function automatically discovers and uses the SystemAgent service.

## Quick Start (2 Minutes)

```bash
# 1. Install MCP Mesh
pip install mcp-mesh

# 2. Run the examples
mcp-mesh-dev start examples/system_agent.py
mcp-mesh-dev start examples/hello_world.py

# 3. Test it
curl http://localhost:8888/greet_from_mcp_mesh_dependency
```

That's literally all you need to get started! 🎉

## What You'll Learn

This section covers the essentials in bite-sized pieces:

1. **[Prerequisites](./01-getting-started/01-prerequisites.md)** - Check your system is ready (5 min)
2. **[Installation](./01-getting-started/02-installation.md)** - Install MCP Mesh (2 min)
3. **[Running Hello World](./01-getting-started/03-hello-world.md)** - See it in action (3 min)
4. **[Understanding Dependency Injection](./01-getting-started/04-dependency-injection.md)** - Learn the magic (10 min)
5. **[Creating Your First Agent](./01-getting-started/05-first-agent.md)** - Build your own (15 min)

Total time: ~35 minutes to become productive with MCP Mesh

## How MCP Mesh Works

```
Your Code                          MCP Mesh (pip package)                    Automatic
┌─────────────────┐               ┌────────────────────┐                ┌──────────────┐
│ @mesh_agent()   │──────────────▶│ • Discovery        │◀──────────────│ • Registry   │
│ def my_func():  │               │ • Injection        │                │ • Health     │
│   return data   │◀──────────────│ • Transport        │                │ • Routing    │
└─────────────────┘               └────────────────────┘                └──────────────┘
   You write this                    Handles complexity                    Runs for you
```

## Key Concepts in 30 Seconds

1. **Agents**: Your Python files with MCP functions
2. **Registry**: Go service that tracks all agents (starts automatically)
3. **Capabilities**: What functions an agent provides (e.g., "weather", "database")
4. **Dependencies**: What functions an agent needs from others
5. **Injection**: Remote functions appear as local parameters

## Why Developers Love MCP Mesh

- **Zero boilerplate**: No interfaces, no service classes, just functions
- **Interface-optional**: No need to define Protocol or ABC classes
- **Graceful degradation**: Functions work even if dependencies are unavailable
- **Local development**: Run everything on your laptop
- **Production ready**: Same code scales to Kubernetes

## Ready to Start?

Let's begin with checking the [Prerequisites](./01-getting-started/01-prerequisites.md) →

---

💡 **Tip**: This guide is designed to be followed sequentially. Each section builds on the previous one, ensuring a smooth learning experience.

📚 **Note**: If you're already familiar with MCP and want to jump straight to advanced topics, check out our [Quick Start Paths](../MCP_MESH_DEPLOYMENT_GUIDE.md#-quick-start-paths) in the main guide.

## 🔧 Troubleshooting

Common issues when getting started:

1. **Python version errors** - Ensure Python 3.9+ is installed
2. **Port conflicts** - Check if ports 8000/8080 are already in use
3. **Import errors** - Verify MCP Mesh is installed in your virtual environment
4. **Registry connection failures** - Ensure registry is running before starting agents

For detailed solutions, see our [Troubleshooting Guide](./01-getting-started/troubleshooting.md).

## ⚠️ Known Limitations

- **Windows Support**: Native Windows support is experimental; WSL2 is recommended
- **Python 3.8**: Not supported; upgrade to Python 3.9+
- **ARM Architecture**: Some features may have limited support on ARM processors
- **Firewall**: Strict firewall rules may block agent communication

## 📝 TODO

- [ ] Add interactive tutorial/playground
- [ ] Create video walkthrough for visual learners
- [ ] Add more real-world examples beyond weather
- [ ] Translate to multiple languages
- [ ] Add performance benchmarks for example agents
