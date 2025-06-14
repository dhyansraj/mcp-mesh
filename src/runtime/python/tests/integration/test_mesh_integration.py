"""
Mesh Integration Tests

Comprehensive tests for @mesh_agent decorator integration, service discovery,
dependency injection, and health monitoring functionality.
"""

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from mcp_mesh.decorators import mesh_agent
from mcp_mesh.runtime.shared.exceptions import MeshAgentError, RegistryConnectionError
from mcp_mesh.runtime.shared.types import HealthStatus
from mcp_mesh.runtime.tools.file_operations import FileOperations


class MockRegistryClient:
    """Mock registry client for testing mesh integration."""

    def __init__(
        self, url: str | None = None, timeout: int = 30, retry_attempts: int = 3
    ):
        self.url = url or "http://mock-registry:8080"
        self.timeout = timeout
        self.retry_attempts = retry_attempts

        # Mock state
        self._agents: dict[str, dict[str, Any]] = {}
        self._dependencies: dict[str, Any] = {}
        self._heartbeats: list[dict[str, Any]] = []
        self._connection_failures = 0
        self._should_fail = False

        # Set up default dependencies
        self._dependencies.update(
            {
                "auth_service": "mock-auth-service-v1.2.3",
                "audit_logger": "mock-audit-logger-v2.1.0",
                "backup_service": "mock-backup-service-v1.0.5",
            }
        )

    async def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        dependencies: list[str],
        security_context: str | None = None,
    ) -> None:
        """Mock agent registration."""
        if self._should_fail:
            self._connection_failures += 1
            raise RegistryConnectionError("Mock registry unavailable")

        self._agents[agent_name] = {
            "capabilities": capabilities,
            "dependencies": dependencies,
            "security_context": security_context,
            "registered_at": datetime.now().isoformat(),
            "status": "active",
        }

    async def get_dependency(self, dependency_name: str) -> str | None:
        """Mock dependency resolution."""
        if self._should_fail:
            raise RegistryConnectionError("Mock registry unavailable")

        return self._dependencies.get(dependency_name)

    async def send_heartbeat(self, health_status: HealthStatus) -> None:
        """Mock heartbeat sending."""
        if self._should_fail:
            raise RegistryConnectionError("Mock registry unavailable")

        self._heartbeats.append(
            {
                "agent_name": health_status.agent_name,
                "status": (
                    health_status.status.value
                    if hasattr(health_status.status, "value")
                    else str(health_status.status)
                ),
                "capabilities": health_status.capabilities,
                "timestamp": health_status.timestamp.isoformat(),
                "metadata": health_status.metadata or {},
            }
        )

    async def close(self) -> None:
        """Mock cleanup."""
        pass

    def set_failure_mode(self, should_fail: bool) -> None:
        """Control mock failure behavior."""
        self._should_fail = should_fail

    def get_registered_agents(self) -> dict[str, dict[str, Any]]:
        """Get registered agents for testing."""
        return self._agents.copy()

    def get_heartbeats(self) -> list[dict[str, Any]]:
        """Get received heartbeats for testing."""
        return self._heartbeats.copy()

    def add_dependency(self, name: str, value: str) -> None:
        """Add dependency for testing."""
        self._dependencies[name] = value


@pytest.fixture
async def mock_registry():
    """Create mock registry client."""
    return MockRegistryClient()


@pytest.fixture
async def file_ops_with_mesh(mock_registry):
    """Create FileOperations with mocked mesh integration."""
    with patch(
        "mcp_mesh.decorators.mesh_agent.RegistryClient", return_value=mock_registry
    ):
        ops = FileOperations()
        yield ops, mock_registry
        await ops.cleanup()


