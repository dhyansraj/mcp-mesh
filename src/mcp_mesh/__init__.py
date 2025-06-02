"""
MCP Mesh - Advanced Features for Model Context Protocol

A production-ready service mesh for Model Context Protocol (MCP) services
with advanced capabilities that extend the basic mcp-mesh-types package.

This package enhances mcp-mesh-types with:
- Advanced mesh integration and service discovery
- Health monitoring and heartbeats
- Dependency injection and service composition
- Enhanced error handling and retry logic
- Audit logging and security features
- Resource management and cleanup

For basic MCP SDK compatibility, use mcp-mesh-types instead.
"""

__version__ = "0.1.0"
__author__ = "MCP Mesh Contributors"
__description__ = "Advanced MCP service mesh with full capabilities"

# Import base types from mcp-mesh-types
from mcp_mesh_types import (
    FileOperationError,
    PermissionDeniedError,
    SecurityValidationError,
)
from mcp_mesh_types import FileOperations as BaseFileOperations
from mcp_mesh_types import mesh_agent as base_mesh_agent

# Enhanced exports
from .client import *
from .decorators import MeshAgentDecorator

# Enhanced mesh_agent decorator that extends the basic one
from .decorators.mesh_agent import mesh_agent
from .server import *
from .shared import *

# Enhanced FileOperations with full mesh capabilities
from .tools.file_operations import FileOperations

__all__ = [
    "__version__",
    "__author__",
    "__description__",
    "mesh_agent",
    "MeshAgentDecorator",
    "FileOperations",
    "BaseFileOperations",
    "FileOperationError",
    "SecurityValidationError",
    "PermissionDeniedError",
]
