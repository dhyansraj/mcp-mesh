"""
Simple shutdown coordination for MCP Mesh agents.

Provides clean shutdown via FastAPI lifespan events and basic signal handling.
The Rust core handles actual deregistration from the registry.
"""

import logging
import signal
from contextlib import asynccontextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SimpleShutdownCoordinator:
    """Lightweight shutdown coordination using FastAPI lifespan.

    The Rust core handles registry deregistration automatically when
    handle.shutdown() is called. This coordinator just manages the
    shutdown signal flow between Python and Rust.
    """

    def __init__(self):
        self._shutdown_requested = False
        self._registry_url: Optional[str] = None
        self._agent_id: Optional[str] = None
        self._shutdown_complete = False  # Flag to prevent race conditions

    def set_shutdown_context(self, registry_url: str, agent_id: str) -> None:
        """Set context for shutdown (used for logging)."""
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

    def request_shutdown(self) -> None:
        """Request shutdown (called when lifespan exits)."""
        self._shutdown_requested = True
        agent_id = self._agent_id or "<unknown>"
        logger.info(f"🔄 Shutdown requested for agent '{agent_id}'")

    def create_shutdown_lifespan(self, original_lifespan=None):
        """Create lifespan function that signals shutdown on exit.

        The Rust core will handle actual deregistration when it receives
        the shutdown signal via handle.shutdown().
        """
        # Capture agent_id at creation time with fallback for None
        agent_id = self._agent_id or "<unknown>"

        @asynccontextmanager
        async def shutdown_lifespan(app):
            # Startup phase
            if original_lifespan:
                # If user had a lifespan, run their startup code
                async with original_lifespan(app):
                    yield
            else:
                yield

            # Shutdown phase - just signal, Rust handles deregistration
            logger.info(
                f"🔄 FastAPI shutdown initiated for agent '{agent_id}', "
                "Rust core will handle deregistration"
            )
            self.request_shutdown()
            self.mark_shutdown_complete()
            logger.info("🏁 Shutdown signaled")

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

    Install signal handlers in main thread for proper shutdown signaling since
    signals to threads can be unreliable for FastAPI lifespan shutdown.

    Note: The Rust core handles registry deregistration automatically when
    handle.shutdown() is called from the heartbeat task.
    """
    logger.info("🔒 MAIN THREAD: Installing signal handlers")

    # Install signal handlers
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
                    "🔄 MAIN THREAD: Shutdown requested, signaling heartbeat to stop..."
                )
                # Mark shutdown complete so heartbeat task will call handle.shutdown()
                # which triggers Rust core to deregister from registry
                _simple_shutdown_coordinator.mark_shutdown_complete()
                logger.info(
                    "🏁 MAIN THREAD: Shutdown signaled, Rust core will handle deregistration"
                )
                break

    except KeyboardInterrupt:
        logger.info("🔄 MAIN THREAD: KeyboardInterrupt received, signaling shutdown...")
        _simple_shutdown_coordinator.mark_shutdown_complete()
        logger.info(
            "🏁 MAIN THREAD: Shutdown signaled, Rust core will handle deregistration"
        )

    logger.info("🏁 MAIN THREAD: Uvicorn thread completed")
