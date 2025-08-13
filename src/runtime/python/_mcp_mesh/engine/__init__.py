"""Engine components for MCP Mesh.

Contains core mesh processing infrastructure:
- HTTP transport capabilities
- Dependency injection system
- MCP client proxies for cross-service communication
- Self-dependency proxies for local calls
- Decorator registry for mesh decorators
- Function signature analysis
"""

# Avoid circular imports by using lazy loading
__all__ = [
    # HTTP infrastructure
    "HttpMcpWrapper",
    "HttpConfig",
    # Dependency injection
    "DependencyInjector",
    "get_global_injector",
    # MCP client proxies (legacy)
    "MCPClientProxy",
    "EnhancedMCPClientProxy",
    "FullMCPProxy",
    "EnhancedFullMCPProxy",
    "AsyncMCPClient",
    # Unified MCP proxy (recommended)
    "UnifiedMCPProxy",
    "EnhancedUnifiedMCPProxy",
    # Self-dependency proxy
    "SelfDependencyProxy",
    # Decorator registry
    "DecoratorRegistry",
    # Signature analysis
    "get_mesh_agent_positions",
    "get_mesh_agent_parameter_names",
    "get_agent_parameter_types",
    "validate_mesh_dependencies",
]


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    # HTTP infrastructure
    if name == "HttpMcpWrapper":
        from .http_wrapper import HttpMcpWrapper

        return HttpMcpWrapper
    elif name == "HttpConfig":
        from .http_wrapper import HttpConfig

        return HttpConfig
    # Dependency injection
    elif name == "DependencyInjector":
        from .dependency_injector import DependencyInjector

        return DependencyInjector
    elif name == "get_global_injector":
        from .dependency_injector import get_global_injector

        return get_global_injector
    # MCP client proxies
    elif name == "MCPClientProxy":
        from .mcp_client_proxy import MCPClientProxy

        return MCPClientProxy
    elif name == "EnhancedMCPClientProxy":
        from .mcp_client_proxy import EnhancedMCPClientProxy

        return EnhancedMCPClientProxy
    elif name == "FullMCPProxy":
        from .full_mcp_proxy import FullMCPProxy

        return FullMCPProxy
    elif name == "EnhancedFullMCPProxy":
        from .full_mcp_proxy import EnhancedFullMCPProxy

        return EnhancedFullMCPProxy
    elif name == "AsyncMCPClient":
        from .async_mcp_client import AsyncMCPClient

        return AsyncMCPClient
    elif name == "UnifiedMCPProxy":
        from .unified_mcp_proxy import UnifiedMCPProxy

        return UnifiedMCPProxy
    elif name == "EnhancedUnifiedMCPProxy":
        from .unified_mcp_proxy import EnhancedUnifiedMCPProxy

        return EnhancedUnifiedMCPProxy
    # Self-dependency proxy
    elif name == "SelfDependencyProxy":
        from .self_dependency_proxy import SelfDependencyProxy

        return SelfDependencyProxy
    # Decorator registry
    elif name == "DecoratorRegistry":
        from .decorator_registry import DecoratorRegistry

        return DecoratorRegistry
    # Signature analysis
    elif name == "get_mesh_agent_positions":
        from .signature_analyzer import get_mesh_agent_positions

        return get_mesh_agent_positions
    elif name == "get_mesh_agent_parameter_names":
        from .signature_analyzer import get_mesh_agent_parameter_names

        return get_mesh_agent_parameter_names
    elif name == "get_agent_parameter_types":
        from .signature_analyzer import get_agent_parameter_types

        return get_agent_parameter_types
    elif name == "validate_mesh_dependencies":
        from .signature_analyzer import validate_mesh_dependencies

        return validate_mesh_dependencies

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
