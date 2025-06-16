"""
Mesh decorators implementation - dual decorator architecture.

Provides @mesh.tool and @mesh.agent decorators with clean separation of concerns.
"""

import atexit
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

# Import from mcp_mesh for registry and runtime integration
from mcp_mesh.decorator_registry import DecoratorRegistry

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global reference to the runtime processor, set by mcp_mesh runtime
_runtime_processor: Any | None = None

# Shared agent ID for all functions in the same process
_SHARED_AGENT_ID: str | None = None

# Auto-run configuration storage
_auto_run_config: dict[str, Any] | None = None


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


def _detect_fastmcp_already_processed(func) -> bool:
    """
    Detect if FastMCP has already processed this function.

    This indicates wrong decorator order: @server.tool() came before @mesh.tool().
    """
    # Simple and reliable check: if FastMCP processed this function first,
    # it will have this marker set by our fastmcp_integration patch
    return hasattr(func, "_fastmcp_processed_first")


def _attempt_fastmcp_replacement(target, wrapped) -> bool:
    """
    Attempt to replace the FastMCP cached function with our wrapper.

    This is a compatibility workaround for wrong decorator order.
    Returns True if successful, False otherwise.
    """
    try:
        func_name = target.__name__
        replaced = False

        logger.debug(f"🔧 Attempting FastMCP replacement for '{func_name}'")
        logger.debug(f"🔸 Target original: {target} at {hex(id(target))}")
        logger.debug(f"🔹 Replacement wrapper: {wrapped} at {hex(id(wrapped))}")

        # Try immediate replacement
        if hasattr(target, "_mcp_server"):
            server = target._mcp_server
            logger.debug(f"🎯 Found _mcp_server on target: {server}")

            if (
                hasattr(server, "_tool_manager")
                and hasattr(server._tool_manager, "_tools")
                and func_name in server._tool_manager._tools
            ):

                # Log what FastMCP currently has cached
                current_cached = server._tool_manager._tools[func_name].fn
                logger.debug(
                    f"📦 FastMCP currently has cached: {current_cached} at {hex(id(current_cached))}"
                )

                server._tool_manager._tools[func_name].fn = wrapped

                # Verify the replacement
                new_cached = server._tool_manager._tools[func_name].fn
                logger.debug(
                    f"✅ FastMCP now has cached: {new_cached} at {hex(id(new_cached))}"
                )

                logger.debug(
                    f"Replaced FastMCP cached function {func_name} with injection wrapper"
                )
                replaced = True

        # Also check global function-to-server mapping
        try:
            from mcp_mesh.runtime.fastmcp_integration import _function_to_server

            if target.__name__ in _function_to_server:
                server = _function_to_server[target.__name__]
                logger.debug(f"🌍 Found server via global mapping: {server}")

                if (
                    hasattr(server, "_tool_manager")
                    and hasattr(server._tool_manager, "_tools")
                    and func_name in server._tool_manager._tools
                ):

                    # Log what FastMCP currently has cached
                    current_cached = server._tool_manager._tools[func_name].fn
                    logger.debug(
                        f"📦 FastMCP (global) currently has cached: {current_cached} at {hex(id(current_cached))}"
                    )

                    server._tool_manager._tools[func_name].fn = wrapped

                    # Verify the replacement
                    new_cached = server._tool_manager._tools[func_name].fn
                    logger.debug(
                        f"✅ FastMCP (global) now has cached: {new_cached} at {hex(id(new_cached))}"
                    )

                    logger.debug(
                        f"Replaced FastMCP cached function {func_name} via global mapping"
                    )
                    replaced = True
        except ImportError:
            logger.debug(
                "❌ Could not import _function_to_server from fastmcp_integration"
            )

        # If immediate replacement failed, set up delayed replacement
        if not replaced:
            target._mesh_delayed_replacement = lambda: _attempt_fastmcp_replacement(
                target, wrapped
            )
            logger.debug(f"⏰ Set up delayed FastMCP replacement for {func_name}")
        else:
            logger.debug(f"✅ FastMCP replacement successful for {func_name}")

        return replaced

    except Exception as e:
        logger.warning(f"❌ FastMCP replacement failed for {target.__name__}: {e}")
        return False


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
                            "version": None,
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

                    validated_dependencies.append(
                        {
                            "capability": dep["capability"],
                            "tags": dep_tags,
                            "version": dep_version,
                        }
                    )
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
        if validated_dependencies:
            try:
                # Import here to avoid circular imports
                from mcp_mesh.runtime.dependency_injector import get_global_injector

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

                # Check if FastMCP has already processed this function (wrong order)
                fastmcp_already_processed = _detect_fastmcp_already_processed(target)

                # For now, always apply the compatibility workaround since both orders
                # end up with FastMCP processing the function before @mesh.tool runs
                # The "correct" syntactic order will be handled cleanly in future versions

                if fastmcp_already_processed:
                    # FastMCP has already cached the function - use replacement workaround
                    logger.debug(
                        f"❌ FastMCP processed first for '{target.__name__}' - applying workaround"
                    )
                    logger.debug(
                        f"🔸 FastMCP cached ORIGINAL: {target} at {hex(id(target))}"
                    )
                    logger.debug(
                        f"🔹 Trying to replace with WRAPPER: {wrapped} at {hex(id(wrapped))}"
                    )

                    # Try the FastMCP internal replacement as fallback
                    success = _attempt_fastmcp_replacement(target, wrapped)
                    if success:
                        logger.debug(
                            f"✅ Successfully replaced FastMCP cache with wrapper for '{target.__name__}'"
                        )
                    else:
                        # Set up delayed replacement
                        target._mesh_delayed_replacement = (
                            lambda: _attempt_fastmcp_replacement(target, wrapped)
                        )
                        logger.debug(
                            f"⏰ Set up delayed replacement for '{target.__name__}'"
                        )

                    # Return original to maintain compatibility
                    logger.debug(
                        f"🔸 Returning ORIGINAL function: {target} at {hex(id(target))}"
                    )
                    return target
                else:
                    # No FastMCP processing yet - return wrapper for clean chaining
                    logger.debug(f"✅ Clean decorator chaining for '{target.__name__}'")
                    logger.debug(
                        f"🔹 Returning WRAPPER: {wrapped} at {hex(id(wrapped))}"
                    )

                    # Return the wrapped function - FastMCP will cache this wrapper when it runs
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

        # If runtime processor is available, register with it
        if _runtime_processor is not None:
            try:
                _runtime_processor.register_function(target, metadata)
            except Exception as e:
                logger.error(f"Runtime registration failed for agent {name}: {e}")

        # Handle auto-run functionality
        if final_auto_run:
            logger.info(
                f"🚀 Auto-run enabled for agent '{name}' - will start service automatically"
            )

            # Store auto-run configuration globally for later execution
            global _auto_run_config
            _auto_run_config = {
                "name": name,
                "interval": final_auto_run_interval,
                "enabled": True,
            }

        return target

    return decorator


