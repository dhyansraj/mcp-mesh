# File Agent Complete Architecture Design

## Executive Summary

The File Agent is a production-ready MCP server that provides secure, mesh-integrated file system operations. It leverages the innovative `@mesh_agent` decorator pattern to achieve zero-boilerplate integration with the MCP Mesh infrastructure while maintaining full compatibility with the standard MCP SDK.

### Key Features

- **Zero Boilerplate**: Single decorator provides complete mesh integration
- **MCP Compliant**: Full compatibility with Model Context Protocol
- **Production Ready**: Comprehensive error handling, security, and monitoring
- **Mesh Native**: Built-in service discovery, dependency injection, and health monitoring
- **Type Safe**: Complete type annotations with Pydantic validation
- **Secure**: Path validation, permission management, and audit logging

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      File Agent                            │
├─────────────────────────────────────────────────────────────┤
│  MCP Protocol Layer                                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │    Tools    │ │  Resources  │ │   Prompts   │          │
│  │ (8 file ops)│ │ (5 resources)│ │ (4 prompts) │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
├─────────────────────────────────────────────────────────────┤
│  @mesh_agent Decorator Layer                               │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ • Registry Registration  • Health Monitoring         │  │
│  │ • Dependency Injection   • Configuration Management  │  │
│  │ • Error Handling        • Graceful Degradation      │  │
│  └──────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  File Operations Layer                                     │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │   Security  │ │  Operations │ │ Validation  │          │
│  │   Context   │ │   Engine    │ │   Layer     │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
├─────────────────────────────────────────────────────────────┤
│  Mesh Integration Layer                                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │  Registry   │ │   Health    │ │ Service     │          │
│  │   Client    │ │  Monitor    │ │ Discovery   │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## Module Structure

### Project Layout

```
src/mcp_mesh_sdk/
├── agents/
│   ├── __init__.py
│   ├── base.py                    # BaseAgent abstract class
│   └── file_agent.py             # FileAgent implementation
├── decorators/
│   ├── __init__.py
│   └── mesh_agent.py             # @mesh_agent decorator
├── shared/
│   ├── __init__.py
│   ├── types.py                  # Type definitions and models
│   ├── exceptions.py             # Exception hierarchy
│   ├── registry_client.py        # Registry integration
│   ├── health_monitor.py         # Health monitoring system
│   ├── validation.py             # Security and validation utilities
│   └── error_handling.py         # Error handling decorators
├── tools/
│   ├── __init__.py
│   └── file_operations.py        # Core file operation implementations
├── resources/
│   ├── __init__.py
│   └── file_resources.py         # MCP resources for file system info
└── prompts/
    ├── __init__.py
    └── file_prompts.py           # MCP prompts for file operations
```

## Core Components

### 1. Base Agent Class

```python
# src/mcp_mesh_sdk/agents/base.py

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from ..shared.types import HealthStatus, FileAgentConfig

class BaseAgent(ABC):
    """Abstract base class for all MCP Mesh agents."""

    def __init__(self, config: FileAgentConfig):
        self.config = config
        self.agent_name = config.agent_name

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize agent resources and mesh integration."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Perform comprehensive health check."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup agent resources."""
        pass

    @abstractmethod
    def get_mcp_server(self):
        """Get the MCP server instance."""
        pass
```

### 2. File Agent Implementation

