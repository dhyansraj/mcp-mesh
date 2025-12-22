"""
MCP Mesh - Internal implementation for Model Context Protocol service mesh.

⚠️  INTERNAL PACKAGE - DO NOT IMPORT DIRECTLY
This package contains internal implementation details and is not part of the public API.
Use the 'mesh' package instead for all user-facing functionality.

The underscore prefix (_mcp_mesh) indicates this is a private package following
Python naming conventions. Direct imports from this package are not supported
and may break in future versions.

Public API: import mesh
"""

import os
import sys

# Type alias for mesh agent proxy injections - use Any for Pydantic compatibility
from typing import Any

# Old mesh_agent decorator has been replaced by mesh.tool and mesh.agent
# Import mesh.tool and mesh.agent instead
from mesh.types import McpMeshAgent

# Import all the existing exports
from .engine.decorator_registry import (
    DecoratedFunction,
    DecoratorRegistry,
    clear_decorator_registry,
    get_all_mesh_agents,
    get_decorator_stats,
)

__version__ = "0.7.12"

# Store reference to runtime processor if initialized
_runtime_processor = None


def initialize_runtime():
    """Initialize the MCP Mesh runtime processor."""
    global _runtime_processor

    if _runtime_processor is not None:
        return  # Already initialized

    try:
        # Legacy processor system has been replaced by pipeline architecture

        # Use pipeline-based runtime
        from .pipeline.mcp_startup import start_runtime

        start_runtime()

        sys.stderr.write("MCP Mesh runtime initialized\n")
    except Exception as e:
        # Log but don't fail - allows graceful degradation
        sys.stderr.write(f"MCP Mesh runtime initialization failed: {e}\n")


# Auto-initialize runtime if enabled
if (
    os.getenv("MCP_MESH_ENABLED", "true").lower() == "true"
    and os.getenv("MCP_MESH_AUTO_RUN", "true").lower() == "true"
):
    # Use debounced initialization instead of immediate MCP startup
    # This allows the system to determine MCP vs API pipeline based on decorators
    try:
        from .pipeline.mcp_startup import start_runtime

        # Start the debounced runtime (sets up coordinator, no immediate pipeline execution)
        start_runtime()

        sys.stderr.write("MCP Mesh debounced runtime initialized\n")
    except Exception as e:
        # Log but don't fail - allows graceful degradation
        sys.stderr.write(f"MCP Mesh runtime initialization failed: {e}\n")


__all__ = [
    # mesh_agent has been removed - use mesh.tool and mesh.agent instead
    "McpMeshAgent",
    "initialize_runtime",
    "DecoratedFunction",
    "DecoratorRegistry",
    "clear_decorator_registry",
    "get_all_mesh_agents",
    "get_decorator_stats",
]
