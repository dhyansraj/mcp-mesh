"""Factory functions for creating FastAPI lifespan context managers.

Provides clean separation of lifespan creation logic from FastAPI app setup.
Handles single FastMCP, multiple FastMCP, and minimal (no FastMCP) scenarios.
"""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


async def _perform_registry_cleanup(
    registry_url: str | None,
    agent_id: str | None,
) -> None:
    """
    Unregister agent from registry during shutdown.

    Skips cleanup if registry_url or agent_id is missing - this indicates
    the agent never connected to registry and is running in standalone mode.
    """
    if not registry_url or not agent_id or agent_id == "unknown":
        logger.debug(
            f"Skipping registry cleanup: registry_url={registry_url}, agent_id={agent_id}"
        )
        return

    try:
        from ...shared.simple_shutdown import _simple_shutdown_coordinator

        _simple_shutdown_coordinator.set_shutdown_context(registry_url, agent_id)
        await _simple_shutdown_coordinator.perform_registry_cleanup()
    except Exception as e:
        logger.error(f"Registry cleanup error: {e}")


def create_single_fastmcp_lifespan(
    fastmcp_lifespan: Callable,
    get_shutdown_context: Callable[[], dict[str, Any]],
) -> Callable:
    """
    Create lifespan for single FastMCP server.

    Args:
        fastmcp_lifespan: The lifespan context manager from FastMCP app
        get_shutdown_context: Callback to get registry_url and agent_id at shutdown time
    """

    @asynccontextmanager
    async def lifespan(app):
        fastmcp_ctx = None
        try:
            fastmcp_ctx = fastmcp_lifespan(app)
            await fastmcp_ctx.__aenter__()
            logger.debug("Started FastMCP lifespan")
        except Exception as e:
            logger.error(f"Failed to start FastMCP lifespan: {e}")

        try:
            yield
        finally:
            ctx = get_shutdown_context()
            await _perform_registry_cleanup(
                ctx.get("registry_url"),
                ctx.get("agent_id"),
            )
            if fastmcp_ctx:
                try:
                    await fastmcp_ctx.__aexit__(None, None, None)
                    logger.debug("FastMCP lifespan stopped")
                except Exception as e:
                    logger.warning(f"Error closing FastMCP lifespan: {e}")

    return lifespan


def create_multiple_fastmcp_lifespan(
    fastmcp_lifespans: list[Callable],
    get_shutdown_context: Callable[[], dict[str, Any]],
) -> Callable:
    """
    Create combined lifespan for multiple FastMCP servers.

    Args:
        fastmcp_lifespans: List of lifespan context managers from FastMCP apps
        get_shutdown_context: Callback to get registry_url and agent_id at shutdown time
    """

    @asynccontextmanager
    async def lifespan(app):
        lifespan_contexts = []
        for ls in fastmcp_lifespans:
            try:
                ctx = ls(app)
                await ctx.__aenter__()
                lifespan_contexts.append(ctx)
            except Exception as e:
                logger.error(f"Failed to start FastMCP lifespan: {e}")

        try:
            yield
        finally:
            ctx = get_shutdown_context()
            await _perform_registry_cleanup(
                ctx.get("registry_url"),
                ctx.get("agent_id"),
            )
            # Exit in reverse order (LIFO) for proper cleanup
            for lctx in reversed(lifespan_contexts):
                try:
                    await lctx.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Error closing FastMCP lifespan: {e}")

    return lifespan


def create_minimal_lifespan(
    get_shutdown_context: Callable[[], dict[str, Any]],
) -> Callable:
    """
    Create minimal lifespan for graceful shutdown only (no FastMCP servers).

    Args:
        get_shutdown_context: Callback to get registry_url and agent_id at shutdown time
    """

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            ctx = get_shutdown_context()
            await _perform_registry_cleanup(
                ctx.get("registry_url"),
                ctx.get("agent_id"),
            )

    return lifespan
