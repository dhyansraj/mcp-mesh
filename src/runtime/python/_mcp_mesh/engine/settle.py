"""
Settling-window dependency grace (issue #1193).

Dependency injection resolves asynchronously: declared dependencies become
available when the first full heartbeat cycle completes and
``dependency_available`` events land. A call that fires during that settling
window would otherwise see a declared-but-unresolved dependency as ``None``
even though resolution typically lands moments later.

This module provides a process-wide settle state:

* The settle window is ANCHORED at the first dependency declaration (the
  first :meth:`SettleState.register_declared` call during startup wiring) —
  not at module import — so slow imports or pre-decoration work never eat
  into the grace budget. The agent is **unsettled** from that anchor until
  EITHER every declared dependency has resolved at least once OR the window
  (``MCP_MESH_SETTLE_TIMEOUT`` seconds, default 20) expires.
* While unsettled, the DI wrappers wait — bounded by the REMAINING settle
  budget — for the dependency to resolve; the existing
  ``_mesh_update_dependency`` funnel wakes waiters the moment the
  dependency resolves. Resolution at 800ms unblocks at 800ms; the budget is
  a ceiling only, never a sleep.
* Once settled — either way — the latch is permanent: calls never touch the
  wait primitives again and fail-fast behavior is byte-identical to the
  pre-grace behavior (unresolved deps inject ``None`` exactly as before).

Wait primitives (two, by execution context):

* Sync tool wrappers (dispatched by FastMCP onto ``anyio.to_thread`` worker
  threads) block on a per-dependency :class:`threading.Event` — resolution
  events arrive on arbitrary threads/loops (MCP heartbeat loop, API/A2A
  heartbeat tasks), and a loop-bound primitive could not be safely set
  across loops. A defensive running-loop probe skips the blocking wait if a
  sync wrapper is ever invoked ON an event loop (blocking there would stall
  the loop that delivers the very resolution events the wait needs).
* Async wrappers await a loop-native :class:`asyncio.Event` mirror that the
  resolution funnel sets via ``loop.call_soon_threadsafe`` — zero executor
  usage, so graced calls never consume the shared default-executor capacity
  the sync-HTTP proxy fallback and media paths rely on, and shutdown
  mid-wait never delays process exit (the awaits are loop-bound and
  cancellable; no daemon-thread games needed).

Caller-supplied slots never wait: the documented mock contract lets callers
pass a fake/proxy for any injectable parameter explicitly — the pending
collection consults the call kwargs and skips those slots entirely.

Scope (deliberate): the grace covers the dependency-injection wrappers only
— ``@mesh.tool`` / ``@mesh.route`` call paths. Lifespan/startup-hook
dependency usage, module-scope captured deps, and ``@mesh.llm``
provider/filter assembly (registration-time, with its own update mechanism)
are NOT covered.

This is environmental, not a declaration mistake: ``MCP_MESH_STRICT_DI``
never interacts with the settle window in any way.
"""

import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

SETTLE_TIMEOUT_DEFAULT_SECONDS = 20.0

# Cached per-process resolution of MCP_MESH_SETTLE_TIMEOUT (mirrors the
# cached-global convention of ``is_strict_di_enabled``). The settle window
# is a process-level posture, not a per-call toggle.
_SETTLE_TIMEOUT: Optional[float] = None


def get_settle_timeout() -> float:
    """Settle window in seconds. ``0`` disables the grace entirely.

    Configurable via ``MCP_MESH_SETTLE_TIMEOUT`` (float seconds, default
    20). Read once per process and cached. Negative or unparseable values
    fall back to the default with a warning.
    """
    global _SETTLE_TIMEOUT
    if _SETTLE_TIMEOUT is None:
        from ..shared.config_resolver import ValidationRule, get_config_value

        value = get_config_value(
            "MCP_MESH_SETTLE_TIMEOUT",
            default=SETTLE_TIMEOUT_DEFAULT_SECONDS,
            rule=ValidationRule.FLOAT_RULE,
        )
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            timeout = SETTLE_TIMEOUT_DEFAULT_SECONDS
        if timeout < 0:
            logger.warning(
                "MCP_MESH_SETTLE_TIMEOUT must be >= 0 (got %s); "
                "using default %.0fs",
                value,
                SETTLE_TIMEOUT_DEFAULT_SECONDS,
            )
            timeout = SETTLE_TIMEOUT_DEFAULT_SECONDS
        _SETTLE_TIMEOUT = timeout
    return _SETTLE_TIMEOUT


