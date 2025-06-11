"""
MCP Mesh Shared Components

Shared utilities and types built on the official MCP SDK.
Common functionality used across server and client components.
"""

# Import only non-circular dependencies at module level
from .exceptions import MeshAgentError, RegistryConnectionError, RegistryTimeoutError
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


# Lazy imports for circular dependency resolution
def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name == "RegistryClient":
        from .registry_client import RegistryClient

        return RegistryClient
    elif name in [
        "ServiceDiscovery",
        "SelectionCriteria",
        "HealthMonitor",
        "EnhancedServiceDiscovery",
    ]:
        from .service_discovery import (  # noqa: F401
            EnhancedServiceDiscovery,
            HealthMonitor,
            SelectionCriteria,
            ServiceDiscovery,
        )

        return locals()[name]
    elif name == "MeshServiceProxy":
        from .service_proxy import MeshServiceProxy

        return MeshServiceProxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
