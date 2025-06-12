# File Agent Architecture Design

## Overview

The File Agent is designed as a production-ready MCP server that provides comprehensive file system operations through the MCP protocol. It integrates seamlessly with the MCP Mesh SDK patterns, leveraging the custom `@mesh_agent` decorator for automatic mesh integration, health monitoring, and dependency injection.

## Core Architecture

### Module Structure

```
src/mcp_mesh_sdk/
├── agents/
│   ├── __init__.py
│   ├── base.py              # Base agent class and interfaces
│   └── file_agent.py        # File Agent implementation
├── decorators/
│   ├── __init__.py
│   └── mesh_agent.py        # @mesh_agent decorator implementation
├── shared/
│   ├── __init__.py
│   ├── types.py             # Common type definitions
│   ├── exceptions.py        # Custom exception classes
│   └── health.py            # Health monitoring utilities
└── tools/
    ├── __init__.py
    └── file_operations.py   # Core file operation tools
```

### Class Hierarchy

```python
# Base Agent Interface
class BaseAgent(ABC):
    """Abstract base class for all MCP Mesh agents."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize agent resources."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Perform health check."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup agent resources."""
        pass

# File Agent Implementation
class FileAgent(BaseAgent):
    """Production-ready file system operations agent."""

    def __init__(self, config: FileAgentConfig):
        self.config = config
        self.app = FastMCP(
            name="file-agent",
            instructions="Secure file system operations with mesh integration"
        )
        self._setup_tools()
        self._setup_resources()
        self._setup_prompts()

    def _setup_tools(self) -> None:
        """Register file operation tools with @mesh_agent decoration."""
        pass

    def _setup_resources(self) -> None:
        """Register file system resources."""
        pass

    def _setup_prompts(self) -> None:
        """Register file operation prompts."""
        pass
```

## Core File Operations

### Tool Definitions

The File Agent will expose the following core operations through MCP tools:

1. **read_file** - Read file contents with security validation
2. **write_file** - Write content to files with atomic operations
3. **list_directory** - List directory contents with filtering
4. **create_directory** - Create directories with proper permissions
5. **delete_file** - Safe file deletion with backup options
6. **copy_file** - Copy files with conflict resolution
7. **move_file** - Move/rename files with validation
8. **get_file_info** - Get file metadata and properties

### Security and Validation

- **Path validation**: Prevent directory traversal attacks
- **Permission checking**: Validate file system permissions
- **Size limits**: Enforce maximum file size constraints
- **Type validation**: Allow/deny specific file types
- **Sandbox mode**: Optional operation within restricted directories

## @mesh_agent Decorator Integration

### Decorator Usage Pattern

```python
from mcp_mesh_sdk.decorators import mesh_agent
from mcp_mesh_sdk.agents.base import BaseAgent

class FileAgent(BaseAgent):

    @mesh_agent(
        capabilities=["file_read", "file_write", "directory_list"],
        health_interval=30,
        dependencies=["auth_service"],
        security_context="file_operations"
    )
    @app.tool()
    async def read_file(
        self,
        path: str,
        encoding: str = "utf-8",
        auth_token: str = None  # Injected by @mesh_agent
    ) -> str:
        """Read file contents with security validation."""
        # Decorator handles:
        # 1. Registry registration of "file_read" capability
        # 2. Health monitoring heartbeat every 30 seconds
        # 3. auth_token injection from "auth_service" dependency
        # 4. Security context validation

        await self._validate_path(path, "read")
        await self._check_permissions(path, auth_token)

        try:
            async with aiofiles.open(path, 'r', encoding=encoding) as f:
                content = await f.read()
            return content
        except Exception as e:
            raise FileOperationError(f"Failed to read {path}: {e}")
```

### Decorator Benefits for File Agent

1. **Automatic Capability Registration**: File operations registered with mesh registry
2. **Health Monitoring**: Periodic heartbeats indicate agent health
3. **Security Integration**: Authentication tokens automatically injected
4. **Error Handling**: Graceful degradation when mesh services unavailable
5. **Dependency Management**: File system dependencies auto-resolved

## MCP Protocol Integration Points

### Tools Registration

```python
# File operations exposed as MCP tools
@app.tool()
@mesh_agent(capabilities=["file_read"])
async def read_file(path: str, encoding: str = "utf-8") -> str:
    """Tool for reading file contents."""
    pass

@app.tool()
@mesh_agent(capabilities=["file_write"])
async def write_file(path: str, content: str, encoding: str = "utf-8") -> bool:
    """Tool for writing file contents."""
    pass
```

