"""Tests for the MeshJob event-injection Python surface (Phase C —
event-channel extension landed in v2.2).

Covers:

* The :mod:`mesh.jobs` public submodule (``post_event``, typed errors).
* End-to-end wiring proof: ``send_event`` from a consumer-side proxy
  reaches a producer-side ``recv_event`` call when both sides run
  against a shared in-process fake registry. Uses the real
  ``mcp_mesh_core`` extension under the hood, swapping only the HTTP
  transport for an ``aiohttp`` test server — so the pyo3 binding, the
  Rust core's long-poll loop, and the Python wrapper layer are all
  exercised.

The ``mesh.jobs.post_event`` helper + typed error classes live in
:mod:`mesh.jobs`. The ``recv_event`` / ``send_event`` methods themselves
are exposed directly on :class:`mcp_mesh_core.JobController` /
:class:`mcp_mesh_core.JobProxy` (the pyo3 bindings introduced in Phase
B), so the Python SDK doesn't add a wrapper class — application code
calls them via the ``MeshJob``-typed parameter the framework injects.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest import mock

import pytest
import pytest_asyncio


# ===========================================================================
# mesh.jobs — typed errors
# ===========================================================================


class TestTypedErrors:
    """:mod:`mesh.jobs` re-classifies the pyo3 layer's ``RuntimeError``
    output into stable subclasses based on Rust ``Display`` substrings.

    Until pyo3 surfaces a dedicated exception type, this is the only way
    application code can ``try/except`` on the underlying ``JobError``
    variant without inspecting strings."""

    def test_translate_job_terminal(self):
        from mesh.jobs import JobTerminalError, _translate_job_error

        rt = RuntimeError("job is terminal: completed")
        out = _translate_job_error(rt)
        assert isinstance(out, JobTerminalError)
        assert out.__cause__ is rt

    def test_translate_job_not_found(self):
        from mesh.jobs import JobNotFoundError, _translate_job_error

        rt = RuntimeError("backend error: job not found: abc-123")
        out = _translate_job_error(rt)
        assert isinstance(out, JobNotFoundError)
        assert out.__cause__ is rt

    def test_translate_unknown_message_passes_through(self):
        from mesh.jobs import _translate_job_error

        rt = RuntimeError("backend error: network error: connection refused")
        # Unknown message: caller will see the original RuntimeError.
        out = _translate_job_error(rt)
        assert out is rt

    def test_translate_non_runtime_error_passes_through(self):
        from mesh.jobs import _translate_job_error

        exc = ValueError("not a runtime error")
        assert _translate_job_error(exc) is exc

    def test_translate_already_typed_passes_through(self):
        """Double-translation must be idempotent — passing a
        JobTerminalError back through the helper returns the same
        instance."""
        from mesh.jobs import JobTerminalError, _translate_job_error

        already = JobTerminalError("job is terminal: completed")
        assert _translate_job_error(already) is already

    def test_error_classes_subclass_runtime_error(self):
        """Existing ``except RuntimeError:`` handlers must continue to
        catch the typed variants — Pythonic Liskov."""
        from mesh.jobs import JobNotFoundError, JobTerminalError

        assert issubclass(JobNotFoundError, RuntimeError)
        assert issubclass(JobTerminalError, RuntimeError)


# ===========================================================================
# mesh.jobs.post_event — convenience helper
# ===========================================================================


class TestPostEventHelper:
    """``mesh.jobs.post_event`` constructs a transient
    :class:`mcp_mesh_core.JobProxy` against the running agent's
    registry URL and forwards a ``send_event`` call."""

    @pytest.mark.asyncio
    async def test_constructs_proxy_with_registry_url_and_forwards(
        self, monkeypatch
    ):
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        captured_construct: dict = {}
        captured_send: dict = {}

        class _FakeJobProxy:
            def __init__(self, job_id: str, registry_url: str) -> None:
                captured_construct["job_id"] = job_id
                captured_construct["registry_url"] = registry_url

            async def send_event(self, event_type: str, payload: dict) -> dict:
                captured_send["event_type"] = event_type
                captured_send["payload"] = payload
                return {
                    "job_id": "job-xyz",
                    "seq": 7,
                    "created_at": 1700000000,
                }

        with mock.patch("mcp_mesh_core.JobProxy", _FakeJobProxy, create=True):
            receipt = await mesh_jobs.post_event(
                "job-xyz", "extend_deadline", {"by_secs": 30}
            )

        assert captured_construct == {
            "job_id": "job-xyz",
            "registry_url": "http://localhost:9999",
        }
        assert captured_send == {
            "event_type": "extend_deadline",
            "payload": {"by_secs": 30},
        }
        assert receipt == {
            "job_id": "job-xyz",
            "seq": 7,
            "created_at": 1700000000,
        }

    @pytest.mark.asyncio
    async def test_none_payload_becomes_empty_dict(self, monkeypatch):
        """``payload=None`` is normalised to ``{}`` before forwarding —
        the pyo3 layer accepts either, but tests should pin the
        convention."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")
        sent: dict = {}

        class _Fake:
            def __init__(self, _jid, _url):
                pass

            async def send_event(self, et, payload):
                sent["payload"] = payload
                return {"job_id": "x", "seq": 1, "created_at": 0}

        with mock.patch("mcp_mesh_core.JobProxy", _Fake, create=True):
            await mesh_jobs.post_event("x", "ping")  # no payload
        assert sent["payload"] == {}

    @pytest.mark.asyncio
    async def test_raises_when_registry_url_missing(self, monkeypatch):
        from mesh import jobs as mesh_jobs

        monkeypatch.delenv("MCP_MESH_REGISTRY_URL", raising=False)
        with pytest.raises(RuntimeError) as exc:
            await mesh_jobs.post_event("x", "y")
        assert "MCP_MESH_REGISTRY_URL" in str(exc.value)

    @pytest.mark.asyncio
    async def test_translates_job_terminal_runtime_error(self, monkeypatch):
        """A ``RuntimeError`` shaped like the Rust JobTerminal variant
        bubbles up as :class:`JobTerminalError` so callers can
        ``except`` on the typed class."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        class _Fake:
            def __init__(self, _jid, _url):
                pass

            async def send_event(self, et, payload):
                raise RuntimeError("job is terminal: completed")

        with mock.patch("mcp_mesh_core.JobProxy", _Fake, create=True):
            with pytest.raises(mesh_jobs.JobTerminalError):
                await mesh_jobs.post_event("x", "y", {})

    @pytest.mark.asyncio
    async def test_translates_job_not_found_runtime_error(self, monkeypatch):
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        class _Fake:
            def __init__(self, _jid, _url):
                pass

            async def send_event(self, et, payload):
                raise RuntimeError("backend error: job not found: missing")

        with mock.patch("mcp_mesh_core.JobProxy", _Fake, create=True):
            with pytest.raises(mesh_jobs.JobNotFoundError):
                await mesh_jobs.post_event("missing", "y", {})

    @pytest.mark.asyncio
    async def test_other_runtime_error_propagates_unchanged(self, monkeypatch):
        """Transient / unknown errors keep their generic
        ``RuntimeError`` type so existing handlers see them verbatim."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        class _Fake:
            def __init__(self, _jid, _url):
                pass

            async def send_event(self, et, payload):
                raise RuntimeError("backend error: network error: refused")

        with mock.patch("mcp_mesh_core.JobProxy", _Fake, create=True):
            with pytest.raises(RuntimeError) as exc:
                await mesh_jobs.post_event("x", "y", {})
        # NOT a typed subclass — kept as base RuntimeError.
        assert type(exc.value) is RuntimeError  # noqa: E721


