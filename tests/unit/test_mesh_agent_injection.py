"""
Unit test proving that mesh_agent decorator needs to create a wrapper for dependency injection.
"""

import functools
from typing import Any
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP


class TestMeshAgentInjection:
    """Test suite for mesh_agent dependency injection."""

    def test_current_mesh_agent_no_wrapper(self):
        """Test that current mesh_agent doesn't create a wrapper."""
        from mcp_mesh import mesh_agent

        def original_func():
            return "original"

        # Apply mesh_agent
        decorated = mesh_agent(capability="test")(original_func)

        # Current implementation returns the same function
        assert decorated is original_func
        assert not hasattr(decorated, "__wrapped__")

    def test_working_injection_decorator(self):
        """Test a working injection decorator that creates wrapper."""

        # Mock registry
        mock_registry = {"SystemAgent": Mock(getDate=lambda: "2024-01-20")}

        def inject_dependencies(
            capability: str, dependencies: list[str] = None, **kwargs
        ):
            def decorator(func):
                @functools.wraps(func)
                def wrapper(**call_kwargs):
                    # Inject from mock registry
                    if dependencies:
                        for dep in dependencies:
                            if dep not in call_kwargs or call_kwargs[dep] is None:
                                if dep in mock_registry:
                                    call_kwargs[dep] = mock_registry[dep]
                    return func(**call_kwargs)

                # Add metadata
                wrapper._mesh_metadata = {
                    "capability": capability,
                    "dependencies": dependencies or [],
                }
                return wrapper

            return decorator

        # Test function
        @inject_dependencies(capability="greet", dependencies=["SystemAgent"])
        def greet(name: str = "User", SystemAgent: Any = None) -> str:
            if SystemAgent:
                return f"Hello {name}, date: {SystemAgent.getDate()}"
            return f"Hello {name}, no SystemAgent"

        # Direct call should inject
        result = greet(name="Test")
        assert "date: 2024-01-20" in result

    @pytest.mark.asyncio
    async def test_decorator_order_with_mcp(self):
        """Test that decorator order affects MCP protocol calls."""

        # Mock registry
        mock_registry = {"Database": Mock(query=lambda x: f"Result for {x}")}

        def working_mesh_agent(
            capability: str, dependencies: list[str] = None, **kwargs
        ):
            def decorator(func):
                @functools.wraps(func)
                def wrapper(**call_kwargs):
                    if dependencies:
                        for dep in dependencies:
                            if dep not in call_kwargs or call_kwargs[dep] is None:
                                if dep in mock_registry:
                                    call_kwargs[dep] = mock_registry[dep]
                    return func(**call_kwargs)

                return wrapper

            return decorator

        server = FastMCP(name="test")

        # Wrong order - injection won't work through MCP
        @server.tool()
        @working_mesh_agent(capability="query1", dependencies=["Database"])
        def query_wrong_order(sql: str = "SELECT 1", Database: Any = None) -> str:
            if Database:
                return f"Wrong order: {Database.query(sql)}"
            return "Wrong order: No Database"

        # Correct order - injection works through MCP
        @working_mesh_agent(capability="query2", dependencies=["Database"])
        @server.tool()
        def query_correct_order(sql: str = "SELECT 1", Database: Any = None) -> str:
            if Database:
                return f"Correct order: {Database.query(sql)}"
            return "Correct order: No Database"

        # Test through MCP protocol
        result1 = await server.call_tool(
            "query_wrong_order", {"sql": "SELECT * FROM users"}
        )
        result2 = await server.call_tool(
            "query_correct_order", {"sql": "SELECT * FROM users"}
        )

        # With current FastMCP behavior, we expect:
        # - Wrong order: Gets injection (because wrapper was applied after registration)
        # - Correct order: No injection (because original function was registered)
        assert "Result for SELECT * FROM users" in result1[0].text
        assert "No Database" in result2[0].text

        # This proves we need to fix our understanding and implementation!


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
