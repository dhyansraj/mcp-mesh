"""
Unit tests for File Operations with @mesh_agent decorator integration.

Tests security validation, error handling, mesh integration, and all file operations.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

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
    OperationType,
    RetryConfig,
    RetryStrategy,
)
from mcp_mesh_runtime.tools.file_operations import FileOperations


@pytest.fixture
async def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
async def file_ops(temp_dir):
    """Create FileOperations instance with temporary base directory."""
    ops = FileOperations(base_directory=str(temp_dir), max_file_size=1024)
    yield ops
    await ops.cleanup()


@pytest.fixture
async def unrestricted_file_ops():
    """Create FileOperations instance without base directory restriction."""
    ops = FileOperations(max_file_size=1024)
    yield ops
    await ops.cleanup()


class TestFileOperationsBasic:
    """Test basic file operations functionality."""

    async def test_read_file_success(self, file_ops, temp_dir):
        """Test successful file reading."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_content = "Hello, MCP-Mesh!"
        test_file.write_text(test_content)

        # Read file
        content = await file_ops.read_file(str(test_file))
        assert content == test_content

    async def test_write_file_success(self, file_ops, temp_dir):
        """Test successful file writing."""
        test_file = temp_dir / "new_file.txt"
        test_content = "New content"

        result = await file_ops.write_file(str(test_file), test_content)
        assert result is True
        assert test_file.read_text() == test_content

    async def test_list_directory_success(self, file_ops, temp_dir):
        """Test successful directory listing."""
        # Create test files
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.json").write_text('{"key": "value"}')
        (temp_dir / ".hidden").write_text("hidden content")
        (temp_dir / "subdir").mkdir()

        # List without hidden files
        entries = await file_ops.list_directory(str(temp_dir))
        visible_entries = [e for e in entries if not e.startswith(".")]
        assert len(visible_entries) == 3  # file1.txt, file2.json, subdir
        assert "file1.txt" in entries
        assert "file2.json" in entries
        assert "subdir" in entries
        assert ".hidden" not in entries

    async def test_list_directory_with_hidden(self, file_ops, temp_dir):
        """Test directory listing including hidden files."""
        # Create test files
        (temp_dir / "visible.txt").write_text("content")
        (temp_dir / ".hidden").write_text("hidden")

        entries = await file_ops.list_directory(str(temp_dir), include_hidden=True)
        assert "visible.txt" in entries
        assert ".hidden" in entries

    async def test_list_directory_with_details(self, file_ops, temp_dir):
        """Test directory listing with detailed information."""
        # Create test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        entries = await file_ops.list_directory(str(temp_dir), include_details=True)
        assert len(entries) == 1

        entry = entries[0]
        assert isinstance(entry, dict)
        assert entry["name"] == "test.txt"
        assert entry["type"] == "file"
        assert entry["size"] == 7  # "content" = 7 bytes
        assert "modified" in entry
        assert "permissions" in entry


