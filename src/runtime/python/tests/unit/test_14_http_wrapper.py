"""
Unit tests for HttpMcpWrapper.

Tests the simplified HTTP wrapper that creates FastMCP apps for mounting
into the main FastAPI application.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
# Import the class under test
from _mcp_mesh.engine.http_wrapper import HttpMcpWrapper


class TestHttpMcpWrapperInitialization:
    """Test HttpMcpWrapper initialization and setup."""

    def test_initialization_basic(self):
        """Test basic initialization with FastMCP server that has no http_app method."""
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_server.name = "test-server"

        # Remove http_app method to test basic case
        del mock_fastmcp_server.http_app

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        assert wrapper.mcp_server == mock_fastmcp_server
        assert wrapper._mcp_app is None  # Not created when no http_app method
        assert wrapper._lifespan is None

    def test_initialization_creates_fastmcp_app_with_stateless(self):
        """Test initialization creates FastMCP app with stateless transport."""
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_app = MagicMock()
        mock_lifespan = MagicMock()

        # Mock FastMCP server with http_app method
        mock_fastmcp_server.http_app.return_value = mock_fastmcp_app
        mock_fastmcp_app.lifespan = mock_lifespan

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # Verify stateless HTTP app was created
        mock_fastmcp_server.http_app.assert_called_once_with(
            stateless_http=True, transport="streamable-http"
        )
        assert wrapper._mcp_app == mock_fastmcp_app
        assert wrapper._lifespan == mock_lifespan

    def test_initialization_fallback_without_stateless(self):
        """Test initialization falls back to non-stateless when stateless fails."""
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_app = MagicMock()
        mock_lifespan = MagicMock()

        # First call (stateless) raises exception, second call succeeds
        mock_fastmcp_server.http_app.side_effect = [
            Exception("Stateless not supported"),
            mock_fastmcp_app,
        ]
        mock_fastmcp_app.lifespan = mock_lifespan

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # Verify both calls were made
        assert mock_fastmcp_server.http_app.call_count == 2
        # First call with stateless params
        mock_fastmcp_server.http_app.assert_any_call(
            stateless_http=True, transport="streamable-http"
        )
        # Second call without params (fallback)
        mock_fastmcp_server.http_app.assert_any_call()

        assert wrapper._mcp_app == mock_fastmcp_app
        assert wrapper._lifespan == mock_lifespan

    def test_initialization_no_lifespan_available(self):
        """Test initialization when FastMCP app has no lifespan."""
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_app = MagicMock()

        # FastMCP app without lifespan attribute
        mock_fastmcp_server.http_app.return_value = mock_fastmcp_app
        del mock_fastmcp_app.lifespan  # Remove lifespan attribute

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        assert wrapper._mcp_app == mock_fastmcp_app
        assert wrapper._lifespan is None

    def test_initialization_http_app_creation_fails_completely(self):
        """Test initialization when FastMCP app creation fails entirely."""
        mock_fastmcp_server = MagicMock()

        # Both stateless and fallback calls fail
        mock_fastmcp_server.http_app.side_effect = [
            Exception("Stateless not supported"),
            Exception("HTTP app creation failed"),
        ]

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # Should handle gracefully
        assert wrapper._mcp_app is None
        assert wrapper._lifespan is None

    def test_initialization_no_http_app_method(self):
        """Test initialization when FastMCP server has no http_app method."""
        mock_fastmcp_server = MagicMock()

        # Remove http_app method
        del mock_fastmcp_server.http_app

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        assert wrapper._mcp_app is None
        assert wrapper._lifespan is None


class TestHttpMcpWrapperSetup:
    """Test HttpMcpWrapper setup method."""

    @pytest.mark.asyncio
    async def test_setup_with_fastmcp_library(self):
        """Test setup with FastMCP library server."""
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_app = MagicMock()

        # Mock FastMCP server with http_app method
        mock_fastmcp_server.http_app.return_value = mock_fastmcp_app
        mock_fastmcp_server.name = "test-server"

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # Setup should complete without error
        await wrapper.setup()

        assert wrapper._mcp_app == mock_fastmcp_app

    @pytest.mark.asyncio
    async def test_setup_without_fastmcp_app(self):
        """Test setup when no FastMCP app is available."""
        mock_fastmcp_server = MagicMock()

        # No http_app method
        del mock_fastmcp_server.http_app

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # Should raise AttributeError
        with pytest.raises(AttributeError, match="No supported HTTP app method"):
            await wrapper.setup()

    @pytest.mark.asyncio
    async def test_setup_with_debug_logging(self):
        """Test setup logs debug information about FastMCP server."""
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_app = MagicMock()

        # Mock server with attributes for debugging
        mock_fastmcp_server.http_app.return_value = mock_fastmcp_app
        mock_fastmcp_server.name = "test-server"
        mock_fastmcp_app.routes = [MagicMock(path="/mcp"), MagicMock(path="/docs")]

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        with patch("_mcp_mesh.engine.http_wrapper.logger") as mock_logger:
            await wrapper.setup()

            # Verify debug logging was called
            assert mock_logger.debug.called
            assert mock_logger.info.called


class TestHttpMcpWrapperUtilityMethods:
    """Test utility methods of HttpMcpWrapper."""

    @patch("_mcp_mesh.shared.host_resolver.HostResolver.get_external_host")
    def test_get_external_host(self, mock_get_external_host):
        """Test _get_external_host uses HostResolver."""
        mock_get_external_host.return_value = "test.example.com"

        mock_fastmcp_server = MagicMock()
        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper._get_external_host()

        assert result == "test.example.com"
        mock_get_external_host.assert_called_once()

    @patch("_mcp_mesh.shared.host_resolver.HostResolver.get_external_host")
    def test_get_endpoint(self, mock_get_external_host):
        """Test get_endpoint constructs correct URL with provided port."""
        mock_get_external_host.return_value = "my-service.cluster.local"

        mock_fastmcp_server = MagicMock()
        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper.get_endpoint(port=8080)

        assert result == "http://my-service.cluster.local:8080"
        mock_get_external_host.assert_called_once()

    def test_get_capabilities_empty(self):
        """Test _get_capabilities returns empty list when no tools."""
        mock_fastmcp_server = MagicMock()

        # Mock server without _tool_manager
        del mock_fastmcp_server._tool_manager

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper._get_capabilities()

        assert result == []

    def test_get_capabilities_with_tools(self):
        """Test _get_capabilities extracts capabilities from tools."""
        mock_fastmcp_server = MagicMock()

        # Mock tools with mesh metadata
        mock_tool1 = MagicMock()
        mock_tool1.fn._mesh_agent_metadata = {"capability": "time_service"}

        mock_tool2 = MagicMock()
        mock_tool2.fn._mesh_agent_metadata = {"capability": "math_service"}

        mock_tool3 = MagicMock()
        # Tool without mesh metadata
        del mock_tool3.fn._mesh_agent_metadata

        mock_fastmcp_server._tool_manager._tools = {
            "tool1": mock_tool1,
            "tool2": mock_tool2,
            "tool3": mock_tool3,
        }

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper._get_capabilities()

        # Should extract capabilities from tools with metadata
        assert set(result) == {"time_service", "math_service"}

    def test_get_dependencies_empty(self):
        """Test _get_dependencies returns empty list when no tools."""
        mock_fastmcp_server = MagicMock()

        # Mock server without _tool_manager
        del mock_fastmcp_server._tool_manager

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper._get_dependencies()

        assert result == []

    def test_get_dependencies_with_tools(self):
        """Test _get_dependencies extracts dependencies from tools."""
        mock_fastmcp_server = MagicMock()

        # Mock tools with mesh dependencies
        mock_tool1 = MagicMock()
        mock_tool1.fn._mesh_agent_dependencies = ["time_service", "config_service"]

        mock_tool2 = MagicMock()
        mock_tool2.fn._mesh_agent_dependencies = ["data_service"]

        mock_tool3 = MagicMock()
        # Tool without dependencies
        del mock_tool3.fn._mesh_agent_dependencies

        mock_fastmcp_server._tool_manager._tools = {
            "tool1": mock_tool1,
            "tool2": mock_tool2,
            "tool3": mock_tool3,
        }

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper._get_dependencies()

        # Should extract all dependencies (deduplicated)
        assert set(result) == {"time_service", "config_service", "data_service"}

    def test_extract_tool_params(self):
        """Test _extract_tool_params returns basic schema."""
        mock_fastmcp_server = MagicMock()
        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        mock_tool = MagicMock()

        result = wrapper._extract_tool_params(mock_tool)

        # Basic schema structure
        assert result == {
            "type": "object",
            "properties": {},
            "required": [],
        }


class TestHttpMcpWrapperEdgeCases:
    """Test edge cases and error conditions."""

    def test_wrapper_with_none_fastmcp_server(self):
        """Test wrapper behavior with None FastMCP server."""
        # This should not normally happen, but test robustness
        wrapper = HttpMcpWrapper(None)

        # Should handle gracefully
        assert wrapper.mcp_server is None
        assert wrapper._mcp_app is None

    @pytest.mark.asyncio
    async def test_setup_with_partially_initialized_wrapper(self):
        """Test setup when wrapper is only partially initialized."""
        mock_fastmcp_server = MagicMock()

        # Server has http_app method but it returns None
        mock_fastmcp_server.http_app.return_value = None

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # _mcp_app should be None, setup should detect this
        with pytest.raises(AttributeError, match="No supported HTTP app method"):
            await wrapper.setup()

    def test_get_capabilities_with_malformed_metadata(self):
        """Test _get_capabilities handles malformed tool metadata."""
        mock_fastmcp_server = MagicMock()

        # Mock tool with malformed metadata
        mock_tool = MagicMock()
        mock_tool.fn._mesh_agent_metadata = {"not_capability": "value"}  # Wrong key

        mock_fastmcp_server._tool_manager._tools = {"tool1": mock_tool}

        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        result = wrapper._get_capabilities()

        # Should handle gracefully, return empty list
        assert result == []


class TestHttpMcpWrapperIntegration:
    """Integration-style tests combining multiple wrapper features."""

    @pytest.mark.asyncio
    async def test_full_wrapper_lifecycle(self):
        """Test complete wrapper lifecycle from creation to endpoint generation."""
        # Create mock FastMCP server with realistic structure
        mock_fastmcp_server = MagicMock()
        mock_fastmcp_server.name = "integration-test-server"

        mock_fastmcp_app = MagicMock()
        mock_lifespan = AsyncMock()
        mock_fastmcp_app.lifespan = mock_lifespan
        mock_fastmcp_app.routes = [
            MagicMock(path="/mcp"),
            MagicMock(path="/docs"),
        ]

        mock_fastmcp_server.http_app.return_value = mock_fastmcp_app

        # Mock tool manager with realistic tools
        mock_tool = MagicMock()
        mock_tool.fn._mesh_agent_metadata = {"capability": "test_service"}
        mock_tool.fn._mesh_agent_dependencies = ["time_service"]

        mock_fastmcp_server._tool_manager._tools = {"test_tool": mock_tool}

        with patch(
            "_mcp_mesh.shared.host_resolver.HostResolver.get_external_host",
            return_value="test-service.default.svc.cluster.local",
        ):
            # Initialize wrapper
            wrapper = HttpMcpWrapper(mock_fastmcp_server)

            # Verify initialization
            assert wrapper._mcp_app == mock_fastmcp_app
            assert wrapper._lifespan == mock_lifespan

            # Setup wrapper
            await wrapper.setup()

            # Test utility methods
            capabilities = wrapper._get_capabilities()
            dependencies = wrapper._get_dependencies()
            endpoint = wrapper.get_endpoint(port=9090)

            # Verify results
            assert capabilities == ["test_service"]
            assert dependencies == ["time_service"]
            assert endpoint == "http://test-service.default.svc.cluster.local:9090"

    def test_wrapper_robustness_with_missing_attributes(self):
        """Test wrapper handles FastMCP servers with missing expected attributes."""
        # Create minimal mock without expected attributes
        mock_fastmcp_server = MagicMock()

        # Remove all expected attributes
        del mock_fastmcp_server.http_app
        del mock_fastmcp_server._tool_manager

        # Should initialize without error
        wrapper = HttpMcpWrapper(mock_fastmcp_server)

        # Should handle missing attributes gracefully
        capabilities = wrapper._get_capabilities()
        dependencies = wrapper._get_dependencies()

        assert capabilities == []
        assert dependencies == []
