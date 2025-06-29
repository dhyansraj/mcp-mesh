"""
MCP Mesh Shared Components

Shared utilities and types built on the official MCP SDK.
Common functionality used across server and client components.

Core mesh processing infrastructure has been moved to mcp_mesh.engine.
"""

# Import only non-circular dependencies at module level
from .support_types import DependencyConfig, HealthStatus

__all__ = [
    "HealthStatus",
    "DependencyConfig",
    "RegistryClient",
    "ContentExtractor",
    "configure_logging",
]


# Lazy imports for circular dependency resolution
def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name == "RegistryClient":
        from ..generated.mcp_mesh_registry_client.api_client import (
            ApiClient as RegistryClient,
        )

        return RegistryClient
    elif name == "ContentExtractor":
        from .content_extractor import ContentExtractor

        return ContentExtractor
    elif name == "configure_logging":
        from .logging_config import configure_logging

        return configure_logging

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
