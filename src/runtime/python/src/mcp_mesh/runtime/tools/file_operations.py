"""
File Operations with dual-decorator pattern (FastMCP + @mesh_agent)

Implements secure file operations with both MCP protocol compliance
and optional mesh integration for enhanced capabilities.
"""

import asyncio
import hashlib
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

import aiofiles

if TYPE_CHECKING:
    pass

try:
    from mcp.server.fastmcp import FastMCP

    FASTMCP_AVAILABLE = True
except ImportError:
    # Fallback for development/testing
    FASTMCP_AVAILABLE = False

    class MockFastMCP:
        def __init__(self, name: str):
            self.name = name
            self.tools = []

        def tool(self, name: str | None = None, description: str | None = None):
            def decorator(func):
                func._tool_name = name or func.__name__
                func._tool_description = description or func.__doc__
                self.tools.append(func)
                return func

            return decorator

    FastMCP = MockFastMCP

from mcp_mesh import mesh_agent

from ..shared.exceptions import (
    DirectoryNotFoundError,
    EncodingError,
    FileAccessDeniedError,
    FileNotFoundError,
    FileOperationError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    MCPErrorCode,
    PathTraversalError,
    RateLimitError,
    SecurityValidationError,
    TransientError,
)
from ..shared.types import (
    FilePath,
    HealthStatus,
    HealthStatusType,
    OperationType,
    RetryConfig,
    RetryStrategy,
)

# Create FastMCP app instance for tool registration
app = (
    FastMCP(name="mcp-mesh-file-operations")
    if FASTMCP_AVAILABLE
    else MockFastMCP("mcp-mesh-file-operations")
)


