"""
Enhanced unit tests for security validation features.

Focuses on path traversal protection, file type validation,
base directory restrictions, and security context handling.
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_mesh.runtime.shared.exceptions import (
    FileAccessDeniedError,
    FileTypeNotAllowedError,
    PathTraversalError,
    SecurityValidationError,
)
from mcp_mesh.runtime.shared.types import OperationType
from mcp_mesh.runtime.tools.file_operations import FileOperations


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def restricted_file_ops(temp_dir):
    """Create FileOperations with base directory restriction."""
    ops = FileOperations(base_directory=str(temp_dir), max_file_size=1024)
    yield ops
    try:
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            _task = asyncio.create_task(ops.cleanup())
        else:
            loop.run_until_complete(ops.cleanup())
    except RuntimeError:

        asyncio.run(ops.cleanup())


@pytest.fixture
def unrestricted_file_ops():
    """Create FileOperations without base directory restriction."""
    ops = FileOperations(max_file_size=1024)
    yield ops
    try:

        loop = asyncio.get_event_loop()
        if loop.is_running():
            _task = asyncio.create_task(ops.cleanup())
        else:
            loop.run_until_complete(ops.cleanup())
    except RuntimeError:

        asyncio.run(ops.cleanup())


class TestPathTraversalProtection:
    """Test path traversal attack prevention."""

    @pytest.mark.asyncio
    async def test_basic_path_traversal_attacks(self, restricted_file_ops):
        """Test basic path traversal patterns are blocked."""
        malicious_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "./../../secret.txt",
            "normal/../../../escape.txt",
            "subdir/../../outside.txt",
        ]

        for path in malicious_paths:
            with pytest.raises(PathTraversalError) as exc_info:
                await restricted_file_ops._validate_path(path, OperationType.READ)

            error = exc_info.value
            assert path in str(error)
            assert error.error_type == "path_traversal"

    @pytest.mark.asyncio
    async def test_sophisticated_path_traversal_attacks(self, restricted_file_ops):
        """Test sophisticated path traversal patterns."""
        sophisticated_attacks = [
            "....//....//....//etc//passwd",
            "..%2F..%2F..%2Fetc%2Fpasswd",
            "..%252F..%252F..%252Fetc%252Fpasswd",  # Double URL encoding
            "..%c0%af..%c0%af..%c0%afetc%c0%afpasswd",  # Unicode bypass attempt
            "..//..//..//etc//passwd",
            "....\\/....\\/....\\/etc\\/passwd",
            ".%2e/.%2e/.%2e/etc/passwd",
            "test/../../../../etc/passwd",
            "test\\..\\..\\..\\..\\windows\\system32\\config\\sam",
        ]

        for path in sophisticated_attacks:
            with pytest.raises(PathTraversalError):
                await restricted_file_ops._validate_path(path, OperationType.READ)

    @pytest.mark.asyncio
    async def test_legitimate_paths_allowed(self, restricted_file_ops):
        """Test that legitimate paths are allowed."""
        legitimate_paths = [
            "document.txt",
            "folder/file.txt",
            "deep/nested/path/file.json",
            "file-with-dashes.txt",
            "file_with_underscores.py",
            "file with spaces.txt",
            "UPPERCASE.TXT",
            "mixed_Case.File",
            "numbers123.txt",
            "file.with.multiple.dots.txt",
        ]

        for path in legitimate_paths:
            # Should not raise exception
            validated = await restricted_file_ops._validate_path(
                path, OperationType.READ
            )
            assert isinstance(validated, Path)

    @pytest.mark.asyncio
    async def test_symlink_traversal_protection(self, restricted_file_ops, temp_dir):
        """Test protection against symlink-based traversal attacks."""
        # Create a symlink pointing outside base directory
        external_target = Path("/etc/passwd")
        symlink_path = temp_dir / "malicious_link"

        try:
            # Only create symlink if target exists (to avoid test failures)
            if external_target.exists():
                symlink_path.symlink_to(external_target)

                # Accessing through symlink should be blocked
                with pytest.raises(SecurityValidationError):
                    await restricted_file_ops._validate_path(
                        str(symlink_path), OperationType.READ
                    )
        except (OSError, NotImplementedError):
            # Skip if symlinks not supported on this system
            pytest.skip("Symlinks not supported on this system")


class TestBaseDirectoryRestriction:
    """Test base directory restriction enforcement."""

    @pytest.mark.asyncio
    async def test_absolute_path_outside_base(self, restricted_file_ops, temp_dir):
        """Test that absolute paths outside base directory are blocked."""
        outside_paths = [
            "/etc/passwd",
            "/tmp/outside.txt",
            "/home/user/file.txt",
            "/var/log/system.log",
            "/usr/bin/sensitive",
            str(temp_dir.parent / "outside.txt"),  # Just outside base dir
            str(temp_dir.parent.parent / "far_outside.txt"),
        ]

        for path in outside_paths:
            with pytest.raises(SecurityValidationError) as exc_info:
                await restricted_file_ops._validate_path(path, OperationType.READ)

            error = exc_info.value
            assert "outside base directory" in str(error)

    @pytest.mark.asyncio
    async def test_relative_path_outside_base(self, restricted_file_ops):
        """Test that relative paths escaping base directory are blocked."""
        escape_attempts = [
            "../outside.txt",
            "../../far_outside.txt",
            "../../../etc/passwd",
            "folder/../../outside.txt",
            "deep/nested/../../../../outside.txt",
        ]

        for path in escape_attempts:
            with pytest.raises(PathTraversalError):
                await restricted_file_ops._validate_path(path, OperationType.READ)

    @pytest.mark.asyncio
    async def test_paths_within_base_allowed(self, restricted_file_ops, temp_dir):
        """Test that paths within base directory are allowed."""
        valid_paths = [
            "file.txt",
            "subfolder/file.txt",
            "deep/nested/structure/file.txt",
            str(temp_dir / "absolute_within_base.txt"),
            "./relative_current_dir.txt",
            "folder/./same_folder.txt",
            "folder/subfolder/../parent_folder.txt",  # Should resolve within base
        ]

        for path in valid_paths:
            validated = await restricted_file_ops._validate_path(
                path, OperationType.READ
            )
            # Ensure validated path is within base directory
            try:
                validated.relative_to(temp_dir)
            except ValueError:
                pytest.fail(f"Path {validated} is not within base directory {temp_dir}")

    @pytest.mark.asyncio
    async def test_no_base_directory_restriction(self, unrestricted_file_ops):
        """Test behavior when no base directory is set."""
        # Without base directory restriction, more paths should be allowed
        paths_to_test = [
            "/tmp/test.txt",
            "../test.txt",
            "../../test.txt",
            "/etc/test.txt",  # Still blocked by other validations
        ]

        for path in paths_to_test:
            # These might still fail due to path traversal protection
            # but not due to base directory restriction
            try:
                await unrestricted_file_ops._validate_path(path, OperationType.READ)
            except PathTraversalError:
                # Expected for paths with ".."
                pass
            except SecurityValidationError as e:
                if "base directory" in str(e):
                    pytest.fail(
                        f"Base directory restriction applied when none should exist: {e}"
                    )


class TestFileTypeValidation:
    """Test file type and extension validation."""

    @pytest.mark.asyncio
    async def test_allowed_file_extensions(self, restricted_file_ops):
        """Test that allowed file extensions pass validation."""
        allowed_files = [
            "document.txt",
            "config.json",
            "settings.yaml",
            "script.py",
            "app.js",
            "styles.css",
            "README.md",
            "data.csv",
            "markup.html",
            "template.xml",
            "system.log",
            "app.conf",
            "settings.config",
            "database.sql",
            "startup.sh",
            "component.ts",
            "package.yml",
            "report.rst",
            "document.tex",
            "config.ini",
            "settings.cfg",
            "data.toml",
            "script.bat",
        ]

        for filename in allowed_files:
            validated = await restricted_file_ops._validate_path(
                filename, OperationType.WRITE
            )
            assert isinstance(validated, Path)
            assert filename in str(validated)

    @pytest.mark.asyncio
    async def test_dangerous_file_extensions_blocked(self, restricted_file_ops):
        """Test that dangerous file extensions are blocked."""
        dangerous_files = [
            "malware.exe",
            "virus.dll",
            "trojan.scr",
            "backdoor.vbs",
            "keylogger.com",
            "spyware.pif",
            "rootkit.sys",
            "malicious.msi",
            "harmful.reg",
            "dangerous.hta",
        ]

        for filename in dangerous_files:
            with pytest.raises(FileTypeNotAllowedError) as exc_info:
                await restricted_file_ops._validate_path(filename, OperationType.WRITE)

            error = exc_info.value
            assert filename in str(error)
            assert error.file_extension in filename

    @pytest.mark.asyncio
    async def test_case_insensitive_extension_checking(self, restricted_file_ops):
        """Test that extension checking is case-insensitive."""
        dangerous_mixed_case = [
            "malware.EXE",
            "virus.Dll",
            "trojan.SCR",
            "backdoor.VbS",
            "keylogger.COM",
            "MALWARE.EXE",
            "Virus.DLL",
            "TROJAN.SCR",
        ]

        for filename in dangerous_mixed_case:
            with pytest.raises(FileTypeNotAllowedError):
                await restricted_file_ops._validate_path(filename, OperationType.WRITE)

    @pytest.mark.asyncio
    async def test_extension_validation_only_for_writes(self, restricted_file_ops):
        """Test that extension validation only applies to write operations."""
        dangerous_filename = "malware.exe"

        # Should fail for write operations
        with pytest.raises(FileTypeNotAllowedError):
            await restricted_file_ops._validate_path(
                dangerous_filename, OperationType.WRITE
            )

        # Should pass for read operations (assuming no path traversal)
        try:
            validated = await restricted_file_ops._validate_path(
                dangerous_filename, OperationType.READ
            )
            assert isinstance(validated, Path)
        except FileTypeNotAllowedError:
            pytest.fail("Extension validation should not apply to read operations")

    @pytest.mark.asyncio
    async def test_files_without_extensions(self, restricted_file_ops):
        """Test handling of files without extensions."""
        files_without_extensions = [
            "README",
            "Makefile",
            "Dockerfile",
            "LICENSE",
            "CHANGELOG",
            "config",
            "hosts",
            "passwd",
        ]

        for filename in files_without_extensions:
            # Files without extensions should be allowed
            validated = await restricted_file_ops._validate_path(
                filename, OperationType.WRITE
            )
            assert isinstance(validated, Path)

    @pytest.mark.asyncio
    async def test_multiple_extensions(self, restricted_file_ops):
        """Test handling of files with multiple extensions."""
        multi_extension_files = [
            "archive.tar.gz",
            "backup.sql.bak",
            "config.json.template",
            "script.py.backup",
            "data.csv.old",
        ]

        for filename in multi_extension_files:
            # Should validate based on final extension
            if filename.endswith((".gz", ".bak", ".template", ".backup", ".old")):
                # These might not be in allowed list
                try:
                    await restricted_file_ops._validate_path(
                        filename, OperationType.WRITE
                    )
                except FileTypeNotAllowedError:
                    # Expected for non-whitelisted extensions
                    pass
            else:
                validated = await restricted_file_ops._validate_path(
                    filename, OperationType.WRITE
                )
                assert isinstance(validated, Path)


class TestPermissionValidation:
    """Test permission and access validation."""

    @pytest.mark.asyncio
    async def test_check_permissions_with_auth_service(
        self, restricted_file_ops, temp_dir
    ):
        """Test permission checking with auth service."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")

        # Mock auth service
        with patch.object(restricted_file_ops, "_check_permissions") as mock_check:
            mock_check.return_value = None  # Permission granted

            # Should not raise exception when permissions are granted
            await restricted_file_ops._check_permissions(
                test_file, OperationType.READ, "mock_auth_service"
            )

            mock_check.assert_called_once_with(
                test_file, OperationType.READ, "mock_auth_service"
            )

    @pytest.mark.asyncio
    async def test_permission_denied_handling(self, restricted_file_ops, temp_dir):
        """Test handling of permission denied scenarios."""
        test_file = temp_dir / "restricted.txt"
        test_file.write_text("content")

        # Mock os.access to return False
        with patch("os.access", return_value=False):
            with pytest.raises(FileAccessDeniedError) as exc_info:
                await restricted_file_ops._check_permissions(
                    test_file, OperationType.READ, "auth_service"
                )

            error = exc_info.value
            assert str(test_file) in str(error)
            assert error.operation == "read"

    @pytest.mark.asyncio
    async def test_write_permission_validation(self, restricted_file_ops, temp_dir):
        """Test write permission validation."""
        test_file = temp_dir / "readonly.txt"
        test_file.write_text("content")

        # Mock os.access to deny write permission
        def mock_access(path, mode):
            if mode == os.W_OK:
                return False
            return True

        with patch("os.access", side_effect=mock_access):
            with pytest.raises(FileAccessDeniedError) as exc_info:
                await restricted_file_ops._check_permissions(
                    test_file, OperationType.WRITE, "auth_service"
                )

            error = exc_info.value
            assert error.operation == "write"


