"""
MCP Mesh SDK Tools

File operations, lifecycle management, versioning, dynamic proxy generation,
and dependency injection tools.
"""

from .dependency_injection import (
    inject_dependencies,
    resolve_dependency,
    resolve_dependency_async,
    validate_dependency_types,
)
from .lifecycle_tools import LifecycleTools, create_lifecycle_tools
from .proxy_factory import (  # Enhanced proxy factory classes; Factory functions; Legacy compatibility; Legacy ProxyFactory (for backward compatibility)
    DynamicProxyGenerator,
    EnhancedProxyFactory,
    ProxyFactory,
    TypeValidator,
    create_service_proxy,
    create_typed_proxy,
    get_proxy_factory,
    proxy_for,
    resolve_service_endpoint,
    round_trip_type_test,
    validate_proxy_compatibility,
    validate_proxy_health,
)
from .selection_tools import SelectionTools
from .versioning_tools import VersioningTools, create_versioning_tools

__all__ = [
    # Core tools
    "VersioningTools",
    "create_versioning_tools",
    "LifecycleTools",
    "create_lifecycle_tools",
    "SelectionTools",
    # Dependency injection tools
    "resolve_dependency",
    "resolve_dependency_async",
    "inject_dependencies",
    "validate_dependency_types",
    # Enhanced proxy generation
    "EnhancedProxyFactory",
    "DynamicProxyGenerator",
    "TypeValidator",
    # Main factory functions
    "create_service_proxy",
    "resolve_service_endpoint",
    "validate_proxy_compatibility",
    "round_trip_type_test",
    "get_proxy_factory",
    # Legacy compatibility
    "ProxyFactory",
    "create_typed_proxy",
    "validate_proxy_health",
    "proxy_for",
]
