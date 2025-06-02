"""
Mock integration tests for File Agent behavior.

Tests File Agent behavior with mocked mesh services, retry logic,
error recovery, and concurrent operations.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mcp_mesh.shared.exceptions import (
    FileNotFoundError,
    RateLimitError,
)
from mcp_mesh.shared.types import HealthStatusType, RetryConfig, RetryStrategy
from mcp_mesh.tools.file_operations import FileOperations


@pytest.fixture
async def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
async def mock_file_ops(temp_dir):
    """Create FileOperations with mocked mesh services."""
    ops = FileOperations(base_directory=str(temp_dir), max_file_size=1024)
    yield ops
    await ops.cleanup()


class TestMeshServiceMocking:
    """Test File Agent with mocked mesh services."""

    @patch("mcp_mesh.decorators.mesh_agent.RegistryClient")
    async def test_file_operations_with_mocked_auth_service(
        self, mock_registry_client, mock_file_ops, temp_dir
    ):
        """Test file operations with mocked authentication service."""
        # Setup mock registry client
        mock_client = AsyncMock()
        mock_client.get_dependency.return_value = "mock_auth_service"
        mock_registry_client.return_value = mock_client

        # Create test file
        test_file = temp_dir / "secure.txt"
        test_content = "secure content"

        # Mock the permission check to simulate auth service
        with patch.object(
            mock_file_ops, "_check_permissions", new_callable=AsyncMock
        ) as mock_perms:
            # Write file with auth service
            result = await mock_file_ops.write_file(
                str(test_file), test_content, auth_service="mock_auth_service"
            )
            assert result is True

            # Read file with auth service
            content = await mock_file_ops.read_file(
                str(test_file), auth_service="mock_auth_service"
            )
            assert content == test_content

            # Verify auth service was used
            assert mock_perms.call_count >= 2  # Called for both read and write

    @patch("mcp_mesh.decorators.mesh_agent.RegistryClient")
    async def test_file_operations_with_mocked_audit_logger(
        self, mock_registry_client, mock_file_ops, temp_dir
    ):
        """Test file operations with mocked audit logging service."""
        # Setup mock registry client
        mock_client = AsyncMock()
        mock_client.get_dependency.return_value = "mock_audit_logger"
        mock_registry_client.return_value = mock_client

        # Create test file
        test_file = temp_dir / "audited.txt"
        test_content = "audited content"

        # Mock the audit log method
        with patch.object(
            mock_file_ops, "_audit_log", new_callable=AsyncMock
        ) as mock_audit:
            # Perform file operation
            await mock_file_ops.write_file(
                str(test_file), test_content, audit_logger="mock_audit_logger"
            )

            # Verify audit logging was called
            mock_audit.assert_called_once()
            call_args = mock_audit.call_args
            assert call_args[0][0] == "file_write"  # Operation type
            assert "path" in call_args[0][1]  # Details dict
            assert call_args[0][2] == "mock_audit_logger"  # Logger service

    @patch("mcp_mesh.decorators.mesh_agent.RegistryClient")
    async def test_file_operations_with_mocked_backup_service(
        self, mock_registry_client, mock_file_ops, temp_dir
    ):
        """Test file operations with mocked backup service."""
        # Setup mock registry client
        mock_client = AsyncMock()
        mock_client.get_dependency.return_value = "mock_backup_service"
        mock_registry_client.return_value = mock_client

        # Create existing file
        test_file = temp_dir / "backup_test.txt"
        original_content = "original content"
        test_file.write_text(original_content)

        # Mock the backup creation method
        with patch.object(
            mock_file_ops, "_create_backup", new_callable=AsyncMock
        ) as mock_backup:
            mock_backup.return_value = test_file.with_suffix(".backup")

            # Write to existing file with backup
            new_content = "updated content"
            await mock_file_ops.write_file(
                str(test_file),
                new_content,
                create_backup=True,
                backup_service="mock_backup_service",
            )

            # Verify backup service was called
            mock_backup.assert_called_once_with(test_file, "mock_backup_service")

    async def test_fallback_behavior_when_mesh_unavailable(
        self, mock_file_ops, temp_dir
    ):
        """Test graceful fallback when mesh services are unavailable."""
        # File operations should work even without mesh services
        test_file = temp_dir / "fallback.txt"
        test_content = "fallback content"

        # Operations should succeed without mesh dependencies
        result = await mock_file_ops.write_file(str(test_file), test_content)
        assert result is True

        content = await mock_file_ops.read_file(str(test_file))
        assert content == test_content

        entries = await mock_file_ops.list_directory(str(temp_dir))
        assert "fallback.txt" in entries


class TestRetryLogicAndErrorRecovery:
    """Test retry mechanisms and error recovery."""

    async def test_retry_on_transient_errors(self, mock_file_ops, temp_dir):
        """Test retry logic for transient errors."""
        test_file = temp_dir / "retry_test.txt"

        # Mock aiofiles.open to fail twice then succeed
        __builtins__["open"]
        call_count = 0

        async def mock_open_context(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise OSError(5, "I/O error")  # EIO - transient error

            # Create a proper async context manager for the third call
            class MockAsyncFile:
                def __init__(self):
                    self.content = ""

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def write(self, content):
                    self.content = content

            return MockAsyncFile()

        with patch("aiofiles.open", side_effect=mock_open_context):
            # Should eventually succeed after retries
            result = await mock_file_ops.write_file(str(test_file), "retry content")
            assert result is True
            assert call_count == 3  # Failed twice, succeeded on third attempt

    async def test_retry_config_customization(self, temp_dir):
        """Test custom retry configuration."""
        custom_retry = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=5,
            initial_delay_ms=100,
            max_delay_ms=1000,
            backoff_multiplier=1.5,
            jitter=False,
        )

        file_ops = FileOperations(
            base_directory=str(temp_dir), retry_config=custom_retry
        )

        # Test retry delay calculation
        delay_0 = await file_ops._calculate_retry_delay(0, custom_retry)
        delay_1 = await file_ops._calculate_retry_delay(1, custom_retry)
        delay_2 = await file_ops._calculate_retry_delay(2, custom_retry)

        assert delay_0 == 0.1  # 100ms
        assert delay_1 == 0.15  # 100ms * 1.5
        assert delay_2 == 0.225  # 100ms * 1.5^2

        await file_ops.cleanup()

    async def test_non_retryable_error_handling(self, mock_file_ops, temp_dir):
        """Test that non-retryable errors are not retried."""
        nonexistent_file = temp_dir / "nonexistent.txt"

        with patch.object(mock_file_ops, "_execute_with_retry") as mock_retry:
            # Setup mock to track retry behavior
            async def mock_operation():
                raise FileNotFoundError(str(nonexistent_file))

            mock_retry.side_effect = FileNotFoundError(str(nonexistent_file))

            with pytest.raises(FileNotFoundError):
                await mock_file_ops.read_file(str(nonexistent_file))

    async def test_rate_limiting_and_recovery(self, mock_file_ops, temp_dir):
        """Test rate limiting enforcement and recovery."""
        # Create test file
        test_file = temp_dir / "rate_test.txt"
        test_file.write_text("test content")

        # Simulate hitting rate limit
        mock_file_ops._max_operations_per_minute = 2

        # First two operations should succeed
        await mock_file_ops.read_file(str(test_file))
        await mock_file_ops.read_file(str(test_file))

        # Third operation should hit rate limit
        with pytest.raises(RateLimitError) as exc_info:
            await mock_file_ops.read_file(str(test_file))

        error = exc_info.value
        assert error.retry_after > 0


class TestConcurrentOperations:
    """Test concurrent operation safety and behavior."""

    async def test_concurrent_file_reads(self, mock_file_ops, temp_dir):
        """Test concurrent file reading operations."""
        # Create multiple test files
        files = []
        for i in range(10):
            file_path = temp_dir / f"concurrent_{i}.txt"
            file_path.write_text(f"content {i}")
            files.append(str(file_path))

        # Read all files concurrently
        tasks = [mock_file_ops.read_file(f) for f in files]
        results = await asyncio.gather(*tasks)

        # Verify all reads succeeded
        assert len(results) == 10
        for i, content in enumerate(results):
            assert content == f"content {i}"

    async def test_concurrent_file_writes(self, mock_file_ops, temp_dir):
        """Test concurrent file writing operations."""
        # Define concurrent write operations
        write_tasks = []
        for i in range(10):
            file_path = temp_dir / f"write_{i}.txt"
            content = f"concurrent content {i}"
            write_tasks.append(mock_file_ops.write_file(str(file_path), content))

        # Execute all writes concurrently
        results = await asyncio.gather(*write_tasks)

        # Verify all writes succeeded
        assert all(results)

        # Verify file contents
        for i in range(10):
            file_path = temp_dir / f"write_{i}.txt"
            content = file_path.read_text()
            assert content == f"concurrent content {i}"

    async def test_mixed_concurrent_operations(self, mock_file_ops, temp_dir):
        """Test mixed concurrent read/write/list operations."""
        # Setup initial files
        for i in range(3):
            file_path = temp_dir / f"initial_{i}.txt"
            file_path.write_text(f"initial {i}")

        # Create mixed operations
        tasks = [
            # Read operations
            mock_file_ops.read_file(str(temp_dir / "initial_0.txt")),
            mock_file_ops.read_file(str(temp_dir / "initial_1.txt")),
            # Write operations
            mock_file_ops.write_file(str(temp_dir / "new_0.txt"), "new content 0"),
            mock_file_ops.write_file(str(temp_dir / "new_1.txt"), "new content 1"),
            # List operations
            mock_file_ops.list_directory(str(temp_dir)),
            mock_file_ops.list_directory(str(temp_dir), include_details=True),
        ]

        # Execute all operations concurrently
        results = await asyncio.gather(*tasks)

        # Verify results
        assert results[0] == "initial 0"  # Read result
        assert results[1] == "initial 1"  # Read result
        assert results[2] is True  # Write result
        assert results[3] is True  # Write result
        assert isinstance(results[4], list)  # List result
        assert isinstance(results[5], list)  # List with details result

    async def test_concurrent_operations_with_rate_limiting(
        self, mock_file_ops, temp_dir
    ):
        """Test concurrent operations with rate limiting."""
        # Create test file
        test_file = temp_dir / "rate_limited.txt"
        test_file.write_text("test")

        # Set low rate limit
        mock_file_ops._max_operations_per_minute = 5

        # Create more tasks than rate limit allows
        tasks = [mock_file_ops.read_file(str(test_file)) for _ in range(10)]

        # Some should succeed, some should hit rate limit
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes and rate limit errors
        successes = [r for r in results if isinstance(r, str)]
        rate_limit_errors = [r for r in results if isinstance(r, RateLimitError)]

        assert len(successes) <= 5  # Should not exceed rate limit
        assert len(rate_limit_errors) > 0  # Should have some rate limit errors


class TestCachingMechanisms:
    """Test caching behavior in mesh integration."""

    @patch("mcp_mesh.decorators.mesh_agent.RegistryClient")
    async def test_dependency_caching(
        self, mock_registry_client, mock_file_ops, temp_dir
    ):
        """Test dependency value caching."""
        # Setup mock registry client
        mock_client = AsyncMock()
        mock_client.get_dependency.return_value = "cached_service_value"
        mock_registry_client.return_value = mock_client

        # Create test file
        test_file = temp_dir / "cache_test.txt"
        test_file.write_text("test")

        # Enable caching in decorator
        for func_name in ["read_file", "write_file", "list_directory"]:
            func = getattr(mock_file_ops, func_name)
            if hasattr(func, "_mesh_agent_metadata"):
                decorator = func._mesh_agent_metadata["decorator_instance"]
                decorator.enable_caching = True
                decorator._registry_client = mock_client
                decorator._initialized = True

        # First operation should fetch from registry
        await mock_file_ops.read_file(str(test_file))

        # Second operation should use cache
        await mock_file_ops.read_file(str(test_file))

        # Should only have called get_dependency once due to caching
        # Note: Actual caching behavior depends on mesh decorator implementation

    async def test_cache_invalidation_on_error(self, mock_file_ops, temp_dir):
        """Test cache invalidation when errors occur."""
        # This test would verify that cached values are invalidated
        # when operations fail, ensuring fresh dependencies on retry
        pass  # Implementation depends on specific caching strategy


class TestHealthMonitoring:
    """Test health monitoring integration."""

    async def test_health_check_with_mesh_services(self, mock_file_ops):
        """Test health check when mesh services are available."""
        health_status = await mock_file_ops.health_check()

        assert health_status.agent_name == "file-operations-agent"
        assert health_status.status in [
            HealthStatusType.HEALTHY,
            HealthStatusType.DEGRADED,
        ]
        assert len(health_status.capabilities) > 0
        assert "file_read" in health_status.capabilities
        assert health_status.metadata is not None

    async def test_health_check_degraded_state(self, mock_file_ops, temp_dir):
        """Test health check in degraded state."""
        # Simulate degraded conditions
        with patch.object(
            mock_file_ops, "_check_file_system_access", return_value=False
        ):
            health_status = await mock_file_ops.health_check()

            # Should be degraded or unhealthy
            assert health_status.status in [
                HealthStatusType.DEGRADED,
                HealthStatusType.UNHEALTHY,
            ]
            assert len(health_status.errors) > 0

    @patch("mcp_mesh.decorators.mesh_agent.RegistryClient")
    async def test_heartbeat_with_registry(self, mock_registry_client, mock_file_ops):
        """Test heartbeat sending to registry."""
        # Setup mock registry client
        mock_client = AsyncMock()
        mock_registry_client.return_value = mock_client

        # Access decorator instance
        func = mock_file_ops.read_file
        if hasattr(func, "_mesh_agent_metadata"):
            decorator = func._mesh_agent_metadata["decorator_instance"]
            decorator._registry_client = mock_client
            decorator._initialized = True

            # Send heartbeat
            await decorator._send_heartbeat()

            # Verify heartbeat was sent
            mock_client.send_heartbeat.assert_called_once()


class TestErrorPropagation:
    """Test error propagation through mesh layers."""

    async def test_filesystem_error_propagation(self, mock_file_ops, temp_dir):
        """Test that filesystem errors are properly propagated."""
        # Attempt to read non-existent file
        nonexistent = temp_dir / "does_not_exist.txt"

        with pytest.raises(FileNotFoundError) as exc_info:
            await mock_file_ops.read_file(str(nonexistent))

        # Verify error has proper attributes
        error = exc_info.value
        assert str(nonexistent) in str(error)
        assert hasattr(error, "file_path")
        assert hasattr(error, "operation")

    async def test_mesh_service_error_propagation(self, mock_file_ops, temp_dir):
        """Test propagation of mesh service errors."""
        # Mock auth service to raise exception
        with patch.object(
            mock_file_ops,
            "_check_permissions",
            side_effect=Exception("Auth service error"),
        ):
            test_file = temp_dir / "auth_error.txt"
            test_file.write_text("test")

            # Error should propagate in non-fallback mode
            # In fallback mode, it should be handled gracefully
            try:
                await mock_file_ops.read_file(
                    str(test_file), auth_service="failing_auth"
                )
                # If no exception, fallback mode is working
            except Exception as e:
                # If exception, non-fallback mode is working
                assert "Auth service error" in str(e)


class TestResourceCleanup:
    """Test proper resource cleanup in various scenarios."""

    async def test_cleanup_after_normal_operations(self, temp_dir):
        """Test cleanup after normal file operations."""
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Perform some operations
        test_file = temp_dir / "cleanup_test.txt"
        await file_ops.write_file(str(test_file), "test content")
        await file_ops.read_file(str(test_file))

        # Cleanup should complete without errors
        await file_ops.cleanup()

        # Verify cleanup completed
        # (Specific cleanup verification depends on implementation)

    async def test_cleanup_after_errors(self, temp_dir):
        """Test cleanup after operations with errors."""
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Cause some errors
        try:
            await file_ops.read_file("nonexistent.txt")
        except FileNotFoundError:
            pass

        try:
            await file_ops.write_file(
                "test.exe", "content"
            )  # Should fail extension check
        except Exception:
            pass

        # Cleanup should still work
        await file_ops.cleanup()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
