"""
Integration with FastMCP to enable dependency injection.

This module monkey-patches FastMCP's tool execution to support our dependency injection.
"""

import asyncio
import logging
from typing import Any

from mcp.server.fastmcp.tools import ToolManager

from .dependency_injector import get_global_injector
from .logging_config import configure_logging

# Ensure logging is configured
configure_logging()

logger = logging.getLogger(__name__)

# Store original methods
_original_call_tool = None
_original_add_tool = None
_patched = False

# Map function to server for HTTP wrapper creation
_function_to_server = {}

# Background thread event loop for cleanup coordination
_background_loop = None
_background_thread = None


def patch_fastmcp():
    """Monkey-patch FastMCP to support dependency injection."""
    global _original_call_tool, _original_add_tool, _patched

    if _patched:
        return

    # Import FastMCP class
    try:
        from fastmcp import FastMCP

        logger.info("🆕 FastMCP Integration: Using NEW FastMCP library (fastmcp)")
    except ImportError:
        try:
            # Fallback to old version
            from mcp.server.fastmcp import FastMCP

            logger.info(
                "🔄 FastMCP Integration: Using OLD FastMCP library (mcp.server.fastmcp)"
            )
        except ImportError:
            logger.warning("FastMCP not available, skipping patches")
            return

    # Store original methods
    _original_call_tool = ToolManager.call_tool
    _original_add_tool = FastMCP.tool

    # Create patched version
    async def patched_call_tool(
        self, name: str, arguments: dict[str, Any], context: Any | None = None
    ) -> Any:
        """Patched call_tool that injects dependencies."""

        # Get the tool
        tool = self._tools.get(name)
        if not tool:
            # Fall back to original
            return await _original_call_tool(self, name, arguments, context=context)

        # Check if the function has dependency metadata
        fn = tool.fn
        logger.info(f"📞 FastMCP CALL: {name} with arguments: {arguments}")
        logger.debug(
            f"🎯 FastMCP calling function: {fn.__name__} at {hex(id(fn))} | Full function: {fn}"
        )
        if hasattr(fn, "_mesh_agent_dependencies"):
            dependencies = fn._mesh_agent_dependencies
            injector = get_global_injector()

            # Inject dependencies into arguments
            for dep_name in dependencies:
                if dep_name not in arguments or arguments[dep_name] is None:
                    dep_value = injector.get_dependency(dep_name)
                    if dep_value is not None:
                        arguments[dep_name] = dep_value
                        logger.debug(f"Injected {dep_name} for tool {name}")

        elif hasattr(fn, "_mesh_tool_metadata"):
            # Check if metadata has dependencies
            metadata = fn._mesh_tool_metadata
            if metadata and "dependencies" in metadata:
                dependencies = [dep["capability"] for dep in metadata["dependencies"]]
                injector = get_global_injector()

                # Inject dependencies into arguments
                for dep_name in dependencies:
                    if dep_name not in arguments or arguments[dep_name] is None:
                        dep_value = injector.get_dependency(dep_name)
                        if dep_value is not None:
                            arguments[dep_name] = dep_value
                            logger.debug(f"Injected {dep_name} for tool {name}")

        # Call original with potentially modified arguments
        result = await _original_call_tool(self, name, arguments, context=context)
        logger.info(f"📞 FastMCP RESPONSE: {name} returned: {result}")
        return result

    # Create patched tool decorator
    def patched_tool(self, *args, **kwargs):
        """Patched tool decorator that tracks server references."""
        # Call original to get the decorator
        decorator = _original_add_tool(self, *args, **kwargs)

        # Create wrapper that stores server reference
        def wrapper(func):
            logger.debug(
                f"🔍 FastMCP patched_tool received function: {func} at {hex(id(func))}"
            )

            # Check if @mesh.tool was applied first (correct order)
            if hasattr(func, "_mesh_tool_metadata"):
                logger.debug(
                    f"✅ Correct decorator order for '{func.__name__}': @mesh.tool() applied before @server.tool()"
                )

                # Check if this is a wrapper from mesh.tool
                if hasattr(func, "_original_func"):
                    original = func._original_func
                    logger.debug("🔍 Function is a mesh.tool wrapper:")
                    logger.debug(f"  🔹 Wrapper: {func} at {hex(id(func))}")
                    logger.debug(f"  🔸 Original: {original} at {hex(id(original))}")
                else:
                    logger.debug(
                        "🔍 Function has mesh metadata but no _original_func - might be original"
                    )
            else:
                # Mark that FastMCP processed this function first (wrong order)
                func._fastmcp_processed_first = True
                logger.debug(
                    f"🔄 FastMCP processing '{func.__name__}' before @mesh.tool() - this indicates wrong decorator order"
                )

            # Apply original decorator
            decorated = decorator(func)
            # Store server reference
            _function_to_server[func.__name__] = self
            _function_to_server[id(func)] = self
            # Also store on function itself
            func._mcp_server = self
            logger.debug(f"Registered function {func.__name__} with server {self.name}")
            logger.debug(f"🏷️  FastMCP will cache: {func} at {hex(id(func))}")

            # CRITICAL: Check if this function has a pending mesh.tool injection wrapper
            # If so, replace the FastMCP cached function immediately
            if hasattr(func, "_mesh_delayed_replacement"):
                try:
                    success = func._mesh_delayed_replacement()
                    if success:
                        delattr(func, "_mesh_delayed_replacement")
                        logger.debug(
                            f"✅ Executed delayed mesh.tool injection replacement for {func.__name__}"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Failed to execute delayed replacement for {func.__name__}"
                        )
                except Exception as e:
                    logger.error(
                        f"Error executing delayed replacement for {func.__name__}: {e}"
                    )

            logger.debug(f"🔍 FastMCP decorated function result: {decorated}")
            return decorated

        return wrapper

    # Apply patches
    logger.info(
        f"🔧 PATCH_DEBUG: Original ToolManager.call_tool: {ToolManager.call_tool}"
    )
    ToolManager.call_tool = patched_call_tool
    logger.info(
        f"🔧 PATCH_DEBUG: Patched ToolManager.call_tool: {ToolManager.call_tool}"
    )
    FastMCP.tool = patched_tool
    _patched = True
    logger.info("FastMCP patched for dependency injection and server tracking")

    # Trigger decorator processing when FastMCP is patched (i.e., when server starts)
    _trigger_decorator_processing()


