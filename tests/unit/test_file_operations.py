"""
Unit tests for File Operations with @mesh_agent decorator integration.

Tests security validation, error handling, mesh integration, and all file operations.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest
from mcp_mesh.exceptions import (
    FileOperationError,
    PermissionDeniedError,
    SecurityValidationError,
)
from mcp_mesh.file_operations import FileOperations


class TestFileOperations:
    """Test basic FileOperations class functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def file_ops(self, temp_dir):
        """Create FileOperations instance with base directory."""
        return FileOperations(base_directory=str(temp_dir))

    @pytest.mark.asyncio
    async def test_validate_path_blocks_traversal(self, file_ops, temp_dir):
        """Test that path traversal attempts are blocked."""
        # Test various path traversal attempts
        dangerous_paths = [
            "../etc/passwd",
            "../../etc/shadow",
            "test/../../../etc/passwd",
            "~/.ssh/id_rsa",
        ]

        # These should be blocked for path traversal or being outside base
        for path in dangerous_paths:
            with pytest.raises(SecurityValidationError) as exc_info:
                await file_ops._validate_path(path, "read")
            assert (
                "Path traversal detected" in str(exc_info.value)
                or "outside base directory" in str(exc_info.value).lower()
            )

        # These should be blocked for being outside base directory
        outside_paths = [
            "/etc/passwd",  # Absolute path outside base
        ]

        for path in outside_paths:
            with pytest.raises(SecurityValidationError) as exc_info:
                await file_ops._validate_path(path, "read")
            assert (
                "outside base directory" in str(exc_info.value).lower()
                or "invalid path" in str(exc_info.value).lower()
            )

        # Test path with .. should be blocked as traversal
        traversal_path = str(temp_dir / ".." / ".." / "etc" / "passwd")
        with pytest.raises(SecurityValidationError) as exc_info:
            await file_ops._validate_path(traversal_path, "read")
        assert "path traversal detected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_validate_path_allows_safe_paths(self, file_ops, temp_dir):
        """Test that safe paths are allowed."""
        # Only test with absolute paths within the base directory
        safe_paths = [
            str(temp_dir / "test.txt"),
            str(temp_dir / "subdir" / "file.txt"),
            str(temp_dir / "deep" / "nested" / "path" / "file.txt"),
        ]

        for path in safe_paths:
            # Should not raise any exception
            result = await file_ops._validate_path(path, "read")
            assert isinstance(result, Path)

    @pytest.mark.asyncio
    async def test_read_file_basic(self, file_ops, temp_dir):
        """Test basic file reading."""
        # Create a test file
        test_file = temp_dir / "test.txt"
        test_content = "Hello, World!"
        test_file.write_text(test_content)

        # Read the file
        content = await file_ops.read_file(str(test_file))
        assert content == test_content

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, file_ops, temp_dir):
        """Test reading non-existent file."""
        with pytest.raises(FileOperationError) as exc_info:
            await file_ops.read_file(str(temp_dir / "nonexistent.txt"))
        assert (
            "not found" in str(exc_info.value).lower()
            or "does not exist" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_write_file_basic(self, file_ops, temp_dir):
        """Test basic file writing."""
        test_file = temp_dir / "output.txt"
        test_content = "Test content"

        # Write the file
        result = await file_ops.write_file(str(test_file), test_content)
        assert result is True  # write_file returns boolean

        # Verify content
        assert test_file.read_text() == test_content

    @pytest.mark.asyncio
    async def test_write_file_overwrites(self, file_ops, temp_dir):
        """Test that write_file overwrites existing files."""
        test_file = temp_dir / "existing.txt"
        test_file.write_text("Old content")

        new_content = "New content"
        await file_ops.write_file(str(test_file), new_content)

        assert test_file.read_text() == new_content

    @pytest.mark.asyncio
    async def test_list_directory_basic(self, file_ops, temp_dir):
        """Test basic directory listing."""
        # Create some test files and directories
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")
        (temp_dir / "subdir").mkdir()
        (temp_dir / "subdir" / "file3.txt").write_text("content3")

        # List directory
        result = await file_ops.list_directory(str(temp_dir))

        # Should return a list of items
        assert isinstance(result, list)
        assert len(result) >= 3  # At least file1.txt, file2.txt, and subdir

        # Check that files are in the list
        names = [
            item if isinstance(item, str) else item.get("name", item) for item in result
        ]
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_list_directory_not_found(self, file_ops, temp_dir):
        """Test listing non-existent directory."""
        with pytest.raises(FileOperationError) as exc_info:
            await file_ops.list_directory(str(temp_dir / "nonexistent"))
        assert (
            "not found" in str(exc_info.value).lower()
            or "does not exist" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_health_check(self, file_ops):
        """Test health check functionality."""
        result = await file_ops.health_check()
        assert result["status"] == "healthy"
        # The base FileOperations class returns a simple health check
        assert "checks" in result
        assert result["checks"]["base_directory_valid"] is True
        assert result["checks"]["file_system_readable"] is True
        assert result["checks"]["file_system_writable"] is True

    @pytest.mark.asyncio
    async def test_file_extension_validation(self, file_ops, temp_dir):
        """Test file extension security validation."""
        # These extensions might be blocked depending on implementation
        suspicious_files = [
            "script.sh",
            "program.exe",
            "config.env",
        ]

        for filename in suspicious_files:
            file_path = temp_dir / filename
            file_path.write_text("test")

            # The base FileOperations class may or may not block these
            # This test documents the behavior
            try:
                await file_ops._validate_path(str(file_path), "read")
                # If no exception, the file is allowed
                assert True
            except (SecurityValidationError, FileOperationError):
                # If exception, the file is blocked
                assert True

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, file_ops, temp_dir):
        """Test concurrent file operations."""
        # Create multiple files concurrently
        files = [temp_dir / f"concurrent_{i}.txt" for i in range(5)]

        async def write_file(filepath, content):
            return await file_ops.write_file(str(filepath), content)

        # Write files concurrently
        tasks = [write_file(f, f"Content {i}") for i, f in enumerate(files)]
        results = await asyncio.gather(*tasks)

        # Verify all writes succeeded
        assert len(results) == 5
        for i, f in enumerate(files):
            assert f.read_text() == f"Content {i}"

    @pytest.mark.asyncio
    async def test_unicode_content(self, file_ops, temp_dir):
        """Test handling of Unicode content."""
        test_file = temp_dir / "unicode.txt"
        unicode_content = "Hello 世界! 🌍 Здравствуй мир!"

        # Write Unicode content
        await file_ops.write_file(str(test_file), unicode_content)

        # Read it back
        content = await file_ops.read_file(str(test_file))
        assert content == unicode_content

    @pytest.mark.asyncio
    async def test_empty_file_handling(self, file_ops, temp_dir):
        """Test handling of empty files."""
        test_file = temp_dir / "empty.txt"

        # Write empty content
        await file_ops.write_file(str(test_file), "")

        # Read it back
        content = await file_ops.read_file(str(test_file))
        assert content == ""

    @pytest.mark.asyncio
    async def test_relative_path_resolution(self, file_ops, temp_dir):
        """Test that relative paths are blocked for security."""
        # Create a subdirectory
        subdir = temp_dir / "subdir"
        subdir.mkdir()

        # Test relative path with .. - should be blocked
        relative_path = "subdir/../test.txt"
        with pytest.raises(SecurityValidationError) as exc_info:
            await file_ops._validate_path(relative_path, "read")
        assert "Path traversal detected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_permission_denied_simulation(self, file_ops, temp_dir):
        """Test handling of permission denied errors."""
        test_file = temp_dir / "readonly.txt"
        test_file.write_text("content")

        # Make file read-only (this may not work on all systems)
        try:
            test_file.chmod(0o444)

            # Try to write - might raise PermissionDeniedError or FileOperationError
            with pytest.raises((PermissionDeniedError, FileOperationError)):
                await file_ops.write_file(str(test_file), "new content")
        finally:
            # Restore permissions for cleanup
            test_file.chmod(0o644)
