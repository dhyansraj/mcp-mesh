"""
Enhanced unit tests for File Operations with comprehensive coverage.

Focused on basic operations, parameter validation, error conditions,
security validation, and mesh integration.
"""

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

import pytest
from mcp_mesh_runtime.shared.exceptions import (
    DirectoryNotFoundError,
    EncodingError,
    FileNotFoundError,
    FileOperationError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    MCPErrorCode,
    PathTraversalError,
    SecurityValidationError,
)
from mcp_mesh_runtime.shared.types import (
    HealthStatusType,
    OperationType,
    RetryConfig,
    RetryStrategy,
)
from mcp_mesh_runtime.tools.file_operations import FileOperations


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def file_ops(temp_dir):
    """Create FileOperations instance with temporary base directory."""
    ops = FileOperations(base_directory=str(temp_dir), max_file_size=1024)
    yield ops
    # Use asyncio.run for cleanup since we can't use await in fixture teardown
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule cleanup as a task
            asyncio.create_task(ops.cleanup())
            # Don't wait for it to complete
        else:
            loop.run_until_complete(ops.cleanup())
    except RuntimeError:
        asyncio.run(ops.cleanup())


@pytest.fixture
def unrestricted_file_ops():
    """Create FileOperations instance without base directory restriction."""
    ops = FileOperations(max_file_size=1024)
    yield ops
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(ops.cleanup())
        else:
            loop.run_until_complete(ops.cleanup())
    except RuntimeError:
        asyncio.run(ops.cleanup())


