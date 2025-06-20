"""MCP Mesh Shared Types

Common types and data structures used across the mesh with comprehensive type annotations.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Literal,
    Protocol,
    TypeVar,
    Union,
)
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.types import NonNegativeInt, PositiveInt, StrictStr

# Type variables for generic types
T = TypeVar("T")
ErrorCodeType = TypeVar("ErrorCodeType", bound=int)


class HealthStatusType(str, Enum):
    """Health status enumeration."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class OperationType(str, Enum):
    """File operation types."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    LIST = "list"
    CREATE = "create"
    MOVE = "move"
    COPY = "copy"


class SecurityContextType(str, Enum):
    """Security context types."""

    FILE_OPERATIONS = "file_operations"
    MESH_OPERATIONS = "mesh_operations"
    REGISTRY_ACCESS = "registry_access"
    ADMIN_OPERATIONS = "admin_operations"


class RetryStrategy(str, Enum):
    """Retry strategy types."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    NO_RETRY = "no_retry"


class FileInfo(BaseModel):
    """File information model."""

    name: StrictStr = Field(..., description="File name")
    path: StrictStr = Field(..., description="File path")
    size: NonNegativeInt = Field(..., description="File size in bytes")
    modified: datetime = Field(..., description="Last modified timestamp")
    created: datetime | None = Field(None, description="Creation timestamp")
    permissions: StrictStr = Field(..., description="File permissions (octal)")
    file_type: Literal["file", "directory", "symlink"] = Field(
        ..., description="File type"
    )
    mime_type: StrictStr | None = Field(None, description="MIME type for files")
    checksum: StrictStr | None = Field(None, description="File checksum (SHA-256)")

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: str) -> str:
        """Validate permissions format."""
        if not v.isdigit() or len(v) != 3:
            raise ValueError("Permissions must be 3-digit octal string")
        return v

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class DirectoryListing(BaseModel):
    """Directory listing model."""

    path: StrictStr = Field(..., description="Directory path")
    entries: list[FileInfo] = Field(..., description="Directory entries")
    total_count: NonNegativeInt = Field(..., description="Total number of entries")
    filtered_count: NonNegativeInt = Field(
        ..., description="Number of entries after filtering"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Listing timestamp"
    )

    @field_validator("filtered_count")
    @classmethod
    def validate_filtered_count(cls, v: int, info: Any) -> int:
        """Validate filtered count does not exceed total count."""
        if info.data and "total_count" in info.data and v > info.data["total_count"]:
            raise ValueError("Filtered count cannot exceed total count")
        return v


