"""Enhanced mesh agent decorator for MCP SDK compatibility with full metadata support."""

import logging
import os
import uuid
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

# Global agent ID shared across all decorators in this process
_SHARED_AGENT_ID: str | None = None


def _get_or_create_agent_id() -> str:
    """Get or create a unique agent ID for this process.

    Returns an agent ID in the format:
    - If MCP_MESH_AGENT_NAME is set: '{name}-{uuid}'
    - Otherwise: 'agent-{uuid}'
    """
    global _SHARED_AGENT_ID

    if _SHARED_AGENT_ID is None:
        # Generate a short UUID suffix (8 chars)
        uuid_suffix = uuid.uuid4().hex[:8]

        # Check for environment variable
        env_name = os.environ.get("MCP_MESH_AGENT_NAME")

        if env_name:
            _SHARED_AGENT_ID = f"{env_name}-{uuid_suffix}"
        else:
            _SHARED_AGENT_ID = f"agent-{uuid_suffix}"

        logger.info(f"Generated agent ID: {_SHARED_AGENT_ID}")

    return _SHARED_AGENT_ID


def _enhance_mesh_agent(processor):
    """Called by the runtime to enhance the decorator with runtime capabilities."""
    global _runtime_processor
    _runtime_processor = processor


def mesh_agent(
    # Multi-tool format (NEW)
    tools: list[dict[str, Any]] | None = None,
    auto_discover_tools: bool = True,
    default_version: str = "1.0.0",
    # Single capability format (LEGACY - for backward compatibility)
    capability: str | None = None,
    # Common parameters
    health_interval: int = 30,
    dependencies: list[str] | None = None,
    registry_url: str | None = None,
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
    enable_http: bool = True,
    http_host: str = "0.0.0.0",
    http_port: int = 0,
    **metadata_kwargs: Any,
) -> Callable[[T], T]:
    """
    Enhanced mesh agent decorator for MCP SDK compatibility with multi-tool support.

    This decorator supports both single-capability (legacy) and multi-tool formats.
    When used with the full mcp-mesh package, it provides complete mesh
    integration including capability registration, health monitoring,
    dependency injection, and service discovery.

    Multi-tool Format (NEW - DEFAULT):
        tools: List of tool definitions with individual dependencies
        auto_discover_tools: Automatically discover @mesh_tool decorated methods (default: True)
        default_version: Default version for auto-discovered tools

    Legacy Format (BACKWARD COMPATIBLE):
        capability: Single capability this agent provides

    Common Args:
        health_interval: Heartbeat interval in seconds (default: 30)
        dependencies: List of capabilities this agent depends on for injection
        enable_http: Enable HTTP wrapper for cross-agent communication (default: True)
                    Note: HTTP is required for dependency injection between agents
                    since stdio-based agents cannot communicate with each other directly.
                    Set to False only if you don't need dependency injection.
        registry_url: Registry service URL (default: from env/config)
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
        # Validation: Cannot specify both single capability and tools
        if capability is not None and tools is not None:
            raise ValueError("Cannot specify both capability and tools parameters")

        # Validation: Must specify either capability OR tools (or auto_discover_tools)
        if capability is None and tools is None and not auto_discover_tools:
            raise ValueError(
                "Must specify either capability (legacy) or tools/auto_discover_tools (new format)"
            )

        # Build tools array based on format
        final_tools = []

        if capability is not None:
            # Legacy single-capability format - convert to multi-tool format
            function_name = getattr(target, "__name__", "legacy_function")
            legacy_deps = []
            if dependencies:
                for dep in dependencies:
                    if isinstance(dep, str):
                        legacy_deps.append({"capability": dep})
                    else:
                        legacy_deps.append(dep)

            final_tools = [
                {
                    "function_name": function_name,
                    "capability": capability,
                    "version": version,
                    "tags": tags or [],
                    "dependencies": legacy_deps,
                }
            ]

        elif tools is not None:
            # New multi-tool format - validate and process
            final_tools = []
            function_names = set()

            for tool in tools:
                # Validate required fields
                if "capability" not in tool:
                    raise ValueError("Tool must have capability")
                if "function_name" not in tool:
                    raise ValueError("Tool must have function_name")

                # Check for duplicate function names
                if tool["function_name"] in function_names:
                    raise ValueError(
                        f"Duplicate function name: {tool['function_name']}"
                    )
                function_names.add(tool["function_name"])

                # Process dependencies
                processed_deps = []
                for dep in tool.get("dependencies", []):
                    if "capability" not in dep:
                        raise ValueError("Dependency must have capability")
                    processed_deps.append(dep)

                # Build complete tool definition
                processed_tool = {
                    "function_name": tool["function_name"],
                    "capability": tool["capability"],
                    "version": tool.get("version", default_version),
                    "tags": tool.get("tags", []),
                    "dependencies": processed_deps,
                }
                final_tools.append(processed_tool)

        # Auto-discover tools from @mesh_tool decorated methods
        if auto_discover_tools:
            discovered_tools = _discover_mesh_tools(target, default_version)
            final_tools.extend(discovered_tools)

        # Collect all capabilities for backward compatibility
        all_capabilities = [tool["capability"] for tool in final_tools]
        legacy_capability = all_capabilities[0] if all_capabilities else None

        # Build enhanced metadata
        metadata = {
            # Multi-tool format (primary)
            "tools": final_tools,
            # Legacy fields for backward compatibility
            "capability": legacy_capability,
            "capabilities": all_capabilities,
            # Common metadata
            "health_interval": health_interval,
            "dependencies": dependencies or [],
            "registry_url": registry_url,
            "agent_name": _get_or_create_agent_id(),
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
        target._mesh_agent_capabilities = all_capabilities
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


def mesh_tool(
    capability: str,
    version: str | None = None,
    tags: list[str] | None = None,
    dependencies: list[dict[str, Any]] | list[str] | None = None,
    **metadata_kwargs: Any,
) -> Callable[[T], T]:
    """
    Decorator for individual tool configuration within a multi-tool agent.

    This decorator marks a method as a mesh tool and stores its metadata
    for auto-discovery by @mesh_agent with auto_discover_tools=True.

    Args:
        capability: The capability this tool provides (required)
        version: Tool version (default: inherited from agent default_version)
        tags: Tool-specific tags for enhanced discovery (default: [])
        dependencies: Tool-specific dependencies (default: [])
        **metadata_kwargs: Additional metadata for the tool

    Returns:
        The original function with tool metadata attached
    """

    def decorator(func: T) -> T:
        # Process dependencies
        processed_deps = []
        if dependencies:
            for dep in dependencies:
                if isinstance(dep, str):
                    processed_deps.append({"capability": dep})
                elif isinstance(dep, dict):
                    if "capability" not in dep:
                        raise ValueError("Dependency must have capability")
                    processed_deps.append(dep)
                else:
                    raise ValueError("Dependencies must be strings or dicts")

        # Store tool metadata on the function
        tool_metadata = {
            "function_name": func.__name__,
            "capability": capability,
            "version": version,  # Will be filled in by auto-discovery if None
            "tags": tags or [],
            "dependencies": processed_deps,
            **metadata_kwargs,
        }

        func._tool_metadata = tool_metadata
        return func

    return decorator


def _discover_mesh_tools(target: Any, default_version: str) -> list[dict[str, Any]]:
    """
    Discover @mesh_tool decorated methods in a class or module.

    Args:
        target: The class or module to search for mesh tools
        default_version: Default version to use for tools without explicit version

    Returns:
        List of tool definitions for discovered tools
    """
    discovered_tools = []

    # Get all methods/functions from the target
    members = target.__dict__.items() if hasattr(target, "__dict__") else []

    for name, member in members:
        # Skip private methods
        if name.startswith("_"):
            continue

        # Check if this member has tool metadata
        if hasattr(member, "_tool_metadata"):
            tool_meta = member._tool_metadata.copy()

            # Fill in default version if not specified
            if tool_meta["version"] is None:
                tool_meta["version"] = default_version

            discovered_tools.append(tool_meta)

    return discovered_tools
