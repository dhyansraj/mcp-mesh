"""
Graceful Shutdown Manager for MCP Mesh agents.

This utility class manages graceful shutdown functionality, including signal handlers,
shutdown context management, and coordination with FastAPI lifecycle and registry.
"""

import asyncio
import logging
import os
import signal
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GracefulShutdownManager:
    """Manages graceful shutdown for MCP Mesh agents."""

    def __init__(self):
        self._shutdown_requested: bool = False
        self._shutdown_context: dict[str, Any] = {}

    def set_shutdown_context(self, context: dict[str, Any]) -> None:
        """Set context for graceful shutdown (called from pipeline)."""
        self._shutdown_context.update(context)

        # Extract FastAPI app from context for coordinated shutdown
        fastapi_app = context.get("fastapi_app")
        if fastapi_app:
            self._shutdown_context["fastapi_app"] = fastapi_app
            logger.debug(
                f"🔧 FastAPI app stored for coordinated shutdown: {type(fastapi_app)}"
            )

        logger.debug(
            f"🔧 Shutdown context updated: agent_id={context.get('agent_id')}, registry_url={context.get('registry_url')}"
        )

    def install_signal_handlers(self) -> None:
        """Install signal handlers that set the shutdown flag."""

        def shutdown_signal_handler(signum, frame):
            """Handle shutdown signals by setting the shutdown flag."""
            logger.info(
                f"🚨 SIGNAL HANDLER: Received signal {signum}, setting shutdown flag"
            )
            self._shutdown_requested = True

        # Install handlers for common termination signals
        signal.signal(signal.SIGTERM, shutdown_signal_handler)
        signal.signal(signal.SIGINT, shutdown_signal_handler)

        logger.info("🛡️ Signal handlers installed for graceful shutdown")

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested

    def perform_graceful_shutdown_from_main_thread(self) -> None:
        """Perform graceful shutdown from main thread (non-async context)."""
        try:
            # Check if we have FastAPI app for coordinated shutdown
            fastapi_app = self._shutdown_context.get("fastapi_app")

            if (
                fastapi_app
                and hasattr(fastapi_app, "state")
                and hasattr(fastapi_app.state, "shutdown_step")
            ):
                # Use FastAPI lifespan shutdown mechanism
                logger.info("🚨 Triggering coordinated FastAPI shutdown...")
                shutdown_step = fastapi_app.state.shutdown_step

                # Create minimal context and call the existing graceful shutdown
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                try:
                    loop.run_until_complete(
                        shutdown_step._graceful_shutdown(fastapi_app)
                    )
                    logger.info("✅ FastAPI coordinated shutdown completed")
                    return
                finally:
                    loop.close()

            # Fallback: Direct registry call if no FastAPI coordination available
            logger.info("🚨 Using fallback direct registry shutdown...")

            # Get registry_url from context or environment (with default)
            registry_url = self._shutdown_context.get("registry_url")
            if not registry_url:
                registry_url = os.getenv(
                    "MCP_MESH_REGISTRY_URL", "http://localhost:8000"
                )
                logger.debug(
                    f"🔧 Using registry URL from environment/default: {registry_url}"
                )

            # Get agent_id from context or generate the same one used for registration
            agent_id = self._shutdown_context.get("agent_id")
            if not agent_id:
                agent_id = self._get_or_create_agent_id()
                logger.debug(f"🔧 Using agent ID from shared state: {agent_id}")

            if not registry_url or not agent_id:
                logger.warning(
                    f"⚠️ Cannot perform graceful shutdown: missing registry_url={registry_url} or agent_id={agent_id}"
                )
                return

            # Create registry client and perform shutdown synchronously
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                loop.run_until_complete(
                    self._perform_graceful_shutdown_async(registry_url, agent_id)
                )
            finally:
                loop.close()

        except Exception as e:
            logger.error(f"❌ Graceful shutdown error: {e}")

    async def _perform_graceful_shutdown_async(
        self, registry_url: str, agent_id: str
    ) -> None:
        """Async graceful shutdown implementation."""
        try:
            # Create registry client for shutdown
            from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import (
                ApiClient,
            )
            from _mcp_mesh.generated.mcp_mesh_registry_client.configuration import (
                Configuration,
            )
            from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper

            config = Configuration(host=registry_url)
            api_client = ApiClient(configuration=config)
            registry_wrapper = RegistryClientWrapper(api_client)

            # Perform graceful unregistration (this sends DELETE /heartbeats)
            success = await registry_wrapper.unregister_agent(agent_id)
            if success:
                logger.info(
                    f"✅ Agent '{agent_id}' successfully unregistered from registry"
                )
            else:
                logger.warning(
                    f"⚠️ Failed to unregister agent '{agent_id}' from registry"
                )

        except Exception as e:
            logger.error(f"❌ Graceful shutdown error: {e}")

    def _get_or_create_agent_id(self) -> str:
        """Get agent ID using the existing decorator registry function."""
        from mesh.decorators import _get_or_create_agent_id

        return _get_or_create_agent_id()

    def start_blocking_loop_with_shutdown_support(self, thread) -> None:
        """
        Start the main thread blocking loop with graceful shutdown support.

        This keeps the main thread alive while monitoring for shutdown signals
        and maintaining the server thread.
        """
        logger.info(
            "🔒 MAIN THREAD: Blocking to keep alive (prevents threading shutdown state)"
        )

        # Install signal handlers
        self.install_signal_handlers()

        try:
            while True:
                # Check shutdown flag (set by signal handlers)
                if self.is_shutdown_requested():
                    logger.info(
                        "🚨 MAIN THREAD: Shutdown requested, performing graceful cleanup..."
                    )
                    self.perform_graceful_shutdown_from_main_thread()
                    break

                if thread.is_alive():
                    thread.join(timeout=1)  # Check every second
                else:
                    logger.warning("⚠️ Server thread died, exiting...")
                    break
        except KeyboardInterrupt:
            logger.info("👋 MAIN THREAD: Received interrupt, shutting down gracefully")
            self.perform_graceful_shutdown_from_main_thread()
        except Exception as e:
            logger.error(f"❌ MAIN THREAD: Error in blocking loop: {e}")

        logger.info("🏁 MAIN THREAD: Exiting blocking loop")


# Global instance for backward compatibility with existing decorators.py usage
_global_shutdown_manager = GracefulShutdownManager()


def get_global_shutdown_manager() -> GracefulShutdownManager:
    """Get the global shutdown manager instance."""
    return _global_shutdown_manager


# Convenience functions for backward compatibility
def set_shutdown_context(context: dict[str, Any]) -> None:
    """Set context for graceful shutdown (global convenience function)."""
    _global_shutdown_manager.set_shutdown_context(context)


def install_graceful_shutdown_handlers() -> None:
    """Install signal handlers that set the shutdown flag (global convenience function)."""
    _global_shutdown_manager.install_signal_handlers()


def is_shutdown_requested() -> bool:
    """Check if shutdown has been requested (global convenience function)."""
    return _global_shutdown_manager.is_shutdown_requested()


def perform_graceful_shutdown_from_main_thread() -> None:
    """Perform graceful shutdown from main thread (global convenience function)."""
    _global_shutdown_manager.perform_graceful_shutdown_from_main_thread()


def start_blocking_loop_with_shutdown_support(thread) -> None:
    """Start the main thread blocking loop with graceful shutdown support (global convenience function)."""
    _global_shutdown_manager.start_blocking_loop_with_shutdown_support(thread)
