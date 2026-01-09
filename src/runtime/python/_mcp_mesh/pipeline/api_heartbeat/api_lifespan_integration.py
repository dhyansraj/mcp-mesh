"""
FastAPI lifespan integration for API heartbeat pipeline.

Handles the execution of API heartbeat as a background task
during FastAPI application lifespan for @mesh.route decorator services.

Uses the Rust core for registry communication.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def api_heartbeat_lifespan_task(heartbeat_config: dict[str, Any]) -> None:
    """
    API heartbeat task that runs in FastAPI lifespan.

    Uses Rust-backed heartbeat for registry communication.

    Args:
        heartbeat_config: Configuration containing service_id, interval,
                         and context for API heartbeat execution
    """
    service_id = heartbeat_config.get("service_id", "unknown-api-service")
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    # Check if running in standalone mode
    if standalone_mode:
        logger.info(
            f"💓 API heartbeat in standalone mode for service '{service_id}' "
            f"(no registry communication)"
        )
        return

    # Use Rust-backed heartbeat
    from .rust_api_heartbeat import rust_api_heartbeat_task

    logger.info(f"💓 Using Rust-backed heartbeat for API service '{service_id}'")
    await rust_api_heartbeat_task(heartbeat_config)


def create_api_lifespan_handler(heartbeat_config: dict[str, Any]) -> Any:
    """
    Create a FastAPI lifespan context manager that runs API heartbeat.

    Args:
        heartbeat_config: Configuration for API heartbeat execution

    Returns:
        Async context manager for FastAPI lifespan
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def api_lifespan(app):
        """FastAPI lifespan context manager with API heartbeat integration."""
        service_id = heartbeat_config.get("service_id", "unknown")
        logger.info(f"🚀 Starting FastAPI lifespan for service '{service_id}'")

        # Start API heartbeat task
        heartbeat_task = asyncio.create_task(
            api_heartbeat_lifespan_task(heartbeat_config)
        )

        try:
            # Yield control to FastAPI
            yield
        finally:
            # Cleanup: cancel heartbeat task
            logger.info(f"🛑 Shutting down FastAPI lifespan for service '{service_id}'")
            heartbeat_task.cancel()

            try:
                await heartbeat_task
            except asyncio.CancelledError:
                logger.info(
                    f"✅ API heartbeat task cancelled for service '{service_id}'"
                )

    return api_lifespan


def integrate_api_heartbeat_with_fastapi(
    fastapi_app: Any, heartbeat_config: dict[str, Any]
) -> None:
    """
    Integrate API heartbeat with FastAPI lifespan events.

    Args:
        fastapi_app: FastAPI application instance
        heartbeat_config: Configuration for heartbeat execution
    """
    service_id = heartbeat_config.get("service_id", "unknown")

    try:
        # Check if FastAPI app already has a lifespan handler
        existing_lifespan = getattr(fastapi_app, "router.lifespan_context", None)

        if existing_lifespan is not None:
            logger.warning(
                f"⚠️ FastAPI app already has lifespan handler - "
                f"API heartbeat integration may conflict for service '{service_id}'"
            )

        # Create and set the lifespan handler
        api_lifespan = create_api_lifespan_handler(heartbeat_config)
        fastapi_app.router.lifespan_context = api_lifespan

        logger.info(
            f"🔗 API heartbeat integrated with FastAPI lifespan for service '{service_id}'"
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to integrate API heartbeat with FastAPI lifespan "
            f"for service '{service_id}': {e}"
        )
        raise
