# Error Handling and Type Annotations Design

## Overview

This document defines the comprehensive error handling strategy and type annotation system for the File Agent, ensuring type safety, proper error propagation, and excellent developer experience.

## Exception Hierarchy

### Core Exception Classes

```python
# src/mcp_mesh_sdk/shared/exceptions.py

from typing import Optional, Dict, Any
from enum import Enum

class ErrorCode(str, Enum):
    """Standardized error codes for File Agent operations."""

    # File operation errors
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_PERMISSION_DENIED = "FILE_PERMISSION_DENIED"
    FILE_ALREADY_EXISTS = "FILE_ALREADY_EXISTS"
    FILE_CORRUPTED = "FILE_CORRUPTED"

    # Directory operation errors
    DIRECTORY_NOT_FOUND = "DIRECTORY_NOT_FOUND"
    DIRECTORY_NOT_EMPTY = "DIRECTORY_NOT_EMPTY"
    DIRECTORY_PERMISSION_DENIED = "DIRECTORY_PERMISSION_DENIED"

    # Path validation errors
    INVALID_PATH = "INVALID_PATH"
    PATH_TRAVERSAL_DETECTED = "PATH_TRAVERSAL_DETECTED"
    UNSAFE_PATH = "UNSAFE_PATH"

    # Security errors
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    SECURITY_CONTEXT_INVALID = "SECURITY_CONTEXT_INVALID"

    # Mesh integration errors
    REGISTRY_CONNECTION_FAILED = "REGISTRY_CONNECTION_FAILED"
    REGISTRY_TIMEOUT = "REGISTRY_TIMEOUT"
    DEPENDENCY_INJECTION_FAILED = "DEPENDENCY_INJECTION_FAILED"
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"

    # Configuration errors
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    INITIALIZATION_FAILED = "INITIALIZATION_FAILED"

class FileAgentError(Exception):
    """Base exception for all File Agent operations."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code.value,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None
        }

class FileOperationError(FileAgentError):
    """Exception for file operation failures."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        file_path: Optional[str] = None,
        operation: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.get("details", {})
        if file_path:
            details["file_path"] = file_path
        if operation:
            details["operation"] = operation

        super().__init__(message, error_code, details, kwargs.get("cause"))

class SecurityError(FileAgentError):
    """Exception for security-related failures."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        security_context: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.get("details", {})
        if security_context:
            details["security_context"] = security_context
        if user_id:
            details["user_id"] = user_id

        super().__init__(message, error_code, details, kwargs.get("cause"))

class MeshIntegrationError(FileAgentError):
    """Exception for mesh integration failures."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        service_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.get("details", {})
        if service_name:
            details["service_name"] = service_name
        if endpoint:
            details["endpoint"] = endpoint

        super().__init__(message, error_code, details, kwargs.get("cause"))

class ConfigurationError(FileAgentError):
    """Exception for configuration-related failures."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        config_key: Optional[str] = None,
        **kwargs
    ):
        details = kwargs.get("details", {})
        if config_key:
            details["config_key"] = config_key

        super().__init__(message, error_code, details, kwargs.get("cause"))

# Specific exception classes for common scenarios
class FileNotFoundError(FileOperationError):
    """File not found exception."""

    def __init__(self, file_path: str, **kwargs):
        super().__init__(
            f"File not found: {file_path}",
            ErrorCode.FILE_NOT_FOUND,
            file_path=file_path,
            operation="access",
            **kwargs
        )

class FileTooLargeError(FileOperationError):
    """File too large exception."""

    def __init__(self, file_path: str, size: int, max_size: int, **kwargs):
        super().__init__(
            f"File {file_path} ({size} bytes) exceeds maximum size ({max_size} bytes)",
            ErrorCode.FILE_TOO_LARGE,
            file_path=file_path,
            operation="read",
            details={"actual_size": size, "max_size": max_size},
            **kwargs
        )

class PermissionDeniedError(FileOperationError):
    """Permission denied exception."""

    def __init__(self, file_path: str, operation: str, **kwargs):
        super().__init__(
            f"Permission denied for {operation} on {file_path}",
            ErrorCode.FILE_PERMISSION_DENIED,
            file_path=file_path,
            operation=operation,
            **kwargs
        )

class PathTraversalError(SecurityError):
    """Path traversal attack detected."""

    def __init__(self, path: str, **kwargs):
        super().__init__(
            f"Path traversal detected in path: {path}",
            ErrorCode.PATH_TRAVERSAL_DETECTED,
            details={"attempted_path": path},
            **kwargs
        )

class RegistryConnectionError(MeshIntegrationError):
    """Registry connection failure."""

    def __init__(self, registry_url: str, **kwargs):
        super().__init__(
            f"Failed to connect to registry at {registry_url}",
            ErrorCode.REGISTRY_CONNECTION_FAILED,
            service_name="registry",
            endpoint=registry_url,
            **kwargs
        )

class RegistryTimeoutError(MeshIntegrationError):
    """Registry operation timeout."""

    def __init__(self, operation: str, timeout: int, **kwargs):
        super().__init__(
            f"Registry operation '{operation}' timed out after {timeout} seconds",
            ErrorCode.REGISTRY_TIMEOUT,
            service_name="registry",
            details={"operation": operation, "timeout": timeout},
            **kwargs
        )
```

