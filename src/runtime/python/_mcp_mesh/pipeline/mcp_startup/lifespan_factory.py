"""Factory functions for creating FastAPI lifespan context managers.

Provides clean separation of lifespan creation logic from FastAPI app setup.
Handles single FastMCP, multiple FastMCP, and minimal (no FastMCP) scenarios.

Lifespan / user-loop hijack (v2.3, issue #1061)
-----------------------------------------------

The :func:`wrap_lifespan_for_user_loop` helper is the *single* entry point
that wraps a user-supplied lifespan so its body runs on the user loop
(worker-0 of the tool_executor pool). Tools and lifespan therefore share
the same asyncio loop, so loop-bound resources (``asyncpg.Pool``,
``redis.asyncio.Redis``, ``aiohttp.ClientSession``) created during lifespan
startup are safely usable from tool bodies. Both wrap sites
(:mod:`_mcp_mesh.pipeline.mcp_startup.lifespan_factory` and
:mod:`mesh.decorators` ``_start_uvicorn_immediately``) call this helper —
the hijack logic lives in exactly one place.

If you hit a problem with this hijack (e.g., an exotic lifespan that uses
contextvars in a non-PEP-567-compatible way, or a third-party library that
captures the loop ref at module import), the recommended escape is to STOP
using FastMCP/FastAPI ``lifespan=`` for loop-bound resources and switch to
mesh-native startup hooks: ``@mesh.on_startup`` / ``@mesh.on_shutdown``
(planned for a future minor release). These hooks run on the user loop
natively and don't depend on uvicorn's lifespan invocation pattern.

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
``app.state``. For the immediate-uvicorn flow this code path is
effectively dead weight (the immediate-uvicorn FastAPI app uses its own
FastMCP lifespan, not the lifespan-factory one), but
:meth:`PythonClaimDispatcher.start` is idempotent so leaving it in
place is harmless.
"""

import asyncio
import contextvars
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


def _log_hijack_startup_failure(exc: BaseException) -> None:
    """Warn when the user-loop hijack fails to enter the user lifespan.

    ``exc`` IS the user's ``__aenter__`` failure (or a framework-side
    abort before enter completed), which is what the caller re-raises.
    """
    logger.warning(
        "Lifespan hijack failed during startup __aenter__ on the user loop. "
        "Re-raising the user exception below. If this keeps happening, "
        "consider moving loop-bound resource init (asyncpg.Pool, redis, "
        "aiohttp.ClientSession) out of FastMCP/FastAPI lifespan and using "
        "@mesh.on_startup / @mesh.on_shutdown hooks (planned for a future "
        "release). Original exception: %s",
        type(exc).__name__ + ": " + str(exc),
    )


def _log_hijack_shutdown_failure(exit_exc: BaseException) -> None:
    """Warn when the user-loop hijack fails during ``__aexit__``.

    ``exit_exc`` is the failure of ``__aexit__`` OR a framework-side
    abort (e.g., uvicorn shutdown timeout cancelling our wait). It is
    NOT necessarily the user's original body exception — the body
    exception (if any) is preserved as ``__context__`` of ``exit_exc``
    when we re-raise.
    """
    logger.warning(
        "Lifespan hijack failed during shutdown __aexit__ on the user loop. "
        "The framework will re-raise the exit-side exception; the user's "
        "original body exception (if any) is preserved as the __context__. "
        "If this keeps happening, consider moving loop-bound resource init "
        "(asyncpg.Pool, redis, aiohttp.ClientSession) out of FastMCP/FastAPI "
        "lifespan and using @mesh.on_startup / @mesh.on_shutdown hooks "
        "(planned for a future release). Exit exception: %s",
        type(exit_exc).__name__ + ": " + str(exit_exc),
    )


