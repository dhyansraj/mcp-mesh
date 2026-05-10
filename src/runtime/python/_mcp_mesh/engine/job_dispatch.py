"""Inbound MeshJob dispatch wrapper (Phase 1 — MeshJob substrate).

This module wires the producer-side dispatch path: when a tool decorated
with ``@mesh.tool(task=True)`` receives an inbound ``tools/call`` bearing
``X-Mesh-Job-Id``, the wrapper:

1. Reads ``X-Mesh-Job-Id`` and (optionally) ``X-Mesh-Timeout`` from the
   active propagated-headers contextvar (populated by the FastMCP session
   middleware in ``http_wrapper.py``).
2. Builds a :class:`mcp_mesh_core.JobController` bound to that job id and
   the running agent's instance id.
3. Sets both the Python :data:`CURRENT_JOB` contextvar and (via
   :func:`mcp_mesh_core.with_job_async`) the Rust core's
   ``job_context::CURRENT_JOB`` task-local, plus the cancel-registry
   entry under the job id.
4. Injects the controller into the user function's ``mesh_job_param_name``
   kwarg.
5. Awaits the user function inside both contexts.
6. Cleans up both contexts on exit (including the panic / exception path).

Tools without ``task=True`` are bypassed entirely (zero overhead). Tools
with ``task=True`` invoked WITHOUT ``X-Mesh-Job-Id`` (a regular synchronous
``tools/call``) fall through to the user function with ``None`` in the
MeshJob slot — per :file:`MESHJOB_DDDI_CONTRACT.md` "Tool invocation: when
``MeshJob`` is present but the call is NOT a job".

The dispatch logic is centralised here so the per-decorator wrapper
created by :func:`_mcp_mesh.engine.dependency_injector.create_injection_wrapper`
can call into it without re-implementing the contract.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Optional

from .job_context import CURRENT_JOB, JobContextSnapshot

logger = logging.getLogger(__name__)


# Cancel-watcher helper for issue #882 Part A. Older mcp-mesh-core
# builds may not export this — degrade gracefully (handler runs to
# natural completion as before, no cancel observability).
try:
    from mcp_mesh_core import await_job_cancel as _await_job_cancel
except ImportError:
    _await_job_cancel = None


# Header names — lowercased to match how the FastMCP middleware stores
# captured inbound headers (via ``str.lower()`` in
# ``http_wrapper.py::MCPSessionRoutingMiddleware.dispatch``).
_HDR_JOB_ID = "x-mesh-job-id"
_HDR_TIMEOUT = "x-mesh-timeout"


def _read_job_headers() -> tuple[Optional[str], Optional[float]]:
    """Pull ``X-Mesh-Job-Id`` / ``X-Mesh-Timeout`` from the propagated-
    headers contextvar populated by the MCP session middleware.

    Returns ``(job_id, deadline_secs_remaining)`` — either may be ``None``.

    Defensive: never raises. If the trace-context module is somehow not
    importable (test harness with stubs), returns ``(None, None)``.
    """
    try:
        from ..tracing.context import TraceContext
    except Exception:
        return None, None

    headers = TraceContext.get_propagated_headers() or {}
    if not headers:
        return None, None

    # Header dict is lowercased by the middleware before storing.
    job_id = headers.get(_HDR_JOB_ID)
    if not job_id:
        return None, None

    timeout_raw = headers.get(_HDR_TIMEOUT)
    deadline_secs: Optional[float] = None
    if timeout_raw:
        try:
            deadline_secs = float(timeout_raw)
            if deadline_secs <= 0:
                deadline_secs = None
        except (TypeError, ValueError):
            logger.debug(
                "job_dispatch: ignoring malformed %s header value %r",
                _HDR_TIMEOUT,
                timeout_raw,
            )
            deadline_secs = None
    return job_id, deadline_secs


def _resolve_runtime_identity() -> tuple[Optional[str], Optional[str]]:
    """Resolve ``(registry_url, instance_id)`` for constructing a
    JobController. Both are needed:

    * ``registry_url`` — the controller flushes terminal deltas (and
      progress, via the batching tick) directly to the registry's
      ``/jobs/batch`` endpoint.
    * ``instance_id`` — written into ``owner_instance_id`` on each delta
      so the registry can correlate this replica with claimed work.

    The ``instance_id`` MUST match the value the claim worker sent on
    ``POST /jobs/claim`` AND the value heartbeat registers with the
    registry — otherwise the registry rejects deltas as ``not_owner``
    and progress / terminal updates silently drop.

    The single source of truth is
    :meth:`_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_resolved_agent_config`
    (specifically the ``agent_id`` key). That same value is what the
    configuration step writes into the pipeline context, what the
    heartbeat sends on registration, and what the claim worker reads —
    so reading from it here closes the instance_id mismatch loop with
    ZERO parallel resolution chains.

    Returns ``(None, None)`` when either piece is missing — the wrapper
    treats that as "job dispatch not available; fall through to a regular
    call". The user function still runs; only the MeshJob slot stays
    ``None``.
    """
    registry_url = os.environ.get("MCP_MESH_REGISTRY_URL")
    instance_id: Optional[str] = None
    try:
        from .decorator_registry import DecoratorRegistry

        cfg = DecoratorRegistry.get_resolved_agent_config()
        if isinstance(cfg, dict):
            candidate = cfg.get("agent_id")
            if candidate and candidate != "unknown":
                instance_id = candidate
    except Exception as e:
        logger.debug(
            "job_dispatch: DecoratorRegistry.get_resolved_agent_config "
            "unavailable (%s); cannot resolve instance_id",
            e,
        )

    if not registry_url or not instance_id:
        return None, None
    return registry_url, instance_id


def is_task_tool(func: Any) -> bool:
    """Return ``True`` iff the function is decorated with
    ``@mesh.tool(task=True)``.

    Reads the metadata stamped by the decorator (see
    ``mesh/decorators.py::tool``). Returns ``False`` defensively if the
    metadata is missing — non-task tools must NOT pay the dispatch cost.
    """
    meta = _read_tool_metadata(func)
    if meta is None:
        return False
    return bool(meta.get("task"))


def _read_tool_metadata(func: Any) -> Optional[dict]:
    """Resolve the @mesh.tool metadata dict from ``func``, following the
    wrapper chain (``_mesh_original_func``) so wrapped DI/isolation
    layers don't hide the decorator's intent.

    Returns ``None`` when no metadata is stamped on either the function
    or its underlying original.
    """
    meta = getattr(func, "_mesh_tool_metadata", None)
    if not isinstance(meta, dict):
        original = getattr(func, "_mesh_original_func", None)
        if original is not None:
            meta = getattr(original, "_mesh_tool_metadata", None)
    if not isinstance(meta, dict):
        return None
    return meta


def get_retry_on(func: Any) -> tuple:
    """Return the ``retry_on`` exception-class tuple stamped by
    ``@mesh.tool(retry_on=(...))`` (issue #879).

    Defaults to an empty tuple when the metadata is missing or the kwarg
    was not set — preserving the existing "every raise → fail" behaviour
    for tools that don't opt in.
    """
    meta = _read_tool_metadata(func)
    if meta is None:
        return ()
    raw = meta.get("retry_on")
    if isinstance(raw, tuple):
        return raw
    return ()


def get_mesh_job_param_name(func: Any) -> Optional[str]:
    """Return the function's ``MeshJob`` parameter name, or ``None`` if
    the function does not declare one.

    Resolves via the DDDI contract analyzer
    (:func:`signature_analyzer.analyze_mesh_job_signature`). Failures
    (forward-ref resolution, missing imports) degrade to ``None`` —
    same defensive posture used elsewhere in the engine.
    """
    try:
        from .signature_analyzer import analyze_mesh_job_signature

        resolution = analyze_mesh_job_signature(func)
        return resolution.mesh_job_param_name
    except Exception as e:
        logger.debug(
            "job_dispatch: analyze_mesh_job_signature failed for %s: %s", func, e
        )
        return None


async def maybe_dispatch_as_job(
    func: Any,
    invoke: Callable[[dict], Awaitable[Any]],
    final_kwargs: dict,
) -> Any:
    """Run ``invoke(kwargs)`` either inside a job context (when an
    inbound ``X-Mesh-Job-Id`` is present and ``func`` is a task tool) or
    directly (otherwise).

    Returns the user function's result verbatim. Never injects job
    semantics into a tool that wasn't decorated ``task=True`` — the
    decorator's intent is the source of truth.

    Args:
        func: The original (or wrapped) user tool function. Used for
            metadata lookups (``task=True`` flag, MeshJob param name) only.
        invoke: A coroutine factory that, given a kwargs dict, returns
            the awaitable invocation of the user function. Wrappers
            already handle DI, tracing, isolation, etc.; this layer just
            wraps the call in a job-context scope.
        final_kwargs: The kwargs dict the wrapper would otherwise pass
            to ``invoke``. The MeshJob param is overlaid on this dict
            when dispatch is active.

    Returns:
        Whatever ``invoke`` returns.
    """
    # Fast bail: not a task tool → no dispatch logic at all (zero overhead).
    if not is_task_tool(func):
        return await invoke(final_kwargs)

    job_id, deadline_secs = _read_job_headers()
    mesh_job_param = get_mesh_job_param_name(func)

    # Ensure the MeshJob param defaults to ``None`` — this is what the
    # contract promises tools that declare ``MeshJob`` but are invoked
    # via a regular tools/call. Done unconditionally so the param is
    # always present in kwargs.
    if mesh_job_param and mesh_job_param not in final_kwargs:
        final_kwargs[mesh_job_param] = None

    if not job_id:
        # task=True tool invoked synchronously (no X-Mesh-Job-Id).
        # Per contract: pass ``None`` in the slot, run as a regular call.
        logger.debug(
            "job_dispatch: %s is task=True but no X-Mesh-Job-Id header; "
            "running as regular tools/call",
            getattr(func, "__name__", "?"),
        )
        return await invoke(final_kwargs)

    registry_url, instance_id = _resolve_runtime_identity()
    if not registry_url or not instance_id:
        logger.warning(
            "job_dispatch: %s received X-Mesh-Job-Id=%s but registry_url / "
            "instance_id is not resolvable (need MCP_MESH_REGISTRY_URL plus a "
            "DecoratorRegistry-resolved agent_id — set MCP_MESH_AGENT_ID for "
            "an explicit override); falling back to a regular call",
            getattr(func, "__name__", "?"),
            job_id,
        )
        return await invoke(final_kwargs)

    # Build the controller. Failure here (e.g. unreachable registry at
    # construction time) is logged and downgraded to a regular call so
    # the user function still runs.
    try:
        from mcp_mesh_core import JobController as PyJobController
    except Exception as e:
        logger.warning(
            "job_dispatch: mcp_mesh_core.JobController unavailable (%s); "
            "running %s as a regular call",
            e,
            getattr(func, "__name__", "?"),
        )
        return await invoke(final_kwargs)

    try:
        controller = PyJobController(job_id, instance_id, registry_url)
    except Exception as e:
        logger.warning(
            "job_dispatch: failed to construct JobController for job=%s "
            "(%s); running %s as a regular call",
            job_id,
            e,
            getattr(func, "__name__", "?"),
        )
        return await invoke(final_kwargs)

    if mesh_job_param:
        final_kwargs[mesh_job_param] = controller

    retry_on = get_retry_on(func)

    async def _run_and_autocomplete() -> Any:
        """Invoke the user function and, if it returned without calling
        ``job.complete(...)`` / ``job.fail(...)`` itself, auto-complete
        with the return value.

        Why this exists: a tool decorated ``task=True`` whose body never
        explicitly closes the row would otherwise stay in ``working``
        until the lease expires (~lease_ttl seconds, typically minutes)
        and the registry sweep marked it failed/orphaned. From the
        caller's point of view the job hung. Auto-completion mirrors the
        "synchronous tool returns -> tools/call response" contract for
        the regular path: when a task-tool returns cleanly, it's done.

        The ``is_terminal()`` query is the source of truth — users who
        DID call ``await job.complete(...)`` themselves already marked
        the queue terminal, and we MUST NOT double-flush (the second
        complete would race with a possibly-arrived progress update on
        another replica and confuse the registry's `not_owner` checks).

        Handler exception handling (issue #879):
          - If ``retry_on`` is set on the @mesh.tool decorator and the
            raised exception matches via ``isinstance``, we call
            ``controller.release_lease(reason)`` so a peer replica can
            re-claim within ~5s. The exception is then SUPPRESSED — the
            dispatch task ends cleanly because the job lifecycle is
            now the registry's concern.
          - If release_lease itself fails (network blip etc.), we fall
            back to ``controller.fail(...)`` so the row doesn't sit in
            ``working`` until the lease expires.
          - If the exception doesn't match retry_on, we propagate up
            through the wrapper chain (existing behaviour). The
            inbound HTTP path or registry sweep is the backstop.

        Cancel observability (issue #882 Part A):
          The user's coroutine is wrapped in an asyncio.Task and raced
          against ``await_job_cancel(job_id)`` — a coroutine that
          resolves when EITHER the cancel-registry token fires
          (explicit cancel via ``POST /jobs/:id/cancel``) OR the
          registry unregisters the job naturally (handler returned).
          When cancel wins the race, the user task is cancelled so
          ``await asyncio.sleep`` / network IO inside the handler
          propagates ``CancelledError`` naturally — without this, a
          handler napping in ``await asyncio.sleep(30)`` would not
          observe a Tokio-side cancel token and would run to natural
          completion despite the registry having flipped the row to
          ``cancelled``. Mirrors the TS SDK's ``awaitJobCancel`` race
          (PR #897) and the Java SDK's ``controller.isCancelled()``
          poll (PR #891).
        """
        try:
            if _await_job_cancel is None:
                result = await invoke(final_kwargs)
            else:
                user_task = asyncio.create_task(
                    invoke(final_kwargs), name=f"mesh-job-{job_id}-user"
                )
                # ``_await_job_cancel`` is a pyo3-async helper that
                # returns a Future (not a coroutine) — use
                # ``ensure_future`` so we accept either shape (the
                # Python-side fallback in some test mocks may return a
                # coroutine instead).
                cancel_watcher = asyncio.ensure_future(
                    _await_job_cancel(job_id)
                )
                done, pending = await asyncio.wait(
                    {user_task, cancel_watcher},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Prefer the user task whenever it's done — even if the
                # cancel-watcher also completed in the same tick (e.g. the
                # job was never registered, so the watcher resolved
                # immediately on its first poll). This keeps the path
                # deterministic for tests + for jobs that finish before
                # the watcher gets to schedule.
                if user_task.done():
                    # Drain the watcher so it doesn't linger in the loop.
                    if not cancel_watcher.done():
                        cancel_watcher.cancel()
                    try:
                        await cancel_watcher
                    except asyncio.CancelledError:
                        pass
                    if user_task.cancelled():
                        # External cancel (loop shutdown, anyio CancelScope, signal) —
                        # propagate so structured-concurrency semantics are preserved.
                        # NOT the watcher-fired cancel path (that's the `else` branch).
                        raise asyncio.CancelledError()
                    user_exc = user_task.exception()
                    if user_exc is not None:
                        raise user_exc
                    result = user_task.result()
                else:
                    # Cancel-watcher resolved before the user task.
                    # Defensive: if the watcher resolved with an
                    # exception (rare; would indicate a pyo3-runtime
                    # issue, not a real cancel), DON'T cancel the user
                    # task — log and let the user task continue to
                    # natural completion. Calling .exception() also
                    # consumes it so asyncio doesn't log "Task
                    # exception was never retrieved" at GC time.
                    watcher_exc = cancel_watcher.exception()
                    if watcher_exc is not None:
                        logger.warning(
                            "job_dispatch: cancel-watcher for job=%s "
                            "resolved with exception (%s); ignoring "
                            "spurious signal and awaiting user task",
                            job_id,
                            watcher_exc,
                        )
                        await user_task
                        if user_task.cancelled():
                            raise asyncio.CancelledError()
                        user_exc = user_task.exception()
                        if user_exc is not None:
                            raise user_exc
                        result = user_task.result()
                    else:
                        # Belt-and-braces guard against a spurious
                        # cancel-watcher resolution. A real cancel goes
                        # through the registry's CancelJob handler, which
                        # marks the row terminal BEFORE firing the
                        # process-wide token — so a true cancel implies
                        # ``controller.is_terminal()`` is True. If the
                        # registry is NOT terminal, the watcher resolved
                        # for some other reason (historically: a
                        # registration race in the Rust core where the
                        # watcher polled before ``register_active_job``
                        # ran and saw "no entry → resolve immediately").
                        # Treat that case as spurious and let the user
                        # task run to natural completion instead of
                        # cancelling it. Mirrors the existing
                        # ``watcher_exc is not None`` arm above.
                        try:
                            registry_terminal = await controller.is_terminal()
                        except Exception as is_terminal_exc:
                            logger.warning(
                                "job_dispatch: failed to query is_terminal for job=%s "
                                "(%s); assuming watcher signal is real",
                                job_id,
                                is_terminal_exc,
                            )
                            registry_terminal = True

                        if not registry_terminal:
                            logger.warning(
                                "job_dispatch: cancel-watcher for job=%s resolved without "
                                "terminal state — treating as spurious and awaiting user task",
                                job_id,
                            )
                            await user_task
                            if user_task.cancelled():
                                raise asyncio.CancelledError()
                            user_exc = user_task.exception()
                            if user_exc is not None:
                                raise user_exc
                            result = user_task.result()
                        else:
                            # Cancel arrived first — abort the user's task
                            # so `await asyncio.sleep` / network IO inside
                            # the handler raises CancelledError. The
                            # registry's CancelJob handler already flipped
                            # the row to cancelled (the cancel route is
                            # what fired the token), so there's nothing
                            # for us to do beyond returning None.
                            user_task.cancel()
                            try:
                                await user_task
                            except asyncio.CancelledError:
                                logger.info(
                                    "job_dispatch: user task for job=%s cancelled via "
                                    "cancel-watcher; registry owns terminal state",
                                    job_id,
                                )
                                return None
                            # User caught CancelledError, did cleanup, and returned normally.
                            # Honor their result — fall through to auto-complete logic with
                            # the captured value. Note: a non-CancelledError exception falls
                            # out to the outer `except Exception as exc:` block and runs the
                            # existing retry_on / fail handling.
                            result = user_task.result()
        except Exception as exc:
            # If the user already called complete/fail explicitly, leave
            # state alone — the user's terminal call is the source of truth.
            try:
                already_terminal = await controller.is_terminal()
            except Exception:
                already_terminal = False
            if already_terminal:
                raise

            if retry_on and isinstance(exc, retry_on):
                reason = f"{type(exc).__name__}: {exc}"
                try:
                    await controller.release_lease(reason=reason)
                    logger.info(
                        "job_dispatch: retry_on match for job=%s (%s); "
                        "released lease for fast retry",
                        job_id,
                        reason,
                    )
                    # Suppress the exception: the job lifecycle is now
                    # the registry's responsibility (re-claim within
                    # ~5s, or mark exhausted/failed if the increment
                    # tipped attempt_count past max_retries).
                    return None
                except Exception as release_err:
                    logger.warning(
                        "job_dispatch: release_lease failed for job=%s "
                        "(%s); falling back to fail() so the row doesn't "
                        "sit in working until lease expiry",
                        job_id,
                        release_err,
                    )
                    try:
                        await controller.fail(
                            f"retry-eligible {reason}; "
                            f"release_lease failed: {release_err}"
                        )
                    except Exception as fail_err:
                        logger.debug(
                            "job_dispatch: fallback fail() also failed for "
                            "job=%s: %s",
                            job_id,
                            fail_err,
                        )
                    return None
            # Non-retryable exception: existing behaviour — propagate up.
            raise

        try:
            already_terminal = await controller.is_terminal()
        except Exception as e:
            logger.debug(
                "job_dispatch: is_terminal probe failed for job=%s (%s); "
                "skipping auto-complete to avoid double-flush",
                job_id,
                e,
            )
            return result
        if already_terminal:
            return result
        try:
            # Wrap non-JSON-serialisable returns in {"value": str(...)}
            # so Rust's ``serde_json::Value`` serialisation doesn't blow
            # up on application returns that are e.g. dataclasses or
            # bytes. The framework owns this auto-call so it can be
            # opinionated; users wanting a structured terminal payload
            # call ``await job.complete(...)`` explicitly.
            await controller.complete(result if _is_json_safe(result) else {"value": str(result)})
            logger.debug(
                "job_dispatch: auto-completed job=%s with handler return value",
                job_id,
            )
        except Exception as e:
            logger.warning(
                "job_dispatch: auto-complete for job=%s failed (%s); "
                "registry sweep will eventually mark the row terminal",
                job_id,
                e,
            )
        return result

    # Bind the Python contextvar so user code (and the outbound proxy
    # inside this Python process) can observe the active job.
    snap = JobContextSnapshot(
        job_id=job_id, deadline_secs_remaining=deadline_secs
    )
    token = CURRENT_JOB.set(snap)
    try:
        # Bind the Rust task-local + cancel registry entry via the FFI
        # helper. The user function call is passed as a Python awaitable
        # so it executes inside the run_as_job scope on the Rust side.
        try:
            from mcp_mesh_core import with_job_async
        except Exception:
            with_job_async = None  # type: ignore[assignment]

        if with_job_async is not None:
            return await with_job_async(
                job_id, deadline_secs, _run_and_autocomplete()
            )
        else:
            # Defensive fallback: if the FFI helper isn't available
            # (e.g. older mcp-mesh-core .so), still run the user
            # function with the Python contextvar set. Outbound HTTP
            # via the unified proxy reads the Python contextvar
            # directly, so X-Mesh-Job-Id propagation still works for
            # Python-originated downstream calls — only the Rust-core
            # task-local is missing.
            logger.debug(
                "job_dispatch: with_job_async not available; running with "
                "Python contextvar only (Rust task-local will not be set)"
            )
            return await _run_and_autocomplete()
    finally:
        CURRENT_JOB.reset(token)


def _is_json_safe(value: Any) -> bool:
    """Cheap check: is ``value`` losslessly representable in JSON?

    Used to decide whether to pass a handler's return verbatim into
    ``controller.complete(...)`` or wrap it in a string envelope. We
    don't try to be exhaustive — primitives, lists, dicts of the same
    are safe; anything else falls through to the str() envelope so the
    Rust JSON layer doesn't error inside the auto-complete path.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return all(_is_json_safe(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_json_safe(v) for k, v in value.items())
    return False
