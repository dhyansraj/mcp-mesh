"""Engine components for MCP Mesh.

Contains server infrastructure and HTTP transport capabilities.
Most utility classes have been moved to mcp_mesh.shared.
"""

# Avoid circular imports by using lazy loading
__all__ = [
    "HttpMcpWrapper",
    "HttpConfig",
]


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name == "HttpMcpWrapper":
        from .http_wrapper import HttpMcpWrapper

        return HttpMcpWrapper
    elif name == "HttpConfig":
        from .http_wrapper import HttpConfig

        return HttpConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