def unpatch_fastmcp():
    """Remove FastMCP patches (for testing)."""
    global _patched

    if not _patched:
        return

    if _original_call_tool:
        ToolManager.call_tool = _original_call_tool

    if _original_add_tool:
        try:
            from fastmcp import FastMCP
        except ImportError:
            try:
                from mcp.server.fastmcp import FastMCP
            except ImportError:
                pass

        if "FastMCP" in locals():
            FastMCP.tool = _original_add_tool

    _patched = False
    logger.info("FastMCP patches removed")


def _trigger_decorator_processing():
    """Trigger decorator processing in a background thread when no event loop is available."""
    try:
        # Try to get the running loop first
        loop = asyncio.get_running_loop()
        # Schedule processing on the current loop
        loop.create_task(_async_trigger_processing())
    except RuntimeError:
        # No event loop running - create a background thread to handle processing
        import threading
        import time

        def background_processor():
            """Run decorator processing in background thread."""
            global _background_loop
            time.sleep(2)  # Give time for all decorators to be registered
            try:
                # Import here to avoid circular imports
                from mcp_mesh import _runtime_processor

                if _runtime_processor is not None:
                    # Create new event loop for background processing
                    # Temporarily disable asyncio debug logging to avoid stdout issues
                    asyncio_logger = logging.getLogger("asyncio")
                    original_level = asyncio_logger.level
                    asyncio_logger.setLevel(logging.WARNING)

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    _background_loop = loop  # Store for shutdown coordination

                    # Restore asyncio logging level
                    asyncio_logger.setLevel(original_level)

                    logger.info("Background processor starting with new event loop")

                    async def process():
                        logger.info(
                            "Starting decorator processing in background thread"
                        )
                        result = await _runtime_processor.process_all_decorators()
                        logger.debug(f"Background processing result: {result}")

                        # Check if any health monitors were created
                        total_health_tasks = 0
                        if hasattr(_runtime_processor, "mesh_agent_processor"):
                            agent_health_tasks = (
                                _runtime_processor.mesh_agent_processor._health_tasks
                            )
                            total_health_tasks += len(agent_health_tasks)

                        if hasattr(_runtime_processor, "mesh_tool_processor"):
                            tool_health_tasks = (
                                _runtime_processor.mesh_tool_processor._health_tasks
                            )
                            total_health_tasks += len(tool_health_tasks)

                        logger.debug(
                            f"Health monitoring tasks created: {total_health_tasks}"
                        )

                        # Don't cleanup - let health monitors continue running

                    loop.run_until_complete(process())
                    # Keep the loop running for health monitoring
                    logger.info(
                        "🏁 Background decorator processing completed, keeping health monitors active"
                    )

                    # Check if auto-run is enabled and start keep-alive service
                    auto_run_enabled = _check_auto_run_enabled()
                    if auto_run_enabled:
                        logger.debug(
                            "🚀 Auto-run enabled - atexit handler will manage keep-alive service"
                        )
                        # Don't start auto-run here - let the atexit handler manage it for cleaner experience

                    # Only run forever if we have health tasks from either processor
                    has_health_tasks = False
                    if (
                        hasattr(_runtime_processor, "mesh_agent_processor")
                        and _runtime_processor.mesh_agent_processor._health_tasks
                    ):
                        has_health_tasks = True

                    if (
                        hasattr(_runtime_processor, "mesh_tool_processor")
                        and _runtime_processor.mesh_tool_processor._health_tasks
                    ):
                        has_health_tasks = True

                    if has_health_tasks:
                        logger.info(
                            "📍 Running event loop forever for health monitoring"
                        )

                        # Since we're in a background thread, we can't use signal handlers
                        # Instead, we'll just run the event loop and let the main thread
                        # handle signals and cleanup
                        try:
                            loop.run_forever()
                        except KeyboardInterrupt:
                            logger.info(
                                "🛑 Received shutdown signal, stopping health monitoring..."
                            )
                        finally:
                            # Schedule cleanup on the event loop
                            if not loop.is_closed():
                                try:
                                    loop.run_until_complete(
                                        _runtime_processor.cleanup()
                                    )
                                    logger.info(
                                        "✅ Health monitoring stopped gracefully"
                                    )
                                except Exception:
                                    # Ignore errors during shutdown (e.g., closed stdout)
                                    pass
                    else:
                        logger.warning(
                            "No health tasks created, not running event loop"
                        )

                    # Clean shutdown
                    loop.close()

            except Exception as e:
                logger.error(
                    f"Background decorator processing failed: {e}", exc_info=True
                )

        # Start background thread
        global _background_thread
        _background_thread = threading.Thread(target=background_processor, daemon=True)
        _background_thread.start()
        logger.info("Started background decorator processing thread")

        # Register shutdown handler in main thread
        # NOTE: Disabled atexit for container deployment - containers handle process lifecycle
        # import atexit
        # atexit.register(_cleanup_background_thread)


