"""Dedicated worker event loops for isolating user tool execution from the main loop.

This prevents a user's blocking syscall (e.g. ``time.sleep`` inside an ``async def``
tool) from freezing uvicorn's main loop and blocking health endpoints / heartbeats,
AND lets concurrent blocking tools run in parallel across N worker threads instead
of serializing on a single worker.

Architecture::

    main thread                          worker pool (N threads)
    ├─ uvicorn event loop                ├─ mesh-tool-worker-0 (own asyncio loop)
    ├─ FastAPI / FastMCP routing         ├─ mesh-tool-worker-1 (own asyncio loop)
    ├─ /health, /ready, /livez           ├─ ...
    └─ heartbeats                        └─ mesh-tool-worker-(N-1)

When the @mesh.tool decorator wraps an ``async def`` user function with
``isolated()``, FastMCP awaits ``isolated`` on the main loop. ``isolated``
calls :func:`dispatch` to schedule the user coroutine on one of the worker
loops via ``asyncio.run_coroutine_threadsafe``, then awaits the resulting
``concurrent.futures.Future`` via ``asyncio.wrap_future``. A user's
``time.sleep(60)`` now blocks only one worker thread, not uvicorn — and other
workers remain free to service concurrent calls.

Pool size:
    Default ``N = min(8, max(2, os.cpu_count() or 2))``.
    Override at startup via ``MCP_MESH_TOOL_WORKERS=<N>`` env var.

    The pool size is read ONCE on first dispatch and cached. Changing the
    env var at runtime has no effect.

Dispatch strategy:
    Round-robin across workers via an ``itertools.cycle`` counter guarded by
    the init lock. Strict fairness is not a goal — rough distribution is
    sufficient since ``asyncio.run_coroutine_threadsafe`` already pushes onto
    the target loop's thread-safe queue.

ContextVars (``trace_id``, propagated headers, etc.) are captured on the
calling thread via ``contextvars.copy_context()`` and re-applied inside the
worker via ``ctx.run(...)`` so tracing keeps working transparently.
"""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import itertools
import logging
import os
import threading
from concurrent.futures import Future
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_workers: list[tuple[threading.Thread, asyncio.AbstractEventLoop]] = []
_next_worker_idx: itertools.cycle | None = None
_shutdown_registered = False


def _resolve_pool_size() -> int:
    """Read pool size from env or compute default. Called once at first init."""
    env_val = os.environ.get("MCP_MESH_TOOL_WORKERS")
    if env_val:
        try:
            n = int(env_val)
            if n >= 1:
                return n
            logger.warning(
                "MCP_MESH_TOOL_WORKERS=%r is < 1; falling back to default", env_val
            )
        except ValueError:
            logger.warning(
                "MCP_MESH_TOOL_WORKERS=%r is not an int; falling back to default",
                env_val,
            )
    cpu = os.cpu_count() or 2
    return min(8, max(2, cpu))


def _start_workers() -> list[tuple[threading.Thread, asyncio.AbstractEventLoop]]:
    """Start the worker pool. Idempotent — first call wins.

    Spawns N daemon threads, each owning its own asyncio event loop. Returns
    the populated worker list. Pool size is determined ONCE here from the
    ``MCP_MESH_TOOL_WORKERS`` env var (or default) and cached for the process
    lifetime.
    """
    global _workers, _next_worker_idx, _shutdown_registered

    with _lock:
        if _workers:
            return _workers

        n = _resolve_pool_size()
        new_workers: list[tuple[threading.Thread, asyncio.AbstractEventLoop]] = []
        thread_names: list[str] = []

        for i in range(n):
            ready = threading.Event()
            loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

            def _run() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop_holder["loop"] = loop
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass

            name = f"mesh-tool-worker-{i}"
            thread = threading.Thread(target=_run, name=name, daemon=True)
            thread.start()
            ready.wait()
            new_workers.append((thread, loop_holder["loop"]))
            thread_names.append(name)

        _workers = new_workers
        _next_worker_idx = itertools.cycle(range(n))

        if not _shutdown_registered:
            atexit.register(_shutdown_workers)
            _shutdown_registered = True

        logger.info(
            "🧵 mesh tool worker pool started: %d workers (%s)",
            n,
            ", ".join(thread_names),
        )
        return _workers


def _shutdown_workers() -> None:
    """Stop all worker loops and join their threads. Best-effort, called via atexit."""
    global _workers, _next_worker_idx

    workers = _workers
    if not workers:
        return

    for _thread, loop in workers:
        try:
            if not loop.is_closed():
                loop.call_soon_threadsafe(loop.stop)
        except Exception as e:
            logger.debug("mesh tool worker stop call failed: %s", e)

    for thread, _loop in workers:
        if thread.is_alive():
            thread.join(timeout=2.0)

    _workers = []
    _next_worker_idx = None


def _pick_loop() -> asyncio.AbstractEventLoop:
    """Round-robin select a worker loop. Caller must hold no locks."""
    with _lock:
        # Cycle is unbounded; advancing it is O(1) and thread-safe under the lock.
        idx = next(_next_worker_idx)  # type: ignore[arg-type]
    return _workers[idx][1]


# Exposed for the proxy's connection-pool cleanup (close_connection_pools), which
# needs to schedule client.aclose() on the worker loop that originally created
# each cached httpx/FastMCP client. Without this, worker-loop clients leak at
# orderly shutdown — they only get reaped at process termination when their
# daemon threads die.
def get_worker_loops() -> list[asyncio.AbstractEventLoop]:
    """Return the live worker event loops (snapshot)."""
    with _lock:
        return [loop for _, loop in _workers]


def dispatch(
    coro_func: Callable[..., Coroutine[Any, Any, Any]],
    args: tuple,
    kwargs: dict,
) -> Future:
    """Run ``coro_func(*args, **kwargs)`` on a worker loop and return a Future.

    The caller's ``contextvars.Context`` (trace IDs, propagated headers, etc.)
    is captured BEFORE crossing the thread boundary, then re-applied on the
    worker thread via ``ctx.run`` so the user's coroutine sees the same
    context that was active at dispatch time.

    Args:
        coro_func: The async user function (or wrapper) to invoke.
        args: Positional arguments.
        kwargs: Keyword arguments.

    Returns:
        ``concurrent.futures.Future`` resolved with the coroutine's result.
        Caller should ``await asyncio.wrap_future(future)`` from the main loop.
    """
    _start_workers()
    loop = _pick_loop()

    # Capture context on the CALLING thread — the worker thread doesn't have it.
    ctx = contextvars.copy_context()

    return asyncio.run_coroutine_threadsafe(
        _invoke_with_context(ctx, coro_func, args, kwargs), loop
    )


async def _invoke_with_context(
    ctx: contextvars.Context,
    coro_func: Callable[..., Coroutine[Any, Any, Any]],
    args: tuple,
    kwargs: dict,
) -> Any:
    """Invoke the user coroutine on the worker loop inside the captured context.

    ``ctx.run`` only runs synchronous callables, so we use it to BUILD the
    coroutine (which sets contextvars at coroutine-creation time, since the
    coroutine object captures the current context). Each ``await`` inside
    the user code then sees those contextvars. We then await the coroutine
    on the worker loop.
    """
    coro = ctx.run(coro_func, *args, **kwargs)
    if not asyncio.iscoroutine(coro):
        return coro
    return await coro