class TestBasicFileOperations:
    """Test basic file operations with various scenarios."""

    @pytest.mark.asyncio
    async def test_read_file_basic(self, file_ops, temp_dir):
        """Test basic file reading functionality."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_content = "Hello, MCP-Mesh!"
        test_file.write_text(test_content, encoding="utf-8")

        # Read file
        content = await file_ops.read_file(str(test_file))
        assert content == test_content

    @pytest.mark.asyncio
    async def test_read_file_with_encoding(self, file_ops, temp_dir):
        """Test file reading with different encodings."""
        test_file = temp_dir / "test_utf8.txt"
        test_content = "Hello, 世界! 🌍"
        test_file.write_text(test_content, encoding="utf-8")

        content = await file_ops.read_file(str(test_file), encoding="utf-8")
        assert content == test_content

    @pytest.mark.asyncio
    async def test_read_file_with_request_id(self, file_ops, temp_dir):
        """Test file reading with request tracking."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        # Should not raise exception when request_id is provided
        content = await file_ops.read_file(
            str(test_file), request_id="test-123", correlation_id="corr-456"
        )
        assert content == "content"

    @pytest.mark.asyncio
    async def test_write_file_basic(self, file_ops, temp_dir):
        """Test basic file writing functionality."""
        test_file = temp_dir / "new_file.txt"
        test_content = "New content"

        result = await file_ops.write_file(str(test_file), test_content)
        assert result is True
        assert test_file.read_text() == test_content

    @pytest.mark.asyncio
    async def test_write_file_creates_directories(self, file_ops, temp_dir):
        """Test that write_file creates parent directories."""
        nested_file = temp_dir / "subdir" / "nested" / "file.txt"
        test_content = "nested content"

        result = await file_ops.write_file(str(nested_file), test_content)
        assert result is True
        assert nested_file.exists()
        assert nested_file.read_text() == test_content

    @pytest.mark.asyncio
    async def test_write_file_with_encoding(self, file_ops, temp_dir):
        """Test file writing with different encodings."""
        test_file = temp_dir / "unicode.txt"
        test_content = "Hello, 世界! 🌍"

        result = await file_ops.write_file(
            str(test_file), test_content, encoding="utf-8"
        )
        assert result is True
        assert test_file.read_text(encoding="utf-8") == test_content

    @pytest.mark.asyncio
    async def test_write_file_without_backup(self, file_ops, temp_dir):
        """Test file writing without backup."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("original")

        result = await file_ops.write_file(str(test_file), "new", create_backup=False)
        assert result is True
        assert test_file.read_text() == "new"

        # Verify no backup files created
        backup_files = list(temp_dir.glob("*.backup.*"))
        assert len(backup_files) == 0

    @pytest.mark.asyncio
    async def test_list_directory_basic(self, file_ops, temp_dir):
        """Test basic directory listing."""
        # Create test files
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.json").write_text('{"key": "value"}')
        (temp_dir / "subdir").mkdir()

        entries = await file_ops.list_directory(str(temp_dir))
        assert "file1.txt" in entries
        assert "file2.json" in entries
        assert "subdir" in entries

    @pytest.mark.asyncio
    async def test_list_directory_hidden_files(self, file_ops, temp_dir):
        """Test directory listing with hidden files."""
        (temp_dir / "visible.txt").write_text("content")
        (temp_dir / ".hidden").write_text("hidden")
        (temp_dir / ".config").mkdir()

        # Without hidden files
        entries = await file_ops.list_directory(str(temp_dir), include_hidden=False)
        assert "visible.txt" in entries
        assert ".hidden" not in entries
        assert ".config" not in entries

        # With hidden files
        entries_with_hidden = await file_ops.list_directory(
            str(temp_dir), include_hidden=True
        )
        assert "visible.txt" in entries_with_hidden
        assert ".hidden" in entries_with_hidden
        assert ".config" in entries_with_hidden

    @pytest.mark.asyncio
    async def test_list_directory_with_details(self, file_ops, temp_dir):
        """Test directory listing with detailed information."""
        test_file = temp_dir / "test.txt"
        test_content = "content"
        test_file.write_text(test_content)

        entries = await file_ops.list_directory(str(temp_dir), include_details=True)
        assert len(entries) == 1

        entry = entries[0]
        assert isinstance(entry, dict)
        assert entry["name"] == "test.txt"
        assert entry["type"] == "file"
        assert entry["size"] == len(test_content)
        assert "modified" in entry
        assert "permissions" in entry
        assert "is_symlink" in entry
        assert entry["is_symlink"] is False


class TestParameterValidation:
    """Test parameter validation and edge cases."""

    @pytest.mark.asyncio
    async def test_empty_path_validation(self, file_ops):
        """Test validation of empty paths."""
        invalid_paths = ["", "   ", "\t", "\n"]

        for path in invalid_paths:
            with pytest.raises(SecurityValidationError):
                await file_ops._validate_path(path, OperationType.READ)

    @pytest.mark.asyncio
    async def test_none_path_validation(self, file_ops):
        """Test validation of None path."""
        with pytest.raises((TypeError, SecurityValidationError)):
            await file_ops._validate_path(None, OperationType.READ)

    @pytest.mark.asyncio
    async def test_read_file_invalid_encoding(self, file_ops, temp_dir):
        """Test read_file with invalid encoding."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        # Invalid encoding should raise exception
        with pytest.raises((LookupError, TypeError)):
            await file_ops.read_file(str(test_file), encoding="invalid-encoding")

    @pytest.mark.asyncio
    async def test_write_file_invalid_encoding(self, file_ops, temp_dir):
        """Test write_file with invalid encoding."""
        test_file = temp_dir / "test.txt"

        with pytest.raises((LookupError, TypeError)):
            await file_ops.write_file(
                str(test_file), "content", encoding="invalid-encoding"
            )

    @pytest.mark.asyncio
    async def test_max_file_size_validation(self, file_ops, temp_dir):
        """Test file size limit validation."""
        test_file = temp_dir / "large.txt"

        # Content larger than max_file_size (1024 bytes)
        large_content = "x" * 1025

        with pytest.raises(FileTooLargeError):
            await file_ops.write_file(str(test_file), large_content)

    @pytest.mark.asyncio
    async def test_empty_content_write(self, file_ops, temp_dir):
        """Test writing empty content."""
        test_file = temp_dir / "empty.txt"

        result = await file_ops.write_file(str(test_file), "")
        assert result is True
        assert test_file.read_text() == ""