class TestSecurityValidation:
    """Test security validation and path checking."""

    async def test_path_traversal_protection(self, file_ops):
        """Test protection against path traversal attacks."""
        malicious_paths = [
            "../../../etc/passwd",
            "../../secret.txt",
            "../outside.txt",
            "subdir/../../escape.txt",
            "./../config",
            "test/../../../etc/shadow",
            "normal/../../sensitive.txt",
        ]

        for path in malicious_paths:
            with pytest.raises(PathTraversalError):
                await file_ops._validate_path(path, OperationType.READ)

    async def test_base_directory_restriction(self, file_ops, temp_dir):
        """Test base directory restriction enforcement."""
        # Try to access file outside base directory
        outside_file = "/tmp/outside_file.txt"

        with pytest.raises(
            SecurityValidationError, match="Path outside base directory"
        ):
            await file_ops._validate_path(outside_file, OperationType.READ)

    async def test_file_extension_validation(self, file_ops):
        """Test file extension validation for write operations."""
        # Allowed extensions should work
        allowed_extensions = [".txt", ".json", ".yaml", ".py", ".md", ".csv"]
        for ext in allowed_extensions:
            valid_path = f"test{ext}"
            validated = await file_ops._validate_path(valid_path, OperationType.WRITE)
            assert validated.name == f"test{ext}"

        # Disallowed extensions should fail
        disallowed_extensions = [".exe", ".dll", ".bat", ".cmd", ".scr", ".vbs"]
        for ext in disallowed_extensions:
            invalid_path = f"malicious{ext}"
            with pytest.raises(FileTypeNotAllowedError):
                await file_ops._validate_path(invalid_path, OperationType.WRITE)

    async def test_extension_case_sensitivity(self, file_ops):
        """Test file extension validation is case-insensitive."""
        # These should all fail regardless of case
        dangerous_extensions = [".EXE", ".Exe", ".DLL", ".BAT"]
        for ext in dangerous_extensions:
            invalid_path = f"malicious{ext}"
            with pytest.raises(FileTypeNotAllowedError):
                await file_ops._validate_path(invalid_path, OperationType.WRITE)

    async def test_max_file_size_read(self, file_ops, temp_dir):
        """Test maximum file size enforcement for reading."""
        # Create file larger than max size
        large_file = temp_dir / "large.txt"
        large_content = "x" * (file_ops.max_file_size + 1)
        large_file.write_text(large_content)

        with pytest.raises(FileTooLargeError):
            await file_ops.read_file(str(large_file))

    async def test_max_file_size_write(self, file_ops, temp_dir):
        """Test maximum file size enforcement for writing."""
        test_file = temp_dir / "test.txt"
        large_content = "x" * (file_ops.max_file_size + 1)

        with pytest.raises(FileTooLargeError):
            await file_ops.write_file(str(test_file), large_content)

    async def test_empty_path_handling(self, file_ops):
        """Test handling of empty or invalid paths."""
        invalid_paths = ["", " ", "\t", "\n", None]

        for path in invalid_paths[
            :4
        ]:  # Skip None for now as it needs different handling
            with pytest.raises(SecurityValidationError):
                await file_ops._validate_path(path, OperationType.READ)

    async def test_special_characters_in_paths(self, file_ops, temp_dir):
        """Test handling of special characters in file paths."""
        # These should work (normal special chars)
        valid_chars = ["-", "_", ".", " ", "(", ")", "[", "]"]
        for char in valid_chars:
            if char != ".":  # Avoid creating hidden files
                test_file = temp_dir / f"test{char}file.txt"
                validated = await file_ops._validate_path(
                    str(test_file), OperationType.WRITE
                )
                assert test_file.name in str(validated)