def _cleanup_background_thread():
    """Clean up the background thread and event loop."""
    global _background_loop, _background_thread

    try:
        if _background_loop and not _background_loop.is_closed():
            logger.info("Stopping background event loop...")
            # Stop the event loop from the main thread
            _background_loop.call_soon_threadsafe(_background_loop.stop)

        if _background_thread and _background_thread.is_alive():
            # Wait a bit for thread to finish
            _background_thread.join(timeout=2.0)
    except Exception:
        # Ignore errors during shutdown
        pass


def stop_background_event_loop():
    """Public function to stop the background event loop gracefully."""
    _cleanup_background_thread()


async def _async_trigger_processing():
    """Trigger processing asynchronously when event loop is available."""
    try:
        # Small delay to ensure all decorators are registered
        await asyncio.sleep(1)

        # Import here to avoid circular imports
        from mcp_mesh import _runtime_processor

        if _runtime_processor is not None:
            await _runtime_processor.process_all_decorators()
            logger.info("Triggered decorator processing on event loop")

    except Exception as e:
        logger.error(f"Async decorator processing failed: {e}")


def get_server_for_function(func_name: str) -> Any:
    """Get the FastMCP server instance for a function."""
    return _function_to_server.get(func_name)


def _check_auto_run_enabled() -> bool:
    """Check if auto-run is enabled in any @mesh.agent decorator."""
    try:
        from mcp_mesh.decorator_registry import DecoratorRegistry

        # Check @mesh.agent decorators for auto_run=True
        mesh_agents = DecoratorRegistry.get_mesh_agents()
        for _func_name, decorated_func in mesh_agents.items():
            metadata = decorated_func.metadata

            # Check environment variable first (takes precedence)
            import os

            env_auto_run = os.environ.get("MCP_MESH_AUTO_RUN", "").lower()
            if env_auto_run in ("true", "1", "yes"):
                logger.debug(
                    "🌐 Auto-run enabled via MCP_MESH_AUTO_RUN environment variable"
                )
                return True
            elif env_auto_run in ("false", "0", "no"):
                logger.debug(
                    "🌐 Auto-run disabled via MCP_MESH_AUTO_RUN environment variable"
                )
                return False

            # Check decorator parameter
            if metadata.get("auto_run", False):
                logger.debug("🎯 Auto-run enabled via @mesh.agent(auto_run=True)")
                return True

        return False

    except Exception as e:
        logger.error(f"Error checking auto-run status: {e}")
        return False


