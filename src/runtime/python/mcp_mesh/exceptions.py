"""Exception classes for MCP Mesh operations.

This module provides basic exception classes for file operations.
Additional exception types are available in runtime.shared.exceptions.
"""


class FileOperationError(Exception):
    """Base exception for file operation errors."""

    pass


class SecurityValidationError(FileOperationError):
    """Raised when security validation fails."""

    pass


class PermissionDeniedError(FileOperationError):
    """Raised when file access is denied due to permissions."""

    pass