class TestErrorHandling:
    """Test comprehensive error handling."""

    async def test_read_nonexistent_file(self, file_ops, temp_dir):
        """Test reading non-existent file."""
        nonexistent_file = temp_dir / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            await file_ops.read_file(str(nonexistent_file))

    async def test_read_directory_as_file(self, file_ops, temp_dir):
        """Test reading directory as file."""
        test_dir = temp_dir / "testdir"
        test_dir.mkdir()

        with pytest.raises(FileOperationError):
            await file_ops.read_file(str(test_dir))

    async def test_list_nonexistent_directory(self, file_ops, temp_dir):
        """Test listing non-existent directory."""
        nonexistent_dir = temp_dir / "nonexistent"

        with pytest.raises(DirectoryNotFoundError):
            await file_ops.list_directory(str(nonexistent_dir))

    async def test_list_file_as_directory(self, file_ops, temp_dir):
        """Test listing file as directory."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        with pytest.raises(FileOperationError, match="Path is not a directory"):
            await file_ops.list_directory(str(test_file))

    async def test_invalid_encoding(self, file_ops, temp_dir):
        """Test handling of encoding errors."""
        # Create binary file
        binary_file = temp_dir / "binary.bin"
        binary_file.write_bytes(b"\x80\x81\x82\x83")

        with pytest.raises(EncodingError):
            await file_ops.read_file(str(binary_file), encoding="utf-8")


class TestBackupCreation:
    """Test backup functionality."""

    async def test_local_backup_creation(self, file_ops, temp_dir):
        """Test local backup file creation."""
        test_file = temp_dir / "test.txt"
        original_content = "original content"
        test_file.write_text(original_content)

        # Create backup
        await file_ops._create_local_backup(test_file)

        # Check backup was created
        backup_files = list(temp_dir.glob("test.txt.backup.*"))
        assert len(backup_files) == 1

        backup_file = backup_files[0]
        assert backup_file.read_text() == original_content

    async def test_write_with_backup(self, file_ops, temp_dir):
        """Test file writing with automatic backup."""
        test_file = temp_dir / "test.txt"
        original_content = "original"
        new_content = "new content"

        # Create original file
        test_file.write_text(original_content)

        # Write new content with backup
        await file_ops.write_file(str(test_file), new_content, create_backup=True)

        # Check new content
        assert test_file.read_text() == new_content

        # Check backup was created
        backup_files = list(temp_dir.glob("test.txt.backup.*"))
        assert len(backup_files) == 1
        assert backup_files[0].read_text() == original_content


class TestMeshIntegration:
    """Test mesh agent decorator integration."""

    @patch("mcp_mesh.tools.file_operations.mesh_agent")
    async def test_mesh_decorator_applied(self, mock_mesh_agent):
        """Test that @mesh_agent decorator is properly applied."""
        # Mock the decorator
        mock_mesh_agent.return_value = lambda func: func

        # Create file operations instance
        file_ops = FileOperations()

        # Verify mesh_agent was called for each operation
        assert mock_mesh_agent.call_count >= 3  # read, write, list operations

        # Check decorator parameters
        calls = mock_mesh_agent.call_args_list
        for call in calls:
            kwargs = call[1]
            assert "capabilities" in kwargs
            assert "dependencies" in kwargs
            assert "health_interval" in kwargs
            assert "security_context" in kwargs
            assert kwargs["fallback_mode"] is True

        await file_ops.cleanup()

    async def test_dependency_injection_handling(self, file_ops, temp_dir):
        """Test handling of injected dependencies."""
        test_file = temp_dir / "test.txt"
        test_content = "test content"

        # The mesh decorator should inject dependencies, but operations should
        # work even when dependencies are None (fallback mode)
        result = await file_ops.write_file(str(test_file), test_content)
        assert result is True

        content = await file_ops.read_file(str(test_file))
        assert content == test_content

    async def test_health_check(self, file_ops):
        """Test health check functionality."""
        health_status = await file_ops.health_check()

        assert health_status.agent_name == "file-operations-agent"
        assert health_status.status in ["healthy", "degraded"]
        assert len(health_status.capabilities) > 0
        assert "file_read" in health_status.capabilities
        assert "file_write" in health_status.capabilities
        assert "directory_list" in health_status.capabilities
        assert health_status.timestamp is not None
        assert "checks" in health_status.metadata


class TestConcurrency:
    """Test concurrent operations."""

    async def test_concurrent_reads(self, file_ops, temp_dir):
        """Test concurrent file reading."""
        # Create test files
        files = []
        for i in range(5):
            test_file = temp_dir / f"test_{i}.txt"
            test_file.write_text(f"content {i}")
            files.append(str(test_file))

        # Read all files concurrently
        tasks = [file_ops.read_file(f) for f in files]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        for i, content in enumerate(results):
            assert content == f"content {i}"

    async def test_concurrent_writes(self, file_ops, temp_dir):
        """Test concurrent file writing."""
        # Define write operations
        writes = []
        for i in range(5):
            test_file = temp_dir / f"concurrent_{i}.txt"
            content = f"concurrent content {i}"
            writes.append((str(test_file), content))

        # Perform all writes concurrently
        tasks = [file_ops.write_file(path, content) for path, content in writes]
        results = await asyncio.gather(*tasks)

        assert all(results)  # All writes should succeed

        # Verify all files were written correctly
        for i, (_path, expected_content) in enumerate(writes):
            actual_content = (temp_dir / f"concurrent_{i}.txt").read_text()
            assert actual_content == expected_content


class TestMCPProtocolCompliance:
    """Test MCP protocol compliance features."""

    async def test_error_message_format(self, file_ops, temp_dir):
        """Test that errors have proper format for MCP protocol."""
        try:
            await file_ops.read_file("nonexistent.txt")
        except FileOperationError as e:
            error_msg = str(e)
            assert "File not found" in error_msg
            assert "nonexistent.txt" in error_msg

    async def test_return_type_consistency(self, file_ops, temp_dir):
        """Test that return types are consistent and JSON-serializable."""
        # Create test setup
        test_file = temp_dir / "test.txt"
        test_content = "test content"
        test_file.write_text(test_content)

        # Test read_file returns string
        content = await file_ops.read_file(str(test_file))
        assert isinstance(content, str)

        # Test write_file returns bool
        result = await file_ops.write_file(str(test_file), "new content")
        assert isinstance(result, bool)

        # Test list_directory returns list
        entries = await file_ops.list_directory(str(temp_dir))
        assert isinstance(entries, list)

        # Test list_directory with details returns list of dicts
        detailed_entries = await file_ops.list_directory(
            str(temp_dir), include_details=True
        )
        assert isinstance(detailed_entries, list)
        if detailed_entries:
            assert isinstance(detailed_entries[0], dict)


@pytest.mark.asyncio
class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    async def test_complete_workflow(self, file_ops, temp_dir):
        """Test complete file operation workflow."""
        # 1. Create a file
        config_file = temp_dir / "config.json"
        config_content = '{"app": "mcp-mesh", "version": "1.0"}'

        result = await file_ops.write_file(str(config_file), config_content)
        assert result is True

        # 2. Read the file back
        read_content = await file_ops.read_file(str(config_file))
        assert read_content == config_content

        # 3. List directory to verify file exists
        entries = await file_ops.list_directory(str(temp_dir))
        assert "config.json" in entries

        # 4. Update the file (with backup)
        updated_config = '{"app": "mcp-mesh", "version": "1.1", "updated": true}'
        result = await file_ops.write_file(
            str(config_file), updated_config, create_backup=True
        )
        assert result is True

        # 5. Verify update
        final_content = await file_ops.read_file(str(config_file))
        assert final_content == updated_config

        # 6. Verify backup was created
        backup_files = list(temp_dir.glob("config.json.backup.*"))
        assert len(backup_files) == 1
        assert backup_files[0].read_text() == config_content

    async def test_security_scenario(self, unrestricted_file_ops):
        """Test security validation in realistic scenarios."""
        # These should all fail with security validation
        malicious_operations = [
            ("read", "../../../etc/passwd"),
            ("read", "..\\..\\windows\\system32\\config\\sam"),
            ("write", "../escape.txt"),
            ("read", "/etc/shadow"),
        ]

        for operation, path in malicious_operations:
            with pytest.raises(SecurityValidationError):
                if operation == "read":
                    await unrestricted_file_ops.read_file(path)
                elif operation == "write":
                    await unrestricted_file_ops.write_file(path, "malicious content")


class TestRetryLogic:
    """Test retry logic and error recovery."""

    async def test_retry_config_creation(self):
        """Test retry configuration creation and validation."""
        retry_config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=5,
            initial_delay_ms=500,
            max_delay_ms=10000,
            backoff_multiplier=1.5,
            jitter=False,
        )

        assert retry_config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF
        assert retry_config.max_retries == 5
        assert retry_config.initial_delay_ms == 500
        assert retry_config.backoff_multiplier == 1.5
        assert retry_config.jitter is False

    async def test_retry_delay_calculation(self, file_ops):
        """Test retry delay calculation for different strategies."""
        # Exponential backoff
        exp_config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            initial_delay_ms=1000,
            backoff_multiplier=2.0,
            jitter=False,
        )

        delay_0 = await file_ops._calculate_retry_delay(0, exp_config)
        delay_1 = await file_ops._calculate_retry_delay(1, exp_config)
        delay_2 = await file_ops._calculate_retry_delay(2, exp_config)

        assert delay_0 == 1.0  # Base delay
        assert delay_1 == 2.0  # 1 * 2^1
        assert delay_2 == 4.0  # 1 * 2^2


class TestRateLimiting:
    """Test rate limiting functionality."""

    async def test_rate_limit_tracking(self, file_ops, temp_dir):
        """Test rate limiting tracking and enforcement."""
        # Create a test file
        test_file = temp_dir / "rate_test.txt"
        test_file.write_text("content")

        # Perform some operations to populate rate limit tracking
        for _i in range(3):
            await file_ops.read_file(str(test_file))

        # Check that operations are being tracked
        assert "read" in file_ops._operation_counts
        assert len(file_ops._operation_counts["read"]) == 3


class TestMCPErrorCompliance:
    """Test MCP JSON-RPC 2.0 error compliance."""

    async def test_error_structure(self, file_ops, temp_dir):
        """Test that errors have proper MCP JSON-RPC 2.0 structure."""
        nonexistent_file = temp_dir / "nonexistent.txt"
        with pytest.raises(FileNotFoundError) as exc_info:
            await file_ops.read_file(str(nonexistent_file))

        e = exc_info.value
        error_dict = e.to_dict()

        # Check required MCP error fields
        assert "code" in error_dict
        assert "message" in error_dict
        assert "data" in error_dict

        # Check specific error code
        assert error_dict["code"] == MCPErrorCode.FILE_NOT_FOUND

        # Check data structure
        data = error_dict["data"]
        assert "timestamp" in data
        assert "error_type" in data
        assert "file_path" in data
        assert data["error_type"] == "file_not_found"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
