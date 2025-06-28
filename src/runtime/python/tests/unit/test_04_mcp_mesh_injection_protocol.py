"""
Unit test for dependency injection through MCP protocol with mocked registry.
"""

import functools
import os
from typing import Any
from unittest.mock import patch

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

from mesh.types import McpMeshAgent


# Mock SystemAgent that will be injected
class MockSystemAgent:
    def getDate(self) -> str:
        return "2024-01-20 12:00:00 (mock)"

    def getUser(self) -> str:
        return "TestUser"


# Mock registry that provides dependencies
class MockRegistry:
    def __init__(self):
        self.dependencies = {"SystemAgent": MockSystemAgent()}

    def get_dependency(self, name: str) -> Any:
        return self.dependencies.get(name)


# Working mesh_agent decorator that actually does injection
def working_mesh_agent(capability: str, dependencies: list[str] = None, **kwargs):
    """A working version of mesh_agent that creates a wrapper for injection."""

    def decorator(target):
        # Add metadata
        target._mesh_metadata = {
            "capability": capability,
            "dependencies": dependencies or [],
            **kwargs,
        }

        # Create wrapper that does injection
        @functools.wraps(target)
        def wrapper(**call_kwargs):
            # Get mock registry
            registry = MockRegistry()

            # Inject dependencies
            if dependencies:
                for dep in dependencies:
                    if dep not in call_kwargs or call_kwargs[dep] is None:
                        injected = registry.get_dependency(dep)
                        if injected:
                            call_kwargs[dep] = injected

            # Call original
            return target(**call_kwargs)

        # Copy metadata to wrapper
        wrapper._mesh_metadata = target._mesh_metadata
        wrapper._mesh_agent_capabilities = [capability]
        wrapper._mesh_agent_dependencies = dependencies or []

        # Return wrapper!
        return wrapper

    return decorator


