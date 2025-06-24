"""
Test that MeshToolProcessor correctly uses @mesh.agent configuration values.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

import mesh
from mcp_mesh import DecoratorRegistry
from mcp_mesh.engine.processor import DecoratorProcessor
from mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient
from mcp_mesh.shared.support_types import MockHTTPResponse


def create_mock_registry_client(response_override=None):
    """Create a mock registry client with proper agents_api setup."""
    mock_registry = AsyncMock(spec=ApiClient)
    mock_agents_api = AsyncMock()
    mock_registry.agents_api = mock_agents_api

    # Create default response
    from mcp_mesh.generated.mcp_mesh_registry_client.models.mesh_registration_response import (
        MeshRegistrationResponse,
    )

    default_response = MeshRegistrationResponse(
        status="success",
        timestamp="2023-01-01T00:00:00Z",
        message="Agent registered via heartbeat",
        agent_id="test-agent",
    )

    mock_agents_api.send_heartbeat = AsyncMock(
        return_value=response_override or default_response
    )
    return mock_registry, mock_agents_api


def extract_heartbeat_payload(call_args):
    """Extract and properly serialize heartbeat payload from mock call args."""
    heartbeat_registration = call_args[0][
        0
    ]  # First positional argument is MeshAgentRegistration
    if hasattr(heartbeat_registration, "model_dump"):
        # Use mode='json' to properly serialize datetime fields
        return heartbeat_registration.model_dump(mode="json")
    else:
        return heartbeat_registration


class TestDecoratorProcessorAgentConfig:
    """Test DecoratorProcessor using agent configuration."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        mock_registry, mock_agents_api = create_mock_registry_client()
        return mock_registry, mock_agents_api

    @pytest.fixture
    def processor(self, mock_registry_client):
        """Create DecoratorProcessor with mock client."""
        mock_registry, mock_agents_api = mock_registry_client
        with patch(
            "mcp_mesh.engine.processor.ApiClient",
            return_value=mock_registry,
        ):
            processor = DecoratorProcessor("http://mock-registry:8000")
            processor.mesh_tool_processor.agents_api = mock_agents_api
            return processor

    @pytest.mark.asyncio
    async def test_processor_uses_agent_config_values(self, processor):
        """Test that processor uses agent config values in registration."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock HTTP wrapper setup to avoid actual server startup
        with patch.object(
            processor.mesh_tool_processor,
            "_setup_http_wrapper_for_tools",
            return_value=None,
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

            # Process all decorators (tools and agents)
            await processor.process_all_decorators()

            # Wait for asynchronous heartbeat to complete
            import asyncio

            await asyncio.sleep(0.1)

            # Verify heartbeat call was made (registration now via heartbeat)
            processor.registry_client.agents_api.send_heartbeat.assert_called_once()

            # Get the actual heartbeat data from the heartbeat call
            call_args = processor.registry_client.agents_api.send_heartbeat.call_args
            registration_data = extract_heartbeat_payload(call_args)

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
            processor.mesh_tool_processor,
            "_setup_http_wrapper_for_tools",
            return_value=None,
        ):

            @mesh.tool(capability="standalone_capability")
            def standalone_function():
                return "standalone"

            # Process all decorators (tools and agents)
            await processor.process_all_decorators()

            # Wait for asynchronous heartbeat to complete
            import asyncio

            await asyncio.sleep(0.1)

            # Verify heartbeat call was made (registration now via heartbeat)
            processor.registry_client.agents_api.send_heartbeat.assert_called_once()

            # Get the actual heartbeat data
            call_args = processor.registry_client.agents_api.send_heartbeat.call_args
            registration_data = extract_heartbeat_payload(call_args)

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
            processor.mesh_tool_processor,
            "_setup_http_wrapper_for_tools",
            return_value=None,
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

                # Process all decorators (tools and agents)
                await processor.process_all_decorators()

                # Wait for asynchronous heartbeat to complete
                import asyncio

                await asyncio.sleep(0.1)

                # Verify heartbeat call was made (registration now via heartbeat)
                processor.registry_client.agents_api.send_heartbeat.assert_called_once()

                # Get the actual heartbeat data
                call_args = (
                    processor.registry_client.agents_api.send_heartbeat.call_args
                )
                registration_data = extract_heartbeat_payload(call_args)

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
            processor.mesh_tool_processor,
            "_setup_http_wrapper_for_tools",
            return_value=None,
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

            # Process all decorators (tools and agents)
            await processor.process_all_decorators()

            # Verify HTTP wrapper setup was called
            mock_http_setup.assert_called_once()

    @pytest.mark.asyncio
    async def test_processor_enable_http_false_skips_wrapper_setup(self, processor):
        """Test that enable_http=False skips HTTP wrapper setup."""
        # Clear registry
        DecoratorRegistry.clear_all()

        # Mock the HTTP wrapper setup method
        with patch.object(
            processor.mesh_tool_processor,
            "_setup_http_wrapper_for_tools",
            return_value=None,
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

            # Process all decorators (tools and agents)
            await processor.process_all_decorators()

            # Verify HTTP wrapper setup was NOT called
            mock_http_setup.assert_not_called()
