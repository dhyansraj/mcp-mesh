"""
Mesh decorators implementation - dual decorator architecture.

Provides @mesh.tool and @mesh.agent decorators with clean separation of concerns.
"""

import logging
import os
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

# Import from mcp_mesh for registry and runtime integration
from mcp_mesh.engine.decorator_registry import DecoratorRegistry

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global reference to the runtime processor, set by mcp_mesh runtime
_runtime_processor: Any | None = None

# Shared agent ID for all functions in the same process
_SHARED_AGENT_ID: str | None = None


def _trigger_debounced_processing():
    """
    Trigger debounced processing when a decorator is applied.

    This connects to the pipeline's debounce coordinator to ensure
    all decorators are captured before processing begins.
    """
    try:
        from mcp_mesh.pipeline.startup import get_debounce_coordinator

        coordinator = get_debounce_coordinator()
        coordinator.trigger_processing()
        logger.debug("⚡ Triggered debounced processing")
    except ImportError:
        # Pipeline orchestrator not available - graceful degradation
        logger.debug(
            "⚠️ Pipeline orchestrator not available, skipping debounced processing"
        )
    except Exception as e:
        # Don't fail decorator application due to processing errors
        logger.debug(f"⚠️ Failed to trigger debounced processing: {e}")


def _get_or_create_agent_id(agent_name: str | None = None) -> str:
    """
    Get or create a shared agent ID for all functions in this process.

    Format: {prefix}-{8chars} where:
    - prefix precedence: MCP_MESH_AGENT_NAME env var > agent_name parameter > "agent"
    - 8chars is first 8 characters of a UUID

    Args:
        agent_name: Optional name from @mesh.agent decorator

    Returns:
        Shared agent ID for this process
    """
    global _SHARED_AGENT_ID

    if _SHARED_AGENT_ID is None:
        # Precedence: env var > agent_name > default "agent"
        if "MCP_MESH_AGENT_NAME" in os.environ:
            prefix = os.environ["MCP_MESH_AGENT_NAME"]
        elif agent_name is not None:
            prefix = agent_name
        else:
            prefix = "agent"

        uuid_suffix = str(uuid.uuid4())[:8]
        _SHARED_AGENT_ID = f"{prefix}-{uuid_suffix}"

    return _SHARED_AGENT_ID


def _enhance_mesh_decorators(processor):
    """Called by mcp_mesh runtime to enhance decorators with runtime capabilities."""
    global _runtime_processor
    _runtime_processor = processor


def _clear_shared_agent_id():
    """Clear the shared agent ID (useful for testing)."""
    global _SHARED_AGENT_ID
    _SHARED_AGENT_ID = None