```python
# src/mcp_mesh_sdk/agents/file_agent.py

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent

from .base import BaseAgent
from ..decorators.mesh_agent import mesh_agent
from ..shared.types import (
    FileAgentConfig, HealthStatus, FileInfo, DirectoryListing,
    SecurityContext, FileOperation
)
from ..shared.registry_client import MeshRegistryClient
from ..shared.health_monitor import FileAgentHealthMonitor
from ..shared.validation import PathValidator, FileValidator
from ..shared.error_handling import handle_file_errors, safe_operation
from ..shared.exceptions import *

class FileAgent(BaseAgent):
    """Production-ready file system operations agent with mesh integration."""

    def __init__(self, config: FileAgentConfig):
        super().__init__(config)

        # Initialize MCP server
        self.app = FastMCP(
            name=config.agent_name,
            instructions="Secure file system operations with mesh integration and MCP compliance."
        )

        # Initialize mesh components
        self.registry_client: Optional[MeshRegistryClient] = None
        self.health_monitor: Optional[FileAgentHealthMonitor] = None

        # Security and validation
        self.path_validator = PathValidator()
        self.file_validator = FileValidator()

        # Operation state
        self._initialized = False
        self._operation_stats = {
            "read_operations": 0,
            "write_operations": 0,
            "delete_operations": 0,
            "list_operations": 0,
            "errors": 0
        }

        self.logger = logging.getLogger(f"file_agent.{self.agent_name}")

        # Setup MCP components
        self._setup_tools()
        self._setup_resources()
        self._setup_prompts()

    async def initialize(self) -> None:
        """Initialize agent resources and mesh integration."""
        if self._initialized:
            return

        try:
            # Initialize registry client if configured
            if self.config.registry_url:
                self.registry_client = MeshRegistryClient(
                    registry_url=self.config.registry_url,
                    agent_name=self.config.agent_name,
                    heartbeat_interval=self.config.health_check_interval
                )
                await self.registry_client.initialize()

                # Register with mesh
                capabilities = [
                    MeshCapability(name="file_read", description="Read file contents"),
                    MeshCapability(name="file_write", description="Write file contents"),
                    MeshCapability(name="directory_list", description="List directory contents"),
                    MeshCapability(name="file_info", description="Get file metadata"),
                    MeshCapability(name="file_delete", description="Delete files/directories"),
                    MeshCapability(name="file_copy", description="Copy files/directories"),
                    MeshCapability(name="file_move", description="Move/rename files"),
                    MeshCapability(name="directory_create", description="Create directories")
                ]

                await self.registry_client.register_agent(
                    capabilities=capabilities,
                    dependencies=["auth_service", "audit_logger", "backup_service"],
                    endpoint="stdio://file-agent",
                    security_context="file_operations"
                )

            # Initialize health monitoring
            self.health_monitor = FileAgentHealthMonitor(
                config=self.config,
                registry_client=self.registry_client
            )
            await self.health_monitor.start_monitoring()

            # Create required directories
            await self._ensure_directories()

            self._initialized = True
            self.logger.info(f"File Agent {self.agent_name} initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize File Agent: {e}")
            raise ConfigurationError(
                f"File Agent initialization failed: {e}",
                ErrorCode.INITIALIZATION_FAILED,
                cause=e
            )

    async def health_check(self) -> HealthStatus:
        """Perform comprehensive health check."""
        if self.health_monitor:
            return await self.health_monitor.perform_health_check()

        # Fallback basic health check
        return HealthStatus(
            status="healthy",
            agent_name=self.agent_name,
            capabilities=["file_read", "file_write", "directory_list"],
            timestamp=datetime.now(),
            checks={"basic": True}
        )

    async def cleanup(self) -> None:
        """Cleanup agent resources."""
        if self.health_monitor:
            await self.health_monitor.stop_monitoring()

        if self.registry_client:
            await self.registry_client.cleanup()

        self.logger.info(f"File Agent {self.agent_name} cleaned up")

    def get_mcp_server(self) -> FastMCP:
        """Get the MCP server instance."""
        return self.app

    def _setup_tools(self) -> None:
        """Register all file operation tools with MCP and mesh integration."""

        @mesh_agent(
            capabilities=["file_read"],
            dependencies=["auth_service"],
            health_interval=30
        )
        @self.app.tool()
        async def read_file(
            path: str,
            encoding: str = "utf-8",
            max_size: int = 1024 * 1024,  # 1MB default
            auth_service: str = None
        ) -> str:
            """
            Read the contents of a file.

            Args:
                path: Absolute or relative path to the file
                encoding: Text encoding (default: utf-8)
                max_size: Maximum file size to read in bytes

            Returns:
                File contents as string
            """
            return await self._execute_read_file(path, encoding, max_size, auth_service)

        @mesh_agent(
            capabilities=["file_write"],
            dependencies=["auth_service", "backup_service"],
            health_interval=30
        )
        @self.app.tool()
        async def write_file(
            path: str,
            content: str,
            encoding: str = "utf-8",
            create_dirs: bool = False,
            backup: bool = True,
            auth_service: str = None,
            backup_service: Any = None
        ) -> bool:
            """
            Write content to a file.

            Args:
                path: Absolute or relative path to the file
                content: Content to write to the file
                encoding: Text encoding (default: utf-8)
                create_dirs: Create parent directories if they don't exist
                backup: Create backup before overwriting existing file

            Returns:
                True if successful
            """
            return await self._execute_write_file(
                path, content, encoding, create_dirs, backup, auth_service, backup_service
            )

        # Additional tools: list_directory, get_file_info, delete_file,
        # copy_file, move_file, create_directory
        # (Implementation follows same pattern as above)

    def _setup_resources(self) -> None:
        """Register file system resources with MCP."""

        @self.app.resource("file://agent/config")
        async def agent_config() -> str:
            """Get File Agent configuration."""
            config_dict = self.config.dict()
            config_dict["base_directory"] = str(config_dict.get("base_directory", ""))
            return json.dumps(config_dict, indent=2)

        @self.app.resource("file://agent/status")
        async def agent_status() -> str:
            """Get current File Agent status."""
            health = await self.health_check()
            status = {
                "agent_name": self.agent_name,
                "health": health.dict(),
                "stats": self._operation_stats,
                "initialized": self._initialized
            }
            return json.dumps(status, indent=2, default=str)

        # Additional resources: stats, system/info, health

    def _setup_prompts(self) -> None:
        """Register file operation prompts with MCP."""

        @self.app.prompt()
        async def analyze_file(file_path: str) -> List[PromptMessage]:
            """Generate prompts for analyzing a file."""
            # Implementation for file analysis prompts
            pass

        # Additional prompts: file_operation_help, directory_summary, file_workflow

    # File operation implementations
    @handle_file_errors("read_file")
    async def _execute_read_file(
        self,
        path: str,
        encoding: str,
        max_size: int,
        auth_service: Optional[str]
    ) -> str:
        """Execute file read operation with security validation."""
        file_path = Path(path)

        # Security validation
        self.path_validator.validate_path_safety(file_path)
        self.file_validator.validate_file_exists(file_path, should_exist=True)
        self.file_validator.validate_file_size(file_path, max_size)

        # Extension validation
        if self.config.allowed_extensions:
            self.path_validator.validate_file_extension(
                file_path,
                allowed=self.config.allowed_extensions
            )

        # Read file
        try:
            content = file_path.read_text(encoding=encoding)
            self._operation_stats["read_operations"] += 1
            return content
        except Exception as e:
            self._operation_stats["errors"] += 1
            raise FileOperationError(
                f"Failed to read file {path}: {e}",
                ErrorCode.FILE_READ_ERROR,
                file_path=str(file_path),
                operation="read",
                cause=e
            )

    async def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        directories_to_create = []

        if self.config.base_directory:
            directories_to_create.append(self.config.base_directory)

        if self.config.enable_backups and self.config.backup_directory:
            directories_to_create.append(self.config.backup_directory)

        for directory in directories_to_create:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Ensured directory exists: {directory}")
            except Exception as e:
                self.logger.warning(f"Failed to create directory {directory}: {e}")

# Factory function for easy instantiation
def create_file_agent(config: Optional[FileAgentConfig] = None) -> FileAgent:
    """
    Create a File Agent instance with default or provided configuration.

    Args:
        config: File Agent configuration, or None for defaults

    Returns:
        Configured FileAgent instance
    """
    if config is None:
        config = FileAgentConfig()

    return FileAgent(config)
```

