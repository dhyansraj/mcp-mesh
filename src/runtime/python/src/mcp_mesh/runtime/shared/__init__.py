"""
MCP Mesh Shared Components

Shared utilities and types built on the official MCP SDK.
Common functionality used across server and client components.
"""

from mcp import types
from mcp.shared import *

from .exceptions import MeshAgentError, RegistryConnectionError, RegistryTimeoutError
from .registry_client import RegistryClient
from .service_discovery import (
    EnhancedServiceDiscovery,
    HealthMonitor,
    SelectionCriteria,
    ServiceDiscovery,
)
from .service_proxy import MeshServiceProxy
from .types import DependencyConfig, HealthStatus

__all__ = [
    "HealthStatus",
    "DependencyConfig",
    "MeshAgentError",
    "RegistryConnectionError",
    "RegistryTimeoutError",
    "RegistryClient",
    "ServiceDiscovery",
    "SelectionCriteria",
    "HealthMonitor",
    "EnhancedServiceDiscovery",
    "MeshServiceProxy",
]
