"""Runtime-specific exceptions for MCP Mesh."""


class RegistryError(Exception):
    """Base exception for registry-related errors."""

    pass


class RegistryConnectionError(RegistryError):
    """Raised when connection to registry fails."""

    pass


class RegistryTimeoutError(RegistryError):
    """Raised when registry operations timeout."""

    pass