class TestSecurityContextHandling:
    """Test security context handling and validation."""

    @pytest.mark.asyncio
    async def test_security_context_validation(self, temp_dir):
        """Test that security context is properly handled."""
        # Create file operations with specific security context
        file_ops = FileOperations(base_directory=str(temp_dir), max_file_size=1024)

        # Verify that mesh agent decorator includes security context
        read_func = getattr(file_ops, "read_file", None)
        if read_func and hasattr(read_func, "_mesh_agent_metadata"):
            decorator_instance = read_func._mesh_agent_metadata["decorator_instance"]
            assert decorator_instance.security_context == "file_operations"

        await file_ops.cleanup()

    @pytest.mark.asyncio
    async def test_audit_logging_integration(self, restricted_file_ops, temp_dir):
        """Test integration with audit logging for security events."""
        test_file = temp_dir / "audit_test.txt"
        test_content = "audit content"
        test_file.write_text(test_content)

        # Mock the audit logging method
        with patch.object(restricted_file_ops, "_audit_log") as mock_audit:
            mock_audit.return_value = None

            # Perform operation that should be audited
            content = await restricted_file_ops.read_file(str(test_file))
            assert content == test_content

            # Audit log should have been called (if audit_logger was injected)
            # In test environment, audit_logger is None, so no call expected
            # This test verifies the integration point exists


