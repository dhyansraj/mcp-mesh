"""MCP Mesh Exceptions

Custom exception classes for mesh operations with MCP JSON-RPC 2.0 compliance.
"""

from datetime import datetime
from enum import IntEnum
from typing import Any


class MCPErrorCode(IntEnum):
    """MCP JSON-RPC 2.0 standard error codes."""

    # Standard JSON-RPC errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # MCP-specific errors
    CAPABILITY_NOT_SUPPORTED = -32000
    RESOURCE_NOT_FOUND = -32001
    RESOURCE_ACCESS_DENIED = -32002
    RESOURCE_TIMEOUT = -32003
    RESOURCE_UNAVAILABLE = -32004
    VALIDATION_ERROR = -32005
    RATE_LIMIT_EXCEEDED = -32006
    SECURITY_VIOLATION = -32007

    # File operation specific errors
    FILE_NOT_FOUND = -33001
    FILE_ACCESS_DENIED = -33002
    FILE_TOO_LARGE = -33003
    FILE_TYPE_NOT_ALLOWED = -33004
    DIRECTORY_NOT_FOUND = -33005
    DISK_FULL = -33006
    ENCODING_ERROR = -33007
    PATH_TRAVERSAL = -33008

    # Mesh operation specific errors
    MESH_CONNECTION_FAILED = -34001
    MESH_TIMEOUT = -34002
    DEPENDENCY_INJECTION_FAILED = -34003
    HEALTH_CHECK_FAILED = -34004
    REGISTRY_UNAVAILABLE = -34005
    SERVICE_DEGRADED = -34006
    AGENT_NOT_FOUND = -34007
    CAPABILITY_MISMATCH = -34008


