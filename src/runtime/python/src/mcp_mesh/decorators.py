"""Enhanced mesh agent decorator for MCP SDK compatibility with full metadata support."""

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from .decorator_registry import DecoratorRegistry

# Import logging config if runtime is available
try:
    from .runtime.logging_config import configure_logging

    configure_logging()
except ImportError:
    # Runtime module not available, skip logging configuration
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global reference to the runtime processor, set by __init__.py
_runtime_processor: Any | None = None


def _enhance_mesh_agent(processor):
    """Called by the runtime to enhance the decorator with runtime capabilities."""
    global _runtime_processor
    _runtime_processor = processor


def mesh_agent(
    capability: str,  # Required single capability
    health_interval: int = 30,
    dependencies: list[str] | None = None,
    registry_url: str | None = None,
    agent_name: str | None = None,
    security_context: str | None = None,
    timeout: int = 30,
    retry_attempts: int = 3,
    enable_caching: bool = True,
    fallback_mode: bool = True,
    # Enhanced capability metadata
    version: str = "1.0.0",
    description: str | None = None,
    endpoint: str | None = None,
    tags: list[str] | None = None,
    performance_profile: dict[str, float] | None = None,
    resource_requirements: dict[str, Any] | None = None,
    # HTTP wrapper configuration
    enable_http: bool | None = None,
    http_host: str = "0.0.0.0",
    http_port: int = 0,
    **metadata_kwargs: Any,
) -> Callable[[T], T]:
    """
    Enhanced mesh agent decorator for MCP SDK compatibility.

    This decorator provides metadata storage in the types-only package.
    When used with the full mcp-mesh package, it provides complete mesh
    integration including capability registration, health monitoring,
    dependency injection, and service discovery.

    Args:
        capability: Single capability this agent provides (required)
        health_interval: Heartbeat interval in seconds (default: 30)
        dependencies: List of service dependencies to inject (default: None)
        registry_url: Registry service URL (default: from env/config)
        agent_name: Agent identifier (default: auto-generated)
        security_context: Security context for authorization (default: None)
        timeout: Network timeout in seconds (default: 30)
        retry_attempts: Number of retry attempts for registry calls (default: 3)
        enable_caching: Enable local caching of dependencies (default: True)
        fallback_mode: Enable graceful degradation mode (default: True)
        version: Agent version for capability versioning (default: "1.0.0")
        description: Agent description for discovery (default: None)
        endpoint: Agent endpoint URL for direct communication (default: None)
        tags: Agent tags for enhanced discovery (default: None)
        performance_profile: Performance characteristics for matching (default: None)
        resource_requirements: Resource requirements specification (default: None)
        enable_http: Enable HTTP wrapper for containerized deployments (default: auto-detect)
        http_host: HTTP server host (default: "0.0.0.0")
        http_port: HTTP server port, 0 for auto-assign (default: 0)
        **metadata_kwargs: Additional metadata for capability registration

    Returns:
        The original function/class with mesh metadata attached
    """

    def decorator(target: T) -> T:
        # Build enhanced metadata for capability registration
        metadata = {
            "capability": capability,
            "capabilities": [capability],  # Store as list for internal compatibility
            "health_interval": health_interval,
            "dependencies": dependencies or [],
            "registry_url": registry_url,
            "agent_name": agent_name or getattr(target, "__name__", "unknown"),
            "security_context": security_context,
            "timeout": timeout,
            "retry_attempts": retry_attempts,
            "enable_caching": enable_caching,
            "fallback_mode": fallback_mode,
            "version": version,
            "description": description or getattr(target, "__doc__", None),
            "endpoint": endpoint,
            "tags": tags or [],
            "performance_profile": performance_profile or {},
            "resource_requirements": resource_requirements or {},
            "enable_http": enable_http,
            "http_host": http_host,
            "http_port": http_port,
            **metadata_kwargs,
        }

        # Register with DecoratorRegistry for later processing
        DecoratorRegistry.register_mesh_agent(target, metadata)

        # Store metadata on function for backward compatibility
        if not hasattr(target, "_mesh_metadata"):
            target._mesh_metadata = {}
        target._mesh_metadata.update(metadata)

        # Store additional metadata for runtime access (backward compatibility)
        target._mesh_agent_capabilities = [capability]
        target._mesh_agent_dependencies = dependencies or []

        # Create dependency injection wrapper if needed
        if dependencies:
            try:
                # Import here to avoid circular imports
                from .runtime.dependency_injector import get_global_injector

                injector = get_global_injector()
                wrapped = injector.create_injection_wrapper(target, dependencies)

                # Preserve all metadata on wrapper
                wrapped._mesh_metadata = target._mesh_metadata
                wrapped._mesh_agent_capabilities = target._mesh_agent_capabilities
                wrapped._mesh_agent_dependencies = target._mesh_agent_dependencies

                # If runtime processor is available, register with it
                if _runtime_processor is not None:
                    try:
                        _runtime_processor.register_function(wrapped, metadata)
                    except Exception as e:
                        logger.error(
                            f"Runtime registration failed for {target.__name__}: {e}"
                        )

                return wrapped
            except Exception as e:
                # Log but don't fail - graceful degradation
                logger.error(
                    f"Dependency injection setup failed for {target.__name__}: {e}"
                )

        # No dependencies - just register with runtime if available
        if _runtime_processor is not None:
            try:
                _runtime_processor.register_function(target, metadata)
            except Exception as e:
                logger.error(f"Runtime registration failed for {target.__name__}: {e}")

        return target

    return decorator