class FileOperations:
    """
    Core file operations with dual-decorator pattern (FastMCP + @mesh_agent).

    Provides secure file system operations that work with both:
    - Standard MCP protocol (via FastMCP decorators)
    - Enhanced mesh capabilities (via @mesh_agent decorators)

    Tools will work with vanilla MCP SDK even if mesh functionality is unavailable.
    """

    def __init__(
        self,
        base_directory: FilePath | None = None,
        max_file_size: int = 10 * 1024 * 1024,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """
        Initialize file operations.

        Args:
            base_directory: Optional base directory for operations (None = no restriction)
            max_file_size: Maximum file size in bytes (default: 10MB)
            retry_config: Default retry configuration for operations
        """
        self.base_directory = Path(base_directory) if base_directory else None
        self.max_file_size = max_file_size
        self.logger = logging.getLogger(__name__)
        self.start_time = datetime.now()

        # Default retry configuration
        self.default_retry_config = retry_config or RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=3,
            initial_delay_ms=1000,
            max_delay_ms=30000,
            backoff_multiplier=2.0,
            jitter=True,
        )

        # Allowed file extensions for security
        self.allowed_extensions: set[str] = {
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".py",
            ".js",
            ".ts",
            ".md",
            ".csv",
            ".xml",
            ".html",
            ".css",
            ".log",
            ".conf",
            ".config",
            ".ini",
            ".cfg",
            ".toml",
            ".rst",
            ".tex",
            ".sql",
            ".sh",
            ".bat",
        }

        # Rate limiting tracking
        self._operation_counts: dict[str, list[float]] = {}
        self._rate_limit_window: int = 60  # 1 minute window
        self._max_operations_per_minute: int = 100

        # Initialize tools with dual-decorator pattern
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Setup file operation tools with dual-decorator pattern (FastMCP + @mesh_agent)."""

        # DUAL-DECORATOR PATTERN: Both @app.tool (MCP protocol) AND @mesh_agent (mesh capabilities)
        @app.tool(
            name="read_file",
            description="Read file contents with security validation and optional mesh integration",
        )
        @mesh_agent(
            capabilities=["file_read", "secure_access"],
            dependencies=["auth_service", "audit_logger"],
            health_interval=30,
            security_context="file_operations",
            agent_name="file-operations-agent",
            fallback_mode=True,
        )
        async def read_file(
            path: str,
            encoding: str = "utf-8",
            request_id: str | None = None,
            correlation_id: str | None = None,
            retry_config: RetryConfig | None = None,
            auth_service: str | None = None,
            audit_logger: str | None = None,
        ) -> str:
            """
            Read file contents with security validation and mesh integration.

            Args:
                path: File path to read
                encoding: File encoding (default: utf-8)
                request_id: Request identifier for tracking
                correlation_id: Correlation identifier for tracking
                retry_config: Override retry configuration
                auth_service: Authentication service (injected by mesh)
                audit_logger: Audit logging service (injected by mesh)

            Returns:
                File contents as string

            Raises:
                FileNotFoundError: If file not found
                FileAccessDeniedError: If access denied
                FileTooLargeError: If file exceeds size limit
                EncodingError: If encoding error occurs
                SecurityValidationError: If security validation fails
            """
            operation_start = time.time()
            self.logger.info(f"Reading file: {path} (request_id: {request_id})")

            # Rate limiting check
            await self._check_rate_limit("read")

            # Security validation
            validated_path = await self._validate_path(path, OperationType.READ)

            # Authentication check (injected dependency)
            if auth_service:
                self.logger.info(f"Using auth service: {auth_service}")
                await self._check_permissions(
                    validated_path, OperationType.READ, auth_service
                )

            async def _read_operation() -> str:
                """Core read operation with proper error handling."""
                try:
                    # Check if file exists
                    if not validated_path.exists():
                        raise FileNotFoundError(
                            str(validated_path),
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )

                    # Check if it's actually a file
                    if not validated_path.is_file():
                        raise FileOperationError(
                            f"Path is not a file: {path}",
                            file_path=str(validated_path),
                            operation="read",
                            code=MCPErrorCode.VALIDATION_ERROR,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )

                    # Check file size before reading
                    file_size = validated_path.stat().st_size
                    if file_size > self.max_file_size:
                        raise FileTooLargeError(
                            str(validated_path),
                            file_size,
                            self.max_file_size,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )

                    # Read file content asynchronously
                    async with aiofiles.open(validated_path, encoding=encoding) as f:
                        content = await f.read()

                    return content

                except FileNotFoundError:
                    raise
                except PermissionError:
                    raise FileAccessDeniedError(
                        str(validated_path),
                        "read",
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except UnicodeDecodeError as e:
                    raise EncodingError(
                        str(validated_path),
                        encoding,
                        str(e),
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except OSError as e:
                    # Handle disk errors, network issues, etc.
                    if e.errno in [
                        28,
                        122,
                    ]:  # ENOSPC (No space left) or EDQUOT (Quota exceeded)
                        raise TransientError(
                            f"Disk space error reading {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=5,
                        )
                    elif e.errno == 13:  # EACCES (Permission denied)
                        raise FileAccessDeniedError(
                            str(validated_path),
                            "read",
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 2:  # ENOENT (No such file or directory)
                        raise FileNotFoundError(
                            str(validated_path),
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 21:  # EISDIR (Is a directory)
                        raise FileOperationError(
                            f"Cannot read directory as file: {path}",
                            file_path=str(validated_path),
                            operation="read",
                            code=MCPErrorCode.VALIDATION_ERROR,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 12:  # ENOMEM (Cannot allocate memory)
                        raise TransientError(
                            f"Insufficient memory reading {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=10,
                        )
                    elif e.errno == 5:  # EIO (Input/output error)
                        raise TransientError(
                            f"I/O error reading {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=3,
                        )
                    raise FileOperationError(
                        f"OS error reading {path}: {e} (errno: {e.errno})",
                        file_path=str(validated_path),
                        operation="read",
                        code=MCPErrorCode.INTERNAL_ERROR,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except Exception as e:
                    raise FileOperationError(
                        f"Unexpected error reading {path}: {e}",
                        file_path=str(validated_path),
                        operation="read",
                        code=MCPErrorCode.INTERNAL_ERROR,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )

            # Execute with retry logic
            effective_retry_config = retry_config or self.default_retry_config
            content: str = await self._execute_with_retry(
                _read_operation, effective_retry_config
            )

            # Audit logging (injected dependency)
            if audit_logger:
                await self._audit_log(
                    "file_read",
                    {
                        "path": str(validated_path),
                        "bytes_read": len(content.encode(encoding)),
                        "encoding": encoding,
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "duration_ms": int((time.time() - operation_start) * 1000),
                    },
                    audit_logger,
                )

            self.logger.info(
                f"Successfully read {len(content)} characters from {validated_path}"
            )
            return content

        # DUAL-DECORATOR PATTERN: Both @app.tool (MCP protocol) AND @mesh_agent (mesh capabilities)
        @app.tool(
            name="write_file",
            description="Write content to file with backup, validation and optional mesh integration",
        )
        @mesh_agent(
            capabilities=["file_write", "secure_access"],
            dependencies=["auth_service", "audit_logger", "backup_service"],
            health_interval=30,
            security_context="file_operations",
            agent_name="file-operations-agent",
            fallback_mode=True,
        )
        async def write_file(
            path: str,
            content: str,
            encoding: str = "utf-8",
            create_backup: bool = True,
            request_id: str | None = None,
            correlation_id: str | None = None,
            retry_config: RetryConfig | None = None,
            auth_service: str | None = None,
            audit_logger: str | None = None,
            backup_service: str | None = None,
        ) -> bool:
            """
            Write content to file with backup, validation and mesh integration.

            Args:
                path: File path to write
                content: Content to write
                encoding: File encoding (default: utf-8)
                create_backup: Whether to create backup before writing
                request_id: Request identifier for tracking
                correlation_id: Correlation identifier for tracking
                retry_config: Override retry configuration
                auth_service: Authentication service (injected by mesh)
                audit_logger: Audit logging service (injected by mesh)
                backup_service: Backup service (injected by mesh)

            Returns:
                True if successful

            Raises:
                FileAccessDeniedError: If access denied
                FileTooLargeError: If content exceeds size limit
                FileTypeNotAllowedError: If file type not allowed
                SecurityValidationError: If security validation fails
            """
            operation_start = time.time()
            self.logger.info(f"Writing to file: {path} (request_id: {request_id})")

            # Rate limiting check
            await self._check_rate_limit("write")

            # Security validation
            validated_path = await self._validate_path(path, OperationType.WRITE)

            # Check content size
            content_size = len(content.encode(encoding))
            if content_size > self.max_file_size:
                raise FileTooLargeError(
                    str(validated_path),
                    content_size,
                    self.max_file_size,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )

            # Authentication check (injected dependency)
            if auth_service:
                self.logger.info(f"Using auth service: {auth_service}")
                await self._check_permissions(
                    validated_path, OperationType.WRITE, auth_service
                )

            async def _write_operation() -> bool:
                """Core write operation with proper error handling."""
                try:
                    # Create backup if file exists and backup requested
                    if create_backup and validated_path.exists():
                        if backup_service:
                            await self._create_backup(validated_path, backup_service)
                        else:
                            await self._create_local_backup(validated_path)

                    # Ensure parent directory exists
                    validated_path.parent.mkdir(parents=True, exist_ok=True)

                    # Write file content asynchronously
                    async with aiofiles.open(
                        validated_path, "w", encoding=encoding
                    ) as f:
                        await f.write(content)

                    return True

                except PermissionError:
                    raise FileAccessDeniedError(
                        str(validated_path),
                        "write",
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except OSError as e:
                    # Handle disk errors, network issues, etc.
                    if e.errno in [
                        28,
                        122,
                    ]:  # ENOSPC (No space left) or EDQUOT (Quota exceeded)
                        raise TransientError(
                            f"Disk space error writing {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=5,
                        )
                    elif e.errno == 13:  # EACCES (Permission denied)
                        raise FileAccessDeniedError(
                            str(validated_path),
                            "write",
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif (
                        e.errno == 2
                    ):  # ENOENT (No such file or directory - parent directory)
                        raise FileOperationError(
                            f"Parent directory does not exist for {path}",
                            file_path=str(validated_path),
                            operation="write",
                            code=MCPErrorCode.VALIDATION_ERROR,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 21:  # EISDIR (Is a directory)
                        raise FileOperationError(
                            f"Cannot write to directory: {path}",
                            file_path=str(validated_path),
                            operation="write",
                            code=MCPErrorCode.VALIDATION_ERROR,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 26:  # ETXTBSY (Text file busy)
                        raise TransientError(
                            f"File is busy and cannot be written: {path}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=2,
                        )
                    elif e.errno == 12:  # ENOMEM (Cannot allocate memory)
                        raise TransientError(
                            f"Insufficient memory writing {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=10,
                        )
                    elif e.errno == 5:  # EIO (Input/output error)
                        raise TransientError(
                            f"I/O error writing {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=3,
                        )
                    elif e.errno == 30:  # EROFS (Read-only file system)
                        raise FileAccessDeniedError(
                            str(validated_path),
                            "write",
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    raise FileOperationError(
                        f"OS error writing {path}: {e} (errno: {e.errno})",
                        file_path=str(validated_path),
                        operation="write",
                        code=MCPErrorCode.INTERNAL_ERROR,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except Exception as e:
                    raise FileOperationError(
                        f"Unexpected error writing {path}: {e}",
                        file_path=str(validated_path),
                        operation="write",
                        code=MCPErrorCode.INTERNAL_ERROR,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )

            # Execute with retry logic
            effective_retry_config = retry_config or self.default_retry_config
            result: bool = await self._execute_with_retry(
                _write_operation, effective_retry_config
            )

            # Audit logging (injected dependency)
            if audit_logger:
                await self._audit_log(
                    "file_write",
                    {
                        "path": str(validated_path),
                        "content_size": content_size,
                        "encoding": encoding,
                        "backup_created": create_backup and validated_path.exists(),
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "duration_ms": int((time.time() - operation_start) * 1000),
                    },
                    audit_logger,
                )

            self.logger.info(
                f"Successfully wrote {content_size} bytes to {validated_path}"
            )
            return result

        # DUAL-DECORATOR PATTERN: Both @app.tool (MCP protocol) AND @mesh_agent (mesh capabilities)
        @app.tool(
            name="list_directory",
            description="List directory contents with security validation and optional mesh integration",
        )
        @mesh_agent(
            capabilities=["directory_list", "secure_access"],
            dependencies=["auth_service", "audit_logger"],
            health_interval=60,  # Less frequent heartbeat for listing
            security_context="file_operations",
            agent_name="file-operations-agent",
            fallback_mode=True,
        )
        async def list_directory(
            path: str,
            include_hidden: bool = False,
            include_details: bool = False,
            request_id: str | None = None,
            correlation_id: str | None = None,
            retry_config: RetryConfig | None = None,
            auth_service: str | None = None,
            audit_logger: str | None = None,
        ) -> list[str | dict[str, Any]]:
            """
            List directory contents with security validation and mesh integration.

            Args:
                path: Directory path to list
                include_hidden: Include hidden files (starting with .)
                include_details: Include file details (size, modified date)
                request_id: Request identifier for tracking
                correlation_id: Correlation identifier for tracking
                retry_config: Override retry configuration
                auth_service: Authentication service (injected by mesh)
                audit_logger: Audit logging service (injected by mesh)

            Returns:
                List of file/directory names or detailed info

            Raises:
                DirectoryNotFoundError: If directory not found
                FileAccessDeniedError: If access denied
                SecurityValidationError: If security validation fails
            """
            operation_start = time.time()
            self.logger.info(f"Listing directory: {path} (request_id: {request_id})")

            # Rate limiting check
            await self._check_rate_limit("list")

            # Security validation
            validated_path = await self._validate_path(path, OperationType.LIST)

            if not validated_path.exists():
                raise DirectoryNotFoundError(
                    str(validated_path),
                    request_id=request_id,
                    correlation_id=correlation_id,
                )

            if not validated_path.is_dir():
                raise FileOperationError(
                    f"Path is not a directory: {path}",
                    file_path=str(validated_path),
                    operation="list",
                    code=MCPErrorCode.VALIDATION_ERROR,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )

            # Authentication check (injected dependency)
            if auth_service:
                self.logger.info(f"Using auth service: {auth_service}")
                await self._check_permissions(
                    validated_path, OperationType.LIST, auth_service
                )

            async def _list_operation() -> list[str | dict[str, Any]]:
                """Core list operation with proper error handling."""
                try:
                    entries: list[str | dict[str, Any]] = []
                    total_count = 0

                    # List directory contents
                    for entry in validated_path.iterdir():
                        total_count += 1

                        # Skip hidden files unless requested
                        if not include_hidden and entry.name.startswith("."):
                            continue

                        if include_details:
                            try:
                                stat_info = entry.stat()
                                entry_info = {
                                    "name": entry.name,
                                    "path": str(entry),
                                    "type": "directory" if entry.is_dir() else "file",
                                    "size": stat_info.st_size if entry.is_file() else 0,
                                    "modified": datetime.fromtimestamp(
                                        stat_info.st_mtime
                                    ).isoformat(),
                                    "permissions": oct(stat_info.st_mode)[-3:],
                                    "is_symlink": entry.is_symlink(),
                                }
                                entries.append(entry_info)
                            except (OSError, PermissionError) as e:
                                # Log but don't fail for individual file errors
                                self.logger.warning(f"Could not stat {entry}: {e}")
                                error_entry_info: dict[str, Any] = {
                                    "name": entry.name,
                                    "path": str(entry),
                                    "type": "unknown",
                                    "size": 0,
                                    "modified": None,
                                    "permissions": "unknown",
                                    "error": str(e),
                                }
                                entries.append(error_entry_info)
                        else:
                            entries.append(entry.name)

                    return entries

                except PermissionError:
                    raise FileAccessDeniedError(
                        str(validated_path),
                        "list",
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except OSError as e:
                    if e.errno == 2:  # ENOENT (No such file or directory)
                        raise DirectoryNotFoundError(
                            str(validated_path),
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 13:  # EACCES (Permission denied)
                        raise FileAccessDeniedError(
                            str(validated_path),
                            "list",
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 20:  # ENOTDIR (Not a directory)
                        raise FileOperationError(
                            f"Path is not a directory: {path}",
                            file_path=str(validated_path),
                            operation="list",
                            code=MCPErrorCode.VALIDATION_ERROR,
                            request_id=request_id,
                            correlation_id=correlation_id,
                        )
                    elif e.errno == 28:  # ENOSPC (No space left on device)
                        raise TransientError(
                            f"No space left on device while listing {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=5,
                        )
                    elif e.errno == 5:  # EIO (Input/output error)
                        raise TransientError(
                            f"I/O error listing directory {path}: {e}",
                            request_id=request_id,
                            correlation_id=correlation_id,
                            retry_delay=3,
                        )
                    raise FileOperationError(
                        f"OS error listing directory {path}: {e} (errno: {e.errno})",
                        file_path=str(validated_path),
                        operation="list",
                        code=MCPErrorCode.INTERNAL_ERROR,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                except Exception as e:
                    raise FileOperationError(
                        f"Unexpected error listing directory {path}: {e}",
                        file_path=str(validated_path),
                        operation="list",
                        code=MCPErrorCode.INTERNAL_ERROR,
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )

            # Execute with retry logic
            effective_retry_config = retry_config or self.default_retry_config
            entries: list[str | dict[str, Any]] = await self._execute_with_retry(
                _list_operation, effective_retry_config
            )

            # Audit logging (injected dependency)
            if audit_logger:
                await self._audit_log(
                    "directory_list",
                    {
                        "path": str(validated_path),
                        "count": len(entries),
                        "include_hidden": include_hidden,
                        "include_details": include_details,
                        "request_id": request_id,
                        "correlation_id": correlation_id,
                        "duration_ms": int((time.time() - operation_start) * 1000),
                    },
                    audit_logger,
                )

            self.logger.info(f"Found {len(entries)} entries in {validated_path}")
            return entries

        # Store references to decorated functions
        self.read_file = read_file
        self.write_file = write_file
        self.list_directory = list_directory

    async def _validate_path(self, path: FilePath, operation: OperationType) -> Path:
        """
        Validate file path for security and constraints.

        Args:
            path: File path to validate
            operation: Operation type

        Returns:
            Validated Path object

        Raises:
            SecurityValidationError: If path validation fails
            PathTraversalError: If path traversal detected
            FileTypeNotAllowedError: If file type not allowed
        """
        try:
            # Convert to Path object and resolve
            path_obj = Path(path).resolve()

            # Check for path traversal attempts
            if ".." in str(path):
                raise PathTraversalError(str(path))

            # Check base directory constraint
            if self.base_directory:
                try:
                    path_obj.relative_to(self.base_directory)
                except ValueError:
                    raise SecurityValidationError(
                        f"Path outside base directory: {path}"
                    )

            # Check file extension for write operations
            if (
                operation == OperationType.WRITE
                and path_obj.suffix
                and path_obj.suffix.lower() not in self.allowed_extensions
            ):
                raise FileTypeNotAllowedError(
                    str(path_obj),
                    path_obj.suffix.lower(),
                    list(self.allowed_extensions),
                )

            return path_obj

        except Exception as e:
            if isinstance(
                e,
                SecurityValidationError | PathTraversalError | FileTypeNotAllowedError,
            ):
                raise
            raise SecurityValidationError(f"Invalid path: {path} - {e}")

    async def _check_permissions(
        self, path: Path, operation: OperationType, auth_service: str
    ) -> None:
        """
        Check file permissions using auth service.

        Args:
            path: Path to check
            operation: Operation type
            auth_service: Auth service identifier

        Raises:
            FileAccessDeniedError: If permission denied
        """
        # In a real implementation, this would call the auth service
        # For now, just log the permission check
        self.logger.info(f"Permission check: {operation} on {path} via {auth_service}")

        # Basic permission check
        if (
            operation in [OperationType.READ, OperationType.LIST]
            and not os.access(path, os.R_OK)
            or (
                operation == OperationType.WRITE
                and path.exists()
                and not os.access(path, os.W_OK)
            )
        ):
            raise FileAccessDeniedError(str(path), operation.value)

    async def _audit_log(
        self, operation: str, details: dict[str, Any], audit_logger: str
    ) -> None:
        """
        Log operation to audit system.

        Args:
            operation: Operation type
            details: Operation details
            audit_logger: Audit logger identifier
        """
        # In a real implementation, this would send to audit system
        audit_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "details": details,
            "logger": audit_logger,
        }
        self.logger.info(f"Audit log: {audit_entry}")

    async def _create_backup(self, path: Path, backup_service: str) -> Path:
        """
        Create backup using backup service.

        Args:
            path: Path to backup
            backup_service: Backup service identifier

        Returns:
            Path to created backup file
        """
        # In a real implementation, this would use the backup service
        self.logger.info(f"Creating backup of {path} via {backup_service}")
        return await self._create_local_backup(path)

    async def _create_local_backup(self, path: Path) -> Path:
        """
        Create local backup file.

        Args:
            path: Path to backup

        Returns:
            Path to created backup file

        Raises:
            FileOperationError: If backup creation fails
        """
        backup_path = path.with_suffix(
            f"{path.suffix}.backup.{int(datetime.now().timestamp())}"
        )
        try:
            async with aiofiles.open(path, "rb") as src:
                async with aiofiles.open(backup_path, "wb") as dst:
                    content = await src.read()
                    await dst.write(content)
            self.logger.info(f"Created local backup: {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.warning(f"Failed to create backup: {e}")
            raise FileOperationError(
                f"Failed to create backup for {path}: {e}",
                file_path=str(path),
                operation="backup",
                code=MCPErrorCode.INTERNAL_ERROR,
            )

    async def _calculate_file_checksum(
        self, path: Path, algorithm: str = "sha256"
    ) -> str:
        """
        Calculate file checksum.

        Args:
            path: Path to file
            algorithm: Hash algorithm (default: sha256)

        Returns:
            Hexadecimal checksum string

        Raises:
            FileOperationError: If checksum calculation fails
        """
        try:
            hash_obj = hashlib.new(algorithm)
            async with aiofiles.open(path, "rb") as f:
                while chunk := await f.read(8192):  # Read in 8KB chunks
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception as e:
            raise FileOperationError(
                f"Failed to calculate {algorithm} checksum for {path}: {e}",
                file_path=str(path),
                operation="checksum",
                code=MCPErrorCode.INTERNAL_ERROR,
            )

    async def _execute_with_retry(
        self, operation: Callable[[], Awaitable[Any]], retry_config: RetryConfig
    ) -> Any:
        """
        Execute operation with retry logic.

        Args:
            operation: Async operation to execute
            retry_config: Retry configuration

        Returns:
            Operation result

        Raises:
            Last exception if all retries exhausted
        """
        last_exception = None

        for attempt in range(retry_config.max_retries + 1):
            try:
                return await operation()
            except Exception as e:
                last_exception = e

                # Check if error is retryable
                if hasattr(e, "code") and e.code not in retry_config.retryable_errors:
                    self.logger.warning(f"Non-retryable error {e.code}: {e}")
                    raise

                # Don't retry on last attempt
                if attempt == retry_config.max_retries:
                    break

                # Calculate delay
                delay = await self._calculate_retry_delay(attempt, retry_config)

                self.logger.warning(
                    f"Operation failed (attempt {attempt + 1}/{retry_config.max_retries + 1}), "
                    f"retrying in {delay:.2f}s: {e}"
                )

                # Wait before retry
                await asyncio.sleep(delay)

        # All retries exhausted
        self.logger.error(
            f"Operation failed after {retry_config.max_retries + 1} attempts"
        )
        if last_exception:
            raise last_exception
        else:
            raise FileOperationError("Operation failed with no specific error")

    async def _calculate_retry_delay(
        self, attempt: int, retry_config: RetryConfig
    ) -> float:
        """
        Calculate retry delay based on strategy.

        Args:
            attempt: Current attempt number (0-based)
            retry_config: Retry configuration

        Returns:
            Delay in seconds
        """
        base_delay = retry_config.initial_delay_ms / 1000.0

        if retry_config.strategy == RetryStrategy.FIXED_DELAY:
            delay = base_delay
        elif retry_config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = base_delay * (attempt + 1)
        elif retry_config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = base_delay * (retry_config.backoff_multiplier**attempt)
        else:
            delay = base_delay

        # Apply maximum delay limit
        delay = min(delay, retry_config.max_delay_ms / 1000.0)

        # Add jitter if enabled
        if retry_config.jitter:
            jitter_factor = random.uniform(0.8, 1.2)
            delay *= jitter_factor

        return delay

    async def _check_rate_limit(self, operation: str) -> None:
        """
        Check and enforce rate limiting.

        Args:
            operation: Operation type

        Raises:
            RateLimitError: If rate limit exceeded
        """
        current_time = time.time()

        # Clean old entries
        if operation not in self._operation_counts:
            self._operation_counts[operation] = []

        # Remove entries older than window
        self._operation_counts[operation] = [
            ts
            for ts in self._operation_counts[operation]
            if current_time - ts < self._rate_limit_window
        ]

        # Check if we're over the limit
        if len(self._operation_counts[operation]) >= self._max_operations_per_minute:
            oldest_request = min(self._operation_counts[operation])
            retry_after = (
                int(self._rate_limit_window - (current_time - oldest_request)) + 1
            )

            raise RateLimitError(
                f"Rate limit exceeded for {operation} operations. "
                f"Max {self._max_operations_per_minute} per {self._rate_limit_window}s.",
                retry_after=retry_after,
            )

        # Record this operation
        self._operation_counts[operation].append(current_time)

    async def health_check(self) -> HealthStatus:
        """
        Perform health check for file operations.

        Returns:
            HealthStatus with current status
        """
        checks = {
            "file_system_access": await self._check_file_system_access(),
            "base_directory": await self._check_base_directory(),
            "permissions": await self._check_base_permissions(),
            "retry_config": self._check_retry_config(),
            "rate_limiting": self._check_rate_limiting(),
        }

        failed_checks = [name for name, passed in checks.items() if not passed]

        if not failed_checks:
            status = HealthStatusType.HEALTHY
        elif len(failed_checks) < len(checks) / 2:  # Less than half failed
            status = HealthStatusType.DEGRADED
        else:
            status = HealthStatusType.UNHEALTHY

        uptime = int((datetime.now() - self.start_time).total_seconds())

        return HealthStatus(
            agent_name="file-operations-agent",
            status=status,
            capabilities=[
                "file_read",
                "file_write",
                "directory_list",
                "secure_access",
                "retry_logic",
                "rate_limiting",
            ],
            timestamp=datetime.now(),
            checks=checks,
            errors=[f"Failed check: {name}" for name in failed_checks],
            uptime_seconds=uptime,
            version="2.0.0",
            metadata={
                "base_directory": (
                    str(self.base_directory) if self.base_directory else None
                ),
                "max_file_size": self.max_file_size,
                "allowed_extensions": list(self.allowed_extensions),
                "retry_strategy": self.default_retry_config.strategy.value,
                "max_retries": self.default_retry_config.max_retries,
                "rate_limit_per_minute": self._max_operations_per_minute,
                "operation_counts": {
                    op: len(times) for op, times in self._operation_counts.items()
                },
            },
        )

    async def _check_file_system_access(self) -> bool:
        """Test basic file system access."""
        try:
            # Try to create and delete a temporary file
            temp_path = Path("/tmp/.mcp_mesh_health_check")
            temp_path.write_text("health_check")
            content = temp_path.read_text()
            temp_path.unlink()
            return content == "health_check"
        except Exception:
            return False

    async def _check_base_directory(self) -> bool:
        """Check base directory access if configured."""
        if not self.base_directory:
            return True
        try:
            return self.base_directory.exists() and self.base_directory.is_dir()
        except Exception:
            return False

    async def _check_base_permissions(self) -> bool:
        """Check base directory permissions if configured."""
        if not self.base_directory:
            return True
        try:
            return os.access(self.base_directory, os.R_OK | os.W_OK)
        except Exception:
            return False

    def _check_retry_config(self) -> bool:
        """Check retry configuration validity."""
        try:
            return (
                self.default_retry_config.max_retries > 0
                and self.default_retry_config.initial_delay_ms > 0
                and self.default_retry_config.max_delay_ms
                >= self.default_retry_config.initial_delay_ms
                and 1.0 <= self.default_retry_config.backoff_multiplier <= 10.0
            )
        except Exception:
            return False

    def _check_rate_limiting(self) -> bool:
        """Check rate limiting configuration."""
        try:
            return (
                self._max_operations_per_minute > 0
                and self._rate_limit_window > 0
                and isinstance(self._operation_counts, dict)
            )
        except Exception:
            return False

    def _convert_exception_to_mcp_error(self, e: Exception) -> dict[str, Any]:
        """
        Convert exception to MCP JSON-RPC 2.0 error format.

        Args:
            e: Exception to convert

        Returns:
            MCP error dictionary
        """
        if hasattr(e, "to_mcp_response"):
            return e.to_mcp_response()  # type: ignore

        # For non-MCP exceptions, create a generic error response
        from ..shared.exceptions import FileOperationError, MCPErrorCode

        generic_error = FileOperationError(
            str(e), error_type="generic_error", code=MCPErrorCode.INTERNAL_ERROR
        )
        return generic_error.to_mcp_response()

    async def _validate_disk_space(self, path: Path, required_bytes: int) -> None:
        """
        Validate available disk space before operations.

        Args:
            path: Path to check disk space for
            required_bytes: Minimum required bytes

        Raises:
            TransientError: If insufficient disk space
        """
        try:
            import shutil

            total, used, free = shutil.disk_usage(
                path.parent if path.is_file() else path
            )

            if free < required_bytes:
                raise TransientError(
                    f"Insufficient disk space: {free} bytes available, {required_bytes} bytes required",
                    retry_delay=30,
                )
        except Exception as e:
            self.logger.warning(f"Could not check disk space: {e}")

    async def _validate_memory_availability(self, required_bytes: int) -> None:
        """
        Validate available memory for large operations.

        Args:
            required_bytes: Minimum required memory in bytes

        Raises:
            TransientError: If insufficient memory available
        """
        try:
            import psutil

            available_memory = psutil.virtual_memory().available

            if available_memory < required_bytes * 2:  # 2x buffer for safety
                raise TransientError(
                    f"Insufficient memory: {available_memory} bytes available, {required_bytes * 2} bytes required",
                    retry_delay=15,
                )
        except ImportError:
            # psutil not available, skip memory check
            self.logger.debug("psutil not available, skipping memory check")
        except Exception as e:
            self.logger.warning(f"Could not check memory availability: {e}")

    async def cleanup(self) -> None:
        """Cleanup resources when file operations are no longer needed."""
        self.logger.info("Cleaning up file operations")

        # Cleanup mesh decorators
        for func_name in ["read_file", "write_file", "list_directory"]:
            func = getattr(self, func_name, None)
            if func and hasattr(func, "_mesh_agent_metadata"):
                decorator_instance = func._mesh_agent_metadata["decorator_instance"]
                await decorator_instance.cleanup()

        # Clear rate limiting data
        self._operation_counts.clear()

        self.logger.info("File operations cleanup completed")
