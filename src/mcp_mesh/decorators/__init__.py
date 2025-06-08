"""
MCP Mesh Decorators

Decorator components for zero-boilerplate mesh integration.
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
    mesh_agent,
)

__all__ = [
    "mesh_agent",
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
