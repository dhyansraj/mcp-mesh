"""Factory functions for creating FastAPI lifespan context managers.

Provides clean separation of lifespan creation logic from FastAPI app setup.
Handles single FastMCP, multiple FastMCP, and minimal (no FastMCP) scenarios.

Phase 1 MeshJob substrate (#bug 2 — backup path)
------------------------------------------------

Each lifespan also tries to start the MeshJob claim dispatchers stashed
by :class:`JobsClaimWorkersStep` on ``app.state.mesh_claim_dispatchers``.

This is a *backup* startup path — the *primary* path is in
:func:`_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat.rust_heartbeat_task`
which starts the dispatchers on the long-lived heartbeat-thread loop.
The backup matters for non-immediate-uvicorn flows where the
lifespan-factory app *is* the serving app and the lifespan startup
section runs *after* the pipeline has stashed dispatchers on
``app.state``.

For the immediate-uvicorn flow this code path is effectively dead
weight (the immediate-uvicorn FastAPI app uses its own FastMCP
lifespan, not the lifespan-factory one), but
:meth:`PythonClaimDispatcher.start` is idempotent so leaving it in
place is harmless.
"""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


def _start_claim_dispatchers(app: Any) -> list:
    """Start any claim dispatchers stashed on ``app.state``.

    Called from inside the lifespan (so the dispatchers run on the
    persistent uvicorn loop). Returns the list of started dispatchers
    so the lifespan can stop them on shutdown.
    """
    dispatchers = []
    try:
        dispatchers = list(getattr(app.state, "mesh_claim_dispatchers", []) or [])
    except Exception as e:
        logger.debug("lifespan: could not read mesh_claim_dispatchers (%s)", e)
        return []

    if not dispatchers:
        return []

    started: list = []
    for d in dispatchers:
        try:
            d.start()
            started.append(d)
        except Exception as e:
            logger.warning(
                "lifespan: failed to start claim dispatcher for capability=%s: %s",
                getattr(d, "capability", "?"),
                e,
            )
    if started:
        logger.info(
            "📨 lifespan: started %d MeshJob claim dispatcher(s) on uvicorn loop",
            len(started),
        )
    return started


async def _stop_claim_dispatchers(dispatchers: list) -> None:
    """Best-effort shutdown of claim dispatchers started by the lifespan."""
    for d in dispatchers:
        try:
            await d.stop()
        except Exception as e:
            logger.warning(
                "lifespan: error stopping claim dispatcher for capability=%s: %s",
                getattr(d, "capability", "?"),
                e,
            )


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

        # Phase 1 MeshJob substrate: start claim dispatchers on the
        # persistent uvicorn loop (not the one-shot startup loop).
        claim_dispatchers = _start_claim_dispatchers(app)

        try:
            yield
        finally:
            await _stop_claim_dispatchers(claim_dispatchers)
            ctx = get_shutdown_context()
            await _perform_registry_cleanup(
                ctx.get("registry_url"),
                ctx.get("agent_id"),
            )
            # Close pooled HTTP clients before FastMCP lifespan exits
            try:
                from ...engine.unified_mcp_proxy import close_connection_pools

                await close_connection_pools()
            except Exception as e:
                logger.warning(f"Error closing connection pools: {e}")
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

        # Phase 1 MeshJob substrate: see single-fastmcp lifespan note.
        claim_dispatchers = _start_claim_dispatchers(app)

        try:
            yield
        finally:
            await _stop_claim_dispatchers(claim_dispatchers)
            ctx = get_shutdown_context()
            await _perform_registry_cleanup(
                ctx.get("registry_url"),
                ctx.get("agent_id"),
            )
            # Close pooled HTTP clients before FastMCP lifespans exit
            try:
                from ...engine.unified_mcp_proxy import close_connection_pools

                await close_connection_pools()
            except Exception as e:
                logger.warning(f"Error closing connection pools: {e}")
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
        # Phase 1 MeshJob substrate: see single-fastmcp lifespan note.
        claim_dispatchers = _start_claim_dispatchers(app)
        try:
            yield
        finally:
            await _stop_claim_dispatchers(claim_dispatchers)
            ctx = get_shutdown_context()
            await _perform_registry_cleanup(
                ctx.get("registry_url"),
                ctx.get("agent_id"),
            )
            # Close pooled HTTP clients
            try:
                from ...engine.unified_mcp_proxy import close_connection_pools

                await close_connection_pools()
            except Exception as e:
                logger.warning(f"Error closing connection pools: {e}")

    return lifespan
