# MCP-Mesh SDK Development Guide

A comprehensive guide for developing with the MCP-Mesh SDK - a production-ready service mesh for Model Context Protocol (MCP) services.

## Table of Contents

1. [Quick Start](#quick-start)
2. [MCP SDK Integration](#mcp-sdk-integration)
3. [@mesh_agent Decorator Usage](#mesh_agent-decorator-usage)
4. [File Agent Development](#file-agent-development)
5. [Development Workflow](#development-workflow)
6. [API Reference](#api-reference)
7. [Testing Guide](#testing-guide)
8. [Performance & Best Practices](#performance--best-practices)
9. [Troubleshooting](#troubleshooting)

## Quick Start

### Installation

```bash
pip install mcp-mesh-sdk
```

### Basic Usage

```python
import asyncio
from mcp_mesh_sdk import mesh_agent

@mesh_agent(
    capabilities=["file_read"],
    dependencies=["auth_service"],
    health_interval=30
)
async def read_file(path: str, auth_service=None) -> str:
    """Read file with automatic mesh integration."""
    # Dependencies are automatically injected
    if auth_service:
        # Validate permissions
        pass

    with open(path, 'r') as f:
        return f.read()

# The decorator handles all mesh integration automatically
async def main():
    content = await read_file("/path/to/file.txt")
    print(content)

asyncio.run(main())
```

## MCP SDK Integration

### Overview

MCP-Mesh SDK builds on the official MCP SDK to provide:

- **Zero-boilerplate mesh integration** via decorators
- **Automatic service registration and discovery**
- **Health monitoring and dependency injection**
- **Security and error handling**

### FastMCP Framework Integration

The SDK seamlessly integrates with FastMCP:

```python
from mcp.server.fastmcp import FastMCP
from mcp_mesh_sdk import mesh_agent

app = FastMCP(name="my-service")

@mesh_agent(
    capabilities=["file_operations"],
    dependencies=["auth_service", "audit_logger"],
    health_interval=30
)
@app.tool(name="read_file", description="Read file with mesh security")
async def read_file(
    path: str,
    auth_service: Optional[str] = None,
    audit_logger: Optional[str] = None
) -> str:
    """File reading with automatic mesh integration."""
    # Mesh decorator handles:
    # - Service registration
    # - Dependency injection
    # - Health monitoring
    # - Error handling

    if auth_service:
        print(f"Using auth service: {auth_service}")

    if audit_logger:
        print(f"Logging to: {audit_logger}")

    with open(path, 'r') as f:
        return f.read()
```

### MCP Protocol Compliance

All components are fully MCP JSON-RPC 2.0 compliant:

```python
from mcp_mesh_sdk.shared.exceptions import MCPError, MCPErrorCode

# MCP-compliant error handling
try:
    result = await some_operation()
except Exception as e:
    mcp_error = MCPError(
        message=str(e),
        code=MCPErrorCode.INTERNAL_ERROR,
        data={"operation": "file_read"}
    )
    # Returns proper JSON-RPC 2.0 error response
    return mcp_error.to_mcp_response()
```

### Tool, Resource, and Prompt Development

#### Tools

```python
@mesh_agent(capabilities=["file_operations"])
async def create_file(path: str, content: str) -> bool:
    """MCP tool with mesh integration."""
    # Tool implementation
    pass
```

#### Resources

```python
@mesh_agent(capabilities=["resource_access"])
async def get_file_resource(uri: str) -> dict:
    """MCP resource with mesh integration."""
    return {
        "uri": uri,
        "mimeType": "text/plain",
        "text": "resource content"
    }
```

#### Prompts

```python
@mesh_agent(capabilities=["prompt_generation"])
async def generate_prompt(context: dict) -> str:
    """MCP prompt with mesh integration."""
    return f"Based on {context}, please..."
```

## @mesh_agent Decorator Usage

### Complete Configuration Reference

```python
@mesh_agent(
    # Core Configuration
    capabilities=["file_read", "file_write"],          # Required: Service capabilities
    dependencies=["auth_service", "audit_logger"],     # Services to inject
    health_interval=30,                                # Heartbeat interval (seconds)

    # Identity & Security
    agent_name="my-file-agent",                        # Agent identifier
    security_context="file_operations",               # Security context

    # Connection & Retry
    registry_url="http://localhost:8080",              # Registry URL (optional)
    timeout=30,                                        # Network timeout
    retry_attempts=3,                                  # Retry attempts

    # Performance
    enable_caching=True,                               # Cache dependencies
    fallback_mode=True                                 # Graceful degradation
)
```

### Configuration Options

#### Capabilities

Define what your service provides:

```python
@mesh_agent(capabilities=["file_read", "file_write", "file_list"])
```

#### Dependencies

Services that will be injected as function parameters:

```python
@mesh_agent(
    dependencies=["auth_service", "audit_logger", "backup_service"]
)
async def my_function(
    path: str,
    auth_service=None,      # Injected by mesh
    audit_logger=None,      # Injected by mesh
    backup_service=None     # Injected by mesh
):
    pass
```

#### Health Monitoring

Configure health check frequency:

```python
@mesh_agent(health_interval=60)  # Check every 60 seconds
```

#### Security Context

Set security boundaries:

```python
@mesh_agent(security_context="file_operations")
```

#### Fallback Mode

Enable graceful degradation when mesh is unavailable:

```python
@mesh_agent(fallback_mode=True)  # Service works without mesh
@mesh_agent(fallback_mode=False) # Service fails without mesh
```

### Integration with Mesh Services

#### Service Registry

Automatic registration with capabilities:

```python
@mesh_agent(capabilities=["data_processing"])
async def process_data(data: dict) -> dict:
    # Automatically registered in service registry
    # Other services can discover this capability
    pass
```

#### Dependency Injection

Automatic injection of mesh services:

```python
@mesh_agent(dependencies=["database", "cache", "logger"])
async def store_data(
    data: dict,
    database=None,    # Injected database service
    cache=None,       # Injected cache service
    logger=None       # Injected logging service
) -> bool:
    if database:
        await database.store(data)
    if cache:
        await cache.set(data['id'], data)
    if logger:
        await logger.info("Data stored")
    return True
```

#### Health Monitoring Setup

Automatic health reporting:

```python
@mesh_agent(health_interval=30)
async def my_service():
    # Health status automatically sent every 30 seconds
    # Includes service status, capabilities, and metadata
    pass
```

## File Agent Development

### Basic File Operations

The SDK provides a comprehensive `FileOperations` class:

```python
from mcp_mesh_sdk.tools.file_operations import FileOperations

# Initialize with security constraints
file_ops = FileOperations(
    base_directory="/safe/directory",  # Restrict operations to this path
    max_file_size=10 * 1024 * 1024    # 10MB limit
)

# File operations are automatically mesh-enabled
content = await file_ops.read_file("/safe/directory/file.txt")
await file_ops.write_file("/safe/directory/new.txt", "content")
files = await file_ops.list_directory("/safe/directory")
```

### Extending File Operations

```python
from mcp_mesh_sdk.tools.file_operations import FileOperations
from mcp_mesh_sdk import mesh_agent

class CustomFileAgent(FileOperations):
    """Extended file agent with custom operations."""

    def __init__(self):
        super().__init__(base_directory="/app/data")
        self._setup_custom_tools()

    def _setup_custom_tools(self):
        """Add custom file operations."""

        @mesh_agent(
            capabilities=["file_search"],
            dependencies=["search_index"],
            health_interval=60
        )
        async def search_files(
            query: str,
            search_index=None
        ) -> list:
            """Search files with mesh integration."""
            if search_index:
                return await search_index.search(query)

            # Fallback to simple file search
            results = []
            for file in self.base_directory.rglob("*.txt"):
                if query.lower() in file.read_text().lower():
                    results.append(str(file))
            return results

        self.search_files = search_files
```

### Security Considerations

#### Path Validation

```python
# Automatic path traversal protection
@mesh_agent(capabilities=["file_read"])
async def read_file(path: str) -> str:
    # Path validation happens automatically
    # Blocks: "../../../etc/passwd"
    # Allows: "documents/file.txt"
    pass
```

#### File Type Restrictions

```python
file_ops = FileOperations()
file_ops.allowed_extensions = {'.txt', '.json', '.yaml'}  # Only allow these types
```

#### Size Limits

```python
file_ops = FileOperations(max_file_size=5 * 1024 * 1024)  # 5MB limit
```

### Error Handling Patterns

```python
from mcp_mesh_sdk.shared.exceptions import (
    FileNotFoundError, FileAccessDeniedError, FileTooLargeError
)

@mesh_agent(capabilities=["file_read"])
async def safe_read_file(path: str) -> str:
    try:
        return await file_ops.read_file(path)
    except FileNotFoundError as e:
        # MCP-compliant error response
        return e.to_mcp_response()
    except FileAccessDeniedError as e:
        # Automatic security logging
        return e.to_mcp_response()
    except FileTooLargeError as e:
        # Detailed error information
        return e.to_mcp_response()
```

### Testing File Operations

```python
import pytest
from mcp_mesh_sdk.tools.file_operations import FileOperations

@pytest.mark.asyncio
async def test_file_read():
    """Test file reading with mesh integration."""
    file_ops = FileOperations(base_directory="/tmp/test")

    # Create test file
    test_file = "/tmp/test/sample.txt"
    await file_ops.write_file(test_file, "test content")

    # Test reading
    content = await file_ops.read_file(test_file)
    assert content == "test content"

    # Test mesh functionality
    func = file_ops.read_file
    assert hasattr(func, '_mesh_agent_metadata')
    assert 'file_read' in func._mesh_agent_metadata['capabilities']
```

## Development Workflow

### Project Structure

```
mcp-mesh-project/
├── src/
│   └── my_mcp_service/
│       ├── __init__.py
│       ├── server.py          # Main MCP server
│       ├── tools/             # MCP tools
│       │   ├── __init__.py
│       │   ├── file_ops.py    # File operations
│       │   └── data_ops.py    # Data operations
│       ├── resources/         # MCP resources
│       │   ├── __init__.py
│       │   └── data.py
│       └── prompts/           # MCP prompts
│           ├── __init__.py
│           └── templates.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── pyproject.toml
└── README.md
```

### Development Environment Setup

1. **Install Dependencies**

```bash
pip install mcp-mesh-sdk[dev]
```

2. **Configuration**

```python
# config.py
import os

MESH_CONFIG = {
    'registry_url': os.getenv('MESH_REGISTRY_URL', 'http://localhost:8080'),
    'agent_name': os.getenv('AGENT_NAME', 'my-service'),
    'health_interval': int(os.getenv('HEALTH_INTERVAL', '30')),
    'fallback_mode': os.getenv('FALLBACK_MODE', 'true').lower() == 'true'
}
```

3. **Main Server**

```python
# server.py
import asyncio
from mcp.server.fastmcp import FastMCP
from mcp_mesh_sdk import mesh_agent
from .config import MESH_CONFIG

app = FastMCP(name="my-service")

@mesh_agent(**MESH_CONFIG, capabilities=["file_operations"])
@app.tool()
async def my_tool(param: str) -> str:
    return f"Processed: {param}"

if __name__ == "__main__":
    app.run()
```

### Testing Procedures

#### Unit Tests

```python
# tests/unit/test_tools.py
import pytest
from my_mcp_service.tools.file_ops import read_file

@pytest.mark.asyncio
async def test_read_file():
    result = await read_file("/test/path.txt")
    assert isinstance(result, str)
```

#### Integration Tests

```python
# tests/integration/test_mesh.py
import pytest
from mcp_mesh_sdk.tools.file_operations import FileOperations

@pytest.mark.asyncio
async def test_mesh_integration():
    file_ops = FileOperations()

    # Test that mesh decorator is applied
    assert hasattr(file_ops.read_file, '_mesh_agent_metadata')

    # Test dependency injection works
    # (requires running mesh registry)
```

#### End-to-End Tests

```python
# tests/e2e/test_complete_workflow.py
@pytest.mark.asyncio
async def test_complete_file_workflow():
    """Test complete file operation workflow."""
    # Test writing, reading, listing files
    pass
```

### Code Quality Standards

#### Linting and Formatting

```bash
# Format code
black src/ tests/
isort src/ tests/

# Check types
mypy src/

# Lint code
ruff check src/ tests/
```

#### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks:
      - id: isort
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.8
    hooks:
      - id: ruff
```

## API Reference

### Core Components

#### @mesh_agent Decorator

```python
def mesh_agent(
    capabilities: List[str],                    # Required: Service capabilities
    dependencies: Optional[List[str]] = None,   # Services to inject
    health_interval: int = 30,                  # Health check interval
    registry_url: Optional[str] = None,         # Registry URL
    agent_name: Optional[str] = None,           # Agent identifier
    security_context: Optional[str] = None,     # Security context
    timeout: int = 30,                          # Network timeout
    retry_attempts: int = 3,                    # Retry attempts
    enable_caching: bool = True,                # Cache dependencies
    fallback_mode: bool = True                  # Graceful degradation
) -> Callable
```

#### FileOperations Class

```python
class FileOperations:
    def __init__(
        self,
        base_directory: Optional[str] = None,   # Base directory constraint
        max_file_size: int = 10485760,          # Max file size (10MB)
        retry_config: Optional[RetryConfig] = None
    )

    async def read_file(
        self,
        path: str,
        encoding: str = "utf-8",
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None
    ) -> str

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_backup: bool = True,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None
    ) -> bool

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
        include_details: bool = False,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        retry_config: Optional[RetryConfig] = None
    ) -> List[Union[str, Dict[str, Any]]]
```

#### Exception Classes

```python
# Base exceptions
class MCPError(Exception)
class MeshAgentError(MCPError)
class FileOperationError(MeshAgentError)

# Specific exceptions
class FileNotFoundError(FileOperationError)
class FileAccessDeniedError(FileOperationError)
class FileTooLargeError(FileOperationError)
class SecurityValidationError(MeshAgentError)
class RegistryConnectionError(MeshAgentError)
```

#### Type Definitions

```python
from mcp_mesh_sdk.shared.types import (
    HealthStatus,
    HealthStatusType,
    RetryConfig,
    RetryStrategy,
    FileInfo,
    DirectoryListing,
    SecurityContext,
    DependencyConfig
)
```

### Usage Examples

#### Basic Tool Development

```python
@mesh_agent(capabilities=["text_processing"])
async def process_text(text: str) -> str:
    """Process text with mesh integration."""
    return text.upper()
```

#### Advanced Configuration

```python
@mesh_agent(
    capabilities=["advanced_processing"],
    dependencies=["ml_service", "cache", "logger"],
    health_interval=15,
    timeout=60,
    retry_attempts=5,
    enable_caching=True,
    fallback_mode=False
)
async def advanced_process(
    data: dict,
    ml_service=None,
    cache=None,
    logger=None
) -> dict:
    """Advanced processing with full mesh integration."""
    if ml_service:
        result = await ml_service.process(data)
    else:
        raise Exception("ML service required")

    if cache:
        await cache.store(data['id'], result)

    if logger:
        await logger.info(f"Processed {data['id']}")

    return result
```

## Testing Guide

### Test Structure

```python
# conftest.py
import pytest
from mcp_mesh_sdk.tools.file_operations import FileOperations

@pytest.fixture
async def file_operations():
    """Provide file operations instance for testing."""
    ops = FileOperations(base_directory="/tmp/test")
    yield ops
    await ops.cleanup()

@pytest.fixture
def mock_mesh_registry():
    """Mock mesh registry for testing."""
    # Mock registry setup
    pass
```

### Unit Testing

```python
@pytest.mark.asyncio
async def test_file_read(file_operations):
    """Test file reading functionality."""
    # Test implementation
    pass

@pytest.mark.asyncio
async def test_mesh_decorator_metadata():
    """Test mesh decorator metadata."""
    @mesh_agent(capabilities=["test"])
    async def test_func():
        pass

    assert hasattr(test_func, '_mesh_agent_metadata')
    assert test_func._mesh_agent_metadata['capabilities'] == ["test"]
```

### Integration Testing

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_mesh_dependency_injection():
    """Test dependency injection with running registry."""
    # Requires running mesh registry
    pass
```

### Performance Testing

```python
@pytest.mark.performance
@pytest.mark.asyncio
async def test_file_operation_performance():
    """Test file operation performance."""
    import time

    start = time.time()
    await file_operations.read_file("/large/file.txt")
    duration = time.time() - start

    assert duration < 1.0  # Should complete in under 1 second
```

## Performance & Best Practices

### Performance Optimization

#### Caching Strategy

```python
@mesh_agent(
    capabilities=["data_processing"],
    enable_caching=True,  # Enable dependency caching
    dependencies=["slow_service"]
)
async def process_data(data: dict, slow_service=None):
    # slow_service is cached for 5 minutes by default
    pass
```

#### Health Check Tuning

```python
# For lightweight operations
@mesh_agent(health_interval=60)  # Less frequent checks

# For critical operations
@mesh_agent(health_interval=15)  # More frequent checks
```

#### Retry Configuration

```python
from mcp_mesh_sdk.shared.types import RetryConfig, RetryStrategy

retry_config = RetryConfig(
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    max_retries=3,
    initial_delay_ms=1000,
    max_delay_ms=30000,
    backoff_multiplier=2.0,
    jitter=True
)

file_ops = FileOperations(retry_config=retry_config)
```

### Best Practices

#### Security

1. **Always validate inputs**

```python
@mesh_agent(capabilities=["file_read"])
async def read_file(path: str) -> str:
    if '..' in path:
        raise SecurityValidationError("Path traversal detected")
    # Automatic additional validation by mesh
```

2. **Use security contexts**

```python
@mesh_agent(security_context="admin_operations")
async def admin_function():
    pass
```

3. **Enable audit logging**

```python
@mesh_agent(dependencies=["audit_logger"])
async def sensitive_operation(audit_logger=None):
    if audit_logger:
        await audit_logger.log("Operation performed")
```

#### Error Handling

1. **Use specific exceptions**

```python
from mcp_mesh_sdk.shared.exceptions import FileNotFoundError

try:
    content = await read_file(path)
except FileNotFoundError:
    # Handle specific error
    pass
```

2. **Provide MCP-compliant responses**

```python
except Exception as e:
    return MCPError(str(e), MCPErrorCode.INTERNAL_ERROR).to_mcp_response()
```

#### Resource Management

1. **Always cleanup resources**

```python
async def main():
    file_ops = FileOperations()
    try:
        # Use file operations
        pass
    finally:
        await file_ops.cleanup()
```

2. **Use context managers when possible**

```python
async with FileOperations() as file_ops:
    content = await file_ops.read_file(path)
    # Automatic cleanup
```

## Troubleshooting

### Common Issues

#### Mesh Registry Connection Failed

```
Error: RegistryConnectionError: Failed to connect to registry
```

**Solutions:**

1. Check registry URL configuration
2. Verify registry is running
3. Enable fallback mode:

```python
@mesh_agent(fallback_mode=True)  # Service works without mesh
```

#### Dependency Injection Failed

```
Error: DependencyInjectionError: Failed to inject dependency 'auth_service'
```

**Solutions:**

1. Verify dependency is registered in mesh
2. Check dependency name spelling
3. Use optional dependencies:

```python
async def my_func(auth_service=None):
    if auth_service:
        # Use service
        pass
    else:
        # Fallback behavior
        pass
```

#### File Permission Errors

```
Error: FileAccessDeniedError: Access denied for read operation
```

**Solutions:**

1. Check file permissions
2. Verify base directory constraints
3. Check security context

#### Health Check Failures

```
Warning: Health check failed for agent 'my-agent'
```

**Solutions:**

1. Check agent status
2. Verify capabilities are registered
3. Adjust health check interval
4. Check for resource constraints

### Debugging

#### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Mesh-specific logging
logger = logging.getLogger("mesh_agent")
logger.setLevel(logging.DEBUG)
```

#### Inspect Mesh Metadata

```python
@mesh_agent(capabilities=["test"])
async def test_func():
    pass

# Check decorator metadata
print(test_func._mesh_agent_metadata)
```

#### Health Status Monitoring

```python
file_ops = FileOperations()
health = await file_ops.health_check()
print(f"Status: {health.status}")
print(f"Failed checks: {health.get_failed_checks()}")
```

### Performance Issues

#### Slow Dependency Injection

```python
# Enable caching
@mesh_agent(enable_caching=True, dependencies=["slow_service"])

# Or reduce dependency calls
@mesh_agent(dependencies=["fast_service"])  # Use faster alternatives
```

#### High Memory Usage

```python
# Set file size limits
file_ops = FileOperations(max_file_size=1024*1024)  # 1MB limit

# Process files in chunks
async def process_large_file(path: str):
    async with aiofiles.open(path, 'r') as f:
        async for line in f:
            # Process line by line
            pass
```

### Getting Help

1. **Check logs** for detailed error information
2. **Review configuration** for typos or invalid values
3. **Test connectivity** to mesh registry
4. **Verify dependencies** are available and registered
5. **Check documentation** for usage examples
6. **Report issues** with reproduction steps

---

This development guide provides comprehensive coverage of MCP-Mesh SDK development. For additional help, refer to the API documentation or open an issue in the project repository.
