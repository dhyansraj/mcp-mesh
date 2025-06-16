"""
Test the mesh.create_server() helper function.
"""

import os
from unittest.mock import Mock, patch

import pytest

import mesh
from mcp_mesh import DecoratorRegistry


@pytest.fixture(autouse=True)
def disable_background_services():
    """Disable background services for all tests in this module."""
    with patch.dict(
        os.environ, {"MCP_MESH_AUTO_RUN": "false", "MCP_MESH_ENABLE_HTTP": "false"}
    ):
        yield


class TestMeshCreateServer:
    """Test mesh.create_server() functionality."""

    def test_create_server_with_explicit_name(self):
        """Test creating server with explicit name."""
        with patch("mcp.server.fastmcp.FastMCP") as mock_fastmcp:
            mock_server = Mock()
            mock_fastmcp.return_value = mock_server

            server = mesh.create_server("my-custom-server")

            mock_fastmcp.assert_called_once_with(name="my-custom-server")
            assert server == mock_server

    def test_create_server_uses_mesh_agent_name(self):
        """Test that create_server uses @mesh.agent name when available."""
        # Clear registry
        DecoratorRegistry.clear_all()

        with patch("mcp.server.fastmcp.FastMCP") as mock_fastmcp:
            mock_server = Mock()
            mock_fastmcp.return_value = mock_server

            # Define agent first
            @mesh.agent(name="test-service")
            class TestAgent:
                pass

            # Create server without explicit name
            server = mesh.create_server()

            # Should use the agent name
            mock_fastmcp.assert_called_once_with(name="test-service")
            assert server == mock_server

    def test_create_server_fallback_name(self):
        """Test that create_server uses fallback name when no agent is defined."""
        # Clear registry
        DecoratorRegistry.clear_all()

        with patch("mcp.server.fastmcp.FastMCP") as mock_fastmcp:
            mock_server = Mock()
            mock_fastmcp.return_value = mock_server

            # Create server without agent or explicit name
            server = mesh.create_server()

            # Should use fallback name
            mock_fastmcp.assert_called_once_with(name="mcp-mesh-server")
            assert server == mock_server

    def test_create_server_import_error(self):
        """Test that create_server raises helpful error when FastMCP not available."""
        # Mock the import statement in create_server to fail
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "mcp.server.fastmcp":
                raise ImportError("No module named 'mcp'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="FastMCP not available"):
                mesh.create_server()

    def test_create_server_prefers_explicit_name_over_agent(self):
        """Test that explicit name takes precedence over @mesh.agent name."""
        # Clear registry
        DecoratorRegistry.clear_all()

        with patch("mcp.server.fastmcp.FastMCP") as mock_fastmcp:
            mock_server = Mock()
            mock_fastmcp.return_value = mock_server

            # Define agent
            @mesh.agent(name="agent-service")
            class TestAgent:
                pass

            # Create server with explicit name
            server = mesh.create_server("explicit-name")

            # Should use explicit name, not agent name
            mock_fastmcp.assert_called_once_with(name="explicit-name")
            assert server == mock_server

    def test_create_server_with_multiple_agents(self):
        """Test that create_server uses first agent when multiple are defined."""
        # Clear registry
        DecoratorRegistry.clear_all()

        with patch("mcp.server.fastmcp.FastMCP") as mock_fastmcp:
            mock_server = Mock()
            mock_fastmcp.return_value = mock_server

            # Define multiple agents
            @mesh.agent(name="first-service")
            class FirstAgent:
                pass

            @mesh.agent(name="second-service")
            class SecondAgent:
                pass

            # Create server without explicit name
            server = mesh.create_server()

            # Should use first agent found (order may vary with dict iteration)
            mock_fastmcp.assert_called_once()
            called_name = mock_fastmcp.call_args[1]["name"]
            assert called_name in ["first-service", "second-service"]
            assert server == mock_server
