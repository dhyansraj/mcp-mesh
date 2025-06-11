"""Runtime components for MCP Mesh."""

# Avoid circular imports by using lazy loading
__all__ = [
    "DecoratorProcessor",
    "RegistryClient",
    "LifecycleManager",
]


def __getattr__(name):
    """Lazy import to avoid circular dependencies."""
    if name == "LifecycleManager":
        from .health_monitor import LifecycleManager

        return LifecycleManager
    elif name == "DecoratorProcessor":
        from .processor import DecoratorProcessor

        return DecoratorProcessor
    elif name == "RegistryClient":
        from .registry_client import RegistryClient

        return RegistryClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
