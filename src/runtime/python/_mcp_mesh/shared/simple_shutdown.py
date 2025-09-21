"""
Simple shutdown coordination for MCP Mesh agents.

Provides clean shutdown via FastAPI lifespan events and basic signal handling.
"""

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SimpleShutdownCoordinator:
    """Lightweight shutdown coordination using FastAPI lifespan."""

    def __init__(self):
        self._shutdown_requested = False
        self._registry_url: Optional[str] = None
        self._agent_id: Optional[str] = None
        self._shutdown_complete = False  # Flag to prevent race conditions

    def set_shutdown_context(self, registry_url: str, agent_id: str) -> None:
        """Set context for shutdown cleanup."""
        self._registry_url = registry_url
        self._agent_id = agent_id
        logger.debug(
            f"🔧 Shutdown context set: agent_id={agent_id}, registry_url={registry_url}"
        )

    def install_signal_handlers(self) -> None:
        """Install minimal signal handlers as backup."""

        def shutdown_signal_handler(signum, frame):
            # Avoid logging in signal handler to prevent reentrant call issues
            self._shutdown_requested = True

        signal.signal(signal.SIGINT, shutdown_signal_handler)
        signal.signal(signal.SIGTERM, shutdown_signal_handler)
        logger.debug("📡 Signal handlers installed")

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown was requested via signal."""
        return self._shutdown_requested

    def is_shutdown_complete(self) -> bool:
        """Check if shutdown cleanup is complete."""
        return self._shutdown_complete

    def mark_shutdown_complete(self) -> None:
        """Mark shutdown cleanup as complete to prevent further operations."""
        self._shutdown_complete = True
        logger.debug("🏁 Shutdown marked as complete")

    async def perform_registry_cleanup(self) -> None:
        """Perform registry cleanup by calling DELETE /agents/{agent_id}."""
        # Try to get the actual agent_id from DecoratorRegistry if available
        actual_agent_id = self._agent_id
        try:
            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            agent_config = DecoratorRegistry.get_resolved_agent_config()
            if agent_config and "agent_id" in agent_config:
                resolved_agent_id = agent_config["agent_id"]
                if resolved_agent_id and resolved_agent_id != "unknown":
                    actual_agent_id = resolved_agent_id
                    logger.debug(
                        f"🔧 Using resolved agent_id from DecoratorRegistry: {actual_agent_id}"
                    )
        except Exception as e:
            logger.debug(f"Could not get agent_id from DecoratorRegistry: {e}")

        if (
            not self._registry_url
            or not actual_agent_id
            or actual_agent_id == "unknown"
        ):
            logger.warning(
                f"⚠️ Missing registry URL or agent ID for cleanup: registry_url={self._registry_url}, agent_id={actual_agent_id}"
            )
            return

        try:
            from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import (
                ApiClient,
            )
            from _mcp_mesh.generated.mcp_mesh_registry_client.configuration import (
                Configuration,
            )
            from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper

            config = Configuration(host=self._registry_url)
            api_client = ApiClient(configuration=config)
            registry_wrapper = RegistryClientWrapper(api_client)

            success = await registry_wrapper.unregister_agent(actual_agent_id)
            if success:
                logger.info(f"✅ Agent '{actual_agent_id}' unregistered from registry")
                self.mark_shutdown_complete()
            else:
                logger.warning(f"⚠️ Failed to unregister agent '{actual_agent_id}'")
                self.mark_shutdown_complete()  # Mark complete even on failure to prevent loops

        except Exception as e:
            logger.error(f"❌ Registry cleanup error: {e}")
            self.mark_shutdown_complete()  # Mark complete even on error to prevent loops

    def create_shutdown_lifespan(self, original_lifespan=None):
        """Create lifespan function that includes registry cleanup."""

        @asynccontextmanager
        async def shutdown_lifespan(app):
            # Startup phase
            if original_lifespan:
                # If user had a lifespan, run their startup code
                async with original_lifespan(app):
                    yield
            else:
                yield

            # Shutdown phase
            logger.info("🔄 FastAPI shutdown initiated, performing registry cleanup...")
            await self.perform_registry_cleanup()
            logger.info("🏁 Registry cleanup completed")

        return shutdown_lifespan

    def inject_shutdown_lifespan(self, app, registry_url: str, agent_id: str) -> None:
        """Inject shutdown lifespan into FastAPI app."""
        self.set_shutdown_context(registry_url, agent_id)

        # Store original lifespan if it exists
        original_lifespan = getattr(app, "router", {}).get("lifespan", None)

        # Replace with our shutdown-aware lifespan
        new_lifespan = self.create_shutdown_lifespan(original_lifespan)
        app.router.lifespan = new_lifespan

        logger.info(f"🔌 Shutdown lifespan injected for agent '{agent_id}'")


# Global instance
_simple_shutdown_coordinator = SimpleShutdownCoordinator()


def inject_shutdown_lifespan(app, registry_url: str, agent_id: str) -> None:
    """Inject shutdown lifespan into FastAPI app (module-level function)."""
    _simple_shutdown_coordinator.inject_shutdown_lifespan(app, registry_url, agent_id)


def install_signal_handlers() -> None:
    """Install signal handlers (module-level function)."""
    _simple_shutdown_coordinator.install_signal_handlers()


def should_stop_heartbeat() -> bool:
    """Check if heartbeat should stop due to shutdown."""
    return _simple_shutdown_coordinator.is_shutdown_complete()


def start_blocking_loop_with_shutdown_support(thread) -> None:
    """
    Keep main thread alive while uvicorn in the thread handles requests.

    Install signal handlers in main thread for proper registry cleanup since
    signals to threads can be unreliable for FastAPI lifespan shutdown.
    """
    logger.info("🔒 MAIN THREAD: Installing signal handlers for registry cleanup")

    # Install signal handlers for proper registry cleanup
    _simple_shutdown_coordinator.install_signal_handlers()

    logger.info(
        "🔒 MAIN THREAD: Waiting for uvicorn thread - signals handled by main thread"
    )

    try:
        # Wait for thread while handling signals in main thread
        while thread.is_alive():
            thread.join(timeout=1.0)

            # Check if shutdown was requested via signal
            if _simple_shutdown_coordinator.is_shutdown_requested():
                logger.info(
                    "🔄 MAIN THREAD: Shutdown requested, performing registry cleanup..."
                )

                # Perform registry cleanup in main thread
                import asyncio

                try:
                    # Run cleanup in main thread
                    asyncio.run(_simple_shutdown_coordinator.perform_registry_cleanup())
                except Exception as e:
                    logger.error(f"❌ Registry cleanup error: {e}")

                logger.info("🏁 MAIN THREAD: Registry cleanup completed, exiting")
                break

    except KeyboardInterrupt:
        logger.info(
            "🔄 MAIN THREAD: KeyboardInterrupt received, performing registry cleanup..."
        )

        # Perform registry cleanup on Ctrl+C
        import asyncio

        try:
            asyncio.run(_simple_shutdown_coordinator.perform_registry_cleanup())
        except Exception as e:
            logger.error(f"❌ Registry cleanup error: {e}")

        logger.info("🏁 MAIN THREAD: Registry cleanup completed")

    logger.info("🏁 MAIN THREAD: Uvicorn thread completed")