def wrap_lifespan_for_user_loop(user_lifespan: Callable) -> Callable:
    """Wrap a user-supplied lifespan so its body runs on the user loop.

    The user's ``lifespan`` is the right place to construct loop-bound
    resources (``asyncpg.Pool``, ``redis.asyncio.Redis``,
    ``aiohttp.ClientSession``). For tools to safely share those
    resources, the lifespan body and tool bodies must run on the same
    asyncio event loop.

    This wrapper:
      1. Eagerly starts the worker loop pool (so worker-0 — the "user
         loop" — exists before lifespan enter runs).
      2. Drives the user lifespan's ``__aenter__`` on the user loop via
         ``run_coroutine_threadsafe`` + ``wrap_future``. The framework
         loop (uvicorn's loop) awaits the resulting future without
         blocking, so ``/health`` / ``/ready`` / ``/livez`` stay
         responsive even if user startup is slow.
      3. Yields control to FastAPI/uvicorn for normal request handling.
      4. Drives ``__aexit__`` on the same user loop on shutdown,
         forwarding any exception raised between yield and exit so the
         user lifespan can react (PEP 343 semantics).

    Contextvar propagation:
        ``contextvars.copy_context()`` is captured on the framework
        (outer) side before crossing the loop boundary, then re-applied
        inside the user-loop worker via ``loop.create_task(coro,
        context=ctx)``. This means a trace ID / propagated header
        seeded on the framework loop is visible inside the user's
        lifespan body. Same pattern as :func:`tool_executor.dispatch`.

    Exception forwarding:
        If uvicorn/FastAPI raises between ``__aenter__`` and the body
        completing (cancelled shutdown, outer composer failure, etc.),
        the exception is forwarded into the user's ``__aexit__`` with
        proper ``exc_type``, ``exc_val``, ``exc_tb`` so it can react.
        If ``__aexit__`` returns truthy the exception is suppressed;
        otherwise it propagates normally to uvicorn. This implements
        the standard async-context-manager contract.

    Partial-startup unwind:
        The ``try/except/else`` shape below guarantees that if
        ``__aenter__`` succeeded but the yielded body raises (e.g., the
        outer composer's claim-dispatcher startup blew up), the user's
        ``__aexit__`` still runs with the exception forwarded. The
        ``else`` branch (clean exit) only fires when the body returned
        without raising.

    Forward-looking escape hatch:
        If you hit a problem with this hijack (e.g., an exotic
        lifespan that uses contextvars in a non-PEP-567-compatible
        way, or a third-party library that captures the loop ref at
        module import), the recommended escape is to STOP using
        FastMCP/FastAPI ``lifespan=`` for loop-bound resources and
        switch to mesh-native startup hooks: ``@mesh.on_startup`` /
        ``@mesh.on_shutdown`` (planned for a future minor release).
        These hooks run on the user loop natively and don't depend on
        uvicorn's lifespan invocation pattern.
    """

    @asynccontextmanager
    async def wrapper(app):
        # Local import to avoid widening the import surface at module load.
        from ...shared.tool_executor import _start_workers, get_worker_loops

        _start_workers()
        user_loops = get_worker_loops()
        if not user_loops:
            raise RuntimeError(
                "user loop pool failed to start before lifespan; "
                "tool_executor returned no worker loops"
            )
        # With default N=1 the first worker IS the user loop. With N>1
        # override, we pin lifespan to worker-0 by convention — multi-loop
        # affinity selection is a follow-up.
        user_loop = user_loops[0]

        cm = user_lifespan(app)

        # Capture contextvars on the framework (outer) side BEFORE crossing
        # the loop boundary. Same pattern as tool_executor.dispatch — see
        # PEP 567 / Python 3.11+ ``loop.create_task(coro, context=ctx)``.
        startup_ctx = contextvars.copy_context()

        async def _enter_on_user_loop():
            loop = asyncio.get_running_loop()
            task = loop.create_task(cm.__aenter__(), context=startup_ctx)
            return await task

        startup_fut = asyncio.run_coroutine_threadsafe(
            _enter_on_user_loop(), user_loop
        )
        try:
            cm_state = await asyncio.wrap_future(startup_fut)
        except BaseException as exc:
            # Framework side aborted (e.g., uvicorn cancellation) or
            # __aenter__ raised. Cancel the user-loop task defensively
            # so it doesn't keep running past the parent's "done".
            # ``concurrent.futures.Future.cancel()`` returns bool and
            # does not itself raise.
            startup_fut.cancel()
            _log_hijack_startup_failure(exc)
            raise

        try:
            yield cm_state
        except BaseException as exc:
            # PEP 343: forward exception info into user __aexit__ so the
            # user lifespan can react (cleanup, suppression, etc.). This
            # also covers Gap 3 (partial-startup unwind) — if the outer
            # composer raises after our __aenter__ succeeded, control
            # lands here and we still drive __aexit__ on the user loop.
            exc_type = type(exc)
            exc_val = exc
            exc_tb = exc.__traceback__

            # Re-capture context for the shutdown side. The yielded body
            # may have seeded contextvars the user wants visible during
            # cleanup (e.g., a trace ID set by the request that triggered
            # shutdown). copy_context() snapshots whatever is current on
            # the framework loop right now.
            shutdown_ctx = contextvars.copy_context()

            async def _exit_with_exc_on_user_loop():
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    cm.__aexit__(exc_type, exc_val, exc_tb),
                    context=shutdown_ctx,
                )
                return await task

            suppress_fut = asyncio.run_coroutine_threadsafe(
                _exit_with_exc_on_user_loop(), user_loop
            )
            try:
                suppressed = await asyncio.wrap_future(suppress_fut)
            except BaseException as exit_exc:
                # Framework side aborted (e.g., uvicorn shutdown timeout)
                # or __aexit__ raised. Cancel the user-loop __aexit__
                # task so it doesn't keep running past the parent's
                # "done", leaking wall-clock and resources.
                suppress_fut.cancel()
                _log_hijack_shutdown_failure(exit_exc)
                raise

            if not suppressed:
                raise
        else:
            # Clean-exit path: __aexit__(None, None, None) on the user loop.
            shutdown_ctx = contextvars.copy_context()

            async def _exit_clean_on_user_loop():
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    cm.__aexit__(None, None, None),
                    context=shutdown_ctx,
                )
                return await task

            shutdown_fut = asyncio.run_coroutine_threadsafe(
                _exit_clean_on_user_loop(), user_loop
            )
            try:
                await asyncio.wrap_future(shutdown_fut)
            except BaseException as exit_exc:
                # Framework side aborted (e.g., uvicorn shutdown timeout)
                # or __aexit__ raised. Cancel the user-loop __aexit__
                # task so it doesn't keep running past the parent's
                # "done", leaking wall-clock and resources.
                shutdown_fut.cancel()
                _log_hijack_shutdown_failure(exit_exc)
                raise

    return wrapper