def tool(
    capability: str | None = None,
    *,
    tags: list[str] | None = None,
    version: str = "1.0.0",
    dependencies: list[dict[str, Any]] | list[str] | None = None,
    description: str | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    Tool-level decorator for individual MCP functions/capabilities.

    Handles individual tool registration, capabilities, and dependencies.

    IMPORTANT: For optimal compatibility with FastMCP, use this decorator order:

    @mesh.tool(capability="example", dependencies=[...])
    @server.tool()
    def my_function():
        pass

    While both orders currently work, the above order is recommended for future compatibility.

    Args:
        capability: Optional capability name this tool provides (default: None)
        tags: Optional list of tags for discovery (default: [])
        version: Tool version (default: "1.0.0")
        dependencies: Optional list of dependencies (default: [])
        description: Optional description (default: function docstring)
        **kwargs: Additional metadata

    Returns:
        Function with dependency injection wrapper if dependencies are specified,
        otherwise the original function with metadata attached
    """

    def decorator(target: T) -> T:
        # Validate optional capability
        if capability is not None and not isinstance(capability, str):
            raise ValueError("capability must be a string")

        # Validate optional parameters
        if tags is not None:
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ValueError("all tags must be strings")

        if not isinstance(version, str):
            raise ValueError("version must be a string")

        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string")

        # Validate and process dependencies
        if dependencies is not None:
            if not isinstance(dependencies, list):
                raise ValueError("dependencies must be a list")

            validated_dependencies = []
            for dep in dependencies:
                if isinstance(dep, str):
                    # Simple string dependency
                    validated_dependencies.append(
                        {
                            "capability": dep,
                            "tags": [],
                        }
                    )
                elif isinstance(dep, dict):
                    # Complex dependency with metadata
                    if "capability" not in dep:
                        raise ValueError("dependency must have 'capability' field")
                    if not isinstance(dep["capability"], str):
                        raise ValueError("dependency capability must be a string")

                    # Validate optional dependency fields
                    dep_tags = dep.get("tags", [])
                    if not isinstance(dep_tags, list):
                        raise ValueError("dependency tags must be a list")
                    for tag in dep_tags:
                        if not isinstance(tag, str):
                            raise ValueError("all dependency tags must be strings")

                    dep_version = dep.get("version")
                    if dep_version is not None and not isinstance(dep_version, str):
                        raise ValueError("dependency version must be a string")

                    dependency_dict = {
                        "capability": dep["capability"],
                        "tags": dep_tags,
                    }
                    if dep_version is not None:
                        dependency_dict["version"] = dep_version
                    validated_dependencies.append(dependency_dict)
                else:
                    raise ValueError("dependencies must be strings or dictionaries")
        else:
            validated_dependencies = []

        # Build tool metadata
        metadata = {
            "capability": capability,
            "tags": tags or [],
            "version": version,
            "dependencies": validated_dependencies,
            "description": description or getattr(target, "__doc__", None),
            **kwargs,
        }

        # Store metadata on function
        target._mesh_tool_metadata = metadata

        # Register with DecoratorRegistry for processor discovery (will be updated with wrapper if needed)
        DecoratorRegistry.register_mesh_tool(target, metadata)

        # Create dependency injection wrapper if needed
        logger.debug(
            f"🔍 Function '{target.__name__}' has {len(validated_dependencies)} validated dependencies: {validated_dependencies}"
        )
        if validated_dependencies:
            try:
                # Import here to avoid circular imports
                from mcp_mesh.engine.dependency_injector import get_global_injector

                # Extract dependency names for injector
                dependency_names = [dep["capability"] for dep in validated_dependencies]

                # Log the original function pointer
                logger.debug(
                    f"🔸 ORIGINAL function pointer: {target} at {hex(id(target))}"
                )

                injector = get_global_injector()
                wrapped = injector.create_injection_wrapper(target, dependency_names)

                # Log the wrapper function pointer
                logger.debug(
                    f"🔹 WRAPPER function pointer: {wrapped} at {hex(id(wrapped))}"
                )

                # Preserve metadata on wrapper
                wrapped._mesh_tool_metadata = metadata

                # Store the wrapper on the original function for reference
                target._mesh_injection_wrapper = wrapped

                # CRITICAL: Update DecoratorRegistry to use the wrapper instead of the original
                DecoratorRegistry.update_mesh_tool_function(target.__name__, wrapped)
                logger.debug(
                    f"🔄 Updated DecoratorRegistry to use wrapper for '{target.__name__}'"
                )

                # If runtime processor is available, register with it
                if _runtime_processor is not None:
                    try:
                        _runtime_processor.register_function(wrapped, metadata)
                    except Exception as e:
                        logger.error(
                            f"Runtime registration failed for {target.__name__}: {e}"
                        )

                # Return the wrapped function - FastMCP will cache this wrapper when it runs
                logger.debug(f"✅ Returning injection wrapper for '{target.__name__}'")
                logger.debug(f"🔹 Returning WRAPPER: {wrapped} at {hex(id(wrapped))}")

                # Trigger debounced processing before returning
                _trigger_debounced_processing()
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

        # Trigger debounced processing before returning
        _trigger_debounced_processing()
        return target

    return decorator


def agent(
    name: str | None = None,
    *,
    version: str = "1.0.0",
    description: str | None = None,
    http_host: str = "0.0.0.0",
    http_port: int = 0,
    enable_http: bool = True,
    namespace: str = "default",
    health_interval: int = 30,
    auto_run: bool = True,  # Changed to True by default!
    auto_run_interval: int = 10,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    Agent-level decorator for agent-wide configuration and metadata.

    This handles agent-level concerns like deployment, infrastructure,
    and overall agent metadata. Applied to classes or main functions.

    Args:
        name: Required agent name (mandatory!)
        version: Agent version (default: "1.0.0")
        description: Optional agent description
        http_host: HTTP server host (default: "0.0.0.0")
            Environment variable: MCP_MESH_HTTP_HOST (takes precedence)
        http_port: HTTP server port (default: 0, means auto-assign)
            Environment variable: MCP_MESH_HTTP_PORT (takes precedence)
        enable_http: Enable HTTP endpoints (default: True)
            Environment variable: MCP_MESH_ENABLE_HTTP (takes precedence)
        namespace: Agent namespace (default: "default")
            Environment variable: MCP_MESH_NAMESPACE (takes precedence)
        health_interval: Health check interval in seconds (default: 30)
            Environment variable: MCP_MESH_HEALTH_INTERVAL (takes precedence)
        auto_run: Automatically start service and keep process alive (default: True)
            Environment variable: MCP_MESH_AUTO_RUN (takes precedence)
        auto_run_interval: Keep-alive heartbeat interval in seconds (default: 10)
            Environment variable: MCP_MESH_AUTO_RUN_INTERVAL (takes precedence)
        **kwargs: Additional agent metadata

    Environment Variables:
        MCP_MESH_HTTP_HOST: Override http_host parameter (string)
        MCP_MESH_HTTP_PORT: Override http_port parameter (integer, 0-65535)
        MCP_MESH_ENABLE_HTTP: Override enable_http parameter (boolean: true/false)
        MCP_MESH_NAMESPACE: Override namespace parameter (string)
        MCP_MESH_HEALTH_INTERVAL: Override health_interval parameter (integer, ≥1)
        MCP_MESH_AUTO_RUN: Override auto_run parameter (boolean: true/false)
        MCP_MESH_AUTO_RUN_INTERVAL: Override auto_run_interval parameter (integer, ≥1)

    Auto-Run Feature:
        When auto_run=True, the decorator automatically starts the service and keeps
        the process alive. This eliminates the need for manual while True loops.

        Example:
            @mesh.agent(name="my-service", auto_run=True)
            class MyAgent:
                pass

            @mesh.tool(capability="greeting")
            def hello():
                return "Hello!"

            # Script automatically stays alive - no while loop needed!

    Returns:
        The original class/function with agent metadata attached
    """

    def decorator(target: T) -> T:
        # Validate required name
        if name is None:
            raise ValueError("name is required for @mesh.agent")
        if not isinstance(name, str):
            raise ValueError("name must be a string")

        # Validate decorator parameters first
        if not isinstance(version, str):
            raise ValueError("version must be a string")

        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string")

        if not isinstance(http_host, str):
            raise ValueError("http_host must be a string")

        if not isinstance(http_port, int):
            raise ValueError("http_port must be an integer")
        if not (0 <= http_port <= 65535):
            raise ValueError("http_port must be between 0 and 65535")

        if not isinstance(enable_http, bool):
            raise ValueError("enable_http must be a boolean")

        if not isinstance(namespace, str):
            raise ValueError("namespace must be a string")

        if not isinstance(health_interval, int):
            raise ValueError("health_interval must be an integer")
        if health_interval < 1:
            raise ValueError("health_interval must be at least 1 second")

        if not isinstance(auto_run, bool):
            raise ValueError("auto_run must be a boolean")

        if not isinstance(auto_run_interval, int):
            raise ValueError("auto_run_interval must be an integer")
        if auto_run_interval < 1:
            raise ValueError("auto_run_interval must be at least 1 second")

        # Get final values with environment variable precedence
        final_http_host = os.environ.get("MCP_MESH_HTTP_HOST", http_host)

        # Handle environment variable conversion and validation
        env_http_port = os.environ.get("MCP_MESH_HTTP_PORT")
        if env_http_port is not None:
            try:
                final_http_port = int(env_http_port)
            except ValueError as e:
                raise ValueError(
                    "MCP_MESH_HTTP_PORT environment variable must be a valid integer"
                ) from e

            if not (0 <= final_http_port <= 65535):
                raise ValueError("http_port must be between 0 and 65535")
        else:
            final_http_port = http_port

        env_enable_http = os.environ.get("MCP_MESH_ENABLE_HTTP")
        if env_enable_http is not None:
            if env_enable_http.lower() in ("true", "1", "yes", "on"):
                final_enable_http = True
            elif env_enable_http.lower() in ("false", "0", "no", "off"):
                final_enable_http = False
            else:
                raise ValueError(
                    "MCP_MESH_ENABLE_HTTP environment variable must be a boolean value (true/false, 1/0, yes/no, on/off)"
                )
        else:
            final_enable_http = enable_http

        final_namespace = os.environ.get("MCP_MESH_NAMESPACE", namespace)

        env_health_interval = os.environ.get("MCP_MESH_HEALTH_INTERVAL")
        if env_health_interval is not None:
            try:
                final_health_interval = int(env_health_interval)
            except ValueError as e:
                raise ValueError(
                    "MCP_MESH_HEALTH_INTERVAL environment variable must be a valid integer"
                ) from e

            if final_health_interval < 1:
                raise ValueError("health_interval must be at least 1 second")
        else:
            final_health_interval = health_interval

        env_auto_run = os.environ.get("MCP_MESH_AUTO_RUN")
        if env_auto_run is not None:
            if env_auto_run.lower() in ("true", "1", "yes", "on"):
                final_auto_run = True
            elif env_auto_run.lower() in ("false", "0", "no", "off"):
                final_auto_run = False
            else:
                raise ValueError(
                    "MCP_MESH_AUTO_RUN environment variable must be a boolean value (true/false, 1/0, yes/no, on/off)"
                )
        else:
            final_auto_run = auto_run

        env_auto_run_interval = os.environ.get("MCP_MESH_AUTO_RUN_INTERVAL")
        if env_auto_run_interval is not None:
            try:
                final_auto_run_interval = int(env_auto_run_interval)
            except ValueError as e:
                raise ValueError(
                    "MCP_MESH_AUTO_RUN_INTERVAL environment variable must be a valid integer"
                ) from e

            if final_auto_run_interval < 1:
                raise ValueError("auto_run_interval must be at least 1 second")
        else:
            final_auto_run_interval = auto_run_interval

        # Build agent metadata
        metadata = {
            "name": name,
            "version": version,
            "description": description,
            "http_host": final_http_host,
            "http_port": final_http_port,
            "enable_http": final_enable_http,
            "namespace": final_namespace,
            "health_interval": final_health_interval,
            "auto_run": final_auto_run,
            "auto_run_interval": final_auto_run_interval,
            **kwargs,
        }

        # Store metadata on target (class or function)
        target._mesh_agent_metadata = metadata

        # Register with DecoratorRegistry for processor discovery
        DecoratorRegistry.register_mesh_agent(target, metadata)

        # Trigger debounced processing
        _trigger_debounced_processing()

        # If runtime processor is available, register with it
        if _runtime_processor is not None:
            try:
                _runtime_processor.register_function(target, metadata)
            except Exception as e:
                logger.error(f"Runtime registration failed for agent {name}: {e}")

        # Auto-run functionality is now handled by the pipeline architecture
        if final_auto_run:
            logger.info(
                f"🚀 Auto-run enabled for agent '{name}' - pipeline will start service automatically"
            )

        return target

    return decorator