class SettleState:
    """Process-wide settle latch + per-dependency resolution wakeups.

    Dependencies are tracked at the AGENT level as the union of declared
    dependency keys across all decorated functions (composite
    ``"<func_id>:dep_<N>"`` keys — the same keys the resolution paths
    already use). The latch flips eagerly when the last declared key
    resolves, or lazily when :meth:`is_settled` observes window expiry.

    The window is anchored at the FIRST :meth:`register_declared` call
    (startup wiring time), not at construction/import time.
    """

    def __init__(self) -> None:
        # Anchored lazily by the first register_declared call.
        self._start: Optional[float] = None
        self._lock = threading.Lock()
        self._declared: set[str] = set()
        self._resolved: set[str] = set()
        self._events: dict[str, threading.Event] = {}
        # Loop-native mirrors for async waiters: dep_key -> [(loop, event)].
        # Set via loop.call_soon_threadsafe from the resolution funnel so
        # async waits never touch a thread pool (see module docstring).
        self._async_waiters: dict[
            str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]
        ] = {}
        self._settled = False
        # Capabilities whose first wait was already logged at INFO —
        # subsequent waits on the same capability log at DEBUG.
        self._logged_waits: set[str] = set()
        # Diagnostic counter: number of actual bounded waits performed.
        # Used by tests to prove the settled steady-state path never
        # touches the wait primitives.
        self.wait_count = 0

    def register_declared(self, dep_key: str) -> None:
        """Record a declared dependency key (decoration/wiring time).

        The FIRST declaration anchors the settle window — the window
        measures topology convergence from the moment the agent starts
        declaring dependencies, not from module import.
        """
        with self._lock:
            if self._start is None:
                self._start = time.monotonic()
            self._declared.add(dep_key)

    def mark_resolved(self, dep_key: str) -> None:
        """Record a resolution and wake any waiter on this key.

        Called from the existing dependency-update funnel whenever a real
        proxy lands. "Resolved at least once" semantics: a later
        unavailability does NOT un-resolve the key — the settle window only
        measures initial topology convergence.
        """
        with self._lock:
            self._resolved.add(dep_key)
            event = self._events.get(dep_key)
            if event is None:
                event = threading.Event()
                self._events[dep_key] = event
            # Snapshot under the lock so a concurrent wait_for_async
            # registration can never be missed (it re-checks _resolved
            # under the same lock before registering).
            async_waiters = list(self._async_waiters.get(dep_key, ()))
            if self._declared and self._declared <= self._resolved:
                # Eager latch: the LAST declared dependency just resolved.
                self._settled = True
        event.set()
        for loop, async_event in async_waiters:
            try:
                loop.call_soon_threadsafe(async_event.set)
            except RuntimeError:
                # The waiter's loop already closed (shutdown mid-wait) —
                # nothing left to wake.
                pass

    def retire_declared(self, dep_key: str) -> None:
        """Remove a declared key that no update path will ever resolve.

        Used by route-wrapper convergence in the dual-import scenario
        (``python main.py`` + ``from main import X``): each decoration pass
        created its own DI wrapper and declared its own func_id-scoped keys,
        but after convergence only the preferred instance receives heartbeat
        updates. Leaving the abandoned instance's keys declared would pin
        the eager latch open for the full window — every graced call would
        then wait out the budget even after all live dependencies resolved.

        Any waiter already parked on the retired key (a call that collected
        its pending set just before convergence) is woken so it proceeds
        immediately instead of dead-waiting a key that can never resolve.
        """
        with self._lock:
            self._declared.discard(dep_key)
            event = self._events.get(dep_key)
            async_waiters = list(self._async_waiters.get(dep_key, ()))
            if self._declared and self._declared <= self._resolved:
                # Eager latch: the retired key was the last unresolved one.
                self._settled = True
        if event is not None:
            event.set()
        for loop, async_event in async_waiters:
            try:
                loop.call_soon_threadsafe(async_event.set)
            except RuntimeError:
                # The waiter's loop already closed (shutdown mid-wait).
                pass

    def is_settled(self) -> bool:
        """Permanent latch check; flips on window expiry or timeout=0."""
        if self._settled:
            return True
        timeout = get_settle_timeout()
        if timeout <= 0:
            self._settled = True
            return True
        if self._start is None:
            # Window not yet anchored — no dependency has been declared,
            # so nothing can be pending. Report settled WITHOUT latching:
            # the window must still open when the first declaration lands.
            return True
        if (time.monotonic() - self._start) >= timeout:
            self._settled = True
            return True
        return False

    def remaining(self) -> float:
        """Remaining settle budget in seconds (>= 0)."""
        if self._start is None:
            return 0.0
        return max(0.0, get_settle_timeout() - (time.monotonic() - self._start))

    def _event_for(self, dep_key: str) -> threading.Event:
        with self._lock:
            event = self._events.get(dep_key)
            if event is None:
                event = threading.Event()
                self._events[dep_key] = event
            return event

    def _log_wait(
        self, capability: str, remaining: float, log: logging.Logger
    ) -> None:
        """One INFO line per capability per process; later waits DEBUG."""
        if capability not in self._logged_waits:
            self._logged_waits.add(capability)
            log.info(
                "waiting up to %.1fs for dependency '%s' to settle",
                remaining,
                capability,
            )
        else:
            log.debug(
                "waiting up to %.1fs for dependency '%s' to settle",
                remaining,
                capability,
            )

    def wait_for(
        self, dep_key: str, capability: str, log: logging.Logger
    ) -> None:
        """Block (current thread) until ``dep_key`` resolves or the budget ends.

        MUST only be called off the event loop — sync tool wrappers run on
        FastMCP's ``anyio.to_thread`` worker threads, and
        :func:`wait_for_settle_sync` probes for a running loop before
        dispatching here. Async wrappers use :meth:`wait_for_async`.
        """
        remaining = self.remaining()
        if remaining <= 0:
            return
        event = self._event_for(dep_key)
        if event.is_set():
            return
        self._log_wait(capability, remaining, log)
        self.wait_count += 1
        # On timeout we simply proceed — the unresolved dep injects None
        # exactly as today, and the existing unresolved-dep warning path
        # covers the diagnostic (no double-logging here).
        event.wait(remaining)

    async def wait_for_async(
        self, dep_key: str, capability: str, log: logging.Logger
    ) -> None:
        """Await ``dep_key``'s resolution on the CURRENT loop, budget-bounded.

        Loop-native: registers an :class:`asyncio.Event` mirror that
        :meth:`mark_resolved` sets via ``loop.call_soon_threadsafe`` from
        whatever thread the resolution funnel runs on. No executor is ever
        touched, the await is cancellable, and shutdown mid-wait cannot
        delay process exit by the window.
        """
        remaining = self.remaining()
        if remaining <= 0:
            return
        loop = asyncio.get_running_loop()
        async_event = asyncio.Event()
        with self._lock:
            if dep_key in self._resolved:
                return
            self._async_waiters.setdefault(dep_key, []).append(
                (loop, async_event)
            )
        self._log_wait(capability, remaining, log)
        self.wait_count += 1
        try:
            # On timeout we simply proceed — same None-injection contract
            # as the sync path.
            await asyncio.wait_for(async_event.wait(), remaining)
        except asyncio.TimeoutError:
            pass
        finally:
            with self._lock:
                waiters = self._async_waiters.get(dep_key)
                if waiters is not None:
                    try:
                        waiters.remove((loop, async_event))
                    except ValueError:
                        pass
                    if not waiters:
                        self._async_waiters.pop(dep_key, None)