class MCPError(Exception):
    """Base MCP exception with JSON-RPC 2.0 compliance."""

    def __init__(
        self,
        message: str,
        code: MCPErrorCode | int,
        data: dict[str, Any] | None = None,
        request_id: str | None = None,
        retry_after: int | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = int(code)
        self.data = data or {}
        self.request_id = request_id
        self.retry_after = retry_after
        self.correlation_id = correlation_id
        self.timestamp = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to MCP JSON-RPC 2.0 error format."""
        data_dict = {
            **self.data,
            "timestamp": self.timestamp.isoformat(),
        }

        if self.correlation_id:
            data_dict["correlation_id"] = self.correlation_id

        if self.retry_after:
            data_dict["retry_after"] = self.retry_after

        error_dict = {
            "code": self.code,
            "message": self.message,
            "data": data_dict,
        }

        return error_dict

    def to_mcp_response(self) -> dict[str, Any]:
        """Convert to full MCP JSON-RPC 2.0 error response."""
        return {"jsonrpc": "2.0", "error": self.to_dict(), "id": self.request_id}


class MeshAgentError(MCPError):
    """Base exception for mesh agent operations."""

    def __init__(
        self,
        message: str,
        code: MCPErrorCode | int = MCPErrorCode.INTERNAL_ERROR,
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, code, data, **kwargs)


class FileOperationError(MeshAgentError):
    """Exception for file operation failures."""

    def __init__(
        self,
        message: str,
        file_path: str | None = None,
        operation: str | None = None,
        error_type: str = "file_operation",
        code: MCPErrorCode | int = MCPErrorCode.INTERNAL_ERROR,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {"error_type": error_type, "file_path": file_path, "operation": operation}
        )
        super().__init__(message, code, data, **kwargs)


class FileNotFoundError(FileOperationError):
    """Exception for file not found errors."""

    def __init__(self, file_path: str, **kwargs: Any) -> None:
        super().__init__(
            f"File not found: {file_path}",
            file_path=file_path,
            error_type="file_not_found",
            code=MCPErrorCode.FILE_NOT_FOUND,
            **kwargs,
        )


class FileAccessDeniedError(FileOperationError):
    """Exception for file access denied errors."""

    def __init__(
        self, file_path: str, operation: str = "access", **kwargs: Any
    ) -> None:
        super().__init__(
            f"Access denied for {operation} operation on: {file_path}",
            file_path=file_path,
            operation=operation,
            error_type="access_denied",
            code=MCPErrorCode.FILE_ACCESS_DENIED,
            **kwargs,
        )


class FileTooLargeError(FileOperationError):
    """Exception for file too large errors."""

    def __init__(self, file_path: str, size: int, max_size: int, **kwargs: Any) -> None:
        data = kwargs.pop("data", {})
        data.update({"actual_size": size, "max_size": max_size})
        super().__init__(
            f"File too large: {size} bytes > {max_size} bytes limit for {file_path}",
            file_path=file_path,
            error_type="file_too_large",
            code=MCPErrorCode.FILE_TOO_LARGE,
            data=data,
            **kwargs,
        )


class FileTypeNotAllowedError(FileOperationError):
    """Exception for file type not allowed errors."""

    def __init__(
        self,
        file_path: str,
        file_extension: str,
        allowed_extensions: list,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {"file_extension": file_extension, "allowed_extensions": allowed_extensions}
        )
        super().__init__(
            f"File type not allowed: {file_extension} for {file_path}",
            file_path=file_path,
            error_type="file_type_not_allowed",
            code=MCPErrorCode.FILE_TYPE_NOT_ALLOWED,
            data=data,
            **kwargs,
        )


class DirectoryNotFoundError(FileOperationError):
    """Exception for directory not found errors."""

    def __init__(self, directory_path: str, **kwargs: Any) -> None:
        super().__init__(
            f"Directory not found: {directory_path}",
            file_path=directory_path,
            error_type="directory_not_found",
            code=MCPErrorCode.DIRECTORY_NOT_FOUND,
            **kwargs,
        )


class EncodingError(FileOperationError):
    """Exception for file encoding errors."""

    def __init__(
        self, file_path: str, encoding: str, original_error: str, **kwargs: Any
    ) -> None:
        data = kwargs.pop("data", {})
        data.update({"encoding": encoding, "original_error": original_error})
        super().__init__(
            f"Encoding error reading {file_path} with {encoding}: {original_error}",
            file_path=file_path,
            error_type="encoding_error",
            code=MCPErrorCode.ENCODING_ERROR,
            data=data,
            **kwargs,
        )


class SecurityValidationError(MeshAgentError):
    """Exception for security validation failures."""

    def __init__(
        self,
        message: str,
        violation_type: str = "security_violation",
        file_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update({"violation_type": violation_type, "file_path": file_path})
        super().__init__(
            message, code=MCPErrorCode.SECURITY_VIOLATION, data=data, **kwargs
        )


class PathTraversalError(SecurityValidationError):
    """Exception for path traversal attempts."""

    def __init__(self, file_path: str, **kwargs: Any) -> None:
        super().__init__(
            f"Path traversal detected: {file_path}",
            violation_type="path_traversal",
            file_path=file_path,
            **kwargs,
        )
        self.code = MCPErrorCode.PATH_TRAVERSAL


class PermissionDeniedError(MeshAgentError):
    """Exception for permission-related failures."""

    def __init__(
        self,
        message: str,
        resource: str | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update({"resource": resource, "operation": operation})
        super().__init__(
            message, code=MCPErrorCode.RESOURCE_ACCESS_DENIED, data=data, **kwargs
        )


class RegistryConnectionError(MeshAgentError):
    """Error connecting to the mesh registry."""

    def __init__(
        self, message: str, registry_url: str | None = None, **kwargs: Any
    ) -> None:
        data = kwargs.pop("data", {})
        data.update({"registry_url": registry_url})
        super().__init__(
            message, code=MCPErrorCode.MESH_CONNECTION_FAILED, data=data, **kwargs
        )


class RegistryTimeoutError(RegistryConnectionError):
    """Timeout when connecting to the mesh registry."""

    def __init__(
        self, timeout_seconds: int, registry_url: str | None = None, **kwargs: Any
    ) -> None:
        data = kwargs.pop("data", {})
        data.update({"timeout_seconds": timeout_seconds})
        super().__init__(
            f"Registry connection timeout after {timeout_seconds} seconds",
            registry_url=registry_url,
            code=MCPErrorCode.MESH_TIMEOUT,
            data=data,
            retry_after=min(
                timeout_seconds * 2, 300
            ),  # Exponential backoff, max 5 minutes
            **kwargs,
        )


class DependencyInjectionError(MeshAgentError):
    """Error during dependency injection."""

    def __init__(
        self,
        dependency_name: str,
        agent_name: str | None = None,
        error_details: str | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {
                "dependency_name": dependency_name,
                "agent_name": agent_name,
                "error_details": error_details,
            }
        )
        message = f"Failed to inject dependency '{dependency_name}'"
        if agent_name:
            message += f" for agent '{agent_name}'"
        if error_details:
            message += f": {error_details}"

        super().__init__(
            message, code=MCPErrorCode.DEPENDENCY_INJECTION_FAILED, data=data, **kwargs
        )


class HealthMonitorError(MeshAgentError):
    """Error in health monitoring operations."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        check_type: str | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update({"agent_name": agent_name, "check_type": check_type})
        super().__init__(
            message, code=MCPErrorCode.HEALTH_CHECK_FAILED, data=data, **kwargs
        )


class RetryableError(MeshAgentError):
    """Base class for errors that support retry logic."""

    def __init__(
        self,
        message: str,
        max_retries: int = 3,
        retry_delay: int = 1,
        backoff_multiplier: float = 2.0,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {
                "max_retries": max_retries,
                "retry_delay": retry_delay,
                "backoff_multiplier": backoff_multiplier,
                "retryable": True,
            }
        )
        super().__init__(message, data=data, **kwargs)


class TransientError(RetryableError):
    """Error that is likely to be resolved by retrying."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message,
            code=MCPErrorCode.RESOURCE_UNAVAILABLE,
            retry_after=kwargs.get("retry_delay", 1),
            **kwargs,
        )


class RateLimitError(RetryableError):
    """Error indicating rate limiting is in effect."""

    def __init__(self, message: str, retry_after: int = 60, **kwargs: Any) -> None:
        super().__init__(
            message,
            code=MCPErrorCode.RATE_LIMIT_EXCEEDED,
            retry_after=retry_after,
            retry_delay=retry_after,
            **kwargs,
        )


class DiskSpaceError(TransientError):
    """Error indicating insufficient disk space."""

    def __init__(
        self,
        message: str,
        path: str | None = None,
        required_bytes: int | None = None,
        available_bytes: int | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {
                "path": path,
                "required_bytes": required_bytes,
                "available_bytes": available_bytes,
                "error_type": "disk_space",
            }
        )
        super().__init__(
            message,
            code=MCPErrorCode.DISK_FULL,
            data=data,
            retry_delay=30,  # Wait 30 seconds before retry
            **kwargs,
        )


class MemoryError(TransientError):
    """Error indicating insufficient memory."""

    def __init__(
        self,
        message: str,
        required_bytes: int | None = None,
        available_bytes: int | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {
                "required_bytes": required_bytes,
                "available_bytes": available_bytes,
                "error_type": "memory",
            }
        )
        super().__init__(
            message,
            code=MCPErrorCode.RESOURCE_UNAVAILABLE,
            data=data,
            retry_delay=15,  # Wait 15 seconds before retry
            **kwargs,
        )


class FileCorruptionError(FileOperationError):
    """Error indicating file corruption detected."""

    def __init__(
        self,
        file_path: str,
        corruption_type: str = "unknown",
        expected_checksum: str | None = None,
        actual_checksum: str | None = None,
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {
                "corruption_type": corruption_type,
                "expected_checksum": expected_checksum,
                "actual_checksum": actual_checksum,
            }
        )
        super().__init__(
            f"File corruption detected in {file_path}: {corruption_type}",
            file_path=file_path,
            error_type="file_corruption",
            code=MCPErrorCode.VALIDATION_ERROR,
            data=data,
            **kwargs,
        )


class BackupError(FileOperationError):
    """Error during backup operations."""

    def __init__(
        self,
        message: str,
        original_path: str | None = None,
        backup_path: str | None = None,
        backup_operation: str = "create",
        **kwargs: Any,
    ) -> None:
        data = kwargs.pop("data", {})
        data.update(
            {
                "original_path": original_path,
                "backup_path": backup_path,
                "backup_operation": backup_operation,
            }
        )
        super().__init__(
            message,
            file_path=original_path,
            operation="backup",
            error_type="backup_error",
            code=MCPErrorCode.INTERNAL_ERROR,
            data=data,
            **kwargs,
        )
