"""
Unit test for dependency injection through MCP protocol with mocked registry.
"""

import functools
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP


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

    def test_decorator_order_works_both_ways(self):
        """Test that both decorator orders now work with FastMCP patching."""
        server = FastMCP(name="test-server")

        # Order 1: @server.tool() first
        @server.tool()
        @working_mesh_agent(capability="test1", dependencies=["SystemAgent"])
        def order1(name: str = "User", SystemAgent: Any = None) -> str:
            if SystemAgent:
                return f"Hello {name}, date is {SystemAgent.getDate()}"
            return f"Hello {name}, no injection"

        # Order 2: @working_mesh_agent first
        @working_mesh_agent(capability="test2", dependencies=["SystemAgent"])
        @server.tool()
        def order2(name: str = "User", SystemAgent: Any = None) -> str:
            if SystemAgent:
                return f"Hello {name}, date is {SystemAgent.getDate()}"
            return f"Hello {name}, no injection"

        # Check what FastMCP stored
        assert hasattr(server, "_tool_manager")
        tools = server._tool_manager._tools

        # Both orders should have metadata preserved
        func1 = tools["order1"].fn
        assert hasattr(func1, "_mesh_metadata")
        assert func1._mesh_metadata["capability"] == "test1"

        func2 = tools["order2"].fn
        assert hasattr(func2, "_mesh_metadata")
        assert func2._mesh_metadata["capability"] == "test2"

    @pytest.mark.asyncio
    async def test_injection_through_server_call_tool(self):
        """Test dependency injection through server.call_tool with FastMCP patching."""
        # Import the real mesh_agent decorator
        from mcp_mesh.decorators import mesh_agent

        # Register dependency first
        from mcp_mesh.runtime.dependency_injector import get_global_injector

        injector = get_global_injector()
        await injector.register_dependency("SystemAgent", MockSystemAgent())

        server = FastMCP(name="test-server")

        # Order 1: @server.tool() first
        @server.tool()
        @mesh_agent(capability="greet1", dependencies=["SystemAgent"])
        def greet_order1(name: str = "User", SystemAgent: Any = None) -> str:
            if SystemAgent:
                return f"Order1: Hello {name}, date={SystemAgent.getDate()}"
            return f"Order1: Hello {name}, no SystemAgent"

        # Order 2: @mesh_agent first
        @mesh_agent(capability="greet2", dependencies=["SystemAgent"])
        @server.tool()
        def greet_order2(name: str = "User", SystemAgent: Any = None) -> str:
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
from mcp_mesh import mesh_agent
from tests.unit.test_dependency_injection_mcp import working_mesh_agent, MockSystemAgent

server = FastMCP(name="test-di-server")

# Test with mesh_agent decorator
@mesh_agent(capability="greeting", dependencies=["SystemAgent"])
@server.tool()
def greet(name: str = "World", SystemAgent = None) -> str:
    """Greeting function with dependency injection."""
    if SystemAgent:
        return f"Hello {name}! SystemAgent says: date={SystemAgent.getDate()}, user={SystemAgent.getUser()}"
    return f"Hello {name}! No SystemAgent available"

# Run server
if __name__ == "__main__":
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

    def test_mesh_agent_wrapper_preserves_metadata(self):
        """Test that the wrapper preserves all metadata."""

        @working_mesh_agent(
            capability="test_func",
            dependencies=["Dep1", "Dep2"],
            version="1.0.0",
            custom_field="custom_value",
        )
        def test_function(x: int, Dep1: Any = None, Dep2: Any = None) -> int:
            """Test function docstring."""
            return x * 2

        # Check wrapper preserved everything
        assert test_function.__name__ == "test_function"
        assert test_function.__doc__ == "Test function docstring."
        assert hasattr(test_function, "_mesh_metadata")
        assert test_function._mesh_metadata["capability"] == "test_func"
        assert test_function._mesh_metadata["dependencies"] == ["Dep1", "Dep2"]
        assert test_function._mesh_metadata["version"] == "1.0.0"
        assert test_function._mesh_metadata["custom_field"] == "custom_value"

        # Test with mock registry
        registry = MockRegistry()
        registry.dependencies["Dep1"] = "MockDep1"
        registry.dependencies["Dep2"] = "MockDep2"

        # Call should work
        result = test_function(x=5)
        assert result == 10


if __name__ == "__main__":
    # Run tests
    import subprocess

    subprocess.run(["pytest", __file__, "-v"])
