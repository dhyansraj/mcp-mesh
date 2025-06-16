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


# Helper function to create FastMCP server with proper naming
def create_server(name: str | None = None) -> "FastMCP":
    """
    Create a FastMCP server with proper naming for MCP Mesh integration.

    If a @mesh.agent decorator has been applied to a class in the current module,
    this function will use the agent name for the server. Otherwise, it uses the
    provided name or a default.

    Args:
        name: Optional server name. If not provided, will try to use @mesh.agent name

    Returns:
        FastMCP server instance with proper name

    Example:
        @mesh.agent(name="my-service")
        class MyAgent:
            pass

        server = mesh.create_server()  # Uses "my-service" as server name

        @mesh.tool(capability="greeting")
        @server.tool()
        def hello():
            return "Hello!"
    """
    try:
        from fastmcp import FastMCP

        print("🆕 Using NEW FastMCP library (fastmcp)")
    except ImportError:
        try:
            # Fallback to old version
            from mcp.server.fastmcp import FastMCP

            print("🔄 Using OLD FastMCP library (mcp.server.fastmcp)")
        except ImportError:
            raise ImportError(
                "FastMCP not available. Install with: pip install fastmcp"
            )

    # Try to get agent name from existing @mesh.agent decorators
    if name is None:
        from mcp_mesh.decorator_registry import DecoratorRegistry

        agents = DecoratorRegistry.get_mesh_agents()

        if agents:
            # Use the first agent's name found
            agent_data = next(iter(agents.values()))
            agent_metadata = agent_data.metadata
            agent_name = agent_metadata.get("name")
            if agent_name:
                name = agent_name

    # Fallback to default name
    if name is None:
        name = "mcp-mesh-server"

    return FastMCP(name=name)


# Make decorators available as mesh.tool and mesh.agent
def __getattr__(name):
    if name == "tool":
        return decorators.tool
    elif name == "agent":
        return decorators.agent
    elif name == "McpMeshAgent":
        return McpMeshAgent
    elif name == "create_server":
        return create_server
    elif name == "start_auto_run_service":
        return decorators.start_auto_run_service
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# Note: In Python, we can't completely prevent 'from mesh import tool'
# but we strongly discourage it for API consistency with MCP patterns
__all__ = []
