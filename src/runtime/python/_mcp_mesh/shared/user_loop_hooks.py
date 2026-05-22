"""Helpers for scheduling work on the user loop and tying its lifetime
to FastAPI ``app.state`` so the lifespan wrapper can cancel it cleanly.

Background
----------
The user-loop hijack (see ``lifespan_factory.py``) runs the user
lifespan body and tool bodies on the same asyncio loop ("the user
loop"). Some framework subsystems also need to run long-lived work on
that loop — most notably the ``health_check_ttl`` refresh
(issue #1072), which must run on the user loop so the user-supplied
``health_check_fn`` can safely touch loop-affine resources created
during ``lifespan`` startup.

These subsystems can't piggyback on ``lifespan`` itself because they
get configured by the startup pipeline *after* ``lifespan`` has already
``__aenter__``-ed (e.g., ``_add_k8s_endpoints`` runs as a pipeline step,
which mounts onto an already-started immediate-uvicorn FastAPI app).
The helpers here instead schedule the work on the user loop via
``run_coroutine_threadsafe`` and stash the resulting future on the
FastAPI app's ``app.state.mesh_user_loop_futures`` list. The lifespan
wrapper cancels every future on that list during ``__aexit__``.

Lifespan-ready gate
-------------------
Subsystems that schedule work via :func:`schedule_on_user_loop` may
need to wait for the user lifespan ``__aenter__`` to complete before
their first iteration (e.g., a periodic refresh that calls a user
function which touches a ``_pool`` global initialized in lifespan).
The lifespan wrapper completes the ``concurrent.futures.Future``
returned by :func:`get_or_create_lifespan_ready_future` once user
``__aenter__`` succeeds; subsystems can do
``await asyncio.wrap_future(fut)`` before their first iteration.
``concurrent.futures.Future`` is loop-agnostic, so this works even
though set-side runs on the framework loop and wait-side runs on the
user loop.

Contract:
  - The coroutine MUST tolerate ``asyncio.CancelledError`` (re-raise or
    return cleanly) so the lifespan exit can stop it.
  - The coroutine SHOULD swallow other exceptions internally to avoid
    polluting the framework logger; the future is fire-and-forget.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

logger = logging.getLogger(__name__)

# Attribute name used on ``app.state`` to track user-loop futures whose
# lifetime is bound to the FastAPI lifespan. Centralized here so both
# the scheduler (subsystem code) and the canceller (lifespan_factory)
# agree on the key.
APP_STATE_ATTR = "mesh_user_loop_futures"

# Attribute name used on ``app.state`` to stash the lifespan-ready
# signal (a ``concurrent.futures.Future``). Whichever side runs first
# (scheduler or lifespan wrapper) creates the future; the other side
# finds it via this key. ``concurrent.futures.Future`` is loop-agnostic,
# so it's safe to set on the framework loop and ``wrap_future`` on the
# user loop.
APP_STATE_LIFESPAN_READY_ATTR = "mesh_lifespan_ready"

# Single lock guarding all reads/writes of ``app.state`` attributes
# owned by this module. ``app.state`` is a Starlette ``State`` object —
# attribute access isn't synchronized. The scheduler runs on the
# framework loop (or wherever the startup pipeline runs) while the
# lifespan wrapper may be running ``__aenter__`` on the user loop and
# completing the ready-future from the framework side. Reads/writes
# from those distinct threads need a mutex.
_app_state_lock = threading.Lock()


def get_or_create_lifespan_ready_future(app) -> Future:
    """Return the shared lifespan-ready future for ``app``.

    Both the lifespan wrapper (which completes the future after user
    ``__aenter__`` succeeds) and subsystem schedulers (which await the
    future before their first iteration) call this. Whichever side
    runs first creates the future; the other finds it.

    Always returns a future; never raises. If ``app.state`` is
    unavailable the caller gets a standalone future that nobody else
    will see — the gate effectively no-ops in that case.
    """
    try:
        with _app_state_lock:
            fut = getattr(app.state, APP_STATE_LIFESPAN_READY_ATTR, None)
            if fut is None:
                fut = Future()
                setattr(app.state, APP_STATE_LIFESPAN_READY_ATTR, fut)
            return fut
    except Exception as e:
        logger.warning(
            "Could not get/create lifespan-ready future on app.state: %s. "
            "Returning a pre-resolved future — gate degrades to no-op so "
            "the refresh loop doesn't stall waiting on something nobody "
            "will ever signal.",
            e,
        )
        fallback = Future()
        fallback.set_result(None)
        return fallback


def signal_lifespan_ready(app) -> None:
    """Mark the user lifespan as ready. Called by the lifespan wrapper
    after user ``__aenter__`` succeeds.

    Idempotent: completing an already-completed future is a no-op
    (``set_result`` would raise ``InvalidStateError``, so we guard).
    """
    fut = get_or_create_lifespan_ready_future(app)
    if not fut.done():
        try:
            fut.set_result(None)
        except Exception as e:
            # Race: another caller completed it between our ``done()``
            # check and ``set_result``. Harmless.
            logger.debug(
                "signal_lifespan_ready: future already completed (%s)", e
            )


def schedule_on_user_loop(
    app,
    user_loop: "asyncio.AbstractEventLoop",
    coro_factory: Callable[[], Awaitable[None]],
    *,
    name: str = "user-loop-task",
) -> "Future | None":
    """Schedule ``coro_factory()`` on ``user_loop`` and register the
    resulting future with ``app.state`` so the lifespan wrapper can
    cancel it on shutdown.

    Returns the ``concurrent.futures.Future`` or ``None`` if scheduling
    failed (we never let a background-scheduling hiccup propagate into
    user-visible startup).
    """
    import asyncio as _asyncio

    # Construct the coroutine first so we can explicitly close it if
    # scheduling fails — otherwise Python emits "coroutine ... was never
    # awaited" and the coroutine object leaks until GC reclaims it.
    coro = coro_factory()
    try:
        fut = _asyncio.run_coroutine_threadsafe(coro, user_loop)
    except Exception as e:
        coro.close()
        logger.warning(
            "Failed to schedule user-loop task %r: %s", name, e
        )
        return None

    try:
        with _app_state_lock:
            futures = getattr(app.state, APP_STATE_ATTR, None)
            if futures is None:
                futures = []
                setattr(app.state, APP_STATE_ATTR, futures)
            futures.append(fut)
    except Exception as e:
        # Registration failed (e.g., frozen ``app.state`` on some
        # Starlette version, or a test mock). The future is running but
        # nobody else holds a handle to it, so it's effectively a leak —
        # cancel it now rather than let it run unmanaged.
        logger.warning(
            "Failed to register user-loop task %r against app.state: %s. "
            "Cancelling the scheduled coroutine to avoid a leak.",
            name,
            e,
        )
        try:
            fut.cancel()
        except Exception as cancel_exc:
            logger.debug(
                "Error cancelling unregistered user-loop future %r: %s",
                name,
                cancel_exc,
            )
        return None

    return fut


def cancel_app_user_loop_futures(app) -> None:
    """Cancel every future registered via :func:`schedule_on_user_loop`
    on this app. Idempotent and best-effort — ``Future.cancel()`` does
    not raise.
    """
    # Take a consistent snapshot under the lock; cancellation itself
    # doesn't need the lock (and shouldn't hold it while iterating).
    try:
        with _app_state_lock:
            futures = list(
                getattr(getattr(app, "state", None), APP_STATE_ATTR, None) or []
            )
    except Exception as e:
        logger.debug("Could not snapshot user-loop futures from app.state: %s", e)
        return

    for fut in futures:
        try:
            fut.cancel()
        except Exception as e:
            logger.debug("Error cancelling user-loop future: %s", e)