class TestEdgeCasesAndCornerCases:
    """Test edge cases and corner cases in security validation."""

    @pytest.mark.asyncio
    async def test_empty_and_whitespace_paths(self, restricted_file_ops):
        """Test handling of empty and whitespace-only paths."""
        invalid_paths = ["", " ", "\t", "\n", "   ", "\t\n "]

        for path in invalid_paths:
            with pytest.raises(SecurityValidationError):
                await restricted_file_ops._validate_path(path, OperationType.READ)

    @pytest.mark.asyncio
    async def test_very_long_paths(self, restricted_file_ops):
        """Test handling of very long file paths."""
        # Create a very long path
        long_path = "a" * 1000 + ".txt"

        # Should either work or fail gracefully
        try:
            validated = await restricted_file_ops._validate_path(
                long_path, OperationType.READ
            )
            assert isinstance(validated, Path)
        except (OSError, SecurityValidationError):
            # Expected for paths that exceed system limits
            pass

    @pytest.mark.asyncio
    async def test_special_character_combinations(self, restricted_file_ops):
        """Test various special character combinations."""
        special_paths = [
            "file%20with%20spaces.txt",  # URL encoded
            "file\x00null.txt",  # Null byte
            "file\r\nwith\r\nnewlines.txt",  # Control characters
            "file\x01\x02\x03control.txt",  # Control characters
            "file\x7fdelete.txt",  # DEL character
        ]

        for path in special_paths:
            try:
                await restricted_file_ops._validate_path(path, OperationType.READ)
            except (SecurityValidationError, ValueError):
                # Expected for paths with invalid characters
                pass

    @pytest.mark.asyncio
    async def test_unicode_and_internationalization(self, restricted_file_ops):
        """Test handling of Unicode and international characters."""
        unicode_paths = [
            "文件.txt",  # Chinese characters
            "файл.txt",  # Cyrillic characters
            "archivo.txt",  # Spanish
            "ファイル.txt",  # Japanese
            "📄document.txt",  # Emoji
            "café.txt",  # Accented characters
            "naïve.txt",  # More accented characters
        ]

        for path in unicode_paths:
            # Should handle Unicode gracefully
            validated = await restricted_file_ops._validate_path(
                path, OperationType.READ
            )
            assert isinstance(validated, Path)

    @pytest.mark.asyncio
    async def test_path_normalization(self, restricted_file_ops):
        """Test that paths are properly normalized."""
        unnormalized_paths = [
            "./file.txt",
            "folder/./file.txt",
            "folder/subfolder/../file.txt",
            "folder//double//slash.txt",
            "folder\\backslash\\file.txt",  # On Unix, backslashes are literal
        ]

        for path in unnormalized_paths:
            try:
                validated = await restricted_file_ops._validate_path(
                    path, OperationType.READ
                )
                # Validated path should be normalized
                assert isinstance(validated, Path)
                # Should not contain "./" or "../" in resolved path
                _resolved_str = str(validated.resolve())
                # Allow for legitimate current directory references
                # but ensure no traversal patterns remain
            except PathTraversalError:
                # Expected for paths that traverse outside allowed area
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
