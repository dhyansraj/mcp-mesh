"""
Unit tests for FastAPIServerSetupStep pipeline step.

Tests the FastAPI server setup logic including configuration resolution,
app creation, K8s endpoints, and MCP wrapper integration without starting
actual servers.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the classes under test
from _mcp_mesh.pipeline.mcp_startup.fastapiserver_setup import FastAPIServerSetupStep
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus


class TestFastAPIServerSetupStep:
    """Test the FastAPIServerSetupStep class initialization and basic properties."""

    def test_initialization(self):
        """Test FastAPIServerSetupStep initialization."""
        step = FastAPIServerSetupStep()

        assert step.name == "fastapi-server-setup"
        assert step.required is False  # Optional - may not have FastMCP instances
        assert (
            step.description
            == "Prepare FastAPI app with K8s endpoints and mount FastMCP servers"
        )

    def test_inheritance(self):
        """Test FastAPIServerSetupStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = FastAPIServerSetupStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = FastAPIServerSetupStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)

    def test_helper_methods_exist(self):
        """Test helper methods exist."""
        step = FastAPIServerSetupStep()
        helper_methods = [
            "_is_http_enabled",
            "_resolve_binding_config",
            "_resolve_advertisement_config",
            "_create_fastapi_app",
            "_add_k8s_endpoints",
            "_integrate_mcp_wrapper",
        ]

        for method_name in helper_methods:
            assert hasattr(step, method_name)
            assert callable(getattr(step, method_name))


class TestConfigurationResolution:
    """Test configuration resolution methods."""

    @pytest.fixture
    def step(self):
        """Create a FastAPIServerSetupStep instance."""
        return FastAPIServerSetupStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {
            "name": "test-agent",
            "version": "1.0.0",
            "http_host": "localhost",
            "http_port": 8080,
        }

    # Note: _is_http_enabled tests removed - HTTP is now always enabled

    @patch.dict("os.environ", {}, clear=True)
    def test_resolve_binding_config_defaults(self, step, mock_agent_config):
        """Test _resolve_binding_config with defaults."""
        result = step._resolve_binding_config(mock_agent_config)

        assert (
            result["bind_host"] == "0.0.0.0"
        )  # Always uses HostResolver.get_binding_host()
        assert result["bind_port"] == 8080  # From agent_config

    @patch.dict("os.environ", {"MCP_MESH_HTTP_PORT": "9000"})
    def test_resolve_binding_config_with_env_port(self, step, mock_agent_config):
        """Test _resolve_binding_config with environment port override."""
        result = step._resolve_binding_config(mock_agent_config)

        assert (
            result["bind_host"] == "0.0.0.0"
        )  # Always uses HostResolver.get_binding_host()
        assert result["bind_port"] == 9000  # From environment

    @patch.dict("os.environ", {}, clear=True)
    @patch(
        "_mcp_mesh.shared.host_resolver.HostResolver.get_external_host",
        return_value="192.168.1.100",
    )
    def test_resolve_advertisement_config_defaults(
        self, mock_get_external_host, step, mock_agent_config
    ):
        """Test _resolve_advertisement_config with defaults."""
        result = step._resolve_advertisement_config(mock_agent_config)

        assert result["external_host"] == "192.168.1.100"
        assert result["external_endpoint"] is None

    @patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "my-service.cluster.local"})
    def test_resolve_advertisement_config_with_host_env(self, step, mock_agent_config):
        """Test _resolve_advertisement_config with MCP_MESH_HTTP_HOST."""
        result = step._resolve_advertisement_config(mock_agent_config)

        assert result["external_host"] == "my-service.cluster.local"

    @patch.dict("os.environ", {}, clear=True)
    @patch(
        "_mcp_mesh.shared.host_resolver.HostResolver.get_external_host",
        return_value="10.0.0.5",
    )
    def test_resolve_advertisement_config_with_custom_host(
        self, mock_get_external_host, step, mock_agent_config
    ):
        """Test _resolve_advertisement_config with custom external host."""
        result = step._resolve_advertisement_config(mock_agent_config)

        assert result["external_host"] == "10.0.0.5"

    @patch.dict("os.environ", {"MCP_MESH_HTTP_ENDPOINT": "https://api.example.com:443"})
    def test_resolve_advertisement_config_with_endpoint_override(
        self, step, mock_agent_config
    ):
        """Test _resolve_advertisement_config with full endpoint override."""
        result = step._resolve_advertisement_config(mock_agent_config)

        assert result["external_endpoint"] == "https://api.example.com:443"


