"""Exception classes for MCP Mesh operations."""


class FileOperationError(Exception):
    """Base exception for file operation errors."""

    pass


class SecurityValidationError(FileOperationError):
    """Raised when security validation fails."""

    pass


class PermissionDeniedError(FileOperationError):
    """Raised when file access is denied due to permissions."""

    pass
