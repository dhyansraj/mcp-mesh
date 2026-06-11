"""
Simple shutdown coordination for MCP Mesh agents.

Provides clean shutdown via FastAPI lifespan events and basic signal handling.
The Rust core handles actual deregistration from the registry.
"""

import atexit
import logging
import signal
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# Active Rust agent-handle registry (issue #877)
# =============================================================================
#
# The Rust core spawns a tokio runtime in a background thread. After futures
# resolve, pyo3-async-runtimes does `spawn_blocking(|| Python::attach(...))`
# to write the result back. If Python's interpreter has begun finalizing
# (e.g. uvicorn failed to bind, sys.exit, unhandled exception in startup) and
# a tokio worker happens to wake up at that moment, it tries to attach to a
# torn-down interpreter and panics with "interpreter is not initialized".
#
# The cure: drain the Rust dispatcher BEFORE Python finalizes. We register
# every live AgentHandle in this process-wide list and an atexit hook calls
# `handle.shutdown()` on each. atexit fires before Py_Finalize tears down the
# interpreter, so the Rust thread sees the shutdown signal and exits before
# anyone tries to Python::attach against a dying interpreter.
#
# Best-effort: if shutdown raises (handle already shut down, channel closed,
# whatever) we swallow it — we're inside atexit, the process is going away,
# nothing useful can be done with the error.
_active_handles_lock = threading.Lock()
_active_handles: list = []
_atexit_installed = False

# Per-handle bound for the atexit drain. If a handle is wedged (Rust dispatcher
# stuck, backend slow), we don't want it to block process exit. Shutdowns are
# run concurrently in daemon threads so the total wait stays bounded by this
# value rather than N * timeout when many handles are registered.
_PER_HANDLE_SHUTDOWN_TIMEOUT_SECS = 2.0


def _safe_shutdown(h: Any) -> None:
    """Best-effort shutdown for a single handle — swallow errors at exit."""
    try:
        h.shutdown()
    except Exception:
        # Best-effort during interpreter shutdown — the channel may be
        # closed, the runtime already gone, etc. Nothing we can do.
        pass


def register_rust_agent_handle(handle: Any) -> None:
    """Track a Rust core AgentHandle so atexit can drain it before Py_Finalize.

    Called by the heartbeat lifespan tasks immediately after `start_agent()`
    returns. Idempotent on repeat: a handle registered twice is only kept
    once. See module docstring for the race this closes.
    """
    global _atexit_installed
    if handle is None:
        return
    with _active_handles_lock:
        # Identity check (handle is a PyO3 object — list doesn't need __eq__).
        if not any(h is handle for h in _active_handles):
            _active_handles.append(handle)
        if not _atexit_installed:
            atexit.register(_atexit_shutdown_active_handles)
            _atexit_installed = True
            logger.debug("Registered atexit hook to drain Rust agent handles")


def unregister_rust_agent_handle(handle: Any) -> None:
    """Drop a handle from the registry (e.g. normal shutdown already drained it).

    Best-effort: if the handle isn't in the list (already removed, never
    registered), we silently no-op.
    """
    if handle is None:
        return
    with _active_handles_lock:
        # Identity-based filter so we don't depend on __eq__ semantics of the
        # PyO3 wrapper.
        _active_handles[:] = [h for h in _active_handles if h is not handle]


