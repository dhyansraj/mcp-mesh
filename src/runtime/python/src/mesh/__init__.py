"""
Mesh Decorators - New dual decorator architecture for MCP Mesh.

Provides two levels of decoration:
- @mesh.tool: Function-level tool registration and capabilities
- @mesh.agent: Agent-level configuration and metadata

Usage:
    import mesh

    @mesh.agent(name="my-agent", version="1.0.0")
    class MyAgent:
        @mesh.tool(capability="greeting")
        def say_hello(self):
            return "Hello!"

Note: Direct imports like 'from mesh import tool' are discouraged.
Use 'import mesh' and then '@mesh.tool()' for consistency with MCP patterns.
"""

from mcp_mesh.types import McpMeshAgent

from . import decorators

__version__ = "1.0.0"


# Make decorators available as mesh.tool and mesh.agent
def __getattr__(name):
    if name == "tool":
        return decorators.tool
    elif name == "agent":
        return decorators.agent
    elif name == "McpMeshAgent":
        return McpMeshAgent
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Note: In Python, we can't completely prevent 'from mesh import tool'
# but we strongly discourage it for API consistency with MCP patterns
__all__ = []