# ===========================================================================
# mesh.__init__ exports
# ===========================================================================


class TestPublicExports:
    """Phase C surface must be discoverable both as ``mesh.jobs.X`` and
    ``from mesh.jobs import X``, per the task spec."""

    def test_mesh_jobs_submodule_import(self):
        import mesh

        assert hasattr(mesh, "jobs")
        # __getattr__ path must also work.
        sub = mesh.jobs
        assert sub.__name__ == "mesh.jobs"
        assert callable(sub.post_event)

    def test_direct_jobs_import(self):
        from mesh.jobs import post_event, JobNotFoundError, JobTerminalError

        assert callable(post_event)
        assert issubclass(JobNotFoundError, RuntimeError)
        assert issubclass(JobTerminalError, RuntimeError)

    def test_error_classes_on_mesh_namespace(self):
        import mesh

        # Lazy __getattr__ path.
        assert mesh.JobNotFoundError is not None
        assert mesh.JobTerminalError is not None


# ===========================================================================
# End-to-end integration: send_event -> recv_event round trip
# ===========================================================================
#
# These tests spin up a tiny in-process aiohttp server that emulates the
# Phase A registry endpoints `POST /jobs/{id}/events` and
# `GET /jobs/{id}/events`. The producer-side `mcp_mesh_core.JobController`
# polls the GET endpoint via long-poll; the consumer-side
# `mcp_mesh_core.JobProxy` posts to the POST endpoint.
#
# This exercises:
#   - Phase A wire contract (request/response shapes, query params)
#   - Phase B Rust core (recv_event loop + send_event call)
#   - Phase C Python wrappers (mesh.jobs.post_event helper)
#
# The test is skipped if `mcp_mesh_core` isn't available (e.g. test env
# without the native extension built).