class TestSecurityValidation:
    """Test security validation features."""

    @pytest.mark.asyncio
    async def test_path_traversal_attacks(self, file_ops):
        """Test protection against various path traversal attacks."""
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam",
            "subdir/../../../secret.txt",
            "./../../escape.txt",
            "normal/../../../sensitive.txt",
            "test/../../../../etc/shadow",
            "../config",
            "./../test",
            "folder/../../outside",
        ]

        for path in malicious_paths:
            with pytest.raises(PathTraversalError):
                await file_ops._validate_path(path, OperationType.READ)

    @pytest.mark.asyncio
    async def test_absolute_path_restriction(self, file_ops, temp_dir):
        """Test that absolute paths outside base directory are blocked."""
        absolute_paths = [
            "/etc/passwd",
            "/tmp/outside.txt",
            "/home/user/file.txt",
            "/var/log/system.log",
        ]

        for path in absolute_paths:
            with pytest.raises(SecurityValidationError):
                await file_ops._validate_path(path, OperationType.READ)

    @pytest.mark.asyncio
    async def test_file_extension_whitelist(self, file_ops):
        """Test file extension whitelist enforcement."""
        # Allowed extensions should pass
        allowed_files = [
            "document.txt",
            "config.json",
            "script.py",
            "data.csv",
            "readme.md",
            "style.css",
            "app.js",
            "types.ts",
            "document.yaml",
            "settings.yml",
        ]

        for filename in allowed_files:
            validated = await file_ops._validate_path(filename, OperationType.WRITE)
            assert filename in str(validated)

    @pytest.mark.asyncio
    async def test_dangerous_file_extensions(self, file_ops):
        """Test that dangerous file extensions are blocked."""
        dangerous_files = [
            "malware.exe",
            "virus.bat",
            "trojan.cmd",
            "backdoor.scr",
            "script.vbs",
            "library.dll",
            "driver.sys",
            "MALWARE.EXE",  # Test case insensitivity
            "Virus.BAT",
        ]

        for filename in dangerous_files:
            with pytest.raises(FileTypeNotAllowedError):
                await file_ops._validate_path(filename, OperationType.WRITE)

    @pytest.mark.asyncio
    async def test_special_characters_validation(self, file_ops, temp_dir):
        """Test handling of special characters in filenames."""
        # These should work
        valid_names = [
            "file-name.txt",
            "file_name.txt",
            "file name.txt",  # Space is allowed
            "file(1).txt",
            "file[backup].txt",
            "file.2023-12-01.txt",
        ]

        for name in valid_names:
            validated = await file_ops._validate_path(name, OperationType.WRITE)
            assert name in str(validated)


