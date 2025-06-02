"""
Enhanced unit tests for @mesh_agent decorator functionality.

Focuses on decorator behavior, dependency injection, health monitoring,
error handling, and integration scenarios.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_mesh.decorators.mesh_agent import MeshAgentDecorator, mesh_agent
from mcp_mesh.shared.exceptions import MeshAgentError, RegistryConnectionError
from mcp_mesh.shared.types import HealthStatus


class TestMeshAgentDecoratorCore:
    """Test core decorator functionality."""

    def test_decorator_initialization_defaults(self):
        """Test decorator initialization with default parameters."""
        decorator = MeshAgentDecorator(capabilities=["test"])

        assert decorator.capabilities == ["test"]
        assert decorator.health_interval == 30
        assert decorator.dependencies == []
        assert decorator.timeout == 30
        assert decorator.retry_attempts == 3
        assert decorator.enable_caching is True
        assert decorator.fallback_mode is True
        assert decorator.agent_name.startswith("agent-")
        assert len(decorator.agent_name) == 14  # "agent-" + 8 hex chars

    def test_decorator_initialization_custom(self):
        """Test decorator initialization with custom parameters."""
        decorator = MeshAgentDecorator(
            capabilities=["file_read", "file_write"],
            health_interval=60,
            dependencies=["auth", "audit"],
            registry_url="http://test-registry:8080",
            agent_name="custom-agent",
            security_context="file_ops",
            timeout=45,
            retry_attempts=5,
            enable_caching=False,
            fallback_mode=False,
        )

        assert decorator.capabilities == ["file_read", "file_write"]
        assert decorator.health_interval == 60
        assert decorator.dependencies == ["auth", "audit"]
        assert decorator.registry_url == "http://test-registry:8080"
        assert decorator.agent_name == "custom-agent"
        assert decorator.security_context == "file_ops"
        assert decorator.timeout == 45
        assert decorator.retry_attempts == 5
        assert decorator.enable_caching is False
        assert decorator.fallback_mode is False

    def test_decorator_metadata_attachment(self):
        """Test that decorator attaches metadata to wrapped functions."""

        @mesh_agent(capabilities=["test"], dependencies=["service"])
        async def test_function():
            return "result"

        assert hasattr(test_function, "_mesh_agent_metadata")
        metadata = test_function._mesh_agent_metadata
        assert metadata["capabilities"] == ["test"]
        assert metadata["dependencies"] == ["service"]
        assert "decorator_instance" in metadata
        assert isinstance(metadata["decorator_instance"], MeshAgentDecorator)

    @pytest.mark.asyncio
    async def test_async_function_decoration(self):
        """Test decorator works correctly with async functions."""
        call_count = 0

        @mesh_agent(capabilities=["test"])
        async def async_function(value: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"async: {value}"

        result = await async_function("test")
        assert result == "async: test"
        assert call_count == 1

    def test_sync_function_decoration(self):
        """Test decorator works correctly with sync functions."""
        call_count = 0

        @mesh_agent(capabilities=["test"])
        def sync_function(value: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"sync: {value}"

        result = sync_function("test")
        assert result == "sync: test"
        assert call_count == 1


class TestMeshAgentInitialization:
    """Test mesh agent initialization process."""

    @pytest.mark.asyncio
    async def test_initialization_called_once(self):
        """Test that initialization is called only once."""
        init_count = 0

        decorator = MeshAgentDecorator(capabilities=["test"])

        # Mock the initialization method
        original_init = decorator._initialize

        async def counting_init():
            nonlocal init_count
            init_count += 1
            await original_init()

        decorator._initialize = counting_init

        @decorator
        async def test_function():
            return "result"

        # Call function multiple times
        await test_function()
        await test_function()
        await test_function()

        # Initialization should only happen once
        assert init_count == 1
        assert decorator._initialized is True

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_initialization_with_registry_success(self):
        """Test successful initialization with registry."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.register_agent = AsyncMock()
            mock_client_class.return_value = mock_client

            decorator = MeshAgentDecorator(
                capabilities=["test"], agent_name="test-agent", fallback_mode=False
            )

            @decorator
            async def test_function():
                return "result"

            result = await test_function()
            assert result == "result"

            # Verify registry interactions
            mock_client.register_agent.assert_called_once_with(
                agent_name="test-agent",
                capabilities=["test"],
                dependencies=[],
                security_context=None,
            )

            await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_initialization_with_registry_failure_fallback(self):
        """Test initialization with registry failure in fallback mode."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.register_agent.side_effect = RegistryConnectionError(
                "Connection failed"
            )
            mock_client_class.return_value = mock_client

            decorator = MeshAgentDecorator(capabilities=["test"], fallback_mode=True)

            @decorator
            async def test_function():
                return "success"

            # Should work despite registry failure
            result = await test_function()
            assert result == "success"
            assert decorator._initialized is True

            await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_initialization_with_registry_failure_no_fallback(self):
        """Test initialization with registry failure without fallback mode."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.register_agent.side_effect = RegistryConnectionError(
                "Connection failed"
            )
            mock_client_class.return_value = mock_client

            decorator = MeshAgentDecorator(capabilities=["test"], fallback_mode=False)

            @decorator
            async def test_function():
                return "result"

            # Should raise exception due to registry failure
            with pytest.raises(MeshAgentError):
                await test_function()

            await decorator.cleanup()