def start_auto_run_service() -> None:
    """
    Start the auto-run service if enabled by @mesh.agent(auto_run=True).

    This function should be called at the end of your script to start the
    keep-alive loop. It only runs if auto_run=True was set on a @mesh.agent.

    Example:
        import mesh

        @mesh.agent(name="my-service", auto_run=True)
        class MyAgent:
            pass

        @mesh.tool(capability="greeting")
        def hello():
            return "Hello!"

        # This will start the service and keep it alive
        mesh.start_auto_run_service()
    """
    global _auto_run_config

    if _auto_run_config is None or not _auto_run_config.get("enabled", False):
        logger.debug("Auto-run not enabled - service will not start automatically")
        return

    import signal
    import sys
    import threading
    import time

    name = _auto_run_config["name"]
    interval = _auto_run_config["interval"]

    logger.info(f"🎯 Starting auto-run service '{name}'")
    logger.info(f"💓 Keep-alive heartbeat every {interval} seconds")
    logger.info("🛑 Press Ctrl+C to stop the service")

    # Set up signal handlers for graceful shutdown
    shutdown_event = threading.Event()

    def signal_handler(signum, frame):
        logger.info(
            f"🔴 Received shutdown signal {signum} for auto-run service '{name}'"
        )
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Give time for all decorators and runtime to initialize
    logger.info("⏳ Initializing service components...")
    time.sleep(3)

    # Keep-alive loop
    heartbeat_count = 0
    try:
        logger.info(f"✅ Service '{name}' is now running")
        while not shutdown_event.is_set():
            time.sleep(interval)
            heartbeat_count += 1

            if heartbeat_count % 6 == 0:  # Every minute with 10s interval
                logger.info(
                    f"💓 Service '{name}' heartbeat #{heartbeat_count} - running for {heartbeat_count * interval} seconds"
                )
            else:
                logger.debug(
                    f"💓 Auto-run heartbeat #{heartbeat_count} for service '{name}'"
                )

    except Exception as e:
        logger.error(f"Auto-run service error: {e}")
    finally:
        logger.info(f"🛑 Auto-run service '{name}' shutting down gracefully")
        sys.exit(0)


def _auto_run_exit_handler():
    """
    atexit handler that automatically starts auto-run service if enabled.

    This provides the ultimate magic experience - scripts with @mesh.agent(auto_run=True)
    will automatically stay alive without requiring any manual calls.
    """
    global _auto_run_config

    # Only auto-start if config exists and auto_run is enabled
    if _auto_run_config is None or not _auto_run_config.get("enabled", False):
        return

    # Give background processor time to complete registration
    import time

    time.sleep(4)

    # Start the auto-run service automatically
    logger.info(
        "🪄 Script ending - auto-starting keep-alive service for ultimate magic experience"
    )
    start_auto_run_service()


# Register the atexit handler for automatic auto-run
atexit.register(_auto_run_exit_handler)