# Back-compat alias: prior code referenced ``_user_loop_dispatched`` (the
# v2.3 prototype name). The canonical name is now
# ``wrap_lifespan_for_user_loop``; existing callers continue to work
# through the alias. Both refer to the same wrapper implementation.
_user_loop_dispatched = wrap_lifespan_for_user_loop


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

    # Hijack the user/FastMCP lifespan so its body runs on the user loop
    # (worker-0 of the tool_executor pool). Tools and lifespan now share
    # the same asyncio loop, so loop-bound resources created in lifespan
    # startup are safely usable from tool bodies. See issue #1061. The
    # hijack logic lives in wrap_lifespan_for_user_loop — single entry
    # point shared with mesh.decorators._start_uvicorn_immediately.
    user_loop_lifespan = wrap_lifespan_for_user_loop(fastmcp_lifespan)

    @asynccontextmanager
    async def lifespan(app):
        fastmcp_ctx = None
        try:
            fastmcp_ctx = user_loop_lifespan(app)
            await fastmcp_ctx.__aenter__()
            logger.debug("Started FastMCP lifespan on user loop")
        except Exception as e:
            logger.error(
                f"Failed to start FastMCP lifespan via user-loop hijack: {e}. "
                f"Agent will fail to start. If this keeps happening, "
                f"consider moving loop-bound resource init out of "
                f"FastMCP/FastAPI lifespan and using @mesh.on_startup / "
                f"@mesh.on_shutdown hooks (planned for a future release)."
            )
            raise

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

    # Hijack each user/FastMCP lifespan so its body runs on the user loop.
    # See wrap_lifespan_for_user_loop / issue #1061.
    user_loop_lifespans = [wrap_lifespan_for_user_loop(ls) for ls in fastmcp_lifespans]

    @asynccontextmanager
    async def lifespan(app):
        lifespan_contexts = []
        for ls in user_loop_lifespans:
            try:
                ctx = ls(app)
                await ctx.__aenter__()
                lifespan_contexts.append(ctx)
            except Exception as e:
                logger.error(
                    f"Failed to start FastMCP lifespan via user-loop "
                    f"hijack: {e}. Agent will fail to start. If this keeps "
                    f"happening, consider moving loop-bound resource init "
                    f"out of FastMCP/FastAPI lifespan and using "
                    f"@mesh.on_startup / @mesh.on_shutdown hooks (planned "
                    f"for a future release)."
                )
                raise

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