class FileOperationRequest(BaseModel):
    """File operation request model."""

    operation: OperationType = Field(..., description="Operation type")
    path: StrictStr = Field(..., description="Target file path")
    content: StrictStr | None = Field(None, description="Content for write operations")
    encoding: StrictStr = Field("utf-8", description="File encoding")
    create_backup: bool = Field(True, description="Create backup before write")
    overwrite: bool = Field(False, description="Allow overwrite existing files")
    recursive: bool = Field(False, description="Recursive operation for directories")
    include_hidden: bool = Field(False, description="Include hidden files in listings")
    include_details: bool = Field(
        False, description="Include detailed file information"
    )
    max_size_bytes: PositiveInt = Field(
        10485760, description="Maximum file size (10MB default)"
    )
    request_id: StrictStr | None = Field(None, description="Request identifier")
    correlation_id: StrictStr | None = Field(None, description="Correlation identifier")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate file path format."""
        if ".." in v:
            raise ValueError("Path cannot contain '..' for security")
        return v

    @model_validator(mode="after")
    def validate_operation_requirements(self) -> "FileOperationRequest":
        """Validate operation-specific requirements."""
        operation = self.operation
        content = self.content

        if operation == OperationType.WRITE and content is None:
            raise ValueError("Write operations require content")

        if (
            operation in [OperationType.READ, OperationType.LIST]
            and content is not None
        ):
            raise ValueError(f"{operation.value} operations should not include content")

        return self


class FileOperationResponse(BaseModel):
    """File operation response model."""

    success: bool = Field(..., description="Operation success status")
    operation: OperationType = Field(..., description="Operation type")
    path: StrictStr = Field(..., description="Target file path")
    content: StrictStr | None = Field(
        None, description="File content for read operations"
    )
    file_info: FileInfo | None = Field(None, description="File information")
    directory_listing: DirectoryListing | None = Field(
        None, description="Directory listing"
    )
    bytes_processed: NonNegativeInt = Field(0, description="Number of bytes processed")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Response timestamp"
    )
    duration_ms: NonNegativeInt = Field(
        ..., description="Operation duration in milliseconds"
    )
    request_id: StrictStr | None = Field(None, description="Request identifier")
    correlation_id: StrictStr | None = Field(None, description="Correlation identifier")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metadata"
    )

    @model_validator(mode="after")
    def validate_response_content(self) -> "FileOperationResponse":
        """Validate response content based on operation type."""
        operation = self.operation
        content = self.content
        directory_listing = self.directory_listing

        if operation == OperationType.READ and not content:
            raise ValueError("Read operations must return content")

        if operation == OperationType.LIST and not directory_listing:
            raise ValueError("List operations must return directory listing")

        return self


class RetryConfig(BaseModel):
    """Retry configuration model."""

    strategy: RetryStrategy = Field(
        RetryStrategy.EXPONENTIAL_BACKOFF, description="Retry strategy"
    )
    max_retries: PositiveInt = Field(3, description="Maximum retry attempts")
    initial_delay_ms: PositiveInt = Field(
        1000, description="Initial delay in milliseconds"
    )
    max_delay_ms: PositiveInt = Field(
        30000, description="Maximum delay in milliseconds"
    )
    backoff_multiplier: float = Field(
        2.0, ge=1.0, le=10.0, description="Backoff multiplier"
    )
    jitter: bool = Field(True, description="Add random jitter to delays")
    retryable_errors: list[int] = Field(
        default_factory=lambda: [-32003, -32004, -34001, -34002, -34005],
        description="List of retryable error codes",
    )

    @field_validator("backoff_multiplier")
    @classmethod
    def validate_backoff_multiplier(cls, v: float) -> float:
        """Validate backoff multiplier is reasonable."""
        if v < 1.0 or v > 10.0:
            raise ValueError("Backoff multiplier must be between 1.0 and 10.0")
        return v


class HealthCheck(BaseModel):
    """Health check configuration and result model."""

    check_name: StrictStr = Field(..., description="Health check name")
    enabled: bool = Field(True, description="Whether check is enabled")
    interval_seconds: PositiveInt = Field(30, description="Check interval in seconds")
    timeout_seconds: PositiveInt = Field(10, description="Check timeout in seconds")
    critical: bool = Field(False, description="Whether failure makes service unhealthy")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Check metadata"
    )


class HealthStatus(BaseModel):
    """Health status information for mesh agents."""

    agent_name: StrictStr = Field(..., description="Agent name")
    status: HealthStatusType = Field(..., description="Overall health status")
    capabilities: list[StrictStr] = Field(..., description="Agent capabilities")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Status timestamp"
    )
    checks: dict[str, bool] = Field(
        default_factory=dict, description="Individual check results"
    )
    errors: list[StrictStr] = Field(default_factory=list, description="Error messages")
    uptime_seconds: NonNegativeInt = Field(0, description="Agent uptime in seconds")
    version: StrictStr | None = Field(None, description="Agent version")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        """Validate capabilities list is not empty."""
        if not v:
            raise ValueError("Agent must have at least one capability")
        return v

    def is_healthy(self) -> bool:
        """Check if agent is healthy."""
        return self.status == HealthStatusType.HEALTHY

    def get_failed_checks(self) -> list[str]:
        """Get list of failed check names."""
        return [name for name, passed in self.checks.items() if not passed]


class DependencyConfig(BaseModel):
    """Configuration for dependency injection."""

    name: StrictStr = Field(..., description="Dependency name")
    type: StrictStr = Field(..., description="Dependency type")
    value: Any = Field(..., description="Dependency value")
    ttl_seconds: PositiveInt = Field(
        300, description="TTL in seconds (5 minutes default)"
    )
    security_context: SecurityContextType | None = Field(
        None, description="Security context"
    )
    required: bool = Field(True, description="Whether dependency is required")
    lazy_load: bool = Field(False, description="Whether to load dependency lazily")
    retry_config: RetryConfig | None = Field(None, description="Retry configuration")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate dependency name format."""
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "Dependency name must be alphanumeric with underscores or hyphens"
            )
        return v