def _atexit_shutdown_active_handles() -> None:
    """atexit hook: drain every still-live Rust handle before Py_Finalize.

    Runs at interpreter shutdown — under abnormal exits (uvicorn bind fail,
    unhandled startup error) the normal shutdown path in the heartbeat task
    never gets a chance to fire, leaving the Rust tokio runtime live. That
    runtime can then race with interpreter finalization and panic in the
    pyo3-async-runtimes Python::attach codepath. Calling shutdown() here
    signals the Rust core to drain its dispatcher and join its background
    thread before the interpreter goes away.
    """
    with _active_handles_lock:
        handles = list(_active_handles)
        _active_handles.clear()
    if not handles:
        return
    # Run each handle's shutdown in its own daemon thread with a bounded join.
    # Concurrent dispatch keeps the total wall-clock bound at
    # _PER_HANDLE_SHUTDOWN_TIMEOUT_SECS even when several handles are live.
    # daemon=True ensures a genuinely-stuck shutdown thread can't block
    # interpreter teardown — Python tears daemons down on exit.
    threads = [
        threading.Thread(
            target=_safe_shutdown,
            args=(h,),
            daemon=True,
            name=f"mesh-atexit-shutdown-{id(h)}",
        )
        for h in handles
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_PER_HANDLE_SHUTDOWN_TIMEOUT_SECS)
    # Brief grace window so the Rust dispatcher thread sees the signal and
    # tears down its tokio runtime before atexit returns and Py_Finalize
    # starts. Matches the 200ms used in the normal-path teardown in
    # rust_heartbeat.py / rust_api_heartbeat.py.
    try:
        time.sleep(0.2)
    except Exception:
        pass


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
        # Uvicorn Server handles (lazily registered by mesh/decorators.py
        # and startup_orchestrator). Signal handlers flip
        # ``server.should_exit`` on EVERY registered server so uvicorn runs
        # its graceful shutdown (which drives the FastAPI lifespan exit
        # phase) before each server thread returns. See issue #1029.
        #
        # This is a list, not a single slot: degenerate startups can leave
        # more than one live server in the process (e.g. the immediate
        # decorator server comes up but the pipeline does not reuse it and
        # starts its own). A single slot would let the second registration
        # overwrite the first, orphaning that server's NON-daemon thread on
        # SIGTERM — the process would never exit.
        self._uvicorn_servers: list[Any] = []

    def set_shutdown_context(self, registry_url: str, agent_id: str) -> None:
        """Set context for shutdown (used for logging)."""
        self._registry_url = registry_url
        self._agent_id = agent_id
        logger.debug(
            f"🔧 Shutdown context set: agent_id={agent_id}, registry_url={registry_url}"
        )

    def register_uvicorn_server(self, server: Any) -> None:
        """Register a uvicorn Server instance so the signal handler can
        request graceful shutdown via ``server.should_exit``.

        Without this hook, SIGTERM merely sets a flag on the main thread and
        the uvicorn worker thread is killed mid-flight — the FastAPI
        lifespan ``finally`` block (e.g. asyncpg pool close, in-flight
        httpx cancel) never runs. With the hook, uvicorn observes
        ``should_exit``, runs its normal graceful-shutdown sequence
        (including the lifespan exit phase), and then ``server.run()``
        returns cleanly. See issue #1029.

        Registrations accumulate (identity-deduplicated): every registered
        server is signaled on SIGTERM/SIGINT, so a second server started in
        a degenerate startup path cannot orphan the first one's non-daemon
        thread.
        """
        if server is None:
            return
        if not any(s is server for s in self._uvicorn_servers):
            self._uvicorn_servers.append(server)
        logger.debug("📡 Uvicorn server registered with shutdown coordinator")

    def install_signal_handlers(self) -> None:
        """Install signal handlers that request uvicorn graceful shutdown.

        When a signal arrives the handler sets the local shutdown flag AND,
        if a uvicorn Server has been registered via
        :meth:`register_uvicorn_server`, flips ``server.should_exit`` so
        uvicorn runs the FastAPI lifespan exit phase before its
        ``run()`` returns. Avoid logging here — signal handlers are async
        w.r.t. the interpreter and logging can reenter (issue #1029).
        """

        def shutdown_signal_handler(signum, frame):
            # Avoid logging in signal handler to prevent reentrant call issues
            self._shutdown_requested = True
            # Tell EVERY registered uvicorn server to begin graceful
            # shutdown — this lets the FastAPI lifespan finally block run
            # before each server thread exits. Best-effort: if no server
            # was registered (e.g. tests, API/A2A flows that don't own
            # uvicorn), just set the flag. Iterate over a snapshot — the
            # handler runs async w.r.t. the interpreter.
            for server in list(self._uvicorn_servers):
                server.should_exit = True

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


def register_uvicorn_server(server: Any) -> None:
    """Register a uvicorn Server instance (module-level function).

    Internal coordination hook between ``mesh/decorators.py`` /
    ``startup_orchestrator`` and the process-wide shutdown coordinator.
    Calling this after :func:`install_signal_handlers` enables graceful
    FastAPI lifespan teardown on SIGTERM/SIGINT (issue #1029). All
    registered servers are signaled — see
    :meth:`SimpleShutdownCoordinator.register_uvicorn_server`.
    """
    _simple_shutdown_coordinator.register_uvicorn_server(server)


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