class TestErrorConditions:
    """Test various error conditions and exception handling."""

    @pytest.mark.asyncio
    async def test_file_not_found_error(self, file_ops, temp_dir):
        """Test FileNotFoundError handling."""
        nonexistent = temp_dir / "nonexistent.txt"

        with pytest.raises(FileNotFoundError) as exc_info:
            await file_ops.read_file(str(nonexistent))

        error = exc_info.value
        assert str(nonexistent) in str(error)
        assert error.error_type == "file_not_found"

    @pytest.mark.asyncio
    async def test_directory_not_found_error(self, file_ops, temp_dir):
        """Test DirectoryNotFoundError handling."""
        nonexistent_dir = temp_dir / "nonexistent_dir"

        with pytest.raises(DirectoryNotFoundError) as exc_info:
            await file_ops.list_directory(str(nonexistent_dir))

        error = exc_info.value
        assert str(nonexistent_dir) in str(error)

    @pytest.mark.asyncio
    async def test_read_directory_as_file(self, file_ops, temp_dir):
        """Test error when trying to read directory as file."""
        test_dir = temp_dir / "testdir"
        test_dir.mkdir()

        with pytest.raises(FileOperationError) as exc_info:
            await file_ops.read_file(str(test_dir))

        error = exc_info.value
        assert "not a file" in str(error)

    @pytest.mark.asyncio
    async def test_list_file_as_directory(self, file_ops, temp_dir):
        """Test error when trying to list file as directory."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        with pytest.raises(FileOperationError) as exc_info:
            await file_ops.list_directory(str(test_file))

        error = exc_info.value
        assert "not a directory" in str(error)

    @pytest.mark.asyncio
    async def test_encoding_error_handling(self, file_ops, temp_dir):
        """Test handling of encoding errors."""
        # Create binary file with invalid UTF-8
        binary_file = temp_dir / "binary.bin"
        binary_file.write_bytes(b"\x80\x81\x82\x83\x84\x85")

        with pytest.raises(EncodingError) as exc_info:
            await file_ops.read_file(str(binary_file), encoding="utf-8")

        error = exc_info.value
        assert "utf-8" in str(error)
        assert str(binary_file) in str(error)

    @pytest.mark.asyncio
    async def test_file_too_large_read_error(self, file_ops, temp_dir):
        """Test FileTooLargeError on reading large files."""
        large_file = temp_dir / "large.txt"
        # Create file larger than max_file_size
        large_content = "x" * (file_ops.max_file_size + 1)
        large_file.write_text(large_content)

        with pytest.raises(FileTooLargeError) as exc_info:
            await file_ops.read_file(str(large_file))

        error = exc_info.value
        assert error.file_size > file_ops.max_file_size
        assert error.max_size == file_ops.max_file_size


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limit_tracking(self, file_ops, temp_dir):
        """Test that operations are tracked for rate limiting."""
        test_file = temp_dir / "rate_test.txt"
        test_file.write_text("content")

        # Perform several read operations
        for _ in range(3):
            await file_ops.read_file(str(test_file))

        # Check rate limiting state
        assert "read" in file_ops._operation_counts
        assert len(file_ops._operation_counts["read"]) == 3

    @pytest.mark.asyncio
    async def test_rate_limit_window_cleanup(self, file_ops, temp_dir):
        """Test that old rate limit entries are cleaned up."""
        # Mock time to simulate old entries
        current_time = time.time()
        old_time = current_time - file_ops._rate_limit_window - 1

        # Add old entry manually
        file_ops._operation_counts["test"] = [old_time]

        # Trigger rate limit check which should clean old entries
        await file_ops._check_rate_limit("test")

        # Old entry should be removed
        assert len(file_ops._operation_counts["test"]) == 1  # Just the new entry


class TestRetryLogic:
    """Test retry logic and configuration."""

    @pytest.mark.asyncio
    async def test_retry_config_validation(self, file_ops):
        """Test retry configuration validation."""
        # Valid config
        valid_config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=3,
            initial_delay_ms=1000,
            max_delay_ms=30000,
            backoff_multiplier=2.0,
            jitter=True,
        )

        assert valid_config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert valid_config.max_retries == 3
        assert valid_config.initial_delay_ms == 1000

    @pytest.mark.asyncio
    async def test_exponential_backoff_calculation(self, file_ops):
        """Test exponential backoff delay calculation."""
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            initial_delay_ms=1000,
            max_delay_ms=10000,
            backoff_multiplier=2.0,
            jitter=False,
        )

        delay_0 = await file_ops._calculate_retry_delay(0, config)
        delay_1 = await file_ops._calculate_retry_delay(1, config)
        delay_2 = await file_ops._calculate_retry_delay(2, config)

        assert delay_0 == 1.0  # 1000ms = 1s
        assert delay_1 == 2.0  # 1000ms * 2^1 = 2s
        assert delay_2 == 4.0  # 1000ms * 2^2 = 4s

    @pytest.mark.asyncio
    async def test_linear_backoff_calculation(self, file_ops):
        """Test linear backoff delay calculation."""
        config = RetryConfig(
            strategy=RetryStrategy.LINEAR_BACKOFF,
            initial_delay_ms=1000,
            max_delay_ms=10000,
            backoff_multiplier=1.0,
            jitter=False,
        )

        delay_0 = await file_ops._calculate_retry_delay(0, config)
        delay_1 = await file_ops._calculate_retry_delay(1, config)
        delay_2 = await file_ops._calculate_retry_delay(2, config)

        assert delay_0 == 1.0  # 1000ms * 1
        assert delay_1 == 2.0  # 1000ms * 2
        assert delay_2 == 3.0  # 1000ms * 3

    @pytest.mark.asyncio
    async def test_fixed_delay_calculation(self, file_ops):
        """Test fixed delay calculation."""
        config = RetryConfig(
            strategy=RetryStrategy.FIXED_DELAY,
            initial_delay_ms=1500,
            max_delay_ms=10000,
            backoff_multiplier=2.0,
            jitter=False,
        )

        delay_0 = await file_ops._calculate_retry_delay(0, config)
        delay_1 = await file_ops._calculate_retry_delay(1, config)
        delay_2 = await file_ops._calculate_retry_delay(2, config)

        assert delay_0 == 1.5  # Always 1500ms
        assert delay_1 == 1.5
        assert delay_2 == 1.5

    @pytest.mark.asyncio
    async def test_max_delay_limit(self, file_ops):
        """Test that delay is capped at max_delay_ms."""
        config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            initial_delay_ms=1000,
            max_delay_ms=3000,  # Cap at 3 seconds
            backoff_multiplier=2.0,
            jitter=False,
        )

        # High attempt number should be capped
        delay_10 = await file_ops._calculate_retry_delay(10, config)
        assert delay_10 == 3.0  # Capped at max_delay_ms


class TestHealthCheck:
    """Test health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_basic(self, file_ops):
        """Test basic health check functionality."""
        health = await file_ops.health_check()

        assert health.agent_name == "file-operations-agent"
        assert health.status in [
            HealthStatusType.HEALTHY,
            HealthStatusType.DEGRADED,
            HealthStatusType.UNHEALTHY,
        ]
        assert isinstance(health.capabilities, list)
        assert len(health.capabilities) > 0
        assert "file_read" in health.capabilities
        assert "file_write" in health.capabilities
        assert "directory_list" in health.capabilities
        assert health.timestamp is not None
        assert health.uptime_seconds >= 0

    @pytest.mark.asyncio
    async def test_health_check_metadata(self, file_ops):
        """Test health check metadata content."""
        health = await file_ops.health_check()

        assert "checks" in health.metadata
        assert "base_directory" in health.metadata
        assert "max_file_size" in health.metadata
        assert "allowed_extensions" in health.metadata
        assert health.metadata["max_file_size"] == file_ops.max_file_size


