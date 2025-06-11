"""FileOperations class for MCP SDK compatibility.

This module provides a compatibility layer that delegates to the comprehensive
implementation in the runtime.tools module when available.
"""

import os
from pathlib import Path
from typing import Any

from .exceptions import (
    FileOperationError,
    PermissionDeniedError,
    SecurityValidationError,
)

# Check if comprehensive implementation is available
try:
    import importlib.util

    spec = importlib.util.find_spec(
        ".runtime.tools.file_operations", package="mcp_mesh"
    )
    ADVANCED_IMPLEMENTATION_AVAILABLE = spec is not None
except ImportError:
    ADVANCED_IMPLEMENTATION_AVAILABLE = False


class FileOperations:
    """
    Abstract FileOperations class with basic implementations.

    This class provides basic file operations for MCP SDK compatibility.
    When used with the full mcp-mesh package, it will be enhanced with
    advanced features like mesh integration, retry logic, and monitoring.
    """

    def __init__(
        self,
        base_directory: str | None = None,
        max_file_size: int = 10 * 1024 * 1024,
        **kwargs: Any,
    ) -> None:
        """
        Initialize file operations.

        Args:
            base_directory: Optional base directory for operations
            max_file_size: Maximum file size in bytes (default: 10MB)
            **kwargs: Additional configuration (ignored in types-only package)
        """
        self.base_directory = Path(base_directory) if base_directory else None
        self.max_file_size = max_file_size

        # Basic allowed file extensions for security
        self.allowed_extensions = {
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

    async def read_file(self, path: str, encoding: str = "utf-8", **kwargs: Any) -> str:
        """
        Read file contents with basic validation.

        Args:
            path: File path to read
            encoding: File encoding (default: utf-8)
            **kwargs: Additional parameters (ignored in types-only package)

        Returns:
            File contents as string

        Raises:
            FileOperationError: If file operation fails
            SecurityValidationError: If security validation fails
            PermissionDeniedError: If access denied
        """
        validated_path = await self._validate_path(path, "read")

        try:
            if not validated_path.exists():
                raise FileOperationError(f"File not found: {path}")

            if not validated_path.is_file():
                raise FileOperationError(f"Path is not a file: {path}")

            # Check file size
            file_size = validated_path.stat().st_size
            if file_size > self.max_file_size:
                raise FileOperationError(
                    f"File too large: {file_size} bytes (max: {self.max_file_size})"
                )

            # Read file content
            with open(validated_path, encoding=encoding) as f:
                content = f.read()

            return content

        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied reading {path}") from e
        except UnicodeDecodeError as e:
            raise FileOperationError(f"Encoding error reading {path}: {e}") from e
        except Exception as e:
            raise FileOperationError(f"Error reading {path}: {e}") from e

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_backup: bool = False,
        **kwargs: Any,
    ) -> bool:
        """
        Write content to file with basic validation.

        Args:
            path: File path to write
            content: Content to write
            encoding: File encoding (default: utf-8)
            create_backup: Whether to create backup (ignored in types-only package)
            **kwargs: Additional parameters (ignored in types-only package)

        Returns:
            True if successful

        Raises:
            FileOperationError: If file operation fails
            SecurityValidationError: If security validation fails
            PermissionDeniedError: If access denied
        """
        validated_path = await self._validate_path(path, "write")

        try:
            # Check content size
            content_size = len(content.encode(encoding))
            if content_size > self.max_file_size:
                raise FileOperationError(
                    f"Content too large: {content_size} bytes (max: {self.max_file_size})"
                )

            # Ensure parent directory exists
            validated_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file content
            with open(validated_path, "w", encoding=encoding) as f:
                f.write(content)

            return True

        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied writing {path}") from e
        except Exception as e:
            raise FileOperationError(f"Error writing {path}: {e}") from e

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
        include_details: bool = False,
        **kwargs: Any,
    ) -> list[str | dict[str, Any]]:
        """
        List directory contents with basic validation.

        Args:
            path: Directory path to list
            include_hidden: Include hidden files (starting with .)
            include_details: Include file details (size, modified date)
            **kwargs: Additional parameters (ignored in types-only package)

        Returns:
            List of file/directory names or detailed info

        Raises:
            FileOperationError: If operation fails
            SecurityValidationError: If security validation fails
            PermissionDeniedError: If access denied
        """
        validated_path = await self._validate_path(path, "list")

        try:
            if not validated_path.exists():
                raise FileOperationError(f"Directory not found: {path}")

            if not validated_path.is_dir():
                raise FileOperationError(f"Path is not a directory: {path}")

            entries = []

            for entry in validated_path.iterdir():
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
                            "is_symlink": entry.is_symlink(),
                        }
                        entries.append(entry_info)
                    except (OSError, PermissionError):
                        # Log but don't fail for individual file errors
                        entries.append(
                            {
                                "name": entry.name,
                                "path": str(entry),
                                "type": "unknown",
                                "error": "Permission denied or stat failed",
                            }
                        )
                else:
                    entries.append(entry.name)

            return entries

        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied listing {path}") from e
        except Exception as e:
            raise FileOperationError(f"Error listing directory {path}: {e}") from e

    async def _validate_path(self, path: str, operation: str) -> Path:
        """
        Validate file path for security and constraints.

        Args:
            path: File path to validate
            operation: Operation type

        Returns:
            Validated Path object

        Raises:
            SecurityValidationError: If path validation fails
        """
        try:
            # Convert to Path object and resolve
            path_obj = Path(path).resolve()

            # Check for path traversal attempts
            if ".." in str(path):
                raise SecurityValidationError(f"Path traversal detected: {path}")

            # Check base directory constraint
            if self.base_directory:
                try:
                    path_obj.relative_to(self.base_directory)
                except ValueError as e:
                    raise SecurityValidationError(
                        f"Path outside base directory: {path}"
                    ) from e

            # Check file extension for write operations
            if operation == "write" and path_obj.suffix:
                if path_obj.suffix.lower() not in self.allowed_extensions:
                    raise SecurityValidationError(
                        f"File type not allowed: {path_obj.suffix}"
                    )

            return path_obj

        except Exception as e:
            if isinstance(e, SecurityValidationError):
                raise
            raise SecurityValidationError(f"Invalid path: {path} - {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """
        Basic health check for file operations.

        Returns:
            Health status dictionary
        """
        try:
            # Test basic file system access
            test_dir = Path("/tmp")
            readable = os.access(test_dir, os.R_OK)
            writable = os.access(test_dir, os.W_OK)

            return {
                "status": "healthy" if readable and writable else "degraded",
                "checks": {
                    "file_system_readable": readable,
                    "file_system_writable": writable,
                    "base_directory_valid": self._check_base_directory(),
                },
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_base_directory(self) -> bool:
        """Check base directory validity."""
        if not self.base_directory:
            return True
        try:
            return self.base_directory.exists() and self.base_directory.is_dir()
        except Exception:
            return False