class TestFastAPIAppCreation:
    """Test FastAPI app creation methods."""

    @pytest.fixture
    def step(self):
        """Create a FastAPIServerSetupStep instance."""
        return FastAPIServerSetupStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {
            "name": "test-agent",
            "version": "1.2.3",
            "description": "Test agent description",
        }

    @pytest.fixture
    def mock_fastmcp_servers(self):
        """Mock FastMCP servers."""
        mock_server = MagicMock()
        mock_server.http_app.return_value.lifespan = AsyncMock()
        return {"test_server": mock_server}

    @pytest.fixture
    def mock_heartbeat_config(self):
        """Mock heartbeat configuration."""
        return {"interval": 30, "heartbeat_task_fn": AsyncMock()}

    @patch("fastapi.FastAPI")
    def test_create_fastapi_app_minimal(
        self, mock_fastapi_class, step, mock_agent_config
    ):
        """Test _create_fastapi_app with minimal configuration."""
        mock_app = MagicMock()
        mock_fastapi_class.return_value = mock_app

        result = step._create_fastapi_app(mock_agent_config, {})

        assert result == mock_app
        mock_fastapi_class.assert_called_once()

        # Check app configuration
        call_kwargs = mock_fastapi_class.call_args[1]
        assert call_kwargs["title"] == "MCP Mesh Agent: test-agent"
        assert call_kwargs["description"] == "Test agent description"
        assert call_kwargs["version"] == "1.2.3"
        assert call_kwargs["docs_url"] == "/docs"
        assert call_kwargs["redoc_url"] == "/redoc"
        # Should have graceful shutdown lifespan
        assert call_kwargs["lifespan"] is not None
        assert callable(call_kwargs["lifespan"])

    @patch("fastapi.FastAPI")
    def test_create_fastapi_app_with_heartbeat(
        self, mock_fastapi_class, step, mock_agent_config, mock_heartbeat_config
    ):
        """Test _create_fastapi_app with heartbeat configuration."""
        mock_app = MagicMock()
        mock_fastapi_class.return_value = mock_app

        result = step._create_fastapi_app(mock_agent_config, {}, mock_heartbeat_config)

        assert result == mock_app

        # Check lifespan was provided
        call_kwargs = mock_fastapi_class.call_args[1]
        assert call_kwargs["lifespan"] is not None

    @patch("fastapi.FastAPI")
    def test_create_fastapi_app_with_fastmcp_servers(
        self, mock_fastapi_class, step, mock_agent_config, mock_fastmcp_servers
    ):
        """Test _create_fastapi_app with FastMCP servers."""
        mock_app = MagicMock()
        mock_fastapi_class.return_value = mock_app

        # Create mock mcp_wrappers with lifespan
        mock_wrapper = MagicMock()
        mock_wrapper._mcp_app.lifespan = MagicMock()
        mock_mcp_wrappers = {
            "test_server": {
                "wrapper": mock_wrapper,
                "server_instance": mock_fastmcp_servers["test_server"],
            }
        }

        result = step._create_fastapi_app(
            mock_agent_config, mock_fastmcp_servers, None, mock_mcp_wrappers
        )

        assert result == mock_app

        # Check lifespan was provided for FastMCP servers
        call_kwargs = mock_fastapi_class.call_args[1]
        assert call_kwargs["lifespan"] is not None

    @patch("fastapi.FastAPI")
    def test_create_fastapi_app_import_error(
        self, mock_fastapi_class, step, mock_agent_config
    ):
        """Test _create_fastapi_app handles FastAPI import error."""
        mock_fastapi_class.side_effect = ImportError("FastAPI not found")

        with pytest.raises(Exception, match="FastAPI not available"):
            step._create_fastapi_app(mock_agent_config, {})


