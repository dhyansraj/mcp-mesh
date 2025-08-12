"""
Unit tests for RegistryConnectionStep pipeline step.

Tests the registry connection logic including configuration resolution,
client creation, connection reuse, and error handling without making
actual network connections.
"""

import os
from typing import Any, Dict
from unittest.mock import MagicMock, call, patch

import pytest

# Import the classes under test
from _mcp_mesh.pipeline.mcp_heartbeat.registry_connection import RegistryConnectionStep
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus


class TestRegistryConnectionStep:
    """Test the RegistryConnectionStep class initialization and basic properties."""

    def test_initialization(self):
        """Test RegistryConnectionStep initialization."""
        step = RegistryConnectionStep()

        assert step.name == "registry-connection"
        assert step.required is True  # Registry connection is required
        assert step.description == "Connect to mesh registry service"

    def test_inheritance(self):
        """Test RegistryConnectionStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = RegistryConnectionStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = RegistryConnectionStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)

    def test_helper_methods_exist(self):
        """Test helper methods exist."""
        step = RegistryConnectionStep()
        helper_methods = ["_get_registry_url"]

        for method_name in helper_methods:
            assert hasattr(step, method_name)
            assert callable(getattr(step, method_name))


class TestRegistryUrlResolution:
    """Test registry URL resolution methods."""

    @pytest.fixture
    def step(self):
        """Create a RegistryConnectionStep instance."""
        return RegistryConnectionStep()

    @patch.dict("os.environ", {}, clear=True)
    def test_get_registry_url_default(self, step):
        """Test _get_registry_url returns default when no environment variable."""
        result = step._get_registry_url()
        assert result == "http://localhost:8000"

    @patch.dict(
        "os.environ", {"MCP_MESH_REGISTRY_URL": "http://registry.example.com:8080"}
    )
    def test_get_registry_url_from_env(self, step):
        """Test _get_registry_url returns environment variable value."""
        result = step._get_registry_url()
        assert result == "http://registry.example.com:8080"

    @patch.dict(
        "os.environ", {"MCP_MESH_REGISTRY_URL": "https://mesh-registry.cluster.local"}
    )
    def test_get_registry_url_https(self, step):
        """Test _get_registry_url with HTTPS URL."""
        result = step._get_registry_url()
        assert result == "https://mesh-registry.cluster.local"

    @patch.dict("os.environ", {"MCP_MESH_REGISTRY_URL": "http://10.0.0.5:9000"})
    def test_get_registry_url_ip_address(self, step):
        """Test _get_registry_url with IP address."""
        result = step._get_registry_url()
        assert result == "http://10.0.0.5:9000"


class TestConnectionReuse:
    """Test existing connection reuse logic."""

    @pytest.fixture
    def step(self):
        """Create a RegistryConnectionStep instance."""
        return RegistryConnectionStep()

    @pytest.fixture
    def mock_existing_wrapper(self):
        """Mock existing registry wrapper."""
        return MagicMock()

    @pytest.fixture
    def mock_context_with_existing_wrapper(self, mock_existing_wrapper):
        """Mock context with existing registry wrapper."""
        return {"registry_wrapper": mock_existing_wrapper, "other_data": "test"}

    @pytest.fixture
    def mock_context_empty(self):
        """Mock empty context."""
        return {}

    @pytest.mark.asyncio
    async def test_execute_reuses_existing_wrapper(
        self, step, mock_context_with_existing_wrapper, mock_existing_wrapper
    ):
        """Test execute reuses existing registry wrapper."""
        result = await step.execute(mock_context_with_existing_wrapper)

        assert result.status == PipelineStatus.SUCCESS
        assert result.message == "Reusing existing registry connection"
        assert result.context.get("registry_wrapper") == mock_existing_wrapper

    @pytest.mark.asyncio
    async def test_execute_existing_wrapper_no_new_connection(
        self, step, mock_context_with_existing_wrapper
    ):
        """Test execute with existing wrapper doesn't create new connection."""
        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient"
        ) as mock_api_client:
            result = await step.execute(mock_context_with_existing_wrapper)

            # Should not create new API client
            mock_api_client.assert_not_called()
            assert result.status == PipelineStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_existing_wrapper_preserves_other_context(
        self, step, mock_existing_wrapper
    ):
        """Test execute with existing wrapper preserves other context data."""
        context = {
            "registry_wrapper": mock_existing_wrapper,
            "other_data": "preserved",
            "agent_id": "test-agent",
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        # Should preserve original context and only add registry_wrapper
        assert result.context.get("registry_wrapper") == mock_existing_wrapper
        # Other context should not be modified by the step
        assert context.get("other_data") == "preserved"
        assert context.get("agent_id") == "test-agent"


class TestNewConnectionCreation:
    """Test new registry connection creation."""

    @pytest.fixture
    def step(self):
        """Create a RegistryConnectionStep instance."""
        return RegistryConnectionStep()

    @pytest.fixture
    def mock_context_empty(self):
        """Mock empty context."""
        return {}

    @pytest.fixture
    def mock_api_client(self):
        """Mock API client."""
        return MagicMock()

    @pytest.fixture
    def mock_configuration(self):
        """Mock Configuration class."""
        return MagicMock()

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper."""
        return MagicMock()

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper")
    @patch.dict("os.environ", {"MCP_MESH_REGISTRY_URL": "http://test-registry:8000"})
    async def test_execute_creates_new_connection(
        self,
        mock_wrapper_class,
        mock_api_client_class,
        mock_config_class,
        step,
        mock_context_empty,
    ):
        """Test execute creates new connection when none exists."""
        mock_config = MagicMock()
        mock_api_client = MagicMock()
        mock_wrapper = MagicMock()

        mock_config_class.return_value = mock_config
        mock_api_client_class.return_value = mock_api_client
        mock_wrapper_class.return_value = mock_wrapper

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.SUCCESS
        assert result.message == "Connected to registry at http://test-registry:8000"

        # Verify configuration was created with correct host
        mock_config_class.assert_called_once_with(host="http://test-registry:8000")

        # Verify API client was created with configuration
        mock_api_client_class.assert_called_once_with(mock_config)

        # Verify wrapper was created with API client
        mock_wrapper_class.assert_called_once_with(mock_api_client)

        # Verify context was populated
        assert result.context.get("registry_url") == "http://test-registry:8000"
        assert result.context.get("registry_client") == mock_api_client
        assert result.context.get("registry_wrapper") == mock_wrapper

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper")
    @patch.dict("os.environ", {}, clear=True)
    async def test_execute_creates_connection_with_default_url(
        self,
        mock_wrapper_class,
        mock_api_client_class,
        mock_config_class,
        step,
        mock_context_empty,
    ):
        """Test execute creates connection with default URL."""
        mock_config = MagicMock()
        mock_api_client = MagicMock()
        mock_wrapper = MagicMock()

        mock_config_class.return_value = mock_config
        mock_api_client_class.return_value = mock_api_client
        mock_wrapper_class.return_value = mock_wrapper

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.SUCCESS
        assert result.message == "Connected to registry at http://localhost:8000"

        # Verify configuration was created with default host
        mock_config_class.assert_called_once_with(host="http://localhost:8000")

        # Verify context has default URL
        assert result.context.get("registry_url") == "http://localhost:8000"

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper")
    async def test_execute_connection_creation_order(
        self,
        mock_wrapper_class,
        mock_api_client_class,
        mock_config_class,
        step,
        mock_context_empty,
    ):
        """Test execute creates components in correct order."""
        mock_config = MagicMock()
        mock_api_client = MagicMock()
        mock_wrapper = MagicMock()

        mock_config_class.return_value = mock_config
        mock_api_client_class.return_value = mock_api_client
        mock_wrapper_class.return_value = mock_wrapper

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.SUCCESS

        # Verify creation order using call order
        expected_calls = [
            call(host="http://localhost:8000"),  # Configuration
        ]
        mock_config_class.assert_has_calls(expected_calls)

        # API client should be created after configuration
        mock_api_client_class.assert_called_once_with(mock_config)

        # Wrapper should be created after API client
        mock_wrapper_class.assert_called_once_with(mock_api_client)


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.fixture
    def step(self):
        """Create a RegistryConnectionStep instance."""
        return RegistryConnectionStep()

    @pytest.fixture
    def mock_context_empty(self):
        """Mock empty context."""
        return {}

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    async def test_execute_configuration_error(
        self, mock_config_class, step, mock_context_empty
    ):
        """Test execute handles Configuration creation error."""
        mock_config_class.side_effect = Exception("Configuration error")

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.FAILED
        assert "Registry connection failed: Configuration error" in result.message
        assert "Configuration error" in result.errors

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient")
    async def test_execute_api_client_error(
        self, mock_api_client_class, mock_config_class, step, mock_context_empty
    ):
        """Test execute handles ApiClient creation error."""
        mock_config = MagicMock()
        mock_config_class.return_value = mock_config
        mock_api_client_class.side_effect = Exception("API client error")

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.FAILED
        assert "Registry connection failed: API client error" in result.message
        assert "API client error" in result.errors

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper")
    async def test_execute_wrapper_error(
        self,
        mock_wrapper_class,
        mock_api_client_class,
        mock_config_class,
        step,
        mock_context_empty,
    ):
        """Test execute handles RegistryClientWrapper creation error."""
        mock_config = MagicMock()
        mock_api_client = MagicMock()

        mock_config_class.return_value = mock_config
        mock_api_client_class.return_value = mock_api_client
        mock_wrapper_class.side_effect = Exception("Wrapper creation error")

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.FAILED
        assert "Registry connection failed: Wrapper creation error" in result.message
        assert "Wrapper creation error" in result.errors

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.os.getenv")
    async def test_execute_url_resolution_error(
        self, mock_getenv, step, mock_context_empty
    ):
        """Test execute handles URL resolution error."""
        mock_getenv.side_effect = Exception("Environment variable error")

        result = await step.execute(mock_context_empty)

        assert result.status == PipelineStatus.FAILED
        assert (
            "Registry connection failed: Environment variable error" in result.message
        )
        assert "Environment variable error" in result.errors

    @pytest.mark.asyncio
    async def test_execute_error_does_not_modify_context(self, step):
        """Test execute with error doesn't add partial context."""
        context = {"existing": "data"}

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration",
            side_effect=Exception("Test error"),
        ):
            result = await step.execute(context)

            assert result.status == PipelineStatus.FAILED
            # Should not have added any registry context on error
            assert "registry_url" not in result.context
            assert "registry_client" not in result.context
            assert "registry_wrapper" not in result.context
            # Original context should remain unchanged
            assert context.get("existing") == "data"