class TestMeshAgentRegistration:
    """Test mesh agent registration functionality."""

    async def test_automatic_capability_registration(self, file_ops_with_mesh):
        """Test that capabilities are automatically registered with mesh."""
        file_ops, mock_registry = file_ops_with_mesh

        # Trigger initialization by calling a method
        try:
            await file_ops.read_file("/tmp/test.txt")
        except:
            pass  # We don't care about the file operation result

        # Verify agent was registered
        agents = mock_registry.get_registered_agents()
        assert "file-operations-agent" in agents

        agent_info = agents["file-operations-agent"]
        expected_capabilities = ["file_read", "secure_access"]
        assert all(cap in agent_info["capabilities"] for cap in expected_capabilities)

        expected_dependencies = ["auth_service", "audit_logger"]
        assert all(dep in agent_info["dependencies"] for dep in expected_dependencies)

    async def test_multiple_tool_registration(self, file_ops_with_mesh):
        """Test registration of multiple tools with different capabilities."""
        file_ops, mock_registry = file_ops_with_mesh

        # Trigger multiple tools to initialize
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            temp_path = f.name

        try:
            # Trigger read tool
            await file_ops.read_file(temp_path)

            # Trigger write tool
            await file_ops.write_file(temp_path, "new content")

            # Trigger list tool
            await file_ops.list_directory("/tmp")

        except Exception:
            pass
        finally:
            import os

            os.unlink(temp_path)

        # All should register under same agent but with combined capabilities
        agents = mock_registry.get_registered_agents()
        assert len(agents) >= 1

        # Check that different capability sets were registered
        all_capabilities = set()
        for agent_info in agents.values():
            all_capabilities.update(agent_info["capabilities"])

        expected_capabilities = [
            "file_read",
            "file_write",
            "directory_list",
            "secure_access",
        ]
        assert all(cap in all_capabilities for cap in expected_capabilities)

    async def test_registration_with_security_context(self, mock_registry):
        """Test registration with security context."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test_capability",
                security_context="test_security_context",
                agent_name="test-agent",
            )
            async def test_function():
                return "test"

            # Trigger initialization
            await test_function()

            # Verify security context was registered
            agents = mock_registry.get_registered_agents()
            assert "test-agent" in agents
            assert agents["test-agent"]["security_context"] == "test_security_context"


class TestDependencyInjection:
    """Test dependency injection functionality."""

    async def test_successful_dependency_injection(self, file_ops_with_mesh):
        """Test successful injection of dependencies."""
        file_ops, mock_registry = file_ops_with_mesh

        # Add custom dependency
        mock_registry.add_dependency("test_service", "test-service-v1.0.0")

        @mesh_agent(
            capability="test", dependencies=["test_service"], fallback_mode=False
        )
        async def test_function(value: str, test_service: str | None = None) -> str:
            return f"{value}:{test_service}"

        # Patch the registry client for this specific test
        decorator_instance = test_function._mesh_agent_metadata["decorator_instance"]
        decorator_instance._registry_client = mock_registry
        decorator_instance._initialized = True

        result = await test_function("hello")
        assert result == "hello:test-service-v1.0.0"

    async def test_dependency_caching(self, mock_registry):
        """Test that dependencies are cached to reduce registry calls."""
        call_count = 0
        original_get_dependency = mock_registry.get_dependency

        async def counted_get_dependency(dep_name: str):
            nonlocal call_count
            call_count += 1
            return await original_get_dependency(dep_name)

        mock_registry.get_dependency = counted_get_dependency

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                dependencies=["auth_service"],
                enable_caching=True,
                fallback_mode=False,
            )
            async def test_function(auth_service: str | None = None) -> str:
                return f"auth:{auth_service}"

            # First call should fetch from registry
            result1 = await test_function()
            assert call_count == 1
            assert "mock-auth-service-v1.2.3" in result1

            # Second call should use cache
            result2 = await test_function()
            assert call_count == 1  # No additional registry call
            assert result1 == result2

    async def test_fallback_mode_with_missing_dependencies(self, mock_registry):
        """Test fallback mode when dependencies are unavailable."""
        # Configure registry to fail dependency resolution
        mock_registry.set_failure_mode(True)

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                dependencies=["unavailable_service"],
                fallback_mode=True,
            )
            async def test_function(
                value: str, unavailable_service: str | None = None
            ) -> str:
                if unavailable_service:
                    return f"{value}:{unavailable_service}"
                return f"{value}:fallback"

            # Should work in fallback mode
            result = await test_function("hello")
            assert result == "hello:fallback"

    async def test_strict_mode_with_missing_dependencies(self, mock_registry):
        """Test strict mode fails when dependencies are unavailable."""
        mock_registry.set_failure_mode(True)

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                dependencies=["required_service"],
                fallback_mode=False,
            )
            async def test_function(required_service: str) -> str:
                return f"result:{required_service}"

            # Should raise exception in strict mode
            with pytest.raises(MeshAgentError):
                await test_function()


class TestHealthMonitoring:
    """Test health monitoring and heartbeat functionality."""

    async def test_automatic_heartbeat_sending(self, file_ops_with_mesh):
        """Test that heartbeats are sent automatically."""
        file_ops, mock_registry = file_ops_with_mesh

        # Trigger initialization
        try:
            await file_ops.read_file("/tmp/test.txt")
        except:
            pass

        # Wait a short time for health monitoring to start
        await asyncio.sleep(0.1)

        # Access the decorator instance to check health task
        read_func = file_ops.read_file
        if hasattr(read_func, "_mesh_agent_metadata"):
            decorator_instance = read_func._mesh_agent_metadata["decorator_instance"]
            assert decorator_instance._health_task is not None
            assert not decorator_instance._health_task.done()

    async def test_health_status_reporting(self, file_ops_with_mesh):
        """Test health status is properly reported."""
        file_ops, mock_registry = file_ops_with_mesh

        # Get health status from file operations
        health_status = await file_ops.health_check()

        # Verify health status structure
        assert isinstance(health_status, HealthStatus)
        assert health_status.agent_name == "file-operations-agent"
        assert hasattr(health_status, "status")
        assert hasattr(health_status, "capabilities")
        assert hasattr(health_status, "timestamp")
        assert hasattr(health_status, "checks")

        # Verify capabilities
        expected_capabilities = [
            "file_read",
            "file_write",
            "directory_list",
            "secure_access",
        ]
        for cap in expected_capabilities:
            assert cap in health_status.capabilities

    async def test_heartbeat_data_format(self, mock_registry):
        """Test heartbeat data format compliance."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                health_interval=1,  # Fast heartbeat for testing
                agent_name="test-heartbeat-agent",
            )
            async def test_function() -> str:
                return "test"

            # Trigger initialization
            await test_function()

            # Wait for at least one heartbeat
            await asyncio.sleep(1.2)

            # Check heartbeat was sent
            heartbeats = mock_registry.get_heartbeats()
            assert len(heartbeats) > 0

            heartbeat = heartbeats[0]
            assert "agent_name" in heartbeat
            assert "status" in heartbeat
            assert "capabilities" in heartbeat
            assert "timestamp" in heartbeat
            assert heartbeat["agent_name"] == "test-heartbeat-agent"

    async def test_health_monitoring_with_registry_failure(self, mock_registry):
        """Test health monitoring behavior when registry is unavailable."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(capability="test", health_interval=1, fallback_mode=True)
            async def test_function() -> str:
                return "test"

            # Initialize normally
            await test_function()

            # Simulate registry failure
            mock_registry.set_failure_mode(True)

            # Wait for heartbeat attempts
            await asyncio.sleep(1.2)

            # Function should still work despite heartbeat failures
            result = await test_function()
            assert result == "test"


class TestServiceDiscovery:
    """Test service discovery functionality."""

    async def test_discover_available_services(self, mock_registry):
        """Test discovery of available services."""
        # Add multiple services to registry
        services = {
            "auth_service": "auth-v2.0.0",
            "audit_logger": "audit-v1.5.0",
            "backup_service": "backup-v3.0.0",
            "monitoring_service": "monitor-v1.0.0",
        }

        for name, version in services.items():
            mock_registry.add_dependency(name, version)

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                dependencies=list(services.keys()),
                fallback_mode=False,
            )
            async def test_function(**kwargs) -> dict[str, str]:
                return kwargs

            result = await test_function()

            # All services should be discovered and injected
            for service_name, expected_version in services.items():
                assert service_name in result
                assert result[service_name] == expected_version

    async def test_partial_service_availability(self, mock_registry):
        """Test behavior when only some services are available."""
        # Only add some services
        mock_registry.add_dependency("available_service", "available-v1.0.0")
        # "unavailable_service" is not added

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                dependencies=["available_service", "unavailable_service"],
                fallback_mode=True,
            )
            async def test_function(**kwargs) -> dict[str, Any]:
                return kwargs

            result = await test_function()

            # Should have available service
            assert "available_service" in result
            assert result["available_service"] == "available-v1.0.0"

            # Should not have unavailable service
            assert "unavailable_service" not in result


class TestMeshIntegrationWithFileOperations:
    """Test mesh integration specifically with file operations."""

    async def test_file_operations_with_audit_logging(self, file_ops_with_mesh):
        """Test file operations with audit logging dependency."""
        file_ops, mock_registry = file_ops_with_mesh

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test content")
            temp_path = f.name

        try:
            # Perform file operation that should trigger audit logging
            content = await file_ops.read_file(temp_path)
            assert content == "test content"

            # Write operation should also work with audit logging
            result = await file_ops.write_file(temp_path, "updated content")
            assert result is True

        finally:

            os.unlink(temp_path)

    async def test_file_operations_with_backup_service(self, file_ops_with_mesh):
        """Test file operations with backup service dependency."""
        file_ops, mock_registry = file_ops_with_mesh

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("original content")
            temp_path = f.name

        try:
            # Write with backup should work
            result = await file_ops.write_file(
                temp_path, "new content", create_backup=True
            )
            assert result is True

            # Verify content was updated
            content = await file_ops.read_file(temp_path)
            assert content == "new content"

        finally:

            os.unlink(temp_path)

    async def test_concurrent_operations_with_mesh(self, file_ops_with_mesh):
        """Test concurrent file operations with mesh integration."""
        file_ops, mock_registry = file_ops_with_mesh

        import os

        with tempfile.TemporaryDirectory() as temp_dir:
            # Create multiple test files
            files = []
            for i in range(5):
                file_path = os.path.join(temp_dir, f"test_{i}.txt")
                with open(file_path, "w") as f:
                    f.write(f"content {i}")
                files.append(file_path)

            # Perform concurrent operations
            tasks = []

            # Mix of read and write operations
            for i, file_path in enumerate(files):
                if i % 2 == 0:
                    # Read operations
                    tasks.append(file_ops.read_file(file_path))
                else:
                    # Write operations
                    tasks.append(file_ops.write_file(file_path, f"updated {i}"))

            # Add list operations
            tasks.append(file_ops.list_directory(temp_dir))

            # Execute all concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Verify results
            assert len(results) == len(tasks)

            # Most operations should succeed
            successful_results = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_results) >= len(tasks) * 0.8  # At least 80% success


class TestMeshErrorHandling:
    """Test error handling in mesh integration scenarios."""

    async def test_registry_connection_failure_handling(self, mock_registry):
        """Test handling of registry connection failures."""
        mock_registry.set_failure_mode(True)

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            # Test with fallback mode enabled
            @mesh_agent(
                capability="test", dependencies=["test_service"], fallback_mode=True
            )
            async def fallback_function(value: str) -> str:
                return f"fallback:{value}"

            # Should work despite registry failure
            result = await fallback_function("test")
            assert result == "fallback:test"

            # Test with fallback mode disabled
            @mesh_agent(
                capability="test",
                dependencies=["test_service"],
                fallback_mode=False,
            )
            async def strict_function(value: str) -> str:
                return f"strict:{value}"

            # Should raise exception
            with pytest.raises(MeshAgentError):
                await strict_function("test")

    async def test_partial_dependency_failure(self, mock_registry):
        """Test handling when some dependencies fail."""
        # Set up one working dependency
        mock_registry.add_dependency("working_service", "working-v1.0.0")

        # Mock get_dependency to fail for specific dependency
        original_get_dependency = mock_registry.get_dependency

        async def selective_get_dependency(dep_name: str):
            if dep_name == "failing_service":
                raise RegistryConnectionError("Service unavailable")
            return await original_get_dependency(dep_name)

        mock_registry.get_dependency = selective_get_dependency

        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(
                capability="test",
                dependencies=["working_service", "failing_service"],
                fallback_mode=True,
            )
            async def mixed_function(**kwargs) -> dict[str, Any]:
                return kwargs

            result = await mixed_function()

            # Should have working service
            assert "working_service" in result
            assert result["working_service"] == "working-v1.0.0"

            # Should not have failing service
            assert "failing_service" not in result

    async def test_mesh_cleanup_on_exception(self, mock_registry):
        """Test proper cleanup when exceptions occur."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=mock_registry,
        ):

            @mesh_agent(capability="test", health_interval=1)
            async def failing_function() -> str:
                raise ValueError("Test exception")

            # Function should raise exception
            with pytest.raises(ValueError):
                await failing_function()

            # Mesh integration should still be cleaned up properly
            decorator_instance = failing_function._mesh_agent_metadata[
                "decorator_instance"
            ]
            await decorator_instance.cleanup()

            # Health task should be cancelled
            if decorator_instance._health_task:
                assert (
                    decorator_instance._health_task.cancelled()
                    or decorator_instance._health_task.done()
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
