"""Simplified mesh agent decorator with clean parameter validation."""

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
    capability: str | None = None,
    tags: list[str] | None = None,
    version: str = "1.0.0",
    http_host: str = "0.0.0.0",
    http_port: int = 0,
    dependencies: list[dict[str, Any]] | None = None,
    description: str | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    Simplified mesh agent decorator.

    Args:
        capability: Optional capability name this agent provides
        tags: Optional list of tags for service discovery (default: [])
        version: Agent version (default: "1.0.0")
        http_host: HTTP server host (default: "0.0.0.0")
        http_port: HTTP server port (default: 0)
        dependencies: Optional list of dependency specifications (default: [])
        description: Optional description (default: function docstring)
        **kwargs: No additional parameters allowed

    Dependency format:
        {
            "capability": "required_service",  # Required
            "tags": ["optional", "tags"],      # Optional, default: []
            "version": ">= 1.0.0"             # Optional, default: None
        }

    Returns:
        The original function/class with simplified mesh metadata attached
    """

    def decorator(target: T) -> T:
        # Validate unknown parameters
        if kwargs:
            unknown_params = ", ".join(kwargs.keys())
            raise ValueError(f"unknown parameter(s): {unknown_params}")

        # Validate capability
        if capability is not None and not isinstance(capability, str):
            raise ValueError("capability must be a string")

        # Validate tags
        if tags is not None:
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ValueError("all tags must be strings")

        # Validate version
        if not isinstance(version, str):
            raise ValueError("version must be a string")

        # Validate http_host
        if not isinstance(http_host, str):
            raise ValueError("http_host must be a string")

        # Validate http_port
        if not isinstance(http_port, int):
            raise ValueError("http_port must be an integer")
        if not (0 <= http_port <= 65535):
            raise ValueError("http_port must be between 0 and 65535")

        # Validate description
        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string")

        # Validate dependencies
        if dependencies is not None:
            if not isinstance(dependencies, list):
                raise ValueError("dependencies must be a list")

            validated_dependencies = []
            for dep in dependencies:
                if not isinstance(dep, dict):
                    raise ValueError("each dependency must be a dictionary")

                # Validate required capability field
                if "capability" not in dep:
                    raise ValueError("dependency must have 'capability' field")
                if not isinstance(dep["capability"], str):
                    raise ValueError("dependency capability must be a string")

                # Validate optional tags field
                dep_tags = dep.get("tags", [])
                if not isinstance(dep_tags, list):
                    raise ValueError("dependency tags must be a list")
                for tag in dep_tags:
                    if not isinstance(tag, str):
                        raise ValueError("all dependency tags must be strings")

                # Validate optional version field
                dep_version = dep.get("version")
                if dep_version is not None and not isinstance(dep_version, str):
                    raise ValueError("dependency version must be a string")

                # Build validated dependency
                validated_dep = {
                    "capability": dep["capability"],
                    "tags": dep_tags,
                    "version": dep_version,
                }
                validated_dependencies.append(validated_dep)
        else:
            validated_dependencies = []

        # Build simplified metadata structure
        metadata = {
            "capability": capability,
            "tags": tags or [],
            "version": version,
            "http_host": http_host,
            "http_port": http_port,
            "dependencies": validated_dependencies,
            "description": description or getattr(target, "__doc__", None),
        }

        # Register with DecoratorRegistry for later processing
        DecoratorRegistry.register_mesh_agent(target, metadata)

        # Store metadata on function
        target._mesh_metadata = metadata

        # Create dependency injection wrapper if needed
        if validated_dependencies:
            try:
                # Import here to avoid circular imports
                from .runtime.dependency_injector import get_global_injector

                # Extract dependency names for injector
                dependency_names = [dep["capability"] for dep in validated_dependencies]

                injector = get_global_injector()
                wrapped = injector.create_injection_wrapper(target, dependency_names)

                # Preserve metadata on wrapper
                wrapped._mesh_metadata = metadata

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