class MeshAgentConfig(BaseModel):
    """Mesh agent configuration model."""

    agent_name: StrictStr = Field(..., description="Agent name")
    capabilities: list[StrictStr] = Field(..., description="Agent capabilities")
    dependencies: list[DependencyConfig] = Field(
        default_factory=list, description="Dependencies"
    )
    health_interval: PositiveInt = Field(
        30, description="Health check interval in seconds"
    )
    security_context: SecurityContextType = Field(..., description="Security context")
    fallback_mode: bool = Field(True, description="Enable fallback mode")
    retry_config: RetryConfig | None = Field(
        None, description="Default retry configuration"
    )
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Agent metadata"
    )

    @field_validator("agent_name")
    @classmethod
    def validate_agent_name(cls, v: str) -> str:
        """Validate agent name format."""
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Agent name must be alphanumeric with hyphens or underscores"
            )
        return v


class MCPRequest(BaseModel):
    """MCP JSON-RPC 2.0 request model."""

    jsonrpc: Literal["2.0"] = Field("2.0", description="JSON-RPC version")
    method: StrictStr = Field(..., description="Method name")
    params: dict[str, Any] | None = Field(None, description="Method parameters")
    id: str | int | None = Field(None, description="Request identifier")


class MCPResponse(BaseModel):
    """MCP JSON-RPC 2.0 response model."""

    jsonrpc: Literal["2.0"] = Field("2.0", description="JSON-RPC version")
    result: Any | None = Field(None, description="Method result")
    error: dict[str, Any] | None = Field(None, description="Error information")
    id: str | int | None = Field(None, description="Request identifier")

    @model_validator(mode="after")
    def validate_result_or_error(self) -> "MCPResponse":
        """Validate that response has either result or error, but not both."""
        result = self.result
        error = self.error

        if result is not None and error is not None:
            raise ValueError("Response cannot have both result and error")

        if result is None and error is None:
            raise ValueError("Response must have either result or error")

        return self


class SecurityContext(BaseModel):
    """Security context model."""

    context_type: SecurityContextType = Field(..., description="Security context type")
    user_id: StrictStr | None = Field(None, description="User identifier")
    session_id: StrictStr | None = Field(None, description="Session identifier")
    permissions: list[StrictStr] = Field(
        default_factory=list, description="Granted permissions"
    )
    restrictions: dict[str, Any] = Field(
        default_factory=dict, description="Security restrictions"
    )
    expiry: datetime | None = Field(None, description="Context expiry time")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Security metadata"
    )

    def is_expired(self) -> bool:
        """Check if security context is expired."""
        if self.expiry is None:
            return False
        return datetime.now() > self.expiry

    def has_permission(self, permission: str) -> bool:
        """Check if context has specific permission."""
        return permission in self.permissions


# Protocol definitions for type checking
class RetryableProtocol(Protocol):
    """Protocol for retryable operations."""

    async def execute_with_retry(
        self, operation: Any, retry_config: RetryConfig | None = None
    ) -> Any:
        """Execute operation with retry logic."""
        ...


class HealthCheckProtocol(Protocol):
    """Protocol for health checkable components."""

    async def health_check(self) -> HealthStatus:
        """Perform health check."""
        ...


class SecureOperationProtocol(Protocol):
    """Protocol for secure operations."""

    async def validate_security_context(self, context: SecurityContext) -> bool:
        """Validate security context."""
        ...


