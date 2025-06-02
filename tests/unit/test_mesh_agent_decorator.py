"""
Tests for the @mesh_agent decorator functionality.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from mcp_mesh.decorators import MeshAgentDecorator, mesh_agent


class TestMeshAgentDecorator:
    """Test cases for the MeshAgentDecorator class."""

    def test_decorator_initialization(self):
        """Test that the decorator initializes with correct parameters."""
        capabilities = ["file_read", "file_write"]
        dependencies = ["auth_service", "audit_logger"]

        decorator = MeshAgentDecorator(
            capabilities=capabilities,
            dependencies=dependencies,
            health_interval=60,
            agent_name="test-agent",
        )

        assert decorator.capabilities == capabilities
        assert decorator.dependencies == dependencies
        assert decorator.health_interval == 60
        assert decorator.agent_name == "test-agent"
        assert decorator.fallback_mode is True
        assert decorator.enable_caching is True

    @pytest.mark.asyncio
    async def test_async_function_decoration(self):
        """Test decorator works with async functions."""

        @mesh_agent(capabilities=["test"])
        async def test_function(value: str) -> str:
            return f"processed: {value}"

        # Verify metadata is attached
        assert hasattr(test_function, "_mesh_agent_metadata")
        metadata = test_function._mesh_agent_metadata
        assert metadata["capabilities"] == ["test"]

        # Test function execution
        result = await test_function("hello")
        assert result == "processed: hello"

    def test_sync_function_decoration(self):
        """Test decorator works with sync functions."""

        @mesh_agent(capabilities=["test"])
        def test_function(value: str) -> str:
            return f"processed: {value}"

        # Verify metadata is attached
        assert hasattr(test_function, "_mesh_agent_metadata")
        metadata = test_function._mesh_agent_metadata
        assert metadata["capabilities"] == ["test"]

        # Test function execution
        result = test_function("hello")
        assert result == "processed: hello"

    @pytest.mark.asyncio
    async def test_dependency_injection(self):
        """Test that dependencies are injected into function kwargs."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.return_value = "injected_value"

        decorator = MeshAgentDecorator(
            capabilities=["test"], dependencies=["test_service"], fallback_mode=False
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(value: str, test_service: str = None) -> str:
            return f"{value}:{test_service}"

        result = await test_function("hello")
        assert result == "hello:injected_value"
        mock_registry.get_dependency.assert_called_with("test_service")

    @pytest.mark.asyncio
    async def test_fallback_mode_on_registry_failure(self):
        """Test graceful degradation when registry is unavailable."""
        decorator = MeshAgentDecorator(capabilities=["test"], fallback_mode=True)

        # Mock registry client to raise exception
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.register_agent.side_effect = Exception("Registry unavailable")
            mock_client_class.return_value = mock_client

            @decorator
            async def test_function(value: str) -> str:
                return f"processed: {value}"

            # Function should still work despite registry failure
            result = await test_function("hello")
            assert result == "processed: hello"

    @pytest.mark.asyncio
    async def test_caching_mechanism(self):
        """Test that dependency values are cached properly."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.return_value = "cached_value"

        decorator = MeshAgentDecorator(
            capabilities=["test"],
            dependencies=["test_service"],
            enable_caching=True,
            fallback_mode=False,
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(test_service: str = None) -> str:
            return test_service

        # First call should fetch from registry
        result1 = await test_function()
        assert result1 == "cached_value"
        assert mock_registry.get_dependency.call_count == 1

        # Second call should use cache
        result2 = await test_function()
        assert result2 == "cached_value"
        assert mock_registry.get_dependency.call_count == 1  # No additional calls

    @pytest.mark.asyncio
    async def test_health_monitoring_initialization(self):
        """Test that health monitoring task is started."""
        decorator = MeshAgentDecorator(
            capabilities=["test"], health_interval=1  # Short interval for testing
        )

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            @decorator
            async def test_function() -> str:
                return "test"

            # Call function to trigger initialization
            await test_function()

            # Verify health task was created
            assert decorator._health_task is not None
            assert not decorator._health_task.done()

            # Cleanup
            await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test that cleanup properly cancels health monitoring."""
        decorator = MeshAgentDecorator(capabilities=["test"])

        # Create a proper asyncio task mock
        async def dummy_coro():
            await asyncio.sleep(1)

        # Create actual task and then mock it
        actual_task = asyncio.create_task(dummy_coro())
        with patch.object(actual_task, "cancel") as mock_cancel:
            decorator._health_task = actual_task

            # Create mock registry client
            mock_registry = AsyncMock()
            decorator._registry_client = mock_registry

            await decorator.cleanup()

            # Verify cleanup actions
            mock_cancel.assert_called_once()
            mock_registry.close.assert_called_once()


class TestMeshAgentFunction:
    """Test cases for the mesh_agent decorator function."""

    def test_decorator_function_parameters(self):
        """Test that the decorator function accepts all parameters."""

        @mesh_agent(
            capabilities=["file_read"],
            health_interval=60,
            dependencies=["auth_service"],
            registry_url="http://test-registry",
            agent_name="test-agent",
            security_context="file_ops",
            timeout=45,
            retry_attempts=5,
            enable_caching=False,
            fallback_mode=False,
        )
        async def test_function():
            pass

        metadata = test_function._mesh_agent_metadata
        decorator_instance = metadata["decorator_instance"]

        assert decorator_instance.capabilities == ["file_read"]
        assert decorator_instance.health_interval == 60
        assert decorator_instance.dependencies == ["auth_service"]
        assert decorator_instance.registry_url == "http://test-registry"
        assert decorator_instance.agent_name == "test-agent"
        assert decorator_instance.security_context == "file_ops"
        assert decorator_instance.timeout == 45
        assert decorator_instance.retry_attempts == 5
        assert decorator_instance.enable_caching is False
        assert decorator_instance.fallback_mode is False

    @pytest.mark.asyncio
    async def test_decorator_with_fastmcp_integration(self):
        """Test that decorator works with FastMCP-style tool decoration."""

        # Simulate FastMCP tool decorator
        def mock_tool_decorator(func):
            func._is_tool = True
            return func

        @mesh_agent(capabilities=["file_read"], dependencies=["auth_service"])
        @mock_tool_decorator
        async def read_file(path: str, auth_service: str = None) -> str:
            if auth_service:
                return f"Authenticated read of {path}"
            return f"Read {path}"

        # Verify both decorators work together
        assert hasattr(read_file, "_mesh_agent_metadata")
        assert hasattr(read_file, "_is_tool")

        result = await read_file("/test/file.txt")
        assert "Read /test/file.txt" in result
