"""
FastAPI lifespan integration for A2A heartbeat pipeline.

Mirrors ``api_heartbeat/api_lifespan_integration.py`` for the A2A flow.
Wires the ``rust_a2a_heartbeat_task`` as a FastAPI lifespan background
task so the user's ``uvicorn.run(app)`` automatically participates in
the mesh's heartbeat round-trips.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def a2a_heartbeat_lifespan_task(heartbeat_config: dict[str, Any]) -> None:
    """
    A2A heartbeat task that runs in FastAPI lifespan.

    Uses Rust-backed heartbeat for registry communication.

    Args:
        heartbeat_config: Configuration containing service_id, interval,
                         and context (with ``a2a_surfaces``) for A2A heartbeat.
    """
    service_id = heartbeat_config.get("service_id", "unknown-a2a-service")
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    if standalone_mode:
        logger.info(
            f"💓 A2A heartbeat in standalone mode for service '{service_id}' "
            "(no registry communication)"
        )
        return

    from .rust_a2a_heartbeat import rust_a2a_heartbeat_task

    logger.info(f"💓 Using Rust-backed heartbeat for A2A service '{service_id}'")
    await rust_a2a_heartbeat_task(heartbeat_config)


def create_a2a_lifespan_handler(heartbeat_config: dict[str, Any]) -> Any:
    """
    Create a FastAPI lifespan context manager that runs A2A heartbeat.

    Args:
        heartbeat_config: Configuration for A2A heartbeat execution

    Returns:
        Async context manager for FastAPI lifespan
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def a2a_lifespan(app):
        """FastAPI lifespan context manager with A2A heartbeat integration."""
        service_id = heartbeat_config.get("service_id", "unknown")
        logger.info(f"🚀 Starting FastAPI lifespan for A2A service '{service_id}'")

        heartbeat_task = asyncio.create_task(
            a2a_heartbeat_lifespan_task(heartbeat_config)
        )

        try:
            yield
        finally:
            logger.info(
                f"🛑 Shutting down FastAPI lifespan for A2A service '{service_id}'"
            )
            heartbeat_task.cancel()

            try:
                await heartbeat_task
            except asyncio.CancelledError:
                logger.info(
                    f"✅ A2A heartbeat task cancelled for service '{service_id}'"
                )

    return a2a_lifespan


def integrate_a2a_heartbeat_with_fastapi(
    fastapi_app: Any, heartbeat_config: dict[str, Any]
) -> None:
    """
    Integrate A2A heartbeat with FastAPI lifespan events.

    Args:
        fastapi_app: FastAPI application instance
        heartbeat_config: Configuration for heartbeat execution
    """
    service_id = heartbeat_config.get("service_id", "unknown")

    try:
        # ``getattr(fastapi_app, "router.lifespan_context", None)`` does NOT
        # traverse dotted attribute names — it looks for a single attribute
        # literally called ``"router.lifespan_context"`` and finds nothing,
        # silently clobbering any user-supplied lifespan. Walk the dotted
        # path explicitly so a pre-existing user lifespan is detected and
        # composed with ours instead of being replaced.
        existing_router = getattr(fastapi_app, "router", None)
        existing_lifespan = (
            getattr(existing_router, "lifespan_context", None)
            if existing_router is not None
            else None
        )

        a2a_lifespan = create_a2a_lifespan_handler(heartbeat_config)

        if existing_lifespan is not None:
            from contextlib import asynccontextmanager

            logger.warning(
                f"⚠️ FastAPI app already has lifespan handler - "
                f"composing A2A heartbeat with user's lifespan for service '{service_id}'"
            )

            @asynccontextmanager
            async def composed_lifespan(app):
                # Enter user's lifespan first, then ours; reverse on exit so
                # the user's resources outlive the heartbeat task and we
                # don't tear down the registry connection while user code
                # still expects it.
                async with existing_lifespan(app):
                    async with a2a_lifespan(app):
                        yield

            fastapi_app.router.lifespan_context = composed_lifespan
        else:
            fastapi_app.router.lifespan_context = a2a_lifespan

        logger.info(
            f"🔗 A2A heartbeat integrated with FastAPI lifespan for service '{service_id}'"
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to integrate A2A heartbeat with FastAPI lifespan "
            f"for service '{service_id}': {e}"
        )
        raise
