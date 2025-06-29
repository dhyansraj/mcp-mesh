# MCP Mesh Python Runtime

Python runtime for the MCP Mesh service mesh framework.

## Installation

```bash
pip install mcp-mesh
```

## Quick Start

```python
import mesh

# Import types from public API
from mesh.types import McpMeshAgent

# Define your agent
@mesh.agent(name="hello-world", http_port=9090)
class HelloWorldAgent:
    """Hello World agent demonstrating MCP Mesh features."""
    pass

# Create a greeting function with dependency injection
@mesh.tool(
    capability="greeting",
    dependencies=["date_service"],
    description="Greeting function with date dependency injection"
)
def greet(name: str = "World", systemDate: McpMeshAgent = None) -> str:
    """Greeting function with automatic dependency injection."""
    if systemDate is not None:
        try:
            current_date = systemDate()
            return f"Hello, {name}! Today is {current_date}"
        except Exception:
            pass

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

## API Architecture

MCP Mesh uses a clear separation between public and private APIs:

- **`mesh`** - Public user API for decorators and types
- **`_mcp_mesh`** - Private internal implementation (do not import directly)

The underscore prefix on `_mcp_mesh` follows Python conventions to indicate internal/private packages. Users should only import from the `mesh` package to ensure compatibility across versions.

## Documentation

See the [main repository](https://github.com/dhyansraj/mcp-mesh) for complete documentation.