# Legacy dataclass for backward compatibility
@dataclass
class LegacyHealthStatus:
    """Legacy health status for backward compatibility."""

    agent_name: str
    status: str
    capabilities: list[str]
    timestamp: datetime
    metadata: dict[str, Any] | None = None

    def dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent_name": self.agent_name,
            "status": self.status,
            "capabilities": self.capabilities,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {},
        }


@dataclass
class LegacyDependencyConfig:
    """Legacy dependency config for backward compatibility."""

    name: str
    type: str
    value: Any
    ttl_seconds: int = 300
    security_context: str | None = None
    metadata: dict[str, Any] | None = None


# Type aliases for common patterns
FilePath = Union[str, Path]
FileContent = Union[str, bytes]
ErrorCode = int
Timestamp = datetime
Metadata = dict[str, Any]
Capabilities = list[str]
Permissions = list[str]


class DiskSpaceInfo(BaseModel):
    """Disk space information model."""

    total_bytes: NonNegativeInt = Field(..., description="Total disk space in bytes")
    used_bytes: NonNegativeInt = Field(..., description="Used disk space in bytes")
    free_bytes: NonNegativeInt = Field(..., description="Free disk space in bytes")
    usage_percent: float = Field(
        ..., ge=0.0, le=100.0, description="Disk usage percentage"
    )
    path: StrictStr = Field(..., description="Path checked for disk space")

    @field_validator("usage_percent")
    @classmethod
    def validate_usage_percent(cls, v: float) -> float:
        """Validate usage percentage is within bounds."""
        if not 0.0 <= v <= 100.0:
            raise ValueError("Usage percentage must be between 0.0 and 100.0")
        return v


class FileChecksum(BaseModel):
    """File checksum model."""

    algorithm: StrictStr = Field(..., description="Hash algorithm (e.g., sha256, md5)")
    digest: StrictStr = Field(..., description="Hexadecimal digest")
    file_path: StrictStr = Field(..., description="Path to file")
    computed_at: datetime = Field(
        default_factory=datetime.now, description="When checksum was computed"
    )

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, v: str) -> str:
        """Validate digest is hexadecimal."""
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("Digest must be hexadecimal")
        return v.lower()


class FileBackup(BaseModel):
    """File backup information model."""

    original_path: StrictStr = Field(..., description="Original file path")
    backup_path: StrictStr = Field(..., description="Backup file path")
    created_at: datetime = Field(
        default_factory=datetime.now, description="Backup creation time"
    )
    original_size: NonNegativeInt = Field(
        ..., description="Original file size in bytes"
    )
    backup_size: NonNegativeInt = Field(..., description="Backup file size in bytes")
    checksum: FileChecksum | None = Field(None, description="Backup file checksum")
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional backup metadata"
    )


class RateLimitStatus(BaseModel):
    """Rate limiting status model."""

    operation: StrictStr = Field(..., description="Operation type")
    current_count: NonNegativeInt = Field(
        ..., description="Current operation count in window"
    )
    max_count: PositiveInt = Field(..., description="Maximum operations allowed")
    window_seconds: PositiveInt = Field(..., description="Time window in seconds")
    reset_at: datetime = Field(..., description="When the rate limit window resets")
    is_limited: bool = Field(..., description="Whether rate limit is currently active")
    retry_after_seconds: PositiveInt | None = Field(
        None, description="Seconds to wait before retry"
    )


class FileOperationMetrics(BaseModel):
    """File operation metrics model."""

    operation_type: OperationType = Field(..., description="Type of operation")
    file_path: StrictStr = Field(..., description="File path")
    duration_ms: NonNegativeInt = Field(
        ..., description="Operation duration in milliseconds"
    )
    bytes_processed: NonNegativeInt = Field(..., description="Bytes read or written")
    success: bool = Field(..., description="Whether operation succeeded")
    error_code: int | None = Field(None, description="Error code if operation failed")
    retry_count: NonNegativeInt = Field(0, description="Number of retries performed")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Operation timestamp"
    )
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Additional metrics"
    )


