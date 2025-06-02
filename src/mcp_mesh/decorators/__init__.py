"""
MCP Mesh Decorators

Decorator components for zero-boilerplate mesh integration.
"""

from mcp_mesh_definitions import mesh_agent

from .mesh_agent import MeshAgentDecorator

__all__ = [
    "mesh_agent",
    "MeshAgentDecorator",
]