class TestLogging:
    """Test logging behavior."""

    @pytest.fixture
    def step(self):
        """Create a RegistryConnectionStep instance."""
        return RegistryConnectionStep()

    @pytest.fixture
    def mock_existing_wrapper(self):
        """Mock existing registry wrapper."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_execute_existing_wrapper_logging(
        self, step, mock_existing_wrapper, caplog
    ):
        """Test execute with existing wrapper logs reuse message."""
        import logging

        context = {"registry_wrapper": mock_existing_wrapper}

        # Set log level to capture DEBUG messages for the specific logger
        caplog.set_level(logging.DEBUG)
        step.logger.setLevel(logging.DEBUG)

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert "Reusing existing registry connection" in caplog.text

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient")
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper")
    @patch.dict("os.environ", {"MCP_MESH_REGISTRY_URL": "http://test-registry:8000"})
    async def test_execute_new_connection_logging(
        self, mock_wrapper_class, mock_api_client_class, mock_config_class, step, caplog
    ):
        """Test execute with new connection logs success message."""
        import logging

        mock_config_class.return_value = MagicMock()
        mock_api_client_class.return_value = MagicMock()
        mock_wrapper_class.return_value = MagicMock()

        # Set log level to capture INFO messages
        caplog.set_level(logging.INFO)

        result = await step.execute({})

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "Registry connection established: http://test-registry:8000" in caplog.text
        )

    @pytest.mark.asyncio
    @patch("_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration")
    async def test_execute_error_logging(self, mock_config_class, step, caplog):
        """Test execute error logging."""
        import logging

        mock_config_class.side_effect = Exception("Test connection error")

        # Set log level to capture ERROR messages
        caplog.set_level(logging.ERROR)

        result = await step.execute({})

        assert result.status == PipelineStatus.FAILED
        assert "Registry connection failed: Test connection error" in caplog.text


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def step(self):
        """Create a RegistryConnectionStep instance."""
        return RegistryConnectionStep()

    @pytest.mark.asyncio
    async def test_execute_none_registry_wrapper_in_context(self, step):
        """Test execute when registry_wrapper is None in context."""
        context = {"registry_wrapper": None}

        with (
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration"
            ) as mock_config_class,
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient"
            ) as mock_api_client_class,
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper"
            ) as mock_wrapper_class,
        ):

            mock_config_class.return_value = MagicMock()
            mock_api_client_class.return_value = MagicMock()
            mock_wrapper_class.return_value = MagicMock()

            result = await step.execute(context)

            # Should create new connection since existing wrapper is None
            assert result.status == PipelineStatus.SUCCESS
            assert "Connected to registry" in result.message
            mock_config_class.assert_called_once()

    @pytest.mark.asyncio
    @patch.dict("os.environ", {"MCP_MESH_REGISTRY_URL": ""})
    async def test_execute_empty_registry_url(self, step):
        """Test execute with empty registry URL environment variable."""
        context = {}

        with (
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration"
            ) as mock_config_class,
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient"
            ) as mock_api_client_class,
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper"
            ) as mock_wrapper_class,
        ):

            mock_config_class.return_value = MagicMock()
            mock_api_client_class.return_value = MagicMock()
            mock_wrapper_class.return_value = MagicMock()

            result = await step.execute(context)

            # Should use empty string when environment variable is set to empty
            assert result.status == PipelineStatus.SUCCESS
            mock_config_class.assert_called_once_with(host="")

    @pytest.mark.asyncio
    async def test_execute_preserves_context_on_success(self, step):
        """Test execute preserves existing context on success."""
        context = {
            "agent_id": "test-agent",
            "other_data": {"key": "value"},
            "numbers": [1, 2, 3],
        }

        with (
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.Configuration"
            ) as mock_config_class,
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.ApiClient"
            ) as mock_api_client_class,
            patch(
                "_mcp_mesh.pipeline.mcp_heartbeat.registry_connection.RegistryClientWrapper"
            ) as mock_wrapper_class,
        ):

            mock_config_class.return_value = MagicMock()
            mock_api_client_class.return_value = MagicMock()
            mock_wrapper_class.return_value = MagicMock()

            result = await step.execute(context)

            assert result.status == PipelineStatus.SUCCESS
            # Original context should remain unchanged
            assert context.get("agent_id") == "test-agent"
            assert context.get("other_data") == {"key": "value"}
            assert context.get("numbers") == [1, 2, 3]
            # New registry context should be added to result
            assert "registry_wrapper" in result.context
            assert "registry_client" in result.context
            assert "registry_url" in result.context
