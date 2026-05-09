"""Consumer-side A2A primitives — A2AClient, A2ABearer, A2AResponse.

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
``tasks/get``. Long-running submit/subscribe and SSE streaming are
deferred to a later phase.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx


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

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_default))
        return self._client

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.auth:
            h.update(self.auth.header())
        return h

    async def _post_jsonrpc(
        self, method: str, params: dict[str, Any], rpc_id: int = 1
    ) -> dict[str, Any]:
        client = await self._http()
        envelope = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        resp = await client.post(self.url, headers=self._headers(), json=envelope)
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

        result = await self._post_jsonrpc(
            "tasks/send", {"id": task_id, "message": message}, rpc_id=1
        )
        state = (result.get("status") or {}).get("state", "unknown")

        if state in ("completed", "failed", "canceled"):
            return self._build_response(task_id, result)

        interval = self.poll_interval
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            result = await self._post_jsonrpc(
                "tasks/get", {"id": task_id}, rpc_id=2
            )
            state = (result.get("status") or {}).get("state", "unknown")
            if state in ("completed", "failed", "canceled"):
                return self._build_response(task_id, result)
            interval = min(self.poll_interval_max, interval * 1.5)

        raise TimeoutError(
            f"A2A task {task_id!r} on {self.url} did not reach terminal "
            f"state within {timeout}s (last state={state!r})"
        )

    def _build_response(self, task_id: str, result: dict[str, Any]) -> A2AResponse:
        artifacts = result.get("artifacts") or []
        artifact_text = ""
        if artifacts:
            parts = artifacts[0].get("parts") or []
            if parts and isinstance(parts[0], dict):
                artifact_text = parts[0].get("text", "")
        return A2AResponse(
            artifact_text=artifact_text,
            state=(result.get("status") or {}).get("state", "unknown"),
            task_id=task_id,
            raw_task=result,
        )

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