class TestDependencyInjectionMCP:
    """Test dependency injection through MCP protocol."""

    @pytest.fixture(autouse=True)
    def disable_background_services(self):
        """Disable background services for all tests in this class."""
        with patch.dict(
            os.environ,
            {
                "MCP_MESH_AUTO_RUN": "false",
                "MCP_MESH_ENABLE_HTTP": "false",
                "MCP_MESH_HEALTH_INTERVAL": "0",
            },
        ):
            yield

    def test_decorator_order_works_both_ways(self):
        """Test that both decorator orders now work with FastMCP patching."""
        import mesh

        server = FastMCP(name="test-server")

        # Order 1: @server.tool() first
        @server.tool()
        @mesh.tool(capability="test1", dependencies=[{"capability": "SystemAgent"}])
        def order1(name: str = "User", SystemAgent: McpMeshAgent = None) -> str:
            if SystemAgent:
                return f"Hello {name}, date is {SystemAgent.getDate()}"
            return f"Hello {name}, no injection"

        # Order 2: @mesh.tool first
        @mesh.tool(capability="test2", dependencies=[{"capability": "SystemAgent"}])
        @server.tool()
        def order2(name: str = "User", SystemAgent: McpMeshAgent = None) -> str:
            if SystemAgent:
                return f"Hello {name}, date is {SystemAgent.getDate()}"
            return f"Hello {name}, no injection"

        # Check that both functions are registered with FastMCP
        assert hasattr(server, "_tool_manager")
        tools = server._tool_manager._tools

        # Both decorator orders should work and functions should be registered
        assert "order1" in tools
        assert "order2" in tools

        # Functions should be callable
        func1 = tools["order1"].fn
        func2 = tools["order2"].fn
        assert callable(func1)
        assert callable(func2)

    @pytest.mark.asyncio
    async def test_injection_through_server_call_tool(self):
        """Test dependency injection through server.call_tool with FastMCP patching."""
        # Import the new mesh decorators
        import mesh

        # Register dependency first
        from mcp_mesh.engine.dependency_injector import get_global_injector

        injector = get_global_injector()
        await injector.register_dependency("SystemAgent", MockSystemAgent())

        server = FastMCP(name="test-server")

        # Order 1: @server.tool() first
        @server.tool()
        @mesh.tool(capability="greet1", dependencies=[{"capability": "SystemAgent"}])
        def greet_order1(name: str = "User", SystemAgent: McpMeshAgent = None) -> str:
            if SystemAgent:
                return f"Order1: Hello {name}, date={SystemAgent.getDate()}"
            return f"Order1: Hello {name}, no SystemAgent"

        # Order 2: @mesh.tool first
        @mesh.tool(capability="greet2", dependencies=[{"capability": "SystemAgent"}])
        @server.tool()
        def greet_order2(name: str = "User", SystemAgent: McpMeshAgent = None) -> str:
            if SystemAgent:
                return f"Order2: Hello {name}, date={SystemAgent.getDate()}"
            return f"Order2: Hello {name}, no SystemAgent"

        # Test through server.call_tool - both should get injection
        result1 = await server.call_tool("greet_order1", {"name": "Alice"})
        assert "date=2024-01-20 12:00:00 (mock)" in result1[0].text

        result2 = await server.call_tool("greet_order2", {"name": "Bob"})
        assert "date=2024-01-20 12:00:00 (mock)" in result2[0].text

    @pytest.mark.asyncio
    async def test_injection_with_mcp_client_server(self):
        """Test dependency injection through full MCP client/server communication."""
        import os
        import tempfile

        # Create a test server script
        server_script = '''
import asyncio
from mcp.server.fastmcp import FastMCP
import mesh
from mesh.types import McpMeshAgent

# Mock SystemAgent for dependency injection
class MockSystemAgent:
    def getDate(self) -> str:
        return "2024-01-20 12:00:00 (mock)"

    def getUser(self) -> str:
        return "TestUser"

server = FastMCP(name="test-di-server")

# Set up dependency injection
async def setup_dependencies():
    """Set up mock dependencies for testing."""
    from mcp_mesh.engine.dependency_injector import get_global_injector

    injector = get_global_injector()
    mock_agent = MockSystemAgent()
    await injector.register_dependency("SystemAgent", mock_agent)
    print("📦 Registered SystemAgent dependency for testing")

# Test with mesh.tool decorator
@mesh.tool(capability="greeting", dependencies=[{"capability": "SystemAgent"}])
@server.tool()
def greet(name: str = "World", SystemAgent: McpMeshAgent = None) -> str:
    """Greeting function with dependency injection."""
    if SystemAgent:
        return f"Hello {name}! SystemAgent says: date={SystemAgent.getDate()}, user={SystemAgent.getUser()}"
    return f"Hello {name}! No SystemAgent available"

# Run server with dependency setup
async def main():
    await setup_dependencies()

if __name__ == "__main__":
    # Set up dependencies first
    asyncio.run(main())
    # Then run server synchronously
    server.run(transport="stdio")
'''

        # Write server script to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(server_script)
            server_file = f.name

        try:
            # Create MCP client and connect
            server_params = StdioServerParameters(
                command="python",
                args=[server_file],
                env={**os.environ, "PYTHONPATH": os.getcwd()},
            )

            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize session
                    await session.initialize()

                    # List tools to verify registration
                    tools = await session.list_tools()
                    tool_names = [t.name for t in tools.tools]
                    assert "greet" in tool_names

                    # Call the function through MCP
                    result = await session.call_tool("greet", {"name": "TestUser"})
                    response_text = result.content[0].text

                    # Verify injection worked
                    assert "SystemAgent says:" in response_text
                    assert "date=2024-01-20 12:00:00 (mock)" in response_text
                    assert "user=TestUser" in response_text

        finally:
            # Cleanup
            os.unlink(server_file)

    def test_mesh_tool_wrapper_preserves_metadata(self):
        """Test that the mesh.tool wrapper preserves all metadata."""
        import mesh

        @mesh.tool(
            capability="test_func",
            dependencies=[{"capability": "Dep1"}, {"capability": "Dep2"}],
            version="1.0.0",
            tags=["test"],
        )
        def test_function(
            x: int, Dep1: McpMeshAgent = None, Dep2: McpMeshAgent = None
        ) -> int:
            """Test function docstring."""
            return x * 2

        # Check wrapper preserved everything
        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "Test function docstring."

        # Check that mesh.tool decorated function is callable
        assert callable(test_function)

        # Test function execution
        result = test_function(x=5)
        assert result == 10


if __name__ == "__main__":
    # Run tests
    import subprocess

    subprocess.run(["pytest", __file__, "-v"])
