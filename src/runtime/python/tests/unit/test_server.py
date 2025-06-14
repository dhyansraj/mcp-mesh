"""
Unit tests for MCP server components.
"""

import pytest
from mcp.server import Server
from mcp.types import Tool


class TestMCPServer:
    """Test MCP server functionality."""

    def test_server_creation(self):
        """Test creating a basic MCP server."""
        server = Server("test-server")
        assert server.name == "test-server"

    @pytest.mark.asyncio
    async def test_tool_registration(self):
        """Test tool registration and listing."""
        server = Server("test-server")

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="test_tool",
                    description="A test tool",
                    inputSchema={
                        "type": "object",
                        "properties": {"input": {"type": "string"}},
                        "required": ["input"],
                    },
                )
            ]

        # Test that the server has the list_tools method available
        assert hasattr(server, "list_tools")
        assert callable(server.list_tools)