def _start_auto_run_keep_alive():
    """Start the auto-run keep-alive service in the background thread."""
    try:
        import os
        import signal
        import time

        from mcp_mesh.decorator_registry import DecoratorRegistry

        # Get configuration from @mesh.agent
        mesh_agents = DecoratorRegistry.get_mesh_agents()
        auto_run_interval = 10  # Default
        agent_name = "auto-run-service"  # Default

        for _func_name, decorated_func in mesh_agents.items():
            metadata = decorated_func.metadata

            # Get interval from environment variable or decorator
            env_interval = os.environ.get("MCP_MESH_AUTO_RUN_INTERVAL")
            if env_interval:
                try:
                    auto_run_interval = int(env_interval)
                    logger.debug(
                        f"🌐 Auto-run interval from environment: {auto_run_interval}s"
                    )
                except ValueError:
                    logger.warning(
                        f"Invalid MCP_MESH_AUTO_RUN_INTERVAL: {env_interval}, using default"
                    )
            else:
                auto_run_interval = metadata.get("auto_run_interval", 10)
                logger.debug(
                    f"🎯 Auto-run interval from decorator: {auto_run_interval}s"
                )

            # Get agent name
            agent_name = metadata.get("name", agent_name)
            break  # Use first agent config

        logger.info(
            f"💓 Starting auto-run keep-alive for '{agent_name}' with {auto_run_interval}s interval"
        )

        # Set up shutdown handling
        shutdown_requested = False

        def signal_handler(signum, frame):
            nonlocal shutdown_requested
            logger.info(
                f"🔴 Received shutdown signal {signum} for auto-run service '{agent_name}'"
            )
            shutdown_requested = True

        # Register signal handlers (only works in main thread, but we'll try)
        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except ValueError:
            # Not in main thread - can't register signal handlers
            logger.debug("Cannot register signal handlers from background thread")

        # Keep-alive loop
        heartbeat_count = 0
        logger.info(f"✅ Auto-run service '{agent_name}' is now running automatically")
        logger.info("🛑 Press Ctrl+C to stop the service")

        try:
            while not shutdown_requested:
                time.sleep(auto_run_interval)
                heartbeat_count += 1
                elapsed_time = heartbeat_count * auto_run_interval
                logger.info(
                    f"💓 Auto-run service '{agent_name}' heartbeat #{heartbeat_count} - running for {elapsed_time} seconds"
                )

        except KeyboardInterrupt:
            logger.info(
                f"🔴 Received KeyboardInterrupt for auto-run service '{agent_name}'"
            )
        finally:
            logger.info(f"🛑 Auto-run service '{agent_name}' shutting down gracefully")

    except Exception as e:
        logger.error(f"Error in auto-run keep-alive: {e}", exc_info=True)