### Resources Registration

```python
# File system resources
@app.resource("file://config")
async def config_resource() -> str:
    """Agent configuration as a resource."""
    return json.dumps(self.config.dict())

@app.resource("file://logs")
async def logs_resource() -> str:
    """Agent logs as a resource."""
    return await self._get_recent_logs()
```

### Prompts Registration

```python
# File operation prompts
@app.prompt()
async def file_analysis_prompt(file_path: str) -> List[PromptMessage]:
    """Generate prompts for file analysis."""
    return [
        PromptMessage(
            role="user",
            content=TextContent(
                type="text",
                text=f"Analyze the file at {file_path} and provide insights."
            )
        )
    ]
```

## Error Handling and Type Annotations

### Custom Exception Hierarchy

```python
class FileAgentError(Exception):
    """Base exception for File Agent operations."""
    pass

class FileOperationError(FileAgentError):
    """Exception for file operation failures."""
    pass

class SecurityValidationError(FileAgentError):
    """Exception for security validation failures."""
    pass

class PermissionDeniedError(FileAgentError):
    """Exception for permission-related failures."""
    pass
```

### Type Definitions

```python
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from pathlib import Path

class FileInfo(BaseModel):
    """File information model."""
    path: Path
    size: int
    modified: datetime
    is_directory: bool
    permissions: str
    mime_type: Optional[str] = None

class FileOperationResult(BaseModel):
    """Result of file operations."""
    success: bool
    message: str
    data: Optional[Any] = None
    error_code: Optional[str] = None

class FileAgentConfig(BaseModel):
    """Configuration for File Agent."""
    base_directory: Optional[Path] = None
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB
    allowed_extensions: Optional[List[str]] = None
    security_mode: str = Field(default="strict")
    enable_backups: bool = Field(default=True)
```

## Mesh Integration and Health Monitoring

### Health Check Implementation

```python
async def health_check(self) -> HealthStatus:
    """Comprehensive health check for File Agent."""
    checks = {
        "file_system_access": await self._check_file_system(),
        "permissions": await self._check_permissions(),
        "disk_space": await self._check_disk_space(),
        "registry_connection": await self._check_registry(),
    }

    return HealthStatus(
        status="healthy" if all(checks.values()) else "degraded",
        checks=checks,
        timestamp=datetime.now()
    )

async def _check_file_system(self) -> bool:
    """Test basic file system operations."""
    try:
        test_path = self.config.base_directory / ".health_check"
        test_path.write_text("health_check")
        content = test_path.read_text()
        test_path.unlink()
        return content == "health_check"
    except Exception:
        return False
```

### Registry Integration

```python
class RegistryClient:
    """Client for mesh registry communication."""

    async def register_capabilities(self, capabilities: List[str]) -> bool:
        """Register agent capabilities with mesh registry."""
        pass

    async def send_heartbeat(self, health_status: HealthStatus) -> bool:
        """Send periodic heartbeat to registry."""
        pass

    async def get_dependencies(self, dependency_names: List[str]) -> Dict[str, Any]:
        """Retrieve dependency configurations from registry."""
        pass
```

## Implementation Plan

### Phase 1: Core Implementation

1. Implement `BaseAgent` abstract class
2. Create `FileAgent` with basic file operations
3. Implement core `@mesh_agent` decorator functionality
4. Add comprehensive error handling and type annotations

### Phase 2: Security and Validation

1. Implement path validation and security checks
2. Add permission-based access control
3. Create sandbox mode for restricted operations
4. Add audit logging for all file operations

### Phase 3: Mesh Integration

1. Implement registry client and health monitoring
2. Add dependency injection system
3. Create configuration management
4. Implement graceful degradation when mesh unavailable

### Phase 4: Production Features

1. Add file operation batching and atomic transactions
2. Implement backup and recovery mechanisms
3. Add performance monitoring and metrics
4. Create comprehensive testing suite

## Configuration Example

```python
# File Agent configuration
file_agent_config = FileAgentConfig(
    base_directory=Path("/safe/operations/directory"),
    max_file_size=50 * 1024 * 1024,  # 50MB
    allowed_extensions=[".txt", ".json", ".yaml", ".py"],
    security_mode="strict",
    enable_backups=True
)

# Initialize and run File Agent
agent = FileAgent(config=file_agent_config)
await agent.initialize()
agent.app.run(transport="stdio")
```

This architecture provides a robust foundation for file operations within the MCP Mesh ecosystem, with clear separation of concerns, comprehensive error handling, and seamless integration with the mesh infrastructure.
