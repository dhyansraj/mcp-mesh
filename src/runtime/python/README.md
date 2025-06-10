# MCP Mesh Python Runtime

Python runtime for the MCP Mesh service mesh framework.

## Installation

```bash
pip install mcp-mesh
```

## Quick Start

```python
from mcp_mesh import mesh_agent
from mcp.server.fastmcp import FastMCP

# Create your MCP server
server = FastMCP()

# Use mesh_agent decorator BEFORE server.tool()
@mesh_agent(capability="greeting")
@server.tool()
def greet(name: str = "World") -> str:
    """Simple greeting function."""
    return f"Hello, {name}!"

# The runtime auto-initializes when you import mcp_mesh
# Your functions are automatically registered with the mesh registry
```

## Features

- **Automatic Registration**: Functions are automatically registered with the Go registry
- **Health Monitoring**: Built-in health checks and heartbeats
- **Dependency Injection**: Inject dependencies into your functions
- **Service Discovery**: Find and use other services in the mesh
- **Graceful Degradation**: Works even if registry is unavailable

## Configuration

The runtime can be configured via environment variables:

- `MCP_MESH_ENABLED`: Enable/disable runtime (default: "true")
- `MCP_MESH_REGISTRY_URL`: Registry URL (default: "http://localhost:8080")
- `MCP_MESH_AGENT_NAME`: Custom agent name (auto-generated if not set)

## Documentation

See the [main repository](https://github.com/mcp-mesh/mcp-mesh) for complete documentation.