class TestK8sEndpoints:
    """Test Kubernetes health endpoints."""

    @pytest.fixture
    def step(self):
        """Create a FastAPIServerSetupStep instance."""
        return FastAPIServerSetupStep()

    @pytest.fixture
    def mock_app(self):
        """Mock FastAPI app."""
        return MagicMock()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {"name": "test-agent", "version": "1.0.0"}

    @pytest.mark.asyncio
    async def test_add_k8s_endpoints(self, step, mock_app, mock_agent_config):
        """Test _add_k8s_endpoints stores health check result in DecoratorRegistry."""
        from unittest.mock import AsyncMock, patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        with patch.object(DecoratorRegistry, "store_health_check_result") as mock_store:
            await step._add_k8s_endpoints(mock_app, mock_agent_config, {}, {})

            # Verify health check result was stored
            mock_store.assert_called_once()
            stored_result = mock_store.call_args[0][0]
            assert stored_result["status"] == "healthy"
            assert stored_result["agent"] == "test-agent"

    @pytest.mark.asyncio
    async def test_health_endpoint_response(self, step, mock_app, mock_agent_config):
        """Test health endpoint response structure with custom health check."""
        from unittest.mock import AsyncMock, patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        async def custom_health_check():
            return {"status": "healthy", "checks": {"test": True}, "errors": []}

        mock_agent_config["health_check"] = custom_health_check

        with patch.object(DecoratorRegistry, "store_health_check_result") as mock_store:
            await step._add_k8s_endpoints(mock_app, mock_agent_config, {}, {})

            # Verify custom health check was executed and result stored
            mock_store.assert_called_once()
            stored_result = mock_store.call_args[0][0]
            assert stored_result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_ready_endpoint_response(self, step, mock_app, mock_agent_config):
        """Test that _add_k8s_endpoints handles default health status."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        # No custom health check - should return default healthy
        with patch.object(DecoratorRegistry, "store_health_check_result") as mock_store:
            await step._add_k8s_endpoints(mock_app, mock_agent_config, {}, {})

            mock_store.assert_called_once()
            stored_result = mock_store.call_args[0][0]
            assert "status" in stored_result
            assert "timestamp" in stored_result

    @pytest.mark.asyncio
    async def test_livez_endpoint_response(self, step, mock_app, mock_agent_config):
        """Test that health check respects TTL configuration."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        mock_agent_config["health_check_ttl"] = 30

        with patch.object(DecoratorRegistry, "store_health_check_result") as mock_store:
            await step._add_k8s_endpoints(mock_app, mock_agent_config, {}, {})

            # Should execute and store result
            mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_endpoint_response(self, step, mock_app, mock_agent_config):
        """Test that errors in health check are handled gracefully."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        async def failing_health_check():
            raise Exception("Health check failed")

        mock_agent_config["health_check"] = failing_health_check

        with patch.object(DecoratorRegistry, "store_health_check_result") as mock_store:
            await step._add_k8s_endpoints(mock_app, mock_agent_config, {}, {})

            # Should still store a result (degraded status)
            mock_store.assert_called_once()
            stored_result = mock_store.call_args[0][0]
            assert "status" in stored_result


class TestExecuteScenarios:
    """Test main execute method scenarios."""

    @pytest.fixture
    def step(self):
        """Create a FastAPIServerSetupStep instance."""
        return FastAPIServerSetupStep()

    @pytest.fixture
    def mock_context_minimal(self):
        """Mock minimal context."""
        return {
            "agent_config": {"name": "test-agent", "http_port": 8080},
            "fastmcp_servers": {},
            "heartbeat_config": None,
        }

    @pytest.fixture
    def mock_context_with_servers(self):
        """Mock context with FastMCP servers."""
        mock_server = MagicMock()
        return {
            "agent_config": {"name": "test-agent", "http_port": 8080},
            "fastmcp_servers": {"test_server": mock_server},
            "heartbeat_config": {"interval": 30},
        }

    @pytest.mark.asyncio
    async def test_execute_http_disabled(self, step, mock_context_minimal):
        """Test execute when HTTP transport is disabled."""
        with patch.object(step, "_is_http_enabled", return_value=False):
            result = await step.execute(mock_context_minimal)

            assert result.status == PipelineStatus.SKIPPED
            assert result.message == "HTTP transport disabled"

    @pytest.mark.asyncio
    @patch("fastapi.FastAPI")
    async def test_execute_no_fastmcp_servers(
        self, mock_fastapi, step, mock_context_minimal
    ):
        """Test execute with no FastMCP servers."""
        mock_app = MagicMock()
        mock_fastapi.return_value = mock_app

        with (
            patch.object(step, "_is_http_enabled", return_value=True),
            patch.object(
                step,
                "_resolve_binding_config",
                return_value={"bind_host": "0.0.0.0", "bind_port": 8080},
            ),
            patch.object(
                step,
                "_resolve_advertisement_config",
                return_value={"external_host": "localhost", "external_endpoint": None},
            ),
        ):

            result = await step.execute(mock_context_minimal)

            assert result.status == PipelineStatus.SUCCESS
            assert "FastAPI app prepared" in result.message

            # Check context was populated
            assert result.context.get("fastapi_app") == mock_app
            assert result.context.get("mcp_wrappers") == {}
            assert "fastapi_binding_config" in result.context
            assert "fastapi_advertisement_config" in result.context

    @pytest.mark.asyncio
    @patch("fastapi.FastAPI")
    @patch("_mcp_mesh.engine.http_wrapper.HttpMcpWrapper")
    async def test_execute_with_fastmcp_servers(
        self, mock_wrapper_class, mock_fastapi, step, mock_context_with_servers
    ):
        """Test execute with FastMCP servers."""
        mock_app = MagicMock()
        mock_fastapi.return_value = mock_app

        mock_wrapper = MagicMock()
        mock_wrapper.setup = AsyncMock()
        mock_wrapper_class.return_value = mock_wrapper

        with (
            patch.object(step, "_is_http_enabled", return_value=True),
            patch.object(
                step,
                "_resolve_binding_config",
                return_value={"bind_host": "0.0.0.0", "bind_port": 8080},
            ),
            patch.object(
                step,
                "_resolve_advertisement_config",
                return_value={"external_host": "localhost", "external_endpoint": None},
            ),
            patch.object(step, "_integrate_mcp_wrapper") as mock_integrate,
        ):

            result = await step.execute(mock_context_with_servers)

            assert result.status == PipelineStatus.SUCCESS

            # Check wrapper was created and setup
            mock_wrapper_class.assert_called_once()
            mock_wrapper.setup.assert_called_once()
            mock_integrate.assert_called_once()

            # Check mcp_wrappers in context
            mcp_wrappers = result.context.get("mcp_wrappers")
            assert "test_server" in mcp_wrappers
            assert mcp_wrappers["test_server"]["wrapper"] == mock_wrapper

    @pytest.mark.asyncio
    async def test_execute_general_exception(self, step, mock_context_minimal):
        """Test execute with general exception."""
        with patch.object(
            step, "_is_http_enabled", side_effect=Exception("General error")
        ):
            result = await step.execute(mock_context_minimal)

            assert result.status == PipelineStatus.FAILED
            assert "FastAPI server setup failed: General error" in result.message
            assert "General error" in result.errors


class TestMCPIntegration:
    """Test MCP wrapper integration methods."""

    @pytest.fixture
    def step(self):
        """Create a FastAPIServerSetupStep instance."""
        return FastAPIServerSetupStep()

    @pytest.fixture
    def mock_app(self):
        """Mock main FastAPI app."""
        return MagicMock()

    @pytest.fixture
    def mock_mcp_wrapper(self):
        """Mock MCP wrapper with FastMCP app."""
        wrapper = MagicMock()

        # Mock FastMCP app for mounting
        mock_fastmcp_app = MagicMock()
        wrapper._mcp_app = mock_fastmcp_app

        return wrapper

    def test_integrate_mcp_wrapper_success(self, step, mock_app, mock_mcp_wrapper):
        """Test _integrate_mcp_wrapper successfully mounts FastMCP app."""
        step._integrate_mcp_wrapper(mock_app, mock_mcp_wrapper, "test_server")

        # Check FastMCP app was mounted at root (since FastMCP provides /mcp routes)
        mock_app.mount.assert_called_once_with("", mock_mcp_wrapper._mcp_app)

    def test_integrate_mcp_wrapper_no_fastmcp_app(self, step, mock_app):
        """Test _integrate_mcp_wrapper when no FastMCP app available."""
        wrapper = MagicMock()
        wrapper._mcp_app = None  # No FastMCP app

        step._integrate_mcp_wrapper(mock_app, wrapper, "test_server")

        # Should not mount anything
        mock_app.mount.assert_not_called()

    def test_integrate_mcp_wrapper_exception(self, step, mock_app):
        """Test _integrate_mcp_wrapper handles exceptions."""
        wrapper = MagicMock()
        # Simulate exception by making _mcp_app access raise an error
        del wrapper._mcp_app

        # Should raise AttributeError since _mcp_app was deleted
        with pytest.raises(AttributeError):
            step._integrate_mcp_wrapper(mock_app, wrapper, "test_server")