## Type Definitions

### Core Type System

```python
# src/mcp_mesh_sdk/shared/types.py

from typing import (
    Dict, List, Optional, Union, Any, Protocol, TypeVar, Generic,
    Literal, Annotated, runtime_checkable
)
from pathlib import Path
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, validator, root_validator
from enum import Enum

T = TypeVar('T')

class OperationResult(BaseModel, Generic[T]):
    """Generic result type for operations."""

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)

class FileInfo(BaseModel):
    """File system information model."""

    path: Path
    name: str
    size: int
    is_directory: bool
    is_file: bool
    is_symlink: bool
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    accessed: Optional[datetime] = None
    permissions: str
    owner: Optional[str] = None
    group: Optional[str] = None
    mime_type: Optional[str] = None
    extension: Optional[str] = None

    @validator('path')
    def validate_path(cls, v):
        """Ensure path is absolute and normalized."""
        return Path(v).resolve()

    @validator('permissions')
    def validate_permissions(cls, v):
        """Validate permission string format."""
        if not isinstance(v, str) or len(v) != 9:
            raise ValueError("Permissions must be a 9-character string")
        return v

class DirectoryListing(BaseModel):
    """Directory listing model."""

    path: Path
    total_items: int
    directories: List[FileInfo]
    files: List[FileInfo]
    symlinks: List[FileInfo]
    hidden_items: int
    total_size: int

    @property
    def all_items(self) -> List[FileInfo]:
        """Get all items in the directory."""
        return self.directories + self.files + self.symlinks

class FileOperation(str, Enum):
    """Supported file operations."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    COPY = "copy"
    MOVE = "move"
    CREATE_DIR = "create_directory"
    LIST_DIR = "list_directory"
    GET_INFO = "get_info"

class SecurityContext(BaseModel):
    """Security context for operations."""

    user_id: Optional[str] = None
    auth_token: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    allowed_paths: Optional[List[Path]] = None
    denied_paths: Optional[List[Path]] = None
    max_file_size: Optional[int] = None
    allowed_extensions: Optional[List[str]] = None

    @validator('allowed_paths', 'denied_paths', pre=True)
    def validate_paths(cls, v):
        """Ensure paths are Path objects."""
        if v is None:
            return v
        return [Path(p) if not isinstance(p, Path) else p for p in v]

class HealthStatus(BaseModel):
    """Health status model."""

    status: Literal["healthy", "degraded", "unhealthy"]
    agent_name: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)
    checks: Dict[str, bool] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error_count: int = 0
    last_error: Optional[str] = None

class FileAgentConfig(BaseModel):
    """Configuration model for File Agent."""

    agent_name: str = "file-agent"
    base_directory: Optional[Path] = None
    max_file_size: int = Field(default=10 * 1024 * 1024, gt=0)  # 10MB
    allowed_extensions: Optional[List[str]] = None
    denied_extensions: List[str] = Field(default_factory=lambda: ['.exe', '.bat', '.sh'])
    security_mode: Literal["strict", "permissive", "sandbox"] = "strict"
    enable_backups: bool = True
    backup_directory: Optional[Path] = None
    enable_audit_log: bool = True
    audit_log_path: Optional[Path] = None
    health_check_interval: int = Field(default=30, gt=0)
    registry_url: Optional[str] = None
    enable_caching: bool = True
    cache_ttl: int = Field(default=300, gt=0)  # 5 minutes

    @validator('base_directory', 'backup_directory', 'audit_log_path', pre=True)
    def validate_paths(cls, v):
        """Ensure paths are Path objects and exist."""
        if v is None:
            return v
        path = Path(v) if not isinstance(v, Path) else v
        return path.resolve()

    @root_validator
    def validate_config(cls, values):
        """Validate configuration consistency."""
        if values.get('enable_backups') and not values.get('backup_directory'):
            values['backup_directory'] = Path.home() / '.mcp_mesh' / 'backups'

        if values.get('enable_audit_log') and not values.get('audit_log_path'):
            values['audit_log_path'] = Path.home() / '.mcp_mesh' / 'audit.log'

        return values

class MeshCapability(BaseModel):
    """Mesh capability definition."""

    name: str
    description: str
    version: str = "1.0.0"
    dependencies: List[str] = Field(default_factory=list)
    security_level: Literal["public", "authenticated", "authorized"] = "authenticated"
    rate_limit: Optional[int] = None
    timeout: int = 30

class DependencyConfig(BaseModel):
    """Dependency configuration model."""

    name: str
    type: Literal["service", "config", "credential"] = "service"
    endpoint: Optional[str] = None
    version: Optional[str] = None
    required: bool = True
    fallback_value: Optional[Any] = None
    cache_ttl: int = 300

# Protocol definitions for extensibility
@runtime_checkable
class FileReader(Protocol):
    """Protocol for file reading implementations."""

    async def read_file(
        self,
        path: Path,
        encoding: str = "utf-8",
        max_size: Optional[int] = None
    ) -> str:
        """Read file contents."""
        ...

@runtime_checkable
class FileWriter(Protocol):
    """Protocol for file writing implementations."""

    async def write_file(
        self,
        path: Path,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = False
    ) -> bool:
        """Write file contents."""
        ...

@runtime_checkable
class SecurityValidator(Protocol):
    """Protocol for security validation implementations."""

    async def validate_path(
        self,
        path: Path,
        operation: FileOperation,
        context: SecurityContext
    ) -> bool:
        """Validate path access for operation."""
        ...

    async def validate_operation(
        self,
        operation: FileOperation,
        context: SecurityContext
    ) -> bool:
        """Validate operation permission."""
        ...

# Type aliases for common patterns
FilePath = Annotated[Path, Field(description="File system path")]
FileContent = Annotated[str, Field(description="File content as string")]
FileSize = Annotated[int, Field(ge=0, description="File size in bytes")]
Permissions = Annotated[str, Field(regex=r"^[rwx-]{9}$", description="Unix-style permissions")]

# Result types for specific operations
FileReadResult = OperationResult[str]
FileWriteResult = OperationResult[bool]
FileInfoResult = OperationResult[FileInfo]
DirectoryListResult = OperationResult[DirectoryListing]
```

