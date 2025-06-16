"""
Test that MeshToolProcessor correctly uses @mesh.agent configuration values.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

import mesh
from mcp_mesh import DecoratorRegistry
from mcp_mesh.runtime.processor import MeshDecoratorProcessor
from mcp_mesh.runtime.registry_client import RegistryClient
from mcp_mesh.runtime.shared.types import MockHTTPResponse


class TestMeshDecoratorProcessorAgentConfig:
    """Test MeshDecoratorProcessor using agent configuration."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        client = Mock(spec=RegistryClient)

        # Mock the post method to return MockHTTPResponse like the real client
        mock_response = MockHTTPResponse(
            {"status": "success", "dependencies_resolved": {}}, 201
        )

        client.post = AsyncMock(return_value=mock_response)
        return client

    @pytest.fixture
    def processor(self, mock_registry_client):
        """Create MeshDecoratorProcessor with mock client."""
        return MeshDecoratorProcessor(mock_registry_client)

    @pytest.mark.asyncio
    async def test_processor_uses_agent_config_values(self, processor):
        """Test that processor uses agent config values in registration."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock HTTP wrapper setup to avoid actual server startup
        with patch.object(
            processor, "_setup_http_wrapper_for_tools", return_value=None
        ):
            # Define agent with custom config - disable HTTP for simplicity in tests
            @mesh.agent(
                name="custom-agent",
                version="2.1.0",
                http_host="127.0.0.1",  # Use localhost to avoid bind issues
                http_port=0,  # Use 0 for auto-assign to avoid port conflicts
                enable_http=False,  # Disable HTTP for test simplicity
                namespace="production",
                auto_run=False,  # Disable auto-run for tests
            )
            class CustomAgent:
                pass

            @mesh.tool(capability="test_capability")
            def test_function():
                return "test"

            # Get registered tools
            tools = DecoratorRegistry.get_mesh_tools()

            # Process tools
            results = await processor.process_tools(tools)

            # Verify registration call was made
            processor.registry_client.post.assert_called_once()

            # Get the actual registration data from the post call
            call_args = processor.registry_client.post.call_args
            registration_data = call_args.kwargs["json"]  # JSON payload

            # Verify agent config values are used
            assert registration_data["version"] == "2.1.0"
            assert registration_data["http_host"] == "127.0.0.1"
            assert registration_data["http_port"] == 0
            assert registration_data["namespace"] == "production"

    @pytest.mark.asyncio
    async def test_processor_uses_defaults_when_no_agent_config(self, processor):
        """Test that processor uses defaults when no @mesh.agent is present."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock HTTP wrapper setup to avoid actual server startup
        with patch.object(
            processor, "_setup_http_wrapper_for_tools", return_value=None
        ):

            @mesh.tool(capability="standalone_capability")
            def standalone_function():
                return "standalone"

            # Get registered tools
            tools = DecoratorRegistry.get_mesh_tools()

            # Process tools
            results = await processor.process_tools(tools)

            # Verify registration call was made
            processor.registry_client.post.assert_called_once()

            # Get the actual registration data
            call_args = processor.registry_client.post.call_args
            registration_data = call_args.kwargs["json"]

            # Verify default values are used
            assert registration_data["version"] == "1.0.0"
            assert registration_data["http_host"] == "0.0.0.0"
            assert registration_data["http_port"] == 0
            assert registration_data["namespace"] == "default"

    @pytest.mark.asyncio
    async def test_processor_uses_agent_config_with_environment_variables(
        self, processor
    ):
        """Test that processor uses agent config values that respect environment variables."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock HTTP wrapper setup to avoid actual server startup
        with patch.object(
            processor, "_setup_http_wrapper_for_tools", return_value=None
        ):
            # Test with environment variables
            with patch.dict(
                "os.environ",
                {
                    "MCP_MESH_HTTP_HOST": "env-host.com",
                    "MCP_MESH_HTTP_PORT": "7777",
                    "MCP_MESH_ENABLE_HTTP": "false",
                    "MCP_MESH_NAMESPACE": "env-namespace",
                },
            ):

                @mesh.agent(
                    name="env-agent",
                    http_host="decorator-host.com",
                    http_port=8888,
                    enable_http=True,
                    namespace="decorator-namespace",
                    auto_run=False,  # Disable auto-run for tests
                )
                class EnvAgent:
                    pass

                @mesh.tool(capability="env_capability")
                def env_function():
                    return "env test"

                # Get registered tools
                tools = DecoratorRegistry.get_mesh_tools()

                # Process tools
                results = await processor.process_tools(tools)

                # Verify registration call was made
                processor.registry_client.post.assert_called_once()

                # Get the actual registration data
                call_args = processor.registry_client.post.call_args
                registration_data = call_args.kwargs["json"]

                # Verify environment variables take precedence
                assert registration_data["http_host"] == "env-host.com"
                assert registration_data["http_port"] == 7777
                assert registration_data["namespace"] == "env-namespace"

    @pytest.mark.asyncio
    async def test_processor_enable_http_affects_wrapper_setup(self, processor):
        """Test that enable_http setting affects HTTP wrapper setup."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock the HTTP wrapper setup method
        with patch.object(
            processor, "_setup_http_wrapper_for_tools", return_value=None
        ) as mock_http_setup:
            # Test with enable_http=True
            @mesh.agent(
                name="http-agent",
                enable_http=True,
                auto_run=False,  # Disable auto-run for tests
            )
            class HttpAgent:
                pass

            @mesh.tool(capability="http_capability")
            def http_function():
                return "http test"

            # Get registered tools
            tools = DecoratorRegistry.get_mesh_tools()

            # Process tools
            results = await processor.process_tools(tools)

            # Verify HTTP wrapper setup was called
            mock_http_setup.assert_called_once()

    @pytest.mark.asyncio
    async def test_processor_enable_http_false_skips_wrapper_setup(self, processor):
        """Test that enable_http=False skips HTTP wrapper setup."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock the HTTP wrapper setup method
        with patch.object(
            processor, "_setup_http_wrapper_for_tools", return_value=None
        ) as mock_http_setup:
            # Test with enable_http=False
            @mesh.agent(
                name="no-http-agent",
                enable_http=False,
                auto_run=False,  # Disable auto-run for tests
            )
            class NoHttpAgent:
                pass

            @mesh.tool(capability="no_http_capability")
            def no_http_function():
                return "no http test"

            # Get registered tools
            tools = DecoratorRegistry.get_mesh_tools()

            # Process tools
            results = await processor.process_tools(tools)

            # Verify HTTP wrapper setup was NOT called
            mock_http_setup.assert_not_called()