class TestDependencyInjection:
    """Test dependency injection functionality."""

    @pytest.mark.asyncio
    async def test_dependency_injection_success(self):
        """Test successful dependency injection."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.return_value = "injected_auth_service"

        decorator = MeshAgentDecorator(
            capabilities=["test"], dependencies=["auth_service"], fallback_mode=False
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(value: str, auth_service: str = None) -> str:
            return f"{value}:{auth_service}"

        result = await test_function("hello")
        assert result == "hello:injected_auth_service"

        mock_registry.get_dependency.assert_called_once_with("auth_service")
        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_dependency_injection_multiple_dependencies(self):
        """Test injection of multiple dependencies."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.side_effect = lambda dep: f"injected_{dep}"

        decorator = MeshAgentDecorator(
            capabilities=["test"],
            dependencies=["auth_service", "audit_logger", "config_service"],
            fallback_mode=False,
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(
            value: str,
            auth_service: str = None,
            audit_logger: str = None,
            config_service: str = None,
        ) -> str:
            return f"{value}:{auth_service}:{audit_logger}:{config_service}"

        result = await test_function("test")
        assert (
            result
            == "test:injected_auth_service:injected_audit_logger:injected_config_service"
        )

        assert mock_registry.get_dependency.call_count == 3
        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_dependency_injection_with_provided_kwargs(self):
        """Test that provided kwargs override dependency injection."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.return_value = "injected_value"

        decorator = MeshAgentDecorator(
            capabilities=["test"], dependencies=["auth_service"], fallback_mode=False
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(auth_service: str = None) -> str:
            return auth_service

        # Explicitly provide auth_service
        result = await test_function(auth_service="provided_value")
        assert result == "provided_value"

        # Registry should not be called since value was provided
        mock_registry.get_dependency.assert_not_called()
        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_dependency_injection_failure_fallback(self):
        """Test dependency injection failure with fallback mode."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.side_effect = Exception("Dependency unavailable")

        decorator = MeshAgentDecorator(
            capabilities=["test"], dependencies=["auth_service"], fallback_mode=True
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(auth_service: str = None) -> str:
            return f"auth_service: {auth_service}"

        # Should work even when dependency injection fails
        result = await test_function()
        assert result == "auth_service: None"

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_dependency_injection_failure_no_fallback(self):
        """Test dependency injection failure without fallback mode."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.side_effect = Exception("Dependency unavailable")

        decorator = MeshAgentDecorator(
            capabilities=["test"], dependencies=["auth_service"], fallback_mode=False
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(auth_service: str = None) -> str:
            return f"auth_service: {auth_service}"

        # Should raise exception due to dependency failure
        with pytest.raises(MeshAgentError):
            await test_function()

        await decorator.cleanup()


class TestCaching:
    """Test dependency caching functionality."""

    @pytest.mark.asyncio
    async def test_dependency_caching_enabled(self):
        """Test that dependencies are cached when caching is enabled."""
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

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_dependency_caching_disabled(self):
        """Test that dependencies are not cached when caching is disabled."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.return_value = "fresh_value"

        decorator = MeshAgentDecorator(
            capabilities=["test"],
            dependencies=["test_service"],
            enable_caching=False,
            fallback_mode=False,
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def test_function(test_service: str = None) -> str:
            return test_service

        # Multiple calls should fetch from registry each time
        await test_function()
        await test_function()
        await test_function()

        assert mock_registry.get_dependency.call_count == 3
        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_cache_expiration(self):
        """Test that cached dependencies expire after TTL."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.return_value = "value"

        decorator = MeshAgentDecorator(
            capabilities=["test"],
            dependencies=["test_service"],
            enable_caching=True,
            fallback_mode=False,
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        # Mock cache TTL to be very short for testing
        timedelta(minutes=5)
        timedelta(seconds=0.1)

        @decorator
        async def test_function(test_service: str = None) -> str:
            return test_service

        # First call
        await test_function()
        assert mock_registry.get_dependency.call_count == 1

        # Manually expire cache entry
        if "test_service" in decorator._dependency_cache:
            decorator._dependency_cache["test_service"]["ttl"] = timedelta(seconds=0)
            decorator._dependency_cache["test_service"][
                "timestamp"
            ] = datetime.now() - timedelta(seconds=1)

        # Second call should fetch fresh value due to expiration
        await test_function()
        assert mock_registry.get_dependency.call_count == 2

        await decorator.cleanup()


class TestHealthMonitoring:
    """Test health monitoring functionality."""

    @pytest.mark.asyncio
    async def test_health_task_creation(self):
        """Test that health monitoring task is created."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            decorator = MeshAgentDecorator(
                capabilities=["test"], health_interval=1  # Short interval for testing
            )

            @decorator
            async def test_function():
                return "result"

            # Trigger initialization
            await test_function()

            # Health task should be created
            assert decorator._health_task is not None
            assert not decorator._health_task.done()

            await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_heartbeat_sending(self):
        """Test that heartbeats are sent to registry."""
        mock_registry = AsyncMock()

        decorator = MeshAgentDecorator(capabilities=["test"], agent_name="test-agent")
        decorator._registry_client = mock_registry
        decorator._initialized = True

        # Send a heartbeat
        await decorator._send_heartbeat()

        # Verify heartbeat was sent
        mock_registry.send_heartbeat.assert_called_once()
        call_args = mock_registry.send_heartbeat.call_args[0][0]

        assert isinstance(call_args, HealthStatus)
        assert call_args.agent_name == "test-agent"
        assert call_args.capabilities == ["test"]
        assert call_args.status == "healthy"

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_heartbeat_failure_handling(self):
        """Test handling of heartbeat failures."""
        mock_registry = AsyncMock()
        mock_registry.send_heartbeat.side_effect = Exception("Heartbeat failed")

        decorator = MeshAgentDecorator(capabilities=["test"])
        decorator._registry_client = mock_registry
        decorator._initialized = True

        # Should not raise exception even if heartbeat fails
        await decorator._send_heartbeat()

        mock_registry.send_heartbeat.assert_called_once()
        await decorator.cleanup()


class TestErrorHandling:
    """Test error handling and recovery."""

    @pytest.mark.asyncio
    async def test_function_success_recording(self):
        """Test that successful function executions are recorded."""
        decorator = MeshAgentDecorator(capabilities=["test"])

        # Mock the success recording method
        decorator._record_success = AsyncMock()

        @decorator
        async def test_function() -> str:
            return "success"

        result = await test_function()
        assert result == "success"

        # Success should be recorded
        decorator._record_success.assert_called_once()
        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_function_failure_recording(self):
        """Test that failed function executions are recorded."""
        decorator = MeshAgentDecorator(capabilities=["test"])

        # Mock the failure recording method
        decorator._record_failure = AsyncMock()

        @decorator
        async def test_function() -> str:
            raise ValueError("Test error")

        # Function should raise the original exception
        with pytest.raises(ValueError, match="Test error"):
            await test_function()

        # Failure should be recorded
        decorator._record_failure.assert_called_once()
        error_arg = decorator._record_failure.call_args[0][0]
        assert isinstance(error_arg, ValueError)
        assert str(error_arg) == "Test error"

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_exception_propagation(self):
        """Test that exceptions are properly propagated."""

        @mesh_agent(capabilities=["test"])
        async def failing_function():
            raise RuntimeError("Custom error")

        with pytest.raises(RuntimeError, match="Custom error"):
            await failing_function()


class TestCleanup:
    """Test cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_health_task(self):
        """Test that cleanup properly cancels health monitoring task."""
        decorator = MeshAgentDecorator(capabilities=["test"])

        # Create a mock task
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()
        decorator._health_task = mock_task

        await decorator.cleanup()

        # Task should be cancelled
        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_registry_client(self):
        """Test that cleanup properly closes registry client."""
        decorator = MeshAgentDecorator(capabilities=["test"])

        # Create mock registry client
        mock_registry = AsyncMock()
        decorator._registry_client = mock_registry

        await decorator.cleanup()

        # Registry client should be closed
        mock_registry.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_with_running_task(self):
        """Test cleanup with actually running health task."""
        decorator = MeshAgentDecorator(
            capabilities=["test"], health_interval=0.1  # Very short interval
        )

        # Start a real health task
        async def mock_health_monitor():
            while True:
                await asyncio.sleep(0.1)

        decorator._health_task = asyncio.create_task(mock_health_monitor())

        # Let it run briefly
        await asyncio.sleep(0.05)

        # Cleanup should cancel the task
        await decorator.cleanup()

        # Task should be cancelled/done
        assert decorator._health_task.done()


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    @pytest.mark.asyncio
    async def test_complete_workflow_with_dependencies(self):
        """Test complete workflow with dependency injection."""
        mock_registry = AsyncMock()
        mock_registry.get_dependency.side_effect = lambda dep: f"mock_{dep}"

        decorator = MeshAgentDecorator(
            capabilities=["file_read", "secure_access"],
            dependencies=["auth_service", "audit_logger"],
            enable_caching=True,
            fallback_mode=False,
        )
        decorator._registry_client = mock_registry
        decorator._initialized = True

        @decorator
        async def secure_read_file(
            path: str, auth_service: str = None, audit_logger: str = None
        ) -> str:
            # Simulate file reading with auth and audit
            return f"File content from {path} (auth: {auth_service}, audit: {audit_logger})"

        result = await secure_read_file("/test/file.txt")
        expected = "File content from /test/file.txt (auth: mock_auth_service, audit: mock_audit_logger)"
        assert result == expected

        # Verify dependencies were injected
        assert mock_registry.get_dependency.call_count == 2
        mock_registry.get_dependency.assert_any_call("auth_service")
        mock_registry.get_dependency.assert_any_call("audit_logger")

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_fallback_mode_degraded_operation(self):
        """Test that functions work in degraded mode when registry is unavailable."""
        decorator = MeshAgentDecorator(
            capabilities=["test"],
            dependencies=["unavailable_service"],
            fallback_mode=True,
        )

        # Simulate registry unavailable
        decorator._registry_client = None
        decorator._initialized = True

        @decorator
        async def resilient_function(
            value: str, unavailable_service: str = None
        ) -> str:
            service_status = "available" if unavailable_service else "unavailable"
            return f"Value: {value}, Service: {service_status}"

        result = await resilient_function("test")
        assert result == "Value: test, Service: unavailable"

        await decorator.cleanup()

    @pytest.mark.asyncio
    async def test_decorator_stacking_compatibility(self):
        """Test that mesh_agent decorator works with other decorators."""

        # Simulate another decorator (like FastMCP's @tool)
        def mock_tool_decorator(name: str):
            def decorator(func):
                func._tool_name = name
                func._is_tool = True
                return func

            return decorator

        @mesh_agent(capabilities=["file_read"])
        @mock_tool_decorator("read_file")
        async def decorated_function(path: str) -> str:
            return f"Reading {path}"

        # Both decorators should work together
        assert hasattr(decorated_function, "_mesh_agent_metadata")
        assert hasattr(decorated_function, "_tool_name")
        assert hasattr(decorated_function, "_is_tool")

        assert decorated_function._tool_name == "read_file"
        assert decorated_function._is_tool is True

        result = await decorated_function("/test/path")
        assert result == "Reading /test/path"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
