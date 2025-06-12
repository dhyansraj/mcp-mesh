# MCP-Mesh SDK API Reference

Complete API documentation for the MCP-Mesh SDK components and classes.

## Table of Contents

1. [Decorators](#decorators)
2. [File Operations](#file-operations)
3. [Shared Types](#shared-types)
4. [Exception Classes](#exception-classes)
5. [Registry Client](#registry-client)
6. [Utilities](#utilities)

## Decorators

### @mesh_agent

The core decorator for integrating MCP tools with mesh infrastructure.

```python
def mesh_agent(
    capabilities: List[str],
    health_interval: int = 30,
    dependencies: Optional[List[str]] = None,
    registry_url: Optional[str] = None,
    agent_name: Optional[str] = None,
    security_context: Optional[str] = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True
) -> Callable[[F], F]
```

#### Parameters

| Parameter          | Type                  | Default      | Description                                    |
| ------------------ | --------------------- | ------------ | ---------------------------------------------- |
| `capabilities`     | `List[str]`           | **Required** | List of capabilities this tool provides        |
| `health_interval`  | `int`                 | `30`         | Heartbeat interval in seconds                  |
| `dependencies`     | `Optional[List[str]]` | `None`       | List of service dependencies to inject         |
| `registry_url`     | `Optional[str]`       | `None`       | Registry service URL (from env/config if None) |
| `agent_name`       | `Optional[str]`       | `None`       | Agent identifier (auto-generated if None)      |
| `security_context` | `Optional[str]`       | `None`       | Security context for authorization             |
| `timeout`          | `int`                 | `30`         | Network timeout in seconds                     |
| `retry_attempts`   | `int`                 | `3`          | Number of retry attempts for registry calls    |
| `enable_caching`   | `bool`                | `True`       | Enable local caching of dependencies           |
| `fallback_mode`    | `bool`                | `True`       | Enable graceful degradation mode               |

#### Returns

- **Type**: `Callable[[F], F]`
- **Description**: Decorated function with mesh integration

#### Example

```python
@mesh_agent(
    capabilities=["file_read", "secure_access"],
    dependencies=["auth_service", "audit_logger"],
    health_interval=30,
    security_context="file_operations",
    agent_name="file-operations-agent"
)
async def read_file(
    path: str,
    encoding: str = "utf-8",
    auth_service: Optional[str] = None,
    audit_logger: Optional[str] = None
) -> str:
    # Implementation
    pass
```

#### Automatic Features

The decorator automatically handles:

- ✅ Registry registration of capabilities
- ✅ Periodic health monitoring
- ✅ Dependency injection
- ✅ Error handling and fallback modes
- ✅ Caching of dependency values
- ✅ Connection retry logic

## File Operations

### FileOperations Class

Provides secure file system operations with mesh integration.

```python
class FileOperations:
    def __init__(
        self,
        base_directory: Optional[FilePath] = None,
        max_file_size: int = 10 * 1024 * 1024,
        retry_config: Optional[RetryConfig] = None
    ) -> None
```

#### Constructor Parameters

| Parameter        | Type                    | Default    | Description                                           |
| ---------------- | ----------------------- | ---------- | ----------------------------------------------------- |
| `base_directory` | `Optional[FilePath]`    | `None`     | Base directory for operations (None = no restriction) |
| `max_file_size`  | `int`                   | `10485760` | Maximum file size in bytes (10MB)                     |
| `retry_config`   | `Optional[RetryConfig]` | `None`     | Default retry configuration                           |

#### Methods

##### read_file

```python
async def read_file(
    self,
    path: str,
    encoding: str = "utf-8",
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    auth_service: Optional[str] = None,
    audit_logger: Optional[str] = None
) -> str
```

Read file contents with security validation and mesh integration.

**Parameters:**

- `path` (str): File path to read
- `encoding` (str): File encoding (default: utf-8)
- `request_id` (Optional[str]): Request identifier for tracking
- `correlation_id` (Optional[str]): Correlation identifier for tracking
- `retry_config` (Optional[RetryConfig]): Override retry configuration
- `auth_service` (Optional[str]): Authentication service (injected by mesh)
- `audit_logger` (Optional[str]): Audit logging service (injected by mesh)

**Returns:** File contents as string

**Raises:**

- `FileNotFoundError`: If file not found
- `FileAccessDeniedError`: If access denied
- `FileTooLargeError`: If file exceeds size limit
- `EncodingError`: If encoding error occurs
- `SecurityValidationError`: If security validation fails

##### write_file

```python
async def write_file(
    self,
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_backup: bool = True,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    auth_service: Optional[str] = None,
    audit_logger: Optional[str] = None,
    backup_service: Optional[str] = None
) -> bool
```

Write content to file with backup, validation and mesh integration.

**Parameters:**

- `path` (str): File path to write
- `content` (str): Content to write
- `encoding` (str): File encoding (default: utf-8)
- `create_backup` (bool): Whether to create backup before writing
- `request_id` (Optional[str]): Request identifier for tracking
- `correlation_id` (Optional[str]): Correlation identifier for tracking
- `retry_config` (Optional[RetryConfig]): Override retry configuration
- `auth_service` (Optional[str]): Authentication service (injected by mesh)
- `audit_logger` (Optional[str]): Audit logging service (injected by mesh)
- `backup_service` (Optional[str]): Backup service (injected by mesh)

**Returns:** True if successful

**Raises:**

- `FileAccessDeniedError`: If access denied
- `FileTooLargeError`: If content exceeds size limit
- `FileTypeNotAllowedError`: If file type not allowed
- `SecurityValidationError`: If security validation fails

##### list_directory

```python
async def list_directory(
    self,
    path: str,
    include_hidden: bool = False,
    include_details: bool = False,
    request_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    auth_service: Optional[str] = None,
    audit_logger: Optional[str] = None
) -> List[Union[str, Dict[str, Any]]]
```

List directory contents with security validation and mesh integration.

**Parameters:**

- `path` (str): Directory path to list
- `include_hidden` (bool): Include hidden files (starting with .)
- `include_details` (bool): Include file details (size, modified date)
- `request_id` (Optional[str]): Request identifier for tracking
- `correlation_id` (Optional[str]): Correlation identifier for tracking
- `retry_config` (Optional[RetryConfig]): Override retry configuration
- `auth_service` (Optional[str]): Authentication service (injected by mesh)
- `audit_logger` (Optional[str]): Audit logging service (injected by mesh)

**Returns:** List of file/directory names or detailed info

**Raises:**

- `DirectoryNotFoundError`: If directory not found
- `FileAccessDeniedError`: If access denied
- `SecurityValidationError`: If security validation fails

##### health_check

```python
async def health_check(self) -> HealthStatus
```

Perform health check for file operations.

**Returns:** HealthStatus with current status

##### cleanup

```python
async def cleanup(self) -> None
```

Cleanup resources when file operations are no longer needed.

## Shared Types

### HealthStatus

```python
class HealthStatus(BaseModel):
    agent_name: StrictStr
    status: HealthStatusType
    capabilities: List[StrictStr]
    timestamp: datetime
    checks: Dict[str, bool] = Field(default_factory=dict)
    errors: List[StrictStr] = Field(default_factory=list)
    uptime_seconds: NonNegativeInt = 0
    version: Optional[StrictStr] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

Health status information for mesh agents.

#### Methods

##### is_healthy

```python
def is_healthy(self) -> bool
```

Check if agent is healthy.

##### get_failed_checks

```python
def get_failed_checks(self) -> List[str]
```

Get list of failed check names.

### HealthStatusType

```python
class HealthStatusType(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
```

### RetryConfig

```python
class RetryConfig(BaseModel):
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    max_retries: PositiveInt = 3
    initial_delay_ms: PositiveInt = 1000
    max_delay_ms: PositiveInt = 30000
    backoff_multiplier: float = Field(2.0, ge=1.0, le=10.0)
    jitter: bool = True
    retryable_errors: List[int] = Field(default_factory=lambda: [-32003, -32004, -34001, -34002, -34005])
```

Retry configuration for operations.

### RetryStrategy

```python
class RetryStrategy(str, Enum):
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    NO_RETRY = "no_retry"
```

### FileInfo

```python
class FileInfo(BaseModel):
    name: StrictStr
    path: StrictStr
    size: NonNegativeInt
    modified: datetime
    created: Optional[datetime] = None
    permissions: StrictStr
    file_type: Literal["file", "directory", "symlink"]
    mime_type: Optional[StrictStr] = None
    checksum: Optional[StrictStr] = None
```

File information model.

### DirectoryListing

```python
class DirectoryListing(BaseModel):
    path: StrictStr
    entries: List[FileInfo]
    total_count: NonNegativeInt
    filtered_count: NonNegativeInt
    timestamp: datetime = Field(default_factory=datetime.now)
```

Directory listing model.

### FileOperationRequest

```python
class FileOperationRequest(BaseModel):
    operation: OperationType
    path: StrictStr
    content: Optional[StrictStr] = None
    encoding: StrictStr = "utf-8"
    create_backup: bool = True
    overwrite: bool = False
    recursive: bool = False
    include_hidden: bool = False
    include_details: bool = False
    max_size_bytes: PositiveInt = 10485760
    request_id: Optional[StrictStr] = None
    correlation_id: Optional[StrictStr] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

File operation request model.

### FileOperationResponse

```python
class FileOperationResponse(BaseModel):
    success: bool
    operation: OperationType
    path: StrictStr
    content: Optional[StrictStr] = None
    file_info: Optional[FileInfo] = None
    directory_listing: Optional[DirectoryListing] = None
    bytes_processed: NonNegativeInt = 0
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_ms: NonNegativeInt
    request_id: Optional[StrictStr] = None
    correlation_id: Optional[StrictStr] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

File operation response model.

### OperationType

```python
class OperationType(str, Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    LIST = "list"
    CREATE = "create"
    MOVE = "move"
    COPY = "copy"
```

### SecurityContext

```python
class SecurityContext(BaseModel):
    context_type: SecurityContextType
    user_id: Optional[StrictStr] = None
    session_id: Optional[StrictStr] = None
    permissions: List[StrictStr] = Field(default_factory=list)
    restrictions: Dict[str, Any] = Field(default_factory=dict)
    expiry: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

Security context model.

#### Methods

##### is_expired

```python
def is_expired(self) -> bool
```

Check if security context is expired.

##### has_permission

```python
def has_permission(self, permission: str) -> bool
```

Check if context has specific permission.

### DependencyConfig

```python
class DependencyConfig(BaseModel):
    name: StrictStr
    type: StrictStr
    value: Any
    ttl_seconds: PositiveInt = 300
    security_context: Optional[SecurityContextType] = None
    required: bool = True
    lazy_load: bool = False
    retry_config: Optional[RetryConfig] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
```

Configuration for dependency injection.

## Exception Classes

### Base Exceptions

#### MCPError

```python
class MCPError(Exception):
    def __init__(
        self,
        message: str,
        code: Union[MCPErrorCode, int],
        data: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        retry_after: Optional[int] = None,
        correlation_id: Optional[str] = None
    ) -> None
```

Base MCP exception with JSON-RPC 2.0 compliance.

**Methods:**

- `to_dict() -> Dict[str, Any]`: Convert to MCP JSON-RPC 2.0 error format
- `to_mcp_response() -> Dict[str, Any]`: Convert to full MCP JSON-RPC 2.0 error response

#### MeshAgentError

```python
class MeshAgentError(MCPError):
    def __init__(
        self,
        message: str,
        code: Union[MCPErrorCode, int] = MCPErrorCode.INTERNAL_ERROR,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None
```

Base exception for mesh agent operations.

### File Operation Exceptions

#### FileOperationError

```python
class FileOperationError(MeshAgentError):
    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        operation: Optional[str] = None,
        error_type: str = "file_operation",
        code: Union[MCPErrorCode, int] = MCPErrorCode.INTERNAL_ERROR,
        **kwargs
    ) -> None
```

Exception for file operation failures.

#### FileNotFoundError

```python
class FileNotFoundError(FileOperationError):
    def __init__(self, file_path: str, **kwargs) -> None
```

Exception for file not found errors.

#### FileAccessDeniedError

```python
class FileAccessDeniedError(FileOperationError):
    def __init__(self, file_path: str, operation: str = "access", **kwargs) -> None
```

Exception for file access denied errors.

#### FileTooLargeError

```python
class FileTooLargeError(FileOperationError):
    def __init__(self, file_path: str, size: int, max_size: int, **kwargs) -> None
```

Exception for file too large errors.

#### FileTypeNotAllowedError

```python
class FileTypeNotAllowedError(FileOperationError):
    def __init__(self, file_path: str, file_extension: str, allowed_extensions: list, **kwargs) -> None
```

Exception for file type not allowed errors.

#### DirectoryNotFoundError

```python
class DirectoryNotFoundError(FileOperationError):
    def __init__(self, directory_path: str, **kwargs) -> None
```

Exception for directory not found errors.

#### EncodingError

```python
class EncodingError(FileOperationError):
    def __init__(self, file_path: str, encoding: str, original_error: str, **kwargs) -> None
```

Exception for file encoding errors.

### Security Exceptions

#### SecurityValidationError

```python
class SecurityValidationError(MeshAgentError):
    def __init__(
        self,
        message: str,
        violation_type: str = "security_violation",
        file_path: Optional[str] = None,
        **kwargs
    ) -> None
```

Exception for security validation failures.

#### PathTraversalError

```python
class PathTraversalError(SecurityValidationError):
    def __init__(self, file_path: str, **kwargs) -> None
```

Exception for path traversal attempts.

### Mesh Operation Exceptions

#### RegistryConnectionError

```python
class RegistryConnectionError(MeshAgentError):
    def __init__(self, message: str, registry_url: Optional[str] = None, **kwargs) -> None
```

Error connecting to the mesh registry.

#### DependencyInjectionError

```python
class DependencyInjectionError(MeshAgentError):
    def __init__(
        self,
        dependency_name: str,
        agent_name: Optional[str] = None,
        error_details: Optional[str] = None,
        **kwargs
    ) -> None
```

Error during dependency injection.

#### RetryableError

```python
class RetryableError(MeshAgentError):
    def __init__(
        self,
        message: str,
        max_retries: int = 3,
        retry_delay: int = 1,
        backoff_multiplier: float = 2.0,
        **kwargs
    ) -> None
```

Base class for errors that support retry logic.

#### TransientError

```python
class TransientError(RetryableError):
    def __init__(self, message: str, **kwargs) -> None
```

Error that is likely to be resolved by retrying.

#### RateLimitError

```python
class RateLimitError(RetryableError):
    def __init__(self, message: str, retry_after: int = 60, **kwargs) -> None
```

Error indicating rate limiting is in effect.

### MCPErrorCode

```python
class MCPErrorCode(IntEnum):
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
```

## Registry Client

### RegistryClient

```python
class RegistryClient:
    def __init__(
        self,
        url: Optional[str] = None,
        timeout: int = 30,
        retry_attempts: int = 3
    ) -> None
```

Client for interacting with the mesh registry.

#### Methods

##### register_agent

```python
async def register_agent(
    self,
    agent_name: str,
    capabilities: List[str],
    dependencies: List[str],
    security_context: Optional[str] = None
) -> None
```

Register agent capabilities with the mesh registry.

##### get_dependency

```python
async def get_dependency(self, dependency_name: str) -> Any
```

Retrieve dependency value from the registry.

##### send_heartbeat

```python
async def send_heartbeat(self, health_status: HealthStatus) -> None
```

Send heartbeat to registry with current health status.

##### close

```python
async def close(self) -> None
```

Close registry client connection.

## Utilities

### Type Aliases

```python
FilePath = Union[str, Path]
FileContent = Union[str, bytes]
ErrorCode = int
Timestamp = datetime
Metadata = Dict[str, Any]
Capabilities = List[str]
Permissions = List[str]
```

### Helper Functions

#### File Operations Helpers

```python
async def calculate_file_checksum(path: Path, algorithm: str = "sha256") -> str
async def validate_disk_space(path: Path, required_bytes: int) -> None
async def validate_memory_availability(required_bytes: int) -> None
```

#### Error Conversion

```python
def convert_exception_to_mcp_error(e: Exception) -> Dict[str, Any]
```

Convert any exception to MCP JSON-RPC 2.0 error format.

### Configuration

#### Environment Variables

| Variable               | Default        | Description                          |
| ---------------------- | -------------- | ------------------------------------ |
| `MESH_REGISTRY_URL`    | `None`         | Default registry URL                 |
| `MESH_AGENT_NAME`      | Auto-generated | Default agent name                   |
| `MESH_HEALTH_INTERVAL` | `30`           | Default health check interval        |
| `MESH_FALLBACK_MODE`   | `true`         | Enable fallback mode by default      |
| `MESH_ENABLE_CACHING`  | `true`         | Enable dependency caching by default |
| `MESH_TIMEOUT`         | `30`           | Default network timeout              |
| `MESH_RETRY_ATTEMPTS`  | `3`            | Default retry attempts               |

## Usage Examples

### Basic File Agent

```python
from mcp_mesh_sdk import mesh_agent
from mcp_mesh_sdk.tools.file_operations import FileOperations

# Create file operations instance
file_ops = FileOperations(base_directory="/safe/path")

# Use mesh-integrated file operations
@mesh_agent(capabilities=["file_read"])
async def read_config_file(filename: str) -> dict:
    content = await file_ops.read_file(f"/config/{filename}")
    return json.loads(content)
```

### Advanced Service Integration

```python
from mcp_mesh_sdk import mesh_agent
from mcp_mesh_sdk.shared.types import RetryConfig, RetryStrategy

# Configure custom retry behavior
retry_config = RetryConfig(
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    max_retries=5,
    initial_delay_ms=500
)

@mesh_agent(
    capabilities=["data_processing", "ml_inference"],
    dependencies=["ml_service", "data_store", "cache"],
    health_interval=15,
    security_context="ml_operations",
    retry_attempts=5,
    enable_caching=True
)
async def process_data(
    data: dict,
    model_name: str,
    ml_service=None,
    data_store=None,
    cache=None
) -> dict:
    """Process data with ML service integration."""

    # Check cache first
    cache_key = f"processed:{hash(str(data))}"
    if cache:
        cached_result = await cache.get(cache_key)
        if cached_result:
            return cached_result

    # Process with ML service
    if ml_service:
        result = await ml_service.predict(data, model_name)
    else:
        # Fallback processing
        result = {"status": "processed_locally", "data": data}

    # Store in cache and data store
    if cache:
        await cache.set(cache_key, result, ttl=3600)

    if data_store:
        await data_store.save(result)

    return result
```

### Error Handling

```python
from mcp_mesh_sdk.shared.exceptions import (
    FileNotFoundError, FileAccessDeniedError, MCPError, MCPErrorCode
)

@mesh_agent(capabilities=["safe_file_read"])
async def safe_read_file(path: str) -> dict:
    """Safely read file with comprehensive error handling."""
    try:
        content = await file_ops.read_file(path)
        return {"success": True, "content": content}

    except FileNotFoundError as e:
        return e.to_mcp_response()

    except FileAccessDeniedError as e:
        return e.to_mcp_response()

    except Exception as e:
        error = MCPError(
            message=f"Unexpected error: {str(e)}",
            code=MCPErrorCode.INTERNAL_ERROR,
            data={"file_path": path}
        )
        return error.to_mcp_response()
```

This comprehensive API reference provides detailed documentation for all MCP-Mesh SDK components. Use this as your primary reference when developing with the SDK.