_settle_state = SettleState()


def get_settle_state() -> SettleState:
    """Get the process-wide settle state."""
    return _settle_state


def _reset_settle_state_for_tests() -> None:
    """Replace the settle state and drop the cached timeout (test support)."""
    global _settle_state, _SETTLE_TIMEOUT
    _settle_state = SettleState()
    _SETTLE_TIMEOUT = None


def _capability_of(dep: object) -> str:
    """Best-effort capability name from a dependency declaration entry."""
    if isinstance(dep, dict):
        return str(dep.get("capability", dep))
    return str(dep)


def collect_pending_settle_deps(
    settle_keys: Optional[list],
    dependencies: list,
    injected_deps_array: list,
    get_dependency_fn,
    call_kwargs: Optional[dict] = None,
    settle_params: Optional[list] = None,
) -> list[tuple[str, str]]:
    """Declared-but-unresolved deps the wrapper is about to inject.

    Returns ``[(dep_key, capability), ...]`` — empty when the agent is
    settled (the steady-state fast path: a single latch check, no wait
    primitives touched), when no settle keys exist, or when everything the
    wrapper would inject already has a proxy.

    ``settle_keys`` is index-aligned with ``dependencies``; ``None``
    entries mark slots the settle grace does not cover (MeshJob submitter
    slots, excess dependencies with no parameter to land in).

    ``settle_params`` (index-aligned parameter names) + ``call_kwargs``
    implement the caller-supplied skip: a slot the caller explicitly
    filled — the documented mock contract that lets tests pass a fake for
    any injectable parameter — is never waited on (the injection path
    will keep the caller's value untouched anyway).
    """
    if not settle_keys:
        return []
    state = get_settle_state()
    if state.is_settled():
        return []
    pending: list[tuple[str, str]] = []
    for dep_index, dep_key in enumerate(settle_keys):
        if dep_key is None:
            continue
        if (
            call_kwargs
            and settle_params is not None
            and dep_index < len(settle_params)
            and settle_params[dep_index] is not None
            and call_kwargs.get(settle_params[dep_index]) is not None
        ):
            # Caller-supplied slot (documented mock contract) — the
            # injection path preserves the caller's value, so there is
            # nothing to wait for.
            continue
        resolved = None
        if dep_index < len(injected_deps_array):
            resolved = injected_deps_array[dep_index]
        if resolved is None:
            resolved = get_dependency_fn(dep_key)
        if resolved is None:
            pending.append((dep_key, _capability_of(dependencies[dep_index])))
    return pending


