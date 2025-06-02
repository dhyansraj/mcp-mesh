"""
MCP Mesh Server Components

MCP server implementations built on the official MCP SDK.
Provides server capabilities for the service mesh.
"""

from mcp.server import Server
from mcp.server.models import *
from mcp.server.session import ServerSession

from .models import (
    AgentCapability,
    AgentRegistration,
    CapabilitySearchQuery,
    ServiceDiscoveryQuery,
)
from .registry import RegistryService, RegistryStorage

# Re-export official MCP server components and registry
__all__ = [
    "Server",
    "ServerSession",
    "RegistryService",
    "RegistryStorage",
    "AgentRegistration",
    "AgentCapability",
    "ServiceDiscoveryQuery",
    "CapabilitySearchQuery",
]
