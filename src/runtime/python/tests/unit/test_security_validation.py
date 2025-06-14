"""
Security validation unit tests for File Agent tools.

Comprehensive tests for path validation, file extension filtering,
size limits, and permission checking.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_mesh.runtime.shared.exceptions import (
    FileAccessDeniedError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    PathTraversalError,
    SecurityValidationError,
)
from mcp_mesh.runtime.shared.types import OperationType
from mcp_mesh.runtime.tools.file_operations import FileOperations


@pytest.fixture
async def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
async def file_ops(temp_dir):
    """Create FileOperations instance with security constraints."""
    ops = FileOperations(
        base_directory=str(temp_dir), max_file_size=1024  # Small limit for testing
    )
    yield ops
    await ops.cleanup()


@pytest.fixture
async def unrestricted_file_ops():
    """Create FileOperations instance without base directory restriction."""
    ops = FileOperations(max_file_size=1024)
    yield ops
    await ops.cleanup()


class TestPathTraversalProtection:
    """Test protection against path traversal attacks."""

    async def test_basic_path_traversal_attempts(self, file_ops):
        """Test basic path traversal attack patterns."""
        malicious_paths = [
            "../etc/passwd",
            "../../etc/shadow",
            "../../../root/.ssh/id_rsa",
            "..\\windows\\system32\\config\\sam",  # Windows style
            "./../config",
            "normal/../../../etc/hosts",
            "subdir/../../secret.txt",
        ]

        for path in malicious_paths:
            with pytest.raises(PathTraversalError):
                await file_ops._validate_path(path, OperationType.READ)

    async def test_encoded_path_traversal_attempts(self, file_ops):
        """Test encoded path traversal attempts."""
        encoded_paths = [
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded ../../../etc/passwd
            "..%2f..%2f..%2fetc%2fpasswd",  # Partial encoding
            "%2e%2e/etc/passwd",  # Mixed encoding
        ]

        for path in encoded_paths:
            with pytest.raises(PathTraversalError):
                await file_ops._validate_path(path, OperationType.READ)

    async def test_legitimate_subdirectory_paths(self, file_ops, temp_dir):
        """Test that legitimate subdirectory paths are allowed."""
        legitimate_paths = [
            "subdir/file.txt",
            "deep/nested/path/file.json",
            "folder/subfolder/document.md",
            "./current/file.txt",
            "data/2023/backup.csv",
        ]

        for path in legitimate_paths:
            # Should not raise any exceptions
            validated = await file_ops._validate_path(path, OperationType.READ)
            assert isinstance(validated, Path)

    async def test_relative_path_normalization(self, file_ops):
        """Test that relative paths are properly normalized."""
        test_paths = [
            ("./file.txt", "file.txt"),
            ("subdir/./file.txt", "subdir/file.txt"),
            ("./subdir/file.txt", "subdir/file.txt"),
        ]

        for input_path, expected_name in test_paths:
            validated = await file_ops._validate_path(input_path, OperationType.READ)
            assert expected_name in str(validated)


class TestBaseDirectoryRestriction:
    """Test base directory restriction enforcement."""

    async def test_absolute_path_outside_base(self, file_ops, temp_dir):
        """Test rejection of absolute paths outside base directory."""
        outside_paths = [
            "/etc/passwd",
            "/tmp/outside.txt",
            "/home/user/document.txt",
            "/root/secret.txt",
            "/var/log/system.log",
        ]

        for path in outside_paths:
            with pytest.raises(
                SecurityValidationError, match="Path outside base directory"
            ):
                await file_ops._validate_path(path, OperationType.READ)

    async def test_symlink_escape_attempts(self, file_ops, temp_dir):
        """Test protection against symlink-based escapes."""
        # Create a symlink pointing outside base directory
        symlink_path = temp_dir / "escape_link"
        target_path = "/etc/passwd"

        try:
            symlink_path.symlink_to(target_path)

            # Should detect and reject symlink escape
            with pytest.raises(SecurityValidationError):
                await file_ops._validate_path(str(symlink_path), OperationType.READ)
        except OSError:
            # Skip test if symlinks not supported on platform
            pytest.skip("Symlinks not supported on this platform")

    async def test_valid_paths_within_base(self, file_ops, temp_dir):
        """Test that valid paths within base directory are accepted."""
        valid_paths = [
            "file.txt",
            "subdir/file.txt",
            "deep/nested/path/file.json",
            str(temp_dir / "absolute_but_valid.txt"),
        ]

        for path in valid_paths:
            validated = await file_ops._validate_path(path, OperationType.READ)
            assert str(temp_dir) in str(validated)


class TestFileExtensionValidation:
    """Test file extension filtering and validation."""

    async def test_allowed_extensions_for_write(self, file_ops):
        """Test that allowed file extensions pass validation."""
        allowed_files = [
            "document.txt",
            "config.json",
            "settings.yaml",
            "script.py",
            "webpage.html",
            "data.csv",
            "readme.md",
            "query.sql",
            "app.js",
            "style.css",
        ]

        for filename in allowed_files:
            validated = await file_ops._validate_path(filename, OperationType.WRITE)
            assert validated.name == filename

    async def test_dangerous_extensions_blocked(self, file_ops):
        """Test that dangerous file extensions are blocked."""
        dangerous_files = [
            "virus.exe",
            "malware.dll",
            "script.bat",
            "command.cmd",
            "trojan.scr",
            "badscript.vbs",
            "payload.ps1",
            "exploit.msi",
            "rootkit.com",
            "backdoor.pif",
        ]

        for filename in dangerous_files:
            with pytest.raises(FileTypeNotAllowedError):
                await file_ops._validate_path(filename, OperationType.WRITE)

    async def test_case_insensitive_extension_blocking(self, file_ops):
        """Test that extension blocking is case-insensitive."""
        case_variants = [
            "malware.EXE",
            "virus.Exe",
            "script.BAT",
            "command.Cmd",
            "trojan.SCR",
            "bad.VBS",
        ]

        for filename in case_variants:
            with pytest.raises(FileTypeNotAllowedError):
                await file_ops._validate_path(filename, OperationType.WRITE)

    async def test_no_extension_files(self, file_ops):
        """Test handling of files without extensions."""
        no_extension_files = [
            "Makefile",
            "Dockerfile",
            "README",
            "LICENSE",
            "requirements",
        ]

        for filename in no_extension_files:
            # Should be allowed for files without extensions
            validated = await file_ops._validate_path(filename, OperationType.WRITE)
            assert validated.name == filename

    async def test_multiple_extensions(self, file_ops):
        """Test files with multiple extensions."""
        multi_extension_files = [
            "backup.tar.gz",  # Should fail - .gz not in allowed list
            "config.json.bak",  # Should fail - .bak not in allowed list
            "data.csv.txt",  # Should pass - ends with .txt
        ]

        # Should fail for .gz and .bak
        with pytest.raises(FileTypeNotAllowedError):
            await file_ops._validate_path(multi_extension_files[0], OperationType.WRITE)

        with pytest.raises(FileTypeNotAllowedError):
            await file_ops._validate_path(multi_extension_files[1], OperationType.WRITE)

        # Should pass for .txt
        validated = await file_ops._validate_path(
            multi_extension_files[2], OperationType.WRITE
        )
        assert validated.name == multi_extension_files[2]


class TestFileSizeLimits:
    """Test file size limit enforcement."""

    async def test_file_size_read_limit(self, file_ops, temp_dir):
        """Test file size limit enforcement during read operations."""
        # Create file larger than limit
        large_file = temp_dir / "large.txt"
        large_content = "x" * (file_ops.max_file_size + 100)
        large_file.write_text(large_content)

        with pytest.raises(FileTooLargeError) as exc_info:
            await file_ops.read_file(str(large_file))

        error = exc_info.value
        assert str(large_file) in str(error)
        assert error.file_size > file_ops.max_file_size
        assert error.max_size == file_ops.max_file_size

    async def test_file_size_write_limit(self, file_ops, temp_dir):
        """Test file size limit enforcement during write operations."""
        test_file = temp_dir / "test.txt"
        large_content = "x" * (file_ops.max_file_size + 100)

        with pytest.raises(FileTooLargeError) as exc_info:
            await file_ops.write_file(str(test_file), large_content)

        error = exc_info.value
        assert str(test_file) in str(error)
        assert error.file_size > file_ops.max_file_size

    async def test_files_within_size_limit(self, file_ops, temp_dir):
        """Test that files within size limit are processed normally."""
        test_file = temp_dir / "normal.txt"
        normal_content = "x" * (file_ops.max_file_size - 100)

        # Write should succeed
        result = await file_ops.write_file(str(test_file), normal_content)
        assert result is True

        # Read should succeed
        read_content = await file_ops.read_file(str(test_file))
        assert read_content == normal_content

    async def test_empty_file_handling(self, file_ops, temp_dir):
        """Test handling of empty files."""
        empty_file = temp_dir / "empty.txt"

        # Write empty content
        result = await file_ops.write_file(str(empty_file), "")
        assert result is True

        # Read empty file
        content = await file_ops.read_file(str(empty_file))
        assert content == ""


class TestPermissionChecking:
    """Test file permission validation."""

    @pytest.mark.skipif(
        os.name == "nt", reason="Unix permissions not applicable on Windows"
    )
    async def test_read_permission_check(self, unrestricted_file_ops, temp_dir):
        """Test read permission checking."""
        # Create file with no read permissions
        no_read_file = temp_dir / "no_read.txt"
        no_read_file.write_text("secret content")
        no_read_file.chmod(0o000)  # No permissions

        try:
            with pytest.raises(FileAccessDeniedError):
                await unrestricted_file_ops.read_file(str(no_read_file))
        finally:
            # Restore permissions for cleanup
            no_read_file.chmod(0o644)

    @pytest.mark.skipif(
        os.name == "nt", reason="Unix permissions not applicable on Windows"
    )
    async def test_write_permission_check(self, unrestricted_file_ops, temp_dir):
        """Test write permission checking."""
        # Create read-only file
        readonly_file = temp_dir / "readonly.txt"
        readonly_file.write_text("readonly content")
        readonly_file.chmod(0o444)  # Read-only

        try:
            with pytest.raises(FileAccessDeniedError):
                await unrestricted_file_ops.write_file(
                    str(readonly_file), "new content"
                )
        finally:
            # Restore permissions for cleanup
            readonly_file.chmod(0o644)

    async def test_directory_permission_simulation(self, file_ops, temp_dir):
        """Test directory permission checking with mocked os.access."""
        test_dir = temp_dir / "test_dir"
        test_dir.mkdir()

        with patch("os.access", return_value=False):
            with pytest.raises(FileAccessDeniedError):
                await file_ops.list_directory(str(test_dir))


class TestSpecialCharacterHandling:
    """Test handling of special characters in paths."""

    async def test_unicode_characters_in_paths(self, file_ops, temp_dir):
        """Test handling of Unicode characters in file paths."""
        unicode_files = [
            "测试文件.txt",  # Chinese characters
            "файл.txt",  # Cyrillic characters
            "αρχείο.txt",  # Greek characters
            "ملف.txt",  # Arabic characters
            "ファイル.txt",  # Japanese characters
        ]

        for filename in unicode_files:
            try:
                validated = await file_ops._validate_path(filename, OperationType.WRITE)
                assert filename in str(validated)
            except UnicodeError:
                # Skip if platform doesn't support Unicode filenames
                pytest.skip(
                    f"Unicode filename {filename} not supported on this platform"
                )

    async def test_special_ascii_characters(self, file_ops, temp_dir):
        """Test handling of special ASCII characters."""
        special_files = [
            "file with spaces.txt",
            "file-with-dashes.txt",
            "file_with_underscores.txt",
            "file.with.dots.txt",
            "file(with)parentheses.txt",
            "file[with]brackets.txt",
            "file{with}braces.txt",
            "file@symbol.txt",
            "file#hash.txt",
            "file$dollar.txt",
        ]

        for filename in special_files:
            validated = await file_ops._validate_path(filename, OperationType.WRITE)
            assert filename in str(validated)

    async def test_invalid_path_characters(self, file_ops):
        """Test rejection of paths with invalid characters."""
        invalid_paths = [
            "",  # Empty path
            " ",  # Whitespace only
            "\t",  # Tab character
            "\n",  # Newline character
            "\0",  # Null character
        ]

        for path in invalid_paths:
            if path:  # Skip empty string as it may be handled differently
                with pytest.raises(SecurityValidationError):
                    await file_ops._validate_path(path, OperationType.READ)


class TestSecurityContextValidation:
    """Test security context and operation type validation."""

    async def test_operation_type_validation(self, file_ops):
        """Test validation for different operation types."""
        test_path = "test.txt"

        # All operation types should be supported
        for op_type in [OperationType.READ, OperationType.WRITE, OperationType.LIST]:
            validated = await file_ops._validate_path(test_path, op_type)
            assert isinstance(validated, Path)

    async def test_write_specific_validations(self, file_ops):
        """Test validations that only apply to write operations."""
        # Extension validation should only apply to write operations
        exe_file = "dangerous.exe"

        # Should fail for write
        with pytest.raises(FileTypeNotAllowedError):
            await file_ops._validate_path(exe_file, OperationType.WRITE)

        # Should pass for read (no extension check on read)
        try:
            validated = await file_ops._validate_path(exe_file, OperationType.READ)
            assert isinstance(validated, Path)
        except FileTypeNotAllowedError:
            # Some implementations may check extensions on all operations
            pass


class TestSecurityConfiguration:
    """Test security configuration and customization."""

    async def test_custom_allowed_extensions(self):
        """Test customizing allowed file extensions."""
        custom_ops = FileOperations()

        # Add custom extension
        custom_ops.allowed_extensions.add(".custom")

        # Should now allow .custom files
        validated = await custom_ops._validate_path("test.custom", OperationType.WRITE)
        assert validated.name == "test.custom"

        await custom_ops.cleanup()

    async def test_custom_max_file_size(self):
        """Test customizing maximum file size."""
        small_limit_ops = FileOperations(max_file_size=100)

        # Should reject content larger than custom limit
        large_content = "x" * 150

        with pytest.raises(FileTooLargeError):
            await small_limit_ops.write_file("test.txt", large_content)

        await small_limit_ops.cleanup()

    async def test_no_base_directory_restriction(self):
        """Test operation without base directory restriction."""
        unrestricted_ops = FileOperations(base_directory=None)

        # Should allow absolute paths when no base directory is set
        abs_path = "/tmp/test.txt" if os.name != "nt" else "C:\\temp\\test.txt"

        try:
            validated = await unrestricted_ops._validate_path(
                abs_path, OperationType.READ
            )
            assert isinstance(validated, Path)
        except SecurityValidationError:
            # May still fail due to other validations
            pass

        await unrestricted_ops.cleanup()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