class EndpointInfo(BaseModel):
    """Service endpoint information model."""

    url: StrictStr = Field(..., description="Service endpoint URL")
    service_name: StrictStr = Field(..., description="Service name")
    service_version: StrictStr = Field("1.0.0", description="Service version")
    protocol: StrictStr = Field("mcp", description="Communication protocol")
    status: HealthStatusType = Field(
        HealthStatusType.UNKNOWN, description="Endpoint status"
    )
    metadata: dict[str, Any] | None = Field(
        default_factory=dict, description="Endpoint metadata"
    )
    last_updated: datetime = Field(
        default_factory=datetime.now, description="Last status update"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate URL format."""
        if not (
            v.startswith("http://")
            or v.startswith("https://")
            or v.startswith("mcp://")
        ):
            raise ValueError("URL must start with http://, https://, or mcp://")
        return v


# Registry models (moved from server/models.py during cleanup)
class AgentCapability(BaseModel):
    """Represents a capability that an agent provides."""

    name: str
    description: str | None = None
    version: str = "1.0.0"
    compatibility_versions: list[str] = Field(default_factory=list)
    parameters_schema: dict[str, Any] | None = None
    security_requirements: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    stability: str = "stable"  # stable, beta, alpha, deprecated

    @field_validator("name")
    @classmethod
    def validate_capability_name(cls, v):
        """Validate capability name format."""
        import re

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", v):
            raise ValueError(
                "Capability name must start with letter and contain only letters, numbers, underscore, hyphen"
            )
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v):
        """Validate semantic version format."""
        import re

        if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9-]+)?$", v):
            raise ValueError("Version must follow semantic versioning (x.y.z)")
        return v

    @field_validator("stability")
    @classmethod
    def validate_stability(cls, v):
        """Validate stability level."""
        if v not in ["stable", "beta", "alpha", "deprecated"]:
            raise ValueError(
                "Stability must be one of: stable, beta, alpha, deprecated"
            )
        return v


class AgentRegistration(BaseModel):
    """Agent registration information following Kubernetes resource pattern."""

    # Kubernetes-style metadata
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    namespace: str = "default"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)

    # Registration metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resource_version: str = Field(default_factory=lambda: str(int(time.time() * 1000)))

    # Agent information
    endpoint: str
    capabilities: list[AgentCapability] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)

    # Health and lifecycle
    status: str = "pending"  # pending, healthy, degraded, expired, offline
    last_heartbeat: datetime | None = None
    health_interval: int = 30  # seconds
    timeout_threshold: int = 60  # seconds until marked degraded
    eviction_threshold: int = 120  # seconds until marked expired/evicted
    agent_type: str = "default"  # for type-specific timeout configuration

    # Configuration
    config: dict[str, Any] = Field(default_factory=dict)
    security_context: str | None = None

    @field_validator("name")
    @classmethod
    def validate_agent_name(cls, v):
        """Validate agent name follows Kubernetes naming convention."""
        import re

        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Agent name must be lowercase alphanumeric with hyphens, start and end with alphanumeric"
            )
        if len(v) > 63:
            raise ValueError("Agent name must be 63 characters or less")
        return v

    @field_validator("namespace")
    @classmethod
    def validate_namespace(cls, v):
        """Validate namespace follows Kubernetes naming convention."""
        import re

        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Namespace must be lowercase alphanumeric with hyphens, start and end with alphanumeric"
            )
        if len(v) > 63:
            raise ValueError("Namespace must be 63 characters or less")
        return v


# Generic response types
SuccessResponse = MCPResponse
ErrorResponse = MCPResponse
AsyncOperation = asyncio.Future[T]
RetryableOperation = Union[Coroutine[Any, Any, T], Callable[[], Awaitable[T]]]


class MockHTTPResponse:
    """Mock HTTP response for fallback scenarios."""

    def __init__(self, data: Any, status: int = 200):
        self.status = status
        self.status_code = status  # Add status_code for compatibility
        self._data = data

    async def json(self) -> Any:
        """Return JSON data."""
        return self._data

    async def text(self) -> str:
        """Return text representation."""
        return str(self._data)
