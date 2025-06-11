"""Runtime-specific exceptions for MCP Mesh.

This module re-exports registry exceptions from the shared module
for backward compatibility.
"""

from .shared.exceptions import (  # Re-export the comprehensive exception hierarchy
    MCPError,
    MCPErrorCode,
    MeshAgentError,
    RegistryConnectionError,
    RegistryTimeoutError,
)


# For backward compatibility, create a base RegistryError that's compatible
# with the new exception hierarchy
class RegistryError(MeshAgentError):
    """Base exception for registry-related errors."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code=MCPErrorCode.REGISTRY_UNAVAILABLE, **kwargs)


__all__ = [
    "RegistryError",
    "RegistryConnectionError",
    "RegistryTimeoutError",
    "MCPError",
    "MCPErrorCode",
    "MeshAgentError",
]