## Error Handling Patterns

### Decorator for Error Handling

```python
# src/mcp_mesh_sdk/shared/error_handling.py

import functools
import logging
from typing import Callable, TypeVar, Any, Optional
from .exceptions import FileAgentError, ErrorCode
from .types import OperationResult

F = TypeVar('F', bound=Callable[..., Any])

def handle_file_errors(
    operation: str,
    default_error_code: ErrorCode = ErrorCode.FILE_OPERATION_FAILED
) -> Callable[[F], F]:
    """
    Decorator for handling file operation errors consistently.

    Args:
        operation: Name of the operation for logging
        default_error_code: Default error code if none specified
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            logger = logging.getLogger(f"file_agent.{operation}")

            try:
                result = await func(*args, **kwargs)
                logger.debug(f"Operation {operation} completed successfully")
                return result

            except FileAgentError:
                # Re-raise FileAgent errors as-is
                raise

            except FileNotFoundError as e:
                logger.warning(f"File not found in {operation}: {e}")
                raise FileNotFoundError(str(e.filename or "unknown"))

            except PermissionError as e:
                logger.warning(f"Permission denied in {operation}: {e}")
                raise PermissionDeniedError(
                    str(e.filename or "unknown"),
                    operation
                )

            except OSError as e:
                logger.error(f"OS error in {operation}: {e}")
                raise FileOperationError(
                    f"Operating system error in {operation}: {e}",
                    default_error_code,
                    operation=operation,
                    cause=e
                )

            except Exception as e:
                logger.error(f"Unexpected error in {operation}: {e}", exc_info=True)
                raise FileOperationError(
                    f"Unexpected error in {operation}: {e}",
                    default_error_code,
                    operation=operation,
                    cause=e
                )

        return wrapper

    return decorator

def safe_operation(
    operation: str,
    return_type: type = bool
) -> Callable[[F], F]:
    """
    Decorator that wraps operations in OperationResult for safe error handling.

    Args:
        operation: Name of the operation
        return_type: Expected return type for success case
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> OperationResult:
            try:
                result = await func(*args, **kwargs)
                return OperationResult(success=True, data=result)

            except FileAgentError as e:
                return OperationResult(
                    success=False,
                    error=e.message,
                    error_code=e.error_code.value
                )

            except Exception as e:
                return OperationResult(
                    success=False,
                    error=f"Unexpected error in {operation}: {e}",
                    error_code=ErrorCode.UNKNOWN_ERROR.value
                )

        return wrapper

    return decorator
```