def _native_core_has_events() -> bool:
    try:
        import mcp_mesh_core
        return hasattr(mcp_mesh_core.JobController, "recv_event") and hasattr(
            mcp_mesh_core.JobProxy, "send_event"
        )
    except Exception:
        return False


@pytest_asyncio.fixture
async def fake_registry():
    """In-process aiohttp app emulating `POST/GET /jobs/{id}/events`.

    Stores events in memory keyed by job_id. The GET handler implements
    a minimal long-poll: it returns immediately if events with
    ``seq > after`` exist, otherwise it waits up to ``wait`` seconds for
    a new one (signalled via an asyncio.Event).
    """
    from aiohttp import web

    state: dict[str, dict[str, Any]] = {}  # job_id -> {"events": [...], "signal": asyncio.Event(), "terminal": bool}

    def _slot(job_id: str) -> dict[str, Any]:
        if job_id not in state:
            state[job_id] = {
                "events": [],
                "signal": asyncio.Event(),
                "terminal": False,
            }
        return state[job_id]

    async def post_events(request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        slot = _slot(job_id)
        if slot["terminal"]:
            return web.json_response(
                {"error": "job is terminal"}, status=409
            )
        body = await request.json()
        ev_type = body["type"]
        payload = body.get("payload")
        seq = len(slot["events"]) + 1
        created_at = 1700000000 + seq
        slot["events"].append(
            {
                "job_id": job_id,
                "seq": seq,
                "type": ev_type,
                "payload": payload,
                "trace_context": None,
                "posted_by": None,
                "created_at": created_at,
            }
        )
        # Wake any waiters.
        slot["signal"].set()
        slot["signal"] = asyncio.Event()
        return web.json_response(
            {"job_id": job_id, "seq": seq, "created_at": created_at}
        )

    async def get_events(request: web.Request) -> web.Response:
        job_id = request.match_info["job_id"]
        slot = _slot(job_id)
        after = int(request.query.get("after", "0"))
        types_q = request.query.get("types") or ""
        types_filter = set(t for t in types_q.split(",") if t)
        wait_secs = int(request.query.get("wait", "0"))
        limit = int(request.query.get("limit", "100"))

        def _collect() -> list[dict[str, Any]]:
            out = []
            for ev in slot["events"]:
                if ev["seq"] <= after:
                    continue
                if types_filter and ev["type"] not in types_filter:
                    continue
                out.append(ev)
                if len(out) >= limit:
                    break
            return out

        events = _collect()
        if not events and wait_secs > 0:
            try:
                await asyncio.wait_for(slot["signal"].wait(), timeout=wait_secs)
                events = _collect()
            except asyncio.TimeoutError:
                events = []
        next_after = events[-1]["seq"] if events else after
        return web.json_response(
            {"events": events, "next_after": next_after}
        )

    app = web.Application()
    app.router.add_post("/jobs/{job_id}/events", post_events)
    app.router.add_get("/jobs/{job_id}/events", get_events)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    # Resolve the bound port.
    server = site._server  # type: ignore[attr-defined]
    sockets = server.sockets or []
    port = sockets[0].getsockname()[1] if sockets else 0
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield {"base_url": base_url, "state": state}
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _native_core_has_events(),
    reason="mcp_mesh_core extension not built with recv_event/send_event "
    "(Phase B Rust changes); skipping end-to-end integration test.",
)
class TestEventInjectionEndToEnd:
    """End-to-end proof that the three phases compose."""

    async def test_consumer_send_event_reaches_producer_recv_event(
        self, fake_registry, monkeypatch
    ):
        """Producer awaits ``recv_event``; consumer 100ms later calls
        ``mesh.jobs.post_event``; producer wakes and observes the
        payload verbatim — all under a 1-second cap."""
        from mcp_mesh_core import JobController

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", fake_registry["base_url"])

        job_id = "job-e2e-1"

        # Producer-side controller. The registry HTTP layer for events
        # uses the same base URL — terminal flush methods aren't
        # exercised in this test, so the absence of /jobs/batch on the
        # fake server is fine.
        controller = JobController(job_id, "producer-1", fake_registry["base_url"])

        # Launch the producer's recv_event in a background task before
        # the consumer posts. Short timeout so a regression makes the
        # test fail fast rather than hang. Use ``ensure_future`` rather
        # than ``create_task`` because the pyo3-async helper returns a
        # Future (not a coroutine).
        recv_task = asyncio.ensure_future(
            controller.recv_event(timeout_secs=2.0)
        )

        # Yield once + sleep so recv_task has registered its long-poll
        # before we post.
        await asyncio.sleep(0.1)

        # Consumer posts via the public helper (Phase C surface).
        from mesh import jobs as mesh_jobs

        receipt = await mesh_jobs.post_event(
            job_id, "test_event", {"x": 42}
        )
        assert receipt["job_id"] == job_id
        assert receipt["seq"] == 1
        assert receipt["created_at"] > 0

        # Producer observes the event.
        event = await asyncio.wait_for(recv_task, timeout=1.0)
        assert event is not None
        assert event["job_id"] == job_id
        assert event["seq"] == 1
        assert event["type"] == "test_event"
        assert event["payload"] == {"x": 42}

    async def test_recv_event_filter_by_type(
        self, fake_registry, monkeypatch
    ):
        """``recv_event(types=['user_input'])`` skips events whose type
        doesn't match — verified by posting a noise event first, then
        the desired one, and checking the producer wakes on the second."""
        from mcp_mesh_core import JobController, JobProxy

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", fake_registry["base_url"])
        job_id = "job-e2e-2"
        controller = JobController(job_id, "producer-2", fake_registry["base_url"])
        proxy = JobProxy(job_id, fake_registry["base_url"])

        # Producer waits specifically for 'user_input'. ``ensure_future``
        # because pyo3-async returns a Future, not a coroutine.
        recv_task = asyncio.ensure_future(
            controller.recv_event(
                types=["user_input"], timeout_secs=2.0
            )
        )
        await asyncio.sleep(0.05)

        # Post noise event — should NOT wake the producer.
        await proxy.send_event("noise", {"ignored": True})
        await asyncio.sleep(0.1)
        assert not recv_task.done(), "noise event should not have woken recv"

        # Post the desired event — producer wakes with seq=2.
        await proxy.send_event("user_input", {"text": "hello"})
        event = await asyncio.wait_for(recv_task, timeout=1.0)
        assert event is not None
        assert event["type"] == "user_input"
        assert event["payload"] == {"text": "hello"}
        assert event["seq"] == 2  # seq=1 was the noise event

    async def test_recv_event_returns_none_on_timeout(
        self, fake_registry, monkeypatch
    ):
        """When no event arrives within ``timeout_secs``, the call
        returns ``None`` (NOT raise) — the contract documented on the
        ``MeshJob`` Protocol."""
        from mcp_mesh_core import JobController

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", fake_registry["base_url"])
        controller = JobController(
            "job-e2e-timeout", "producer-3", fake_registry["base_url"]
        )

        # Short timeout, no posts.
        result = await controller.recv_event(timeout_secs=0.5)
        assert result is None
