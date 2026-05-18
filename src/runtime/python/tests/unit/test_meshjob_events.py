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


@pytest.fixture(autouse=True)
def _clear_jobproxy_cache():
    """Reset the module-level proxy cache between tests so each
    test starts from a clean slate. The cache is intentionally
    process-lived in production (W5 — see ``mesh.jobs``); tests
    must invalidate it to avoid one test's mock JobProxy bleeding
    into the next test's run.
    """
    from mesh import jobs as mesh_jobs

    mesh_jobs._proxy_cache.clear()
    yield
    mesh_jobs._proxy_cache.clear()


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

    @pytest.mark.asyncio
    async def test_proxy_is_cached_per_registry_url_and_job_id(
        self, monkeypatch
    ):
        """W5 (review #1032): two `post_event` calls against the same
        ``(registry_url, job_id)`` MUST share a single underlying
        ``JobProxy`` instance. Pre-W5 each call constructed a fresh
        proxy + reqwest pool, costing a TCP/TLS handshake per send.
        """
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        construct_count = 0

        class _CountingFake:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                nonlocal construct_count
                construct_count += 1

            async def send_event(self, _et: str, _payload: dict) -> dict:
                return {"job_id": "job-cached", "seq": 0, "created_at": 0}

        with mock.patch("mcp_mesh_core.JobProxy", _CountingFake, create=True):
            await mesh_jobs.post_event("job-cached", "tick", {"i": 1})
            await mesh_jobs.post_event("job-cached", "tick", {"i": 2})
            await mesh_jobs.post_event("job-cached", "tick", {"i": 3})

        # Three sends, ONE proxy construction.
        assert construct_count == 1, (
            f"expected JobProxy to be constructed exactly once per "
            f"(registry_url, job_id) key; got {construct_count} constructions"
        )

    @pytest.mark.asyncio
    async def test_proxy_cache_keyed_by_job_id(self, monkeypatch):
        """Different ``job_id`` values get separate cached proxies — the
        cache key is ``(registry_url, job_id)``, not just registry_url."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        seen_ids: list[str] = []

        class _RecordingFake:
            def __init__(self, job_id: str, _registry_url: str) -> None:
                seen_ids.append(job_id)

            async def send_event(self, _et: str, _payload: dict) -> dict:
                return {"job_id": "", "seq": 0, "created_at": 0}

        with mock.patch("mcp_mesh_core.JobProxy", _RecordingFake, create=True):
            await mesh_jobs.post_event("job-A", "ping", {})
            await mesh_jobs.post_event("job-B", "ping", {})
            # Second call against job-A reuses the cached proxy.
            await mesh_jobs.post_event("job-A", "ping", {})

        # Exactly two constructions — one per distinct job_id.
        assert seen_ids == ["job-A", "job-B"], (
            f"expected one construction per distinct job_id, got {seen_ids}"
        )


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
        assert callable(sub.subscribe_events)

    def test_direct_jobs_import(self):
        from mesh.jobs import (
            JobNotFoundError,
            JobTerminalError,
            post_event,
            subscribe_events,
        )

        assert callable(post_event)
        assert callable(subscribe_events)
        assert issubclass(JobNotFoundError, RuntimeError)
        assert issubclass(JobTerminalError, RuntimeError)

    def test_error_classes_on_mesh_namespace(self):
        import mesh

        # Lazy __getattr__ path.
        assert mesh.JobNotFoundError is not None
        assert mesh.JobTerminalError is not None


# ===========================================================================
# mesh.jobs.subscribe_events — observer-side async iterator
# ===========================================================================


class TestSubscribeEvents:
    """``mesh.jobs.subscribe_events`` builds a long-lived async iterator
    on top of the pyo3 ``JobProxy.list_events`` batch primitive. The
    iterator manages its own cursor (no shared state with the producer's
    ``recv_event``) and yields events strictly in ascending-seq order
    until the caller breaks out of the loop."""

    @pytest.mark.asyncio
    async def test_subscribe_events_yields_events_until_break(
        self, monkeypatch
    ):
        """A subscriber yields every event the fake ``list_events`` returns
        across multiple batches, in order, until the caller breaks."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        # Two batches: first returns 2 events, second returns 1, then
        # any further call returns []. The subscriber should yield 3
        # events total, in seq order.
        batches: list[list[dict[str, Any]]] = [
            [
                {"job_id": "j1", "seq": 1, "type": "work", "payload": {"n": 1}},
                {"job_id": "j1", "seq": 2, "type": "work", "payload": {"n": 2}},
            ],
            [
                {"job_id": "j1", "seq": 3, "type": "work", "payload": {"n": 3}},
            ],
        ]

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                self._cursor = 0

            async def list_events(
                self, after: int, _types: Any, _wait: float
            ) -> tuple[list[dict[str, Any]], int]:
                if batches:
                    batch = batches.pop(0)
                    return batch, batch[-1]["seq"]
                return [], after

        observed: list[dict[str, Any]] = []
        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            async for event in mesh_jobs.subscribe_events(
                "j1", long_poll_secs=0.0
            ):
                observed.append(event)
                if len(observed) == 3:
                    break

        seqs = [e["seq"] for e in observed]
        assert seqs == [1, 2, 3], (
            f"subscriber must yield events in ascending-seq order, got {seqs}"
        )
        assert observed[0]["payload"] == {"n": 1}
        assert observed[2]["payload"] == {"n": 3}

    @pytest.mark.asyncio
    async def test_subscribe_events_advances_cursor_between_calls(
        self, monkeypatch
    ):
        """The cursor passed to the SECOND ``list_events`` call must be
        the seq of the last yielded event — proves the iterator advances
        its watermark internally between batches."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        cursors_seen: list[int] = []
        batches: list[list[dict[str, Any]]] = [
            [
                {"job_id": "j1", "seq": 1, "type": "x", "payload": None},
                {"job_id": "j1", "seq": 5, "type": "x", "payload": None},
            ],
            [
                {"job_id": "j1", "seq": 9, "type": "x", "payload": None},
            ],
        ]

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                pass

            async def list_events(
                self, after: int, _types: Any, _wait: float
            ) -> tuple[list[dict[str, Any]], int]:
                cursors_seen.append(after)
                if batches:
                    batch = batches.pop(0)
                    return batch, batch[-1]["seq"]
                return [], after

        observed: list[int] = []
        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            async for event in mesh_jobs.subscribe_events(
                "j1", long_poll_secs=0.0
            ):
                observed.append(event["seq"])
                if len(observed) == 3:
                    break

        # First call uses the initial cursor (default 0). Second call
        # must use the max seq from the first batch (5). Third would be
        # 9 if we kept going, but we break first — at minimum the second
        # call's cursor proves the advance.
        assert cursors_seen[0] == 0, (
            f"first list_events must use the initial after=0; got {cursors_seen[0]}"
        )
        assert cursors_seen[1] == 5, (
            f"second list_events must use the seq of the last yielded event "
            f"(5), got {cursors_seen[1]}"
        )

    @pytest.mark.asyncio
    async def test_subscribe_events_filter_by_types(self, monkeypatch):
        """The ``types`` arg passes through to ``list_events`` so the
        registry-side filter trims the batch BEFORE the iterator
        observes it."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        types_seen: list[Any] = []

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                pass

            async def list_events(
                self, _after: int, types: Any, _wait: float
            ) -> tuple[list[dict[str, Any]], int]:
                types_seen.append(types)
                return [
                    {"job_id": "j1", "seq": 1, "type": "user_input", "payload": None}
                ], 1

        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            async for _ in mesh_jobs.subscribe_events(
                "j1", types=["user_input"], long_poll_secs=0.0
            ):
                break

        assert types_seen[0] == ["user_input"], (
            f"types filter must pass through to list_events verbatim; "
            f"got {types_seen[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_subscribe_events_propagates_job_not_found(
        self, monkeypatch
    ):
        """When ``list_events`` raises a JobNotFound-shaped RuntimeError
        (registry reaped the job row), the iterator must surface it as
        the typed :class:`JobNotFoundError` so callers can ``except``
        cleanly without inspecting strings."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                pass

            async def list_events(self, *_args: Any, **_kw: Any) -> list[Any]:
                raise RuntimeError("backend error: job not found: gone")

        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            with pytest.raises(mesh_jobs.JobNotFoundError):
                async for _ in mesh_jobs.subscribe_events(
                    "missing", long_poll_secs=0.0
                ):
                    pass  # pragma: no cover - iterator raises on first call

    @pytest.mark.asyncio
    async def test_mesh_jobs_subscribe_events_uses_cached_proxy(
        self, monkeypatch
    ):
        """``subscribe_events`` reuses the same module-level
        ``(registry_url, job_id)`` proxy cache as ``post_event``. Two
        sequential subscriptions to the same job must construct ONE
        underlying ``JobProxy`` instance (the cache is shared across
        helpers)."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        construct_count = 0

        class _CountingFake:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                nonlocal construct_count
                construct_count += 1

            async def list_events(
                self, _after: int, _types: Any, _wait: float
            ) -> tuple[list[dict[str, Any]], int]:
                return [
                    {"job_id": "j-cached", "seq": 1, "type": "t", "payload": None}
                ], 1

        with mock.patch("mcp_mesh_core.JobProxy", _CountingFake, create=True):
            async for _ in mesh_jobs.subscribe_events(
                "j-cached", long_poll_secs=0.0
            ):
                break
            async for _ in mesh_jobs.subscribe_events(
                "j-cached", long_poll_secs=0.0
            ):
                break

        # Two iterations, ONE proxy construction — the cache hit on the
        # second call must reuse the proxy from the first call (same
        # `(registry_url, job_id)` key as `post_event`).
        assert construct_count == 1, (
            f"expected the JobProxy cache to be shared across helpers "
            f"(post_event + subscribe_events); got {construct_count} "
            f"constructions for the same job_id"
        )

    @pytest.mark.asyncio
    async def test_subscribe_events_forwards_none_long_poll_secs(
        self, monkeypatch
    ):
        """``long_poll_secs=None`` MUST pass through verbatim to the pyo3
        binding so the Rust side treats it as "single immediate read"
        (no ``wait`` query param sent). Pre-fix the signature typed this
        as ``float`` and hid the ``None`` path entirely."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        wait_args: list[Any] = []

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                pass

            async def list_events(
                self, _after: int, _types: Any, wait: Any
            ) -> tuple[list[dict[str, Any]], int]:
                wait_args.append(wait)
                return [
                    {"job_id": "j1", "seq": 1, "type": "x", "payload": None}
                ], 1

        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            async for _ in mesh_jobs.subscribe_events(
                "j1", long_poll_secs=None
            ):
                break

        assert wait_args[0] is None, (
            f"long_poll_secs=None must forward as None to proxy.list_events "
            f"(single immediate read); got {wait_args[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_subscribe_events_raises_on_missing_seq(self, monkeypatch):
        """An event missing the integer ``seq`` key surfaces as a
        ``RuntimeError`` BEFORE the event is yielded — so callers don't
        observe a half-yielded malformed payload, and the error message
        names the offending field."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                pass

            async def list_events(
                self, _after: int, _types: Any, _wait: Any
            ) -> tuple[list[dict[str, Any]], int]:
                return [{"type": "work", "payload": {}}], 0  # no 'seq' key

        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            with pytest.raises(RuntimeError) as exc:
                async for _ in mesh_jobs.subscribe_events(
                    "j1", long_poll_secs=0.0
                ):
                    pass  # pragma: no cover - iterator raises on first event
        assert "seq" in str(exc.value)

    @pytest.mark.asyncio
    async def test_subscribe_events_rejects_bool_seq(self, monkeypatch):
        """A bool ``seq`` value (``True``/``False``) must be rejected:
        ``isinstance(True, int)`` is True in Python, but the registry
        contract is integer seqs — a bool here is a malformed wire payload.
        The guard uses ``type(seq) is not int`` so booleans fail BEFORE
        the event is yielded."""
        from mesh import jobs as mesh_jobs

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")

        class _FakeProxy:
            def __init__(self, _job_id: str, _registry_url: str) -> None:
                pass

            async def list_events(
                self, _after: int, _types: Any, _wait: Any
            ) -> tuple[list[dict[str, Any]], int]:
                return [{"seq": True, "type": "work", "payload": {}}], 1

        with mock.patch("mcp_mesh_core.JobProxy", _FakeProxy, create=True):
            with pytest.raises(RuntimeError) as exc:
                async for _ in mesh_jobs.subscribe_events(
                    "j1", long_poll_secs=0.0
                ):
                    pass  # pragma: no cover - iterator raises on first event
        assert "seq" in str(exc.value)


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