class TestMCPErrorCompliance:
    """Test MCP JSON-RPC 2.0 error compliance."""

    @pytest.mark.asyncio
    async def test_error_structure_compliance(self, file_ops, temp_dir):
        """Test that errors comply with MCP JSON-RPC 2.0 structure."""
        nonexistent = temp_dir / "nonexistent.txt"

        with pytest.raises(FileNotFoundError) as exc_info:
            await file_ops.read_file(str(nonexistent))

        error = exc_info.value
        error_dict = error.to_dict()

        # Required MCP fields
        assert "code" in error_dict
        assert "message" in error_dict
        assert "data" in error_dict

        # Check error code
        assert error_dict["code"] == MCPErrorCode.FILE_NOT_FOUND

        # Check data structure
        data = error_dict["data"]
        assert "timestamp" in data
        assert "error_type" in data
        assert "file_path" in data
        assert data["error_type"] == "file_not_found"

    @pytest.mark.asyncio
    async def test_mcp_error_conversion(self, file_ops):
        """Test conversion of generic exceptions to MCP format."""
        # Create a generic Python exception
        generic_error = ValueError("Generic error message")

        mcp_error = file_ops._convert_exception_to_mcp_error(generic_error)

        assert "code" in mcp_error
        assert "message" in mcp_error
        assert "data" in mcp_error
        assert mcp_error["code"] == MCPErrorCode.INTERNAL_ERROR


class TestConcurrentOperations:
    """Test concurrent operations and thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_reads(self, file_ops, temp_dir):
        """Test concurrent file reading operations."""
        # Create multiple test files
        test_files = []
        for i in range(5):
            test_file = temp_dir / f"concurrent_{i}.txt"
            test_content = f"content {i}"
            test_file.write_text(test_content)
            test_files.append((str(test_file), test_content))

        # Read all files concurrently
        tasks = [file_ops.read_file(path) for path, _ in test_files]
        results = await asyncio.gather(*tasks)

        # Verify results
        assert len(results) == 5
        for i, content in enumerate(results):
            assert content == f"content {i}"

    @pytest.mark.asyncio
    async def test_concurrent_writes(self, file_ops, temp_dir):
        """Test concurrent file writing operations."""
        # Define write operations
        write_ops = []
        for i in range(5):
            path = temp_dir / f"write_{i}.txt"
            content = f"write content {i}"
            write_ops.append((str(path), content))

        # Perform all writes concurrently
        tasks = [file_ops.write_file(path, content) for path, content in write_ops]
        results = await asyncio.gather(*tasks)

        # All writes should succeed
        assert all(results)

        # Verify file contents
        for i, (path, expected_content) in enumerate(write_ops):
            actual_content = (temp_dir / f"write_{i}.txt").read_text()
            assert actual_content == expected_content

    @pytest.mark.asyncio
    async def test_mixed_concurrent_operations(self, file_ops, temp_dir):
        """Test mixed concurrent read/write/list operations."""
        # Prepare existing files
        for i in range(3):
            (temp_dir / f"existing_{i}.txt").write_text(f"content {i}")

        # Define mixed operations
        tasks = [
            file_ops.read_file(str(temp_dir / "existing_0.txt")),
            file_ops.write_file(str(temp_dir / "new_1.txt"), "new content 1"),
            file_ops.list_directory(str(temp_dir)),
            file_ops.read_file(str(temp_dir / "existing_1.txt")),
            file_ops.write_file(str(temp_dir / "new_2.txt"), "new content 2"),
        ]

        # Execute all operations concurrently
        results = await asyncio.gather(*tasks)

        # Verify results
        assert results[0] == "content 0"  # read
        assert results[1] is True  # write
        assert isinstance(results[2], list)  # list
        assert results[3] == "content 1"  # read
        assert results[4] is True  # write


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
