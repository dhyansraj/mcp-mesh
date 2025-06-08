"""
MCP Mesh Decorators

Decorator components for zero-boilerplate mesh integration.

IMPORTANT: The mesh_agent decorator is no longer exported from this module.
Use mcp_mesh.mesh_agent instead for the auto-enhanced version.
"""

from .mesh_agent import (
    MeshAgentDecorator,
    get_mesh_capabilities,
    get_mesh_decorator_instance,
    get_mesh_metadata,
    get_mesh_method_by_name,
    get_mesh_method_metadata,
    get_mesh_registry_metadata,
    get_mesh_service_contract,
    is_mesh_decorated,
)
from .mesh_agent import (
    mesh_agent as _deprecated_mesh_agent,  # Import the deprecated public function for compatibility
)

# mesh_agent is no longer publicly exported - use mcp_mesh.mesh_agent
__all__ = [
    # "mesh_agent",  # REMOVED - use mcp_mesh.mesh_agent instead
    "MeshAgentDecorator",
    "get_mesh_metadata",
    "get_mesh_capabilities",
    "get_mesh_method_metadata",
    "get_mesh_service_contract",
    "get_mesh_registry_metadata",
    "is_mesh_decorated",
    "get_mesh_decorator_instance",
    "get_mesh_method_by_name",
]
