"""
Integration with FastMCP to enable dependency injection.

This module monkey-patches FastMCP's tool execution to support our dependency injection.
"""

import asyncio
import logging
from typing import Any

from mcp.server.fastmcp.tools import ToolManager

from .dependency_injector import get_global_injector

logger = logging.getLogger(__name__)

# Store original methods
_original_call_tool = None
_patched = False


def patch_fastmcp():
    """Monkey-patch FastMCP to support dependency injection."""
    global _original_call_tool, _patched

    if _patched:
        return

    # Store original method
    _original_call_tool = ToolManager.call_tool

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

        # Call original with potentially modified arguments
        return await _original_call_tool(self, name, arguments, context=context)

    # Apply patch
    ToolManager.call_tool = patched_call_tool
    _patched = True
    logger.info("FastMCP patched for dependency injection support")

    # Trigger decorator processing when FastMCP is patched (i.e., when server starts)
    _trigger_decorator_processing()


def unpatch_fastmcp():
    """Remove FastMCP patches (for testing)."""
    global _patched

    if not _patched:
        return

    if _original_call_tool:
        ToolManager.call_tool = _original_call_tool

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
            time.sleep(2)  # Give time for all decorators to be registered
            try:
                # Import here to avoid circular imports
                from mcp_mesh import _runtime_processor

                if _runtime_processor is not None:
                    # Create new event loop for background processing
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    logger.info("Background processor starting with new event loop")

                    async def process():
                        logger.info(
                            "Starting decorator processing in background thread"
                        )
                        result = await _runtime_processor.process_all_decorators()
                        logger.info(f"Background processing result: {result}")

                        # Check if any health monitors were created
                        if hasattr(_runtime_processor, "mesh_agent_processor"):
                            health_tasks = (
                                _runtime_processor.mesh_agent_processor._health_tasks
                            )
                            logger.info(
                                f"Health monitoring tasks created: {len(health_tasks)}"
                            )

                        # Don't cleanup - let health monitors continue running

                    loop.run_until_complete(process())
                    # Keep the loop running for health monitoring
                    logger.info(
                        "Background decorator processing completed, keeping health monitors active"
                    )

                    # Only run forever if we have health tasks
                    if (
                        hasattr(_runtime_processor, "mesh_agent_processor")
                        and _runtime_processor.mesh_agent_processor._health_tasks
                    ):
                        logger.info("Running event loop forever for health monitoring")
                        loop.run_forever()
                    else:
                        logger.warning(
                            "No health tasks created, not running event loop"
                        )
                        loop.close()

            except Exception as e:
                logger.error(
                    f"Background decorator processing failed: {e}", exc_info=True
                )

        # Start background thread
        thread = threading.Thread(target=background_processor, daemon=True)
        thread.start()
        logger.info("Started background decorator processing thread")


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