## Integration Points Summary

### 1. MCP SDK Integration

- **Tools**: 8 file operations exposed as MCP tools
- **Resources**: 5 resources providing agent status and configuration
- **Prompts**: 4 prompts for file analysis and workflow assistance
- **Protocol**: Full MCP compliance with proper error handling

### 2. @mesh_agent Decorator Integration

- **Zero Boilerplate**: Single decorator handles all mesh integration
- **Capabilities**: Automatic registry registration of file operations
- **Dependencies**: Injection of auth_service, audit_logger, backup_service
- **Health Monitoring**: Periodic heartbeats with configurable intervals
- **Fallback Mode**: Graceful degradation when mesh services unavailable

### 3. Error Handling and Type Safety

- **Exception Hierarchy**: Structured error types with standardized codes
- **Type Annotations**: Complete Pydantic models with validation
- **Error Decorators**: Consistent error handling across operations
- **MCP Compliance**: Error formats compatible with MCP protocol

### 4. Security and Validation

- **Path Security**: Prevention of directory traversal attacks
- **Permission Validation**: File system permission checking
- **Extension Filtering**: Allow/deny lists for file types
- **Audit Logging**: Comprehensive operation logging
- **Security Context**: Role-based access control integration

### 5. Health Monitoring

- **System Metrics**: CPU, memory, disk space monitoring
- **Application Health**: File system access, permissions, directories
- **Mesh Health**: Registry connectivity, service discovery
- **Custom Checks**: Extensible health check framework
- **Metrics Collection**: Performance and error tracking