def wait_for_settle_sync(
    pending: list[tuple[str, str]], log: logging.Logger
) -> None:
    """Blocking settle wait for sync wrappers (worker-thread dispatch).

    Waits each pending dependency in turn; the per-wait budget is the
    REMAINING window, so the total wait is bounded by the settle window
    regardless of how many deps are pending.

    Defensive guard: if this is ever invoked ON a running event loop
    (a dispatch path we don't model calling the sync wrapper inline), the
    wait is SKIPPED — blocking that loop would stall the very machinery
    that delivers the resolution events, turning the grace into a
    guaranteed dead wait. Skipping degrades to today's None-injection.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        log.debug(
            "settle wait skipped: sync wrapper invoked on a running event "
            "loop — blocking here would stall the loop that delivers the "
            "resolution events; proceeding without the grace"
        )
        return
    state = get_settle_state()
    for dep_key, capability in pending:
        state.wait_for(dep_key, capability, log)


async def wait_for_settle_async(
    pending: list[tuple[str, str]], log: logging.Logger
) -> None:
    """Settle wait for async wrappers — never blocks the event loop.

    Awaits loop-native :class:`asyncio.Event` mirrors set by the
    resolution funnel via ``call_soon_threadsafe`` — no thread pool, no
    executor pressure, cancellable, and shutdown-friendly (see
    :meth:`SettleState.wait_for_async`).
    """
    state = get_settle_state()
    for dep_key, capability in pending:
        await state.wait_for_async(dep_key, capability, log)