### Validation Utilities

```python
# src/mcp_mesh_sdk/shared/validation.py

import os
import re
from pathlib import Path
from typing import List, Optional
from .exceptions import PathTraversalError, SecurityError, ErrorCode
from .types import SecurityContext, FileOperation

class PathValidator:
    """Utility class for path validation and security checks."""

    @staticmethod
    def validate_path_safety(path: Path) -> None:
        """
        Validate that a path is safe and doesn't contain traversal attempts.

        Raises:
            PathTraversalError: If path traversal is detected
            SecurityError: If path is otherwise unsafe
        """
        # Convert to absolute path for analysis
        abs_path = path.resolve()

        # Check for path traversal patterns
        path_str = str(path)
        if ".." in path_str or path_str.startswith("/"):
            raise PathTraversalError(str(path))

        # Check for suspicious patterns
        suspicious_patterns = [
            r"\.\.[\\/]",  # Directory traversal
            r"[\\/]\.\.[\\/]",  # Mid-path traversal
            r"^[\\/]",  # Absolute path attempts
            r"^[a-zA-Z]:",  # Windows drive letters
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, path_str):
                raise PathTraversalError(str(path))

    @staticmethod
    def validate_file_extension(
        path: Path,
        allowed: Optional[List[str]] = None,
        denied: Optional[List[str]] = None
    ) -> None:
        """
        Validate file extension against allow/deny lists.

        Args:
            path: File path to check
            allowed: List of allowed extensions (if None, all allowed)
            denied: List of denied extensions

        Raises:
            SecurityError: If extension is not allowed
        """
        ext = path.suffix.lower()

        if denied and ext in denied:
            raise SecurityError(
                f"File extension '{ext}' is not allowed",
                ErrorCode.SECURITY_VALIDATION_FAILED,
                details={"extension": ext, "path": str(path)}
            )

        if allowed and ext not in allowed:
            raise SecurityError(
                f"File extension '{ext}' is not in allowed list",
                ErrorCode.SECURITY_VALIDATION_FAILED,
                details={"extension": ext, "allowed": allowed, "path": str(path)}
            )

    @staticmethod
    def validate_path_access(
        path: Path,
        operation: FileOperation,
        context: SecurityContext
    ) -> None:
        """
        Validate path access based on security context.

        Args:
            path: Path to validate
            operation: Requested operation
            context: Security context

        Raises:
            SecurityError: If access is denied
        """
        abs_path = path.resolve()

        # Check allowed paths
        if context.allowed_paths:
            allowed = any(
                abs_path.is_relative_to(allowed_path)
                for allowed_path in context.allowed_paths
            )
            if not allowed:
                raise SecurityError(
                    f"Path '{path}' is not in allowed paths",
                    ErrorCode.AUTHORIZATION_FAILED,
                    details={"path": str(path), "allowed_paths": [str(p) for p in context.allowed_paths]}
                )

        # Check denied paths
        if context.denied_paths:
            denied = any(
                abs_path.is_relative_to(denied_path)
                for denied_path in context.denied_paths
            )
            if denied:
                raise SecurityError(
                    f"Path '{path}' is in denied paths",
                    ErrorCode.AUTHORIZATION_FAILED,
                    details={"path": str(path), "denied_paths": [str(p) for p in context.denied_paths]}
                )

        # Check operation permissions
        required_permission = f"file_{operation.value}"
        if required_permission not in context.permissions:
            raise SecurityError(
                f"Permission '{required_permission}' not granted",
                ErrorCode.AUTHORIZATION_FAILED,
                details={"required_permission": required_permission, "granted_permissions": context.permissions}
            )

class FileValidator:
    """Utility class for file-specific validation."""

    @staticmethod
    def validate_file_size(path: Path, max_size: Optional[int] = None) -> None:
        """
        Validate file size against maximum allowed size.

        Args:
            path: File path to check
            max_size: Maximum allowed size in bytes

        Raises:
            FileTooLargeError: If file exceeds maximum size
        """
        if max_size is None:
            return

        try:
            size = path.stat().st_size
            if size > max_size:
                raise FileTooLargeError(str(path), size, max_size)
        except OSError as e:
            raise FileOperationError(
                f"Cannot check file size for {path}: {e}",
                ErrorCode.FILE_ACCESS_ERROR,
                file_path=str(path),
                operation="size_check",
                cause=e
            )

    @staticmethod
    def validate_file_exists(path: Path, should_exist: bool = True) -> None:
        """
        Validate file existence.

        Args:
            path: File path to check
            should_exist: Whether file should exist

        Raises:
            FileNotFoundError: If file should exist but doesn't
            FileOperationError: If file shouldn't exist but does
        """
        exists = path.exists()

        if should_exist and not exists:
            raise FileNotFoundError(str(path))

        if not should_exist and exists:
            raise FileOperationError(
                f"File already exists: {path}",
                ErrorCode.FILE_ALREADY_EXISTS,
                file_path=str(path),
                operation="existence_check"
            )
```

This comprehensive error handling and type annotation system provides:

1. **Structured Exception Hierarchy**: Clear error types with standardized codes
2. **Rich Type System**: Pydantic models with validation for all data structures
3. **Protocol Definitions**: Extensible interfaces for different implementations
4. **Validation Utilities**: Reusable security and safety validation functions
5. **Error Handling Decorators**: Consistent error handling across all operations
6. **MCP Compliance**: Error formats compatible with MCP protocol requirements

The system ensures type safety, security, and excellent error reporting while maintaining clean separation of concerns.
