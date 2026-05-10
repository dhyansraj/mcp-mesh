"""Consumer-side A2A primitives — A2AClient, A2ABearer, A2AResponse,
A2AJob, A2AStream, A2AEvent.

The producer-side surface (``@mesh.a2a`` + ``mesh.a2a.mount``) lets a
mesh agent expose a tool over A2A v1.0. This module is the mirror image:
a thin async client a mesh agent uses to CALL an external A2A endpoint
synchronously and re-publish the result as a regular mesh capability.

Typical use is via the ``@mesh.a2a_consumer`` decorator (see
``mesh.decorators.a2a_consumer``) which constructs a per-tool
``A2AClient`` instance and injects it into the user function as the
``_a2a`` keyword argument. Direct construction is supported for
advanced cases (e.g. dynamic endpoint per call, custom polling).

Phase 1 covers sync ``tasks/send`` + poll-until-terminal via
``tasks/get``. Phase 3 adds the long-running primitives:
``A2AClient.submit`` returns an ``A2AJob`` handle for non-blocking
submit + ``tasks/get`` polling, ``A2AClient.subscribe`` returns an
``A2AStream`` async iterator over ``tasks/sendSubscribe`` SSE events.
Both expose a ``bridge(mesh_job)`` convenience that mirrors the
remote A2A task into a mesh ``MeshJob`` (JobController) for the
typical ``task=True`` consumer pattern.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .types import MeshJob

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Active A2AClient tracking — atexit drain (mirrors simple_shutdown.py pattern
# for Rust agent handles). httpx.AsyncClient bound to a torn-down loop emits
# noisy "Unclosed client" warnings at GC. We mark every live client closed at
# interpreter exit so any in-flight user code raises cleanly; httpx's own GC
# + the OS reclaim the actual sockets. No async aclose() in the atexit hook —
# interpreter is finalizing and there's no guaranteed loop to await on.
# ---------------------------------------------------------------------------
_ACTIVE_CLIENTS: "weakref.WeakSet[A2AClient]" = weakref.WeakSet()
_ATEXIT_LOCK = threading.Lock()
_ATEXIT_HOOK_REGISTERED = False


def _register_active_client(client: "A2AClient") -> None:
    global _ATEXIT_HOOK_REGISTERED
    with _ATEXIT_LOCK:
        _ACTIVE_CLIENTS.add(client)
        if not _ATEXIT_HOOK_REGISTERED:
            atexit.register(_atexit_close_active_clients)
            _ATEXIT_HOOK_REGISTERED = True


def _atexit_close_active_clients() -> None:
    """At interpreter exit: mark every living A2AClient closed so any
    in-flight user code raises cleanly. We don't await aclose() here —
    interpreter is finalizing and there's no guaranteed event loop to
    drive the async close. httpx's own GC + the OS reclaim the sockets;
    the explicit close-flag prevents post-finalize use of cached state.
    """
    for client in list(_ACTIVE_CLIENTS):
        try:
            client._closed = True
        except Exception:
            pass


@dataclass
class A2ABearer:
    """Bearer-token credential for an outbound A2A call.

    Provide either ``token`` (literal) or ``token_env`` (name of an env
    var that holds the token). Resolution happens at header-build time
    so rotating the env var between calls picks up the new value
    without re-decorating the consumer. Raises ``RuntimeError`` if
    neither source yields a value.
    """

    token_env: Optional[str] = None
    token: Optional[str] = None

    def header(self) -> dict[str, str]:
        tok = self.token or (os.getenv(self.token_env) if self.token_env else None)
        if not tok:
            raise RuntimeError(
                f"A2ABearer: no token available "
                f"(token_env={self.token_env!r}, "
                f"explicit_token={'set' if self.token else 'unset'})"
            )
        return {"Authorization": f"Bearer {tok}"}


@dataclass
class A2AResponse:
    """Result of a synchronous ``A2AClient.send`` call.

    ``artifact_text`` is the canonical sync return — the producer-side
    surface places the handler's return value as
    ``result.artifacts[0].parts[0].text`` and JSON-stringifies non-string
    returns. Consumers that need the raw envelope (multi-artifact
    responses, status messages, history) can read ``raw_task``.
    """

    artifact_text: str
    state: str
    task_id: str
    raw_task: dict[str, Any]


class A2AClient:
    """Thin async A2A v1.0 client — sync ``tasks/send`` + poll until terminal.

    One instance per (url, skill_id, auth) tuple — the ``@mesh.a2a_consumer``
    decorator constructs one per decorated function and reuses it across
    calls to amortize the underlying ``httpx.AsyncClient`` connection
    pool. Direct construction is supported for users who need finer
    control (e.g. dynamic URL per call).

    ``send`` POSTs a JSON-RPC ``tasks/send`` request, then polls
    ``tasks/get`` with exponential-ish backoff (capped at
    ``poll_interval_max``) until the task reaches a terminal state
    (``completed`` / ``failed`` / ``canceled``) or ``timeout`` elapses.
    """

    def __init__(
        self,
        url: str,
        skill_id: str,
        auth: Optional[A2ABearer] = None,
        timeout_default: float = 30.0,
        poll_interval: float = 0.5,
        poll_interval_max: float = 2.0,
    ):
        self.url = url.rstrip("/")
        self.skill_id = skill_id
        self.auth = auth
        self.timeout_default = timeout_default
        self.poll_interval = poll_interval
        self.poll_interval_max = poll_interval_max
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed: bool = False
        _register_active_client(self)

    async def _http(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError(
                f"A2AClient(url={self.url!r}) is closed. "
                "Create a new instance instead of reusing a closed one."
            )
        loop = asyncio.get_running_loop()
        if (
            self._client is not None
            and self._client_loop is loop
            and not self._client.is_closed
        ):
            return self._client
        # Loop mismatch (fork-after-import, pytest-asyncio new-loop-per-test,
        # or any other multi-loop scenario) OR no client yet OR client closed.
        # Drop the old reference and let GC handle it — closing an
        # AsyncClient from a different loop than its origin is undefined
        # behavior in httpx.
        # Fork-after-import caveat: this swap is steady-state safe but does NOT
        # protect coroutines mid-call holding the previous client when the loop
        # transitions (e.g., os.fork after import). Drain in-flight work before
        # forking, or use a per-process A2AClient instance.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_default))
        self._client_loop = loop
        return self._client

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.auth:
            h.update(self.auth.header())
        return h

    async def _post_jsonrpc(
        self,
        method: str,
        params: dict[str, Any],
        rpc_id: int = 1,
        request_timeout: Any = httpx.USE_CLIENT_DEFAULT,
    ) -> dict[str, Any]:
        client = await self._http()
        envelope = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        # Default sentinel preserves the AsyncClient construction-time timeout
        # for callers that don't pass an override (passing `None` to httpx
        # would disable the timeout entirely, not fall back to the default).
        # send() passes the per-call remaining-deadline so individual calls
        # (initial tasks/send + each tasks/get poll) honor the user override.
        resp = await client.post(
            self.url, headers=self._headers(), json=envelope, timeout=request_timeout
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            err = body["error"]
            raise RuntimeError(
                f"A2A error from {self.url}: "
                f"{err.get('code')} {err.get('message')}"
            )
        return body.get("result", {})

    async def send(
        self,
        message: dict[str, Any],
        *,
        task_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> A2AResponse:
        """POST ``tasks/send`` and poll ``tasks/get`` until terminal.

        ``message`` is the A2A v1.0 request message dict (typically
        ``{"role": "user", "parts": [{"type": "text", "text": "..."}]}``).
        Returns an ``A2AResponse`` whose ``artifact_text`` carries the
        producer-side handler's return value (JSON-stringified for
        non-string returns — match the producer convention with
        ``json.loads`` on the consumer side when the upstream returns a
        dict).

        Raises ``TimeoutError`` if the task does not reach a terminal
        state within ``timeout`` seconds (defaults to
        ``timeout_default``). Raises ``RuntimeError`` for JSON-RPC error
        envelopes from the producer.
        """
        timeout = timeout if timeout is not None else self.timeout_default
        deadline = time.monotonic() + timeout
        if task_id is None:
            task_id = f"c-{uuid.uuid4().hex}"

        remaining = max(0.001, deadline - time.monotonic())
        result = await self._post_jsonrpc(
            "tasks/send",
            {"id": task_id, "message": message},
            rpc_id=1,
            request_timeout=remaining,
        )
        state = (result.get("status") or {}).get("state", "unknown")

        if _is_terminal(state):
            return self._build_response(task_id, result)

        interval = self.poll_interval
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            remaining = max(0.001, deadline - time.monotonic())
            result = await self._post_jsonrpc(
                "tasks/get",
                {"id": task_id},
                rpc_id=2,
                request_timeout=remaining,
            )
            state = (result.get("status") or {}).get("state", "unknown")
            if _is_terminal(state):
                return self._build_response(task_id, result)
            interval = min(self.poll_interval_max, interval * 1.5)

        raise TimeoutError(
            f"A2A task {task_id!r} on {self.url} did not reach terminal "
            f"state within {timeout}s (last state={state!r})"
        )

    def _build_response(self, task_id: str, result: dict[str, Any]) -> A2AResponse:
        artifacts = result.get("artifacts") or []
        artifact_text = ""
        if artifacts and isinstance(artifacts[0], dict):
            parts = artifacts[0].get("parts") or []
            if parts and isinstance(parts[0], dict):
                artifact_text = parts[0].get("text", "")
        return A2AResponse(
            artifact_text=artifact_text,
            state=(result.get("status") or {}).get("state", "unknown"),
            task_id=task_id,
            raw_task=result,
        )

    async def submit(
        self,
        message: dict[str, Any],
        *,
        task_id: Optional[str] = None,
    ) -> "A2AJob":
        """POST ``tasks/send`` and return an ``A2AJob`` handle WITHOUT polling.

        Use this when the surrounding @mesh.tool is decorated with
        ``task=True`` and the bridging logic wants explicit control over
        when to poll (typically via ``A2AJob.bridge(mesh_job)`` which
        mirrors progress into the framework-injected ``MeshJob``).

        ``message`` is the A2A v1.0 request message dict (typically
        ``{"role": "user", "parts": [{"type": "text", "text": "..."}]}``).
        Raises ``RuntimeError`` for JSON-RPC error envelopes from the
        producer; non-error responses with any state (working / completed
        / failed / canceled) return an ``A2AJob`` so callers can decide
        whether to poll, bridge, or exit early.
        """
        if task_id is None:
            task_id = f"c-{uuid.uuid4().hex}"

        result = await self._post_jsonrpc(
            "tasks/send",
            {"id": task_id, "message": message},
            rpc_id=1,
            request_timeout=self.timeout_default,
        )
        state = (result.get("status") or {}).get("state", "unknown")
        return A2AJob(
            client=self,
            task_id=task_id,
            initial_state=state,
            initial_result=result,
        )

    async def subscribe(
        self,
        message: dict[str, Any],
        *,
        task_id: Optional[str] = None,
    ) -> "A2AStream":
        """POST ``tasks/sendSubscribe`` and return an async iterator of A2AEvent.

        The returned stream MUST be either iterated to completion OR
        explicitly ``aclose()``-d to release the underlying connection.
        ``async with`` is supported via the stream's async context-manager
        protocol.

        ``message`` is the A2A v1.0 request message dict — same shape as
        ``send`` and ``submit``. The stream's first event is normally a
        ``state="working"`` status; subsequent events carry progress
        updates and the final ``artifact`` event before the producer
        closes the stream.
        """
        if task_id is None:
            task_id = f"c-{uuid.uuid4().hex}"

        client = await self._http()
        envelope = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/sendSubscribe",
            "params": {"id": task_id, "message": message},
        }
        headers = self._headers()
        headers["Accept"] = "text/event-stream"

        # AsyncClient.stream returns a context manager that owns the
        # response; we manually __aenter__ here and stash the manager on
        # the stream so A2AStream.aclose can __aexit__ it later. This is
        # the documented pattern for "open the response, hand it off,
        # close it elsewhere" — see httpx docs on streaming responses.
        cm = client.stream(
            "POST",
            self.url,
            headers=headers,
            json=envelope,
            timeout=None,
        )
        response = await cm.__aenter__()
        try:
            response.raise_for_status()
        except Exception:
            await cm.__aexit__(None, None, None)
            raise
        return A2AStream(response=response, task_id=task_id, _cm=cm)

    async def aclose(self) -> None:
        self._closed = True
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                # Best-effort: a loop-mismatched close (e.g. pytest-asyncio
                # tearing down a previous loop) can raise; the client is
                # marked closed regardless so subsequent _http() raises.
                pass
        self._client = None
        self._client_loop = None


# ---------------------------------------------------------------------------
# Phase 3 — long-running submit + SSE subscribe
# ---------------------------------------------------------------------------


class A2AJobError(RuntimeError):
    """Base class for A2A job terminal errors (failed / canceled)."""


class A2AJobFailed(A2AJobError):
    """A2A task reached state=failed."""


class A2AJobCanceled(A2AJobError):
    """A2A task reached state=canceled.

    Raised either when the upstream producer canceled the task OR when
    mesh-side cancellation was propagated upstream via ``tasks/cancel``
    during ``A2AJob.bridge`` / ``A2AStream.bridge``.
    """


# Mesh JobController uses UK spelling "cancelled"; A2A v1.0 uses US
# spelling "canceled". When mirroring states we accept both as the
# terminal-canceled signal.
_TERMINAL_STATES = ("completed", "failed", "canceled", "cancelled")


def _is_terminal(state: Optional[str]) -> bool:
    return state in _TERMINAL_STATES


def _build_artifact_value(result: dict[str, Any]) -> Any:
    """Return the artifact text from a Task envelope, parsed as JSON when valid.

    Mirrors the producer-side convention: handler returns are placed in
    ``artifacts[0].parts[0].text`` (JSON-stringified for non-string
    returns). On the consumer side we attempt ``json.loads`` and fall
    back to the raw text when parsing fails — primitive string returns
    survive the round-trip.
    """
    artifacts = result.get("artifacts") or []
    text = ""
    if artifacts and isinstance(artifacts[0], dict):
        parts = artifacts[0].get("parts") or []
        if parts and isinstance(parts[0], dict):
            text = parts[0].get("text", "")
    if not text:
        return text
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def _terminal_message(result: dict[str, Any]) -> str:
    """Pull a human-readable message from the terminal status, when present."""
    status = result.get("status") or {}
    msg = status.get("message")
    if isinstance(msg, dict):
        parts = msg.get("parts") or []
        if parts and isinstance(parts[0], dict):
            return str(parts[0].get("text", ""))
    return ""


@dataclass
class A2AJob:
    """A handle to a long-running A2A task — returned by ``A2AClient.submit``.

    Provides direct task lifecycle methods (``status``, ``wait``,
    ``cancel``) AND a convenience ``bridge(mesh_job)`` that mirrors A2A
    polling into a mesh ``MeshJob`` (JobController). The bridge is the
    typical pattern when the surrounding @mesh.tool is ``task=True``
    and the mesh job substrate has injected a JobController as the
    ``job`` parameter.
    """

    client: "A2AClient"
    task_id: str
    initial_state: str
    initial_result: dict[str, Any] = field(default_factory=dict)

    async def status(self) -> dict[str, Any]:
        """POST ``tasks/get`` and return the raw Task envelope's result dict."""
        return await self.client._post_jsonrpc(
            "tasks/get",
            {"id": self.task_id},
            rpc_id=2,
            request_timeout=self.client.timeout_default,
        )

    async def cancel(self, reason: Optional[str] = None) -> None:
        """POST ``tasks/cancel``. Idempotent — already-terminal tasks return cleanly."""
        params: dict[str, Any] = {"id": self.task_id}
        if reason is not None:
            params["reason"] = reason
        try:
            await self.client._post_jsonrpc(
                "tasks/cancel",
                params,
                rpc_id=3,
                request_timeout=self.client.timeout_default,
            )
        except Exception as exc:
            # Mirror the producer-side cancel posture (best-effort): the
            # remote may have already terminated the task. Log and move on
            # so callers can still raise A2AJobCanceled or similar.
            logger.info(
                "A2A tasks/cancel: remote raised for task %s on %s "
                "(may already be terminal): %s",
                self.task_id,
                self.client.url,
                exc,
            )

    async def wait(
        self,
        timeout_secs: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> "A2AResponse":
        """Poll ``tasks/get`` until terminal; return an A2AResponse on completed.

        Raises ``A2AJobFailed`` on state=failed, ``A2AJobCanceled`` on
        state=canceled, ``TimeoutError`` if ``timeout_secs`` elapses.
        ``poll_interval`` defaults to the client's ``poll_interval`` and
        backs off (1.5x per iteration) up to ``poll_interval_max``.
        """
        timeout = timeout_secs if timeout_secs is not None else self.client.timeout_default
        deadline = time.monotonic() + timeout

        # If the initial submit response was already terminal, short-circuit.
        if _is_terminal(self.initial_state) and self.initial_result:
            return self._terminal_to_response_or_raise(self.initial_result)

        interval = poll_interval if poll_interval is not None else self.client.poll_interval
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            result = await self.status()
            state = (result.get("status") or {}).get("state", "unknown")
            if _is_terminal(state):
                return self._terminal_to_response_or_raise(result)
            interval = min(self.client.poll_interval_max, interval * 1.5)

        raise TimeoutError(
            f"A2A task {self.task_id!r} on {self.client.url} did not reach "
            f"terminal state within {timeout}s"
        )

    def _terminal_to_response_or_raise(self, result: dict[str, Any]) -> "A2AResponse":
        state = (result.get("status") or {}).get("state", "unknown")
        if state == "completed":
            return self.client._build_response(self.task_id, result)
        msg = _terminal_message(result) or f"A2A task {self.task_id} state={state}"
        if state in ("canceled", "cancelled"):
            raise A2AJobCanceled(msg)
        raise A2AJobFailed(msg)

    async def bridge(
        self,
        mesh_job: "MeshJob",
        *,
        poll_interval: Optional[float] = None,
    ) -> Any:
        """Poll the A2A backend, mirror progress into ``mesh_job`` until terminal.

        Returns the final artifact value (parsed via ``json.loads`` when
        the artifact text is valid JSON, otherwise the raw text). The
        framework's ``task=True`` wrapper takes the return and calls
        ``mesh_job.complete(...)`` itself — this method only mirrors
        progress + propagates terminal state.

        Raises:
            A2AJobFailed: upstream task reached state=failed.
            A2AJobCanceled: upstream task reached state=canceled, OR
                mesh-side cancel was propagated (asyncio.CancelledError
                during the polling loop triggers ``tasks/cancel``
                upstream and re-raises as A2AJobCanceled).
        """
        interval = poll_interval if poll_interval is not None else self.client.poll_interval
        last_progress: Any = None
        last_message: Any = None

        async def _mirror(result: dict[str, Any]) -> None:
            nonlocal last_progress, last_message
            metadata = result.get("metadata") or {}
            progress = metadata.get("progress")
            status = result.get("status") or {}
            msg_obj = status.get("message")
            message: Optional[str] = None
            if isinstance(msg_obj, dict):
                parts = msg_obj.get("parts") or []
                if parts and isinstance(parts[0], dict):
                    message = parts[0].get("text")
            if progress is None and message is None:
                return
            if progress == last_progress and message == last_message:
                return
            try:
                # update_progress signature: (progress: float, message: Optional[str])
                # Coerce missing progress to last-known or 0.0 — mesh
                # requires a float, but the consumer surface allows
                # message-only progress events. Clamp to [0.0, 1.0] —
                # the MeshJob.update_progress contract expects a normalized
                # fraction; raw A2A producer progress values are advisory.
                raw_p = float(progress) if progress is not None else (last_progress or 0.0)
                p = min(1.0, max(0.0, raw_p))
                await mesh_job.update_progress(p, message)
            except Exception:
                # Do NOT advance ``last_progress`` / ``last_message`` on
                # delivery failure — leaving them stale ensures the next
                # poll's equality check sees a delta and retries the
                # update. Bumped to WARNING so transient registry
                # outages are observable in logs.
                logger.warning(
                    "A2AJob.bridge: mesh_job.update_progress failed "
                    "(task=%s, progress=%s, msg=%r) — will retry on next poll",
                    self.task_id, progress, message,
                    exc_info=True,
                )
                return
            last_progress = progress if progress is not None else last_progress
            last_message = message

        # Mirror anything carried in the initial submit response — first
        # progress event from the producer often rides on the tasks/send
        # reply rather than the first poll.
        if self.initial_result:
            try:
                await _mirror(self.initial_result)
            except Exception:
                pass

        if _is_terminal(self.initial_state) and self.initial_result:
            return self._terminal_to_artifact_or_raise(self.initial_result)

        try:
            while True:
                try:
                    result = await self.status()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # tasks/get itself failed (network error, HTTP 5xx,
                    # malformed envelope, ...). The upstream producer is
                    # almost certainly still running — best-effort POST
                    # tasks/cancel so it stops billing for work whose
                    # result we'll never observe. Cancel is best-effort:
                    # any cancel-side error is swallowed so we don't mask
                    # the original poll failure.
                    try:
                        await self.cancel(reason="consumer poll failed")
                    except Exception:
                        logger.debug(
                            "A2AJob.bridge: upstream cancel after poll "
                            "failure also failed (task=%s)",
                            self.task_id,
                            exc_info=True,
                        )
                    # Surface as A2AJobFailed so the bridging contract is
                    # consistent with terminal state=failed (the user
                    # function bubbles it; the framework calls mesh_job.fail).
                    raise A2AJobFailed(
                        f"A2A status poll failed for task {self.task_id}: {exc}"
                    ) from exc

                state = (result.get("status") or {}).get("state", "unknown")
                await _mirror(result)
                if _is_terminal(state):
                    return self._terminal_to_artifact_or_raise(result)
                await asyncio.sleep(interval)
                interval = min(self.client.poll_interval_max, interval * 1.5)
        except asyncio.CancelledError:
            # Mesh-side cancel arrived (the dispatch wrapper's
            # await_job_cancel race fired and cancelled this user task).
            # Propagate the cancel upstream so the remote producer stops
            # billing for the work, then re-raise as A2AJobCanceled so
            # the @mesh.tool wrapper records a canceled outcome.
            #
            # Shield the upstream cancel POST so a parent re-cancel doesn't
            # interrupt it mid-flight — the remote producer must observe the
            # cancel even if our own task gets cancelled again.
            try:
                await asyncio.shield(self.cancel(reason="mesh-side cancel"))
            except asyncio.CancelledError:
                # If our own task is cancelled while shield is propagating
                # the inner cancel-result, swallow — the inner POST still
                # ran (shield protects it) so the upstream is notified.
                pass
            raise A2AJobCanceled(
                f"A2A task {self.task_id} canceled by mesh-side request"
            )

    def _terminal_to_artifact_or_raise(self, result: dict[str, Any]) -> Any:
        state = (result.get("status") or {}).get("state", "unknown")
        if state == "completed":
            return _build_artifact_value(result)
        msg = _terminal_message(result) or f"A2A task {self.task_id} state={state}"
        if state in ("canceled", "cancelled"):
            raise A2AJobCanceled(msg)
        raise A2AJobFailed(msg)


@dataclass
class A2AEvent:
    """One parsed event from a ``tasks/sendSubscribe`` SSE stream.

    ``kind`` is ``"status"`` for TaskStatusUpdateEvent frames and
    ``"artifact"`` for TaskArtifactUpdateEvent frames. Status events
    carry ``state``/``progress``/``message`` (and ``final=True`` on the
    terminal frame); artifact events carry ``artifact_text``. ``raw``
    is the unparsed JSON-RPC envelope for callers that need fields the
    convenience accessors don't expose.
    """

    kind: str
    state: Optional[str] = None
    progress: Optional[float] = None
    message: Optional[str] = None
    artifact_text: Optional[str] = None
    final: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


def _parse_sse_envelope(envelope: dict[str, Any], task_id: str) -> Optional[A2AEvent]:
    """Translate one A2A v1.0 JSON-RPC SSE envelope into an A2AEvent.

    Returns ``None`` for envelopes that don't match either known shape
    (status / artifact) — callers skip them rather than fail the whole
    stream on an unrecognized frame.
    """
    result = envelope.get("result")
    if not isinstance(result, dict):
        return None

    # Artifact events have the ``artifact`` key.
    artifact = result.get("artifact")
    if isinstance(artifact, dict):
        text = ""
        parts = artifact.get("parts") or []
        if parts and isinstance(parts[0], dict):
            text = parts[0].get("text", "")
        return A2AEvent(kind="artifact", artifact_text=text, raw=envelope)

    # Status events have ``status``.
    status = result.get("status")
    if isinstance(status, dict):
        state = status.get("state")
        message: Optional[str] = None
        msg_obj = status.get("message")
        if isinstance(msg_obj, dict):
            parts = msg_obj.get("parts") or []
            if parts and isinstance(parts[0], dict):
                message = parts[0].get("text")
        progress: Optional[float] = None
        metadata = result.get("metadata") or {}
        if isinstance(metadata, dict) and "progress" in metadata:
            try:
                progress = float(metadata["progress"])
            except (TypeError, ValueError):
                progress = None
        final = bool(result.get("final", False))
        return A2AEvent(
            kind="status",
            state=state,
            progress=progress,
            message=message,
            final=final,
            raw=envelope,
        )

    return None


def _stream_finalizer(response_ref: "weakref.ref", task_id: str) -> None:
    """Best-effort sync cleanup when an A2AStream is GC'd without
    explicit aclose(). Warning fires unconditionally so the user sees
    the leak even if the response was already collected. Sync close is
    best-effort — ``httpx.Response.close()`` on an async-transport
    response running from a finalizer (possibly on a torn-down loop)
    may no-op rather than fully drain the async connection pool.
    """
    logger.warning(
        "A2AStream for task=%s was garbage-collected without explicit aclose(). "
        "Use 'async with stream:' or 'await stream.aclose()' to release the "
        "connection cleanly. Best-effort sync close attempted.",
        task_id,
    )
    response = response_ref()
    if response is None:
        return
    try:
        response.close()
    except Exception:
        pass


class A2AStream:
    """Async iterator over parsed A2A SSE events.

    Returned by ``A2AClient.subscribe``. Implements ``__aiter__`` /
    ``__anext__`` and the async context-manager protocol so callers
    can ``async with await client.subscribe(...) as stream:``. The
    convenience ``bridge(mesh_job)`` method mirrors events into a
    mesh JobController and returns the final artifact value.

    The stream MUST be iterated to completion OR explicitly closed
    (``await stream.aclose()`` or ``async with``) so the underlying
    httpx response releases its connection back to the pool.
    """

    def __init__(
        self,
        response: httpx.Response,
        task_id: str,
        _cm: Any = None,
    ) -> None:
        self._response = response
        self.task_id = task_id
        self._cm = _cm
        self._line_iter: Optional[AsyncIterator[str]] = None
        self._closed = False
        # weakref.finalize fires when self is GC'd. Holding a weakref to the
        # response (rather than the response directly) keeps the finalizer
        # from extending the lifetime of self. aclose() detaches the
        # finalizer on the explicit-close path so the leak warning only
        # fires when the caller dropped the stream without iterating to
        # completion or awaiting aclose.
        self._finalizer = weakref.finalize(
            self,
            _stream_finalizer,
            weakref.ref(response),
            task_id,
        )

    def __aiter__(self) -> "A2AStream":
        return self

    async def __anext__(self) -> A2AEvent:
        if self._closed:
            raise StopAsyncIteration
        if self._line_iter is None:
            self._line_iter = self._response.aiter_lines()

        # Read SSE frames one event at a time. An SSE event may span
        # multiple ``data:`` continuation lines (joined with newlines)
        # and is terminated by a blank line. Comment lines (``:``) and
        # other field lines (``event:``, ``id:``) are skipped.
        data_buf: list[str] = []
        try:
            try:
                async for line in self._line_iter:
                    if line == "":
                        if not data_buf:
                            continue
                        payload = "\n".join(data_buf)
                        data_buf = []
                        try:
                            envelope = json.loads(payload)
                        except (ValueError, TypeError) as exc:
                            logger.debug(
                                "A2AStream: skipping non-JSON SSE frame "
                                "(task=%s): %s — payload=%r",
                                self.task_id, exc, payload,
                            )
                            continue
                        event = _parse_sse_envelope(envelope, self.task_id)
                        if event is None:
                            continue
                        if event.final:
                            # Drain politely so the connection can be reused.
                            await self.aclose()
                        return event
                    if line.startswith(":"):
                        # SSE comment (keepalive) — ignore.
                        continue
                    if line.startswith("data:"):
                        # Strip ``data:`` prefix and one optional space.
                        data_buf.append(line[5:].lstrip(" "))
                        continue
                    # event:/id:/retry: lines and unknown — ignore for v1.0.
            except httpx.RemoteProtocolError as exc:
                logger.debug(
                    "A2AStream: remote closed mid-frame (task=%s): %s",
                    self.task_id, exc,
                )

            # Iterator exhausted — flush any pending frame, then stop.
            if data_buf:
                payload = "\n".join(data_buf)
                try:
                    envelope = json.loads(payload)
                    event = _parse_sse_envelope(envelope, self.task_id)
                    if event is not None:
                        await self.aclose()
                        return event
                except (ValueError, TypeError):
                    pass
            await self.aclose()
            raise StopAsyncIteration
        except httpx.HTTPError:
            # Any other transient httpx error (ReadTimeout, NetworkError,
            # ReadError, ...) propagates — ensure the streaming response
            # is closed so we don't leak the underlying connection. The
            # ``aclose()`` call is idempotent via the ``self._closed``
            # flag, so a re-entrant close from within the block is safe.
            await self.aclose()
            raise

    async def __aenter__(self) -> "A2AStream":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Explicit close — detach the finalizer so the leak warning is
        # suppressed for the well-behaved path.
        self._finalizer.detach()
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug(
                    "A2AStream.aclose: response cleanup raised "
                    "(task=%s): %s",
                    self.task_id, exc,
                )
            finally:
                self._cm = None

    async def bridge(self, mesh_job: "MeshJob") -> Any:
        """Iterate events; mirror progress to ``mesh_job``; return artifact value.

        Returns the final artifact value (parsed via ``json.loads`` when
        the text is valid JSON, otherwise raw text). The framework's
        ``task=True`` wrapper handles ``mesh_job.complete(...)`` from the
        return; this method only mirrors progress + propagates terminal
        state.

        Raises ``A2AJobFailed`` / ``A2AJobCanceled`` on terminal failure.
        Honors mesh-side cancellation: ``asyncio.CancelledError`` raised
        during iteration closes the SSE stream and re-raises as
        ``A2AJobCanceled``. The bridge does NOT POST tasks/cancel for SSE
        streams (per A2A v1.0, disconnect is a transient signal — the
        producer continues running unless explicitly canceled).
        """
        last_progress: Any = None
        last_message: Any = None
        artifact_value: Any = None
        saw_artifact = False
        terminal_state: Optional[str] = None
        terminal_message: Optional[str] = None

        try:
            try:
                async for event in self:
                    if event.kind == "artifact":
                        artifact_value = (
                            event.artifact_text
                            if event.artifact_text is None
                            else _maybe_json_loads(event.artifact_text)
                        )
                        saw_artifact = True
                        continue
                    # status event
                    if event.progress is not None or event.message is not None:
                        if (
                            event.progress != last_progress
                            or event.message != last_message
                        ):
                            # Clamp to [0.0, 1.0] — the MeshJob.update_progress
                            # contract expects a normalized fraction; raw A2A
                            # progress values are advisory and may drift.
                            raw_p = (
                                float(event.progress)
                                if event.progress is not None
                                else (last_progress or 0.0)
                            )
                            p = min(1.0, max(0.0, raw_p))
                            try:
                                await mesh_job.update_progress(p, event.message)
                            except Exception:
                                # Do NOT advance ``last_progress`` /
                                # ``last_message`` — leaving them stale ensures
                                # the next event with the same value still
                                # passes the equality check below and retries.
                                logger.warning(
                                    "A2AStream.bridge: mesh_job.update_progress "
                                    "failed (task=%s, progress=%s, msg=%r) — "
                                    "will retry on next event",
                                    self.task_id, event.progress, event.message,
                                    exc_info=True,
                                )
                            else:
                                last_progress = (
                                    event.progress
                                    if event.progress is not None
                                    else last_progress
                                )
                                last_message = event.message
                    if event.final:
                        terminal_state = event.state
                        terminal_message = event.message
                        break
            except asyncio.CancelledError:
                raise A2AJobCanceled(
                    f"A2A subscribe stream {self.task_id} canceled by mesh-side request"
                )
        finally:
            # Ensure the SSE stream is closed on any exit path (normal
            # completion, asyncio cancel, or httpx error bubbling from
            # ``__anext__``). ``aclose()`` is idempotent.
            await self.aclose()

        if terminal_state in ("canceled", "cancelled"):
            raise A2AJobCanceled(
                terminal_message or f"A2A task {self.task_id} canceled"
            )
        if terminal_state == "failed":
            raise A2AJobFailed(
                terminal_message or f"A2A task {self.task_id} failed"
            )
        if not saw_artifact:
            # Stream closed without an artifact event AND without a
            # terminal failure — surface as failed so the user function
            # raises rather than silently returning None.
            raise A2AJobFailed(
                f"A2A subscribe stream {self.task_id} ended without artifact"
            )
        return artifact_value


def _maybe_json_loads(text: str) -> Any:
    if not text:
        return text
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text