## Configuration Example

```python
from pathlib import Path
from mcp_mesh_sdk.agents.file_agent import create_file_agent, FileAgentConfig

# Create configuration
config = FileAgentConfig(
    agent_name="production-file-agent",
    base_directory=Path("/safe/operations"),
    max_file_size=50 * 1024 * 1024,  # 50MB
    allowed_extensions=[".txt", ".json", ".yaml", ".py", ".md"],
    security_mode="strict",
    enable_backups=True,
    backup_directory=Path("/backups/file-agent"),
    enable_audit_log=True,
    registry_url="http://mesh-registry:8080",
    health_check_interval=30
)

# Create and initialize agent
agent = create_file_agent(config)
await agent.initialize()

# Run MCP server
server = agent.get_mcp_server()
server.run(transport="stdio")
```

## Deployment Architecture

```
┌─────────────────────────────────────────┐
│           MCP Client                    │
│       (Claude Desktop/API)              │
└─────────────┬───────────────────────────┘
              │ MCP Protocol (stdio/HTTP)
              │
┌─────────────▼───────────────────────────┐
│         File Agent                      │
│  ┌─────────────────────────────────┐   │
│  │       FastMCP Server            │   │
│  │  ┌─────┐ ┌─────┐ ┌─────────┐   │   │
│  │  │Tools│ │Rsrc.│ │ Prompts │   │   │
│  │  └─────┘ └─────┘ └─────────┘   │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │     @mesh_agent Layer           │   │
│  └─────────────────────────────────┘   │
└─────────────┬───────────────────────────┘
              │ HTTP/gRPC
              │
┌─────────────▼───────────────────────────┐
│        Mesh Registry                    │
│  ┌─────────────────────────────────┐   │
│  │ Service Discovery │ Health Mon. │   │
│  │ Dependency Mgmt   │ Config Mgmt │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## Implementation Timeline

### Phase 1: Core Implementation (Week 1, Days 2-3)

- [ ] Implement BaseAgent and FileAgent classes
- [ ] Create @mesh_agent decorator core functionality
- [ ] Implement basic file operations (read, write, list)
- [ ] Add MCP protocol integration
- [ ] Create comprehensive test suite

### Phase 2: Advanced Features (Week 1, Days 4-5)

- [ ] Implement security validation and path safety
- [ ] Add comprehensive error handling
- [ ] Create health monitoring system
- [ ] Implement mesh registry integration
- [ ] Add audit logging and metrics

### Phase 3: Production Readiness (Week 2)

- [ ] Performance optimization and caching
- [ ] Advanced security features
- [ ] Comprehensive documentation
- [ ] Deployment automation
- [ ] Monitoring and observability

## Success Criteria

1. **Functionality**: All 8 file operations working correctly with MCP protocol
2. **Security**: Path validation, permission checking, and audit logging implemented
3. **Mesh Integration**: @mesh_agent decorator providing zero-boilerplate mesh integration
4. **Type Safety**: Complete type annotations with Pydantic validation
5. **Error Handling**: Comprehensive error hierarchy with proper MCP error responses
6. **Health Monitoring**: Real-time health checks and metrics collection
7. **Documentation**: Complete API documentation and usage examples
8. **Testing**: 95%+ test coverage with unit, integration, and e2e tests

This File Agent architecture provides a robust, secure, and mesh-native foundation for file operations within the MCP ecosystem, demonstrating the power and simplicity of the @mesh_agent decorator pattern.
