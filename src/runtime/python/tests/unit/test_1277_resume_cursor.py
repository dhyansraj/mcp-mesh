"""Issue #1277 — resume_cursor opt-in (Python reference implementation).

Covers the three moving parts of the Python surface:

1. Decorator opt-in: ``@mesh.tool(resume_cursor=True)`` stamps metadata,
   requires ``task=True``, defaults ``False``, must be a bool.
2. Cursor propagation: the claim dispatcher serializes ``recv_cursor`` onto
   the ``x-mesh-recv-cursor`` header (JSON); ``_read_job_headers`` round-trips
   it back to a dict; absent / malformed → ``None`` (never crashes).
3. The single gate: ``maybe_dispatch_as_job`` seeds the controller from the
   parsed cursor ONLY when the tool opted in AND a cursor is present.
"""

from __future__ import annotations

import json
from unittest import mock

import mesh
import pytest


# ===========================================================================
# 1. Decorator opt-in surface
# ===========================================================================


class TestResumeCursorDecorator:
    def test_resume_cursor_true_on_task_tool_sets_metadata(self):
        @mesh.tool(capability="resumable", task=True, resume_cursor=True)
        async def handler():
            pass

        meta = handler._mesh_tool_metadata
        assert meta["resume_cursor"] is True
        assert meta["task"] is True

    def test_resume_cursor_default_false(self):
        @mesh.tool(capability="replayer", task=True)
        async def handler():
            pass

        assert handler._mesh_tool_metadata["resume_cursor"] is False

    def test_resume_cursor_on_non_task_tool_raises(self):
        with pytest.raises(ValueError, match="resume_cursor is only valid with task=True"):

            @mesh.tool(capability="bad", resume_cursor=True)
            async def handler():
                pass

    def test_resume_cursor_non_bool_raises(self):
        with pytest.raises(ValueError, match="resume_cursor must be a boolean"):

            @mesh.tool(capability="bad_type", task=True, resume_cursor="yes")
            async def handler():
                pass


class TestGetResumeCursor:
    def test_reads_flag_true(self):
        from _mcp_mesh.engine.job_dispatch import get_resume_cursor

        async def fn():
            pass

        fn._mesh_tool_metadata = {"task": True, "resume_cursor": True}
        assert get_resume_cursor(fn) is True

    def test_defaults_false_when_absent(self):
        from _mcp_mesh.engine.job_dispatch import get_resume_cursor

        async def fn():
            pass

        fn._mesh_tool_metadata = {"task": True}
        assert get_resume_cursor(fn) is False

    def test_defaults_false_when_no_metadata(self):
        from _mcp_mesh.engine.job_dispatch import get_resume_cursor

        async def fn():
            pass

        assert get_resume_cursor(fn) is False

    def test_follows_wrapped_original(self):
        from _mcp_mesh.engine.job_dispatch import get_resume_cursor

        async def original():
            pass

        original._mesh_tool_metadata = {"task": True, "resume_cursor": True}

        async def wrapper():
            pass

        wrapper._mesh_original_func = original
        assert get_resume_cursor(wrapper) is True


# ===========================================================================
# 2a. _read_job_headers round-trip
# ===========================================================================


class TestReadJobHeadersRecvCursor:
    def _read_with(self, headers):
        from _mcp_mesh.engine.job_dispatch import _read_job_headers
        from _mcp_mesh.tracing.context import TraceContext

        TraceContext.set_propagated_headers(headers)
        try:
            return _read_job_headers()
        finally:
            TraceContext.set_propagated_headers({})

    def test_parses_recv_cursor_to_dict(self):
        cursor = {"work": 7, "answer": 3}
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": json.dumps(cursor)}
        )
        assert recv == cursor

    def test_absent_recv_cursor_is_none(self):
        _jid, _dl, _ep, recv = self._read_with({"x-mesh-job-id": "j1"})
        assert recv is None

    def test_blank_recv_cursor_is_none(self):
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": "   "}
        )
        assert recv is None

    def test_malformed_recv_cursor_is_none_no_crash(self):
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": "{not json"}
        )
        assert recv is None

    def test_non_object_recv_cursor_is_none(self):
        # Valid JSON but not an object (a list) → None, no crash.
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": "[1, 2, 3]"}
        )
        assert recv is None

    def test_string_value_dropped_empty_map_is_none(self):
        # A registry cursor whose value is a string is NOT a valid seq — it
        # would throw at PyO3 extraction. Filtered out → empty → None (so the
        # controller is still constructed, replay-from-0).
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": '{"work": "5"}'}
        )
        assert recv is None

    def test_fractional_value_dropped_empty_map_is_none(self):
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": '{"work": 2.5}'}
        )
        assert recv is None

    def test_negative_value_dropped(self):
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": '{"work": -1}'}
        )
        assert recv is None

    def test_bool_value_dropped(self):
        # JSON true/false parse to Python bool (an int subclass) but a seq is
        # never a bool — must be dropped.
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": '{"work": true}'}
        )
        assert recv is None

    def test_mixed_map_keeps_only_non_negative_ints(self):
        # The shared cross-runtime mixed-map: only "a":4 survives.
        _jid, _dl, _ep, recv = self._read_with(
            {
                "x-mesh-job-id": "j1",
                "x-mesh-recv-cursor": '{"a": 4, "b": -1, "c": 2.5, "d": "x"}',
            }
        )
        assert recv == {"a": 4}

    def test_zero_is_kept(self):
        _jid, _dl, _ep, recv = self._read_with(
            {"x-mesh-job-id": "j1", "x-mesh-recv-cursor": '{"work": 0}'}
        )
        assert recv == {"work": 0}


# ===========================================================================
# 2b. Claim dispatcher sets the header from claimed.recv_cursor
# ===========================================================================


class TestDispatchSetsRecvCursorHeader:
    def _make_dispatcher(self, handler):
        from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

        return PythonClaimDispatcher(
            capability="cap",
            instance_id="inst",
            registry_url="http://registry:8000",
            handler=handler,
            func_id="mod.fn",
            required_deps=[],
        )

    @pytest.mark.asyncio
    async def test_dispatch_serializes_recv_cursor_header(self):
        from _mcp_mesh.tracing.context import TraceContext

        seen: dict = {}

        async def handler(**kwargs):
            seen["headers"] = dict(TraceContext.get_propagated_headers())

        d = self._make_dispatcher(handler)
        cursor = {"work": 4, "signal": 1}
        try:
            await d._dispatch(
                {
                    "id": "job-1",
                    "submitted_payload": {},
                    "claim_epoch": 2,
                    "recv_cursor": cursor,
                }
            )
        finally:
            TraceContext.set_propagated_headers({})

        assert "x-mesh-recv-cursor" in seen["headers"]
        assert json.loads(seen["headers"]["x-mesh-recv-cursor"]) == cursor

    @pytest.mark.asyncio
    async def test_dispatch_without_recv_cursor_sets_no_header(self):
        from _mcp_mesh.tracing.context import TraceContext

        seen: dict = {}

        async def handler(**kwargs):
            seen["headers"] = dict(TraceContext.get_propagated_headers())

        d = self._make_dispatcher(handler)
        try:
            await d._dispatch(
                {"id": "job-2", "submitted_payload": {}, "claim_epoch": 2}
            )
        finally:
            TraceContext.set_propagated_headers({})

        assert "x-mesh-recv-cursor" not in seen["headers"]

    @pytest.mark.asyncio
    async def test_dispatch_empty_recv_cursor_sets_no_header(self):
        from _mcp_mesh.tracing.context import TraceContext

        seen: dict = {}

        async def handler(**kwargs):
            seen["headers"] = dict(TraceContext.get_propagated_headers())

        d = self._make_dispatcher(handler)
        try:
            await d._dispatch(
                {
                    "id": "job-3",
                    "submitted_payload": {},
                    "recv_cursor": {},
                }
            )
        finally:
            TraceContext.set_propagated_headers({})

        assert "x-mesh-recv-cursor" not in seen["headers"]


# ===========================================================================
# 3. The single gate in maybe_dispatch_as_job
# ===========================================================================


# Module-level fixture: get_type_hints resolves annotations against module
# globals, so the MeshJob-slotted function must live at module scope.
from mesh import MeshJob as _MeshJob  # noqa: E402


async def _task_fixture(user: str, job: _MeshJob = None):
    pass


class TestResumeGate:
    async def _run_gate(self, monkeypatch, *, resume_cursor, header_cursor):
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job
        from _mcp_mesh.tracing.context import TraceContext

        fn = _task_fixture
        fn._mesh_tool_metadata = {"task": True, "resume_cursor": resume_cursor}

        headers = {"x-mesh-job-id": "job-1", "x-mesh-claim-epoch": "5"}
        if header_cursor is not None:
            headers["x-mesh-recv-cursor"] = json.dumps(header_cursor)
        TraceContext.set_propagated_headers(headers)
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "agent-1")

        seen: dict = {}

        async def invoke(_kw):
            return "ok"

        class _FakeController:
            def __init__(
                self,
                job_id,
                instance_id,
                registry_url,
                claim_epoch=None,
                initial_cursors=None,
            ):
                seen["initial_cursors"] = initial_cursors
                # Record whether the kwarg was passed at all (sentinel is the
                # default; the gate must NOT pass it on the replay path).
                seen["kwargs_seen"] = True

        async def _passthrough(job_id, deadline, awaitable, claim_epoch=None):
            return await awaitable

        try:
            with mock.patch(
                "mcp_mesh_core.JobController", _FakeController, create=True
            ), mock.patch(
                "mcp_mesh_core.with_job_async", _passthrough, create=True
            ):
                await maybe_dispatch_as_job(fn, invoke, {"user": "alice"})
        finally:
            TraceContext.set_propagated_headers({})
        return seen

    @pytest.mark.asyncio
    async def test_opted_in_with_cursor_seeds_controller(self, monkeypatch):
        cursor = {"work": 9}
        seen = await self._run_gate(
            monkeypatch, resume_cursor=True, header_cursor=cursor
        )
        assert seen["initial_cursors"] == cursor

    @pytest.mark.asyncio
    async def test_off_with_cursor_present_does_not_seed(self, monkeypatch):
        # resume_cursor OFF but the header IS present → must NOT seed.
        seen = await self._run_gate(
            monkeypatch, resume_cursor=False, header_cursor={"work": 9}
        )
        assert seen["initial_cursors"] is None

    @pytest.mark.asyncio
    async def test_opted_in_no_cursor_does_not_seed(self, monkeypatch):
        # resume_cursor ON but no cursor rode the header → no seed.
        seen = await self._run_gate(
            monkeypatch, resume_cursor=True, header_cursor=None
        )
        assert seen["initial_cursors"] is None

    @pytest.mark.asyncio
    async def test_opted_in_bad_value_cursor_still_constructs_controller(
        self, monkeypatch
    ):
        # A registry cursor with a non-integer value must NOT drop us to a
        # plain call with no controller (that would break a resume handler
        # calling recv_event). The controller IS constructed, seeded with
        # None (filtered empty) → clean replay-from-0.
        seen = await self._run_gate(
            monkeypatch, resume_cursor=True, header_cursor={"work": "5"}
        )
        assert seen.get("kwargs_seen") is True, "controller must be constructed"
        assert seen["initial_cursors"] is None

    @pytest.mark.asyncio
    async def test_opted_in_mixed_map_seeds_filtered(self, monkeypatch):
        seen = await self._run_gate(
            monkeypatch,
            resume_cursor=True,
            header_cursor={"a": 4, "b": -1, "c": 2.5, "d": "x"},
        )
        assert seen["initial_cursors"] == {"a": 4}


# ===========================================================================
# 4. Outbound header hygiene: x-mesh-recv-cursor is claim-LOCAL, must not leak
# ===========================================================================


class TestOutboundScrub:
    """The recv-cursor is read once (claim→handler seed) from the contextvar;
    it must NOT ride outbound downstream calls. The dispatch job/epoch pair
    (which DO propagate for calling-job identity) are unaffected."""

    def teardown_method(self):
        from _mcp_mesh.tracing.context import TraceContext

        TraceContext.set_propagated_headers({})

    def _merged(self):
        from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy

        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool")
        _args, merged = proxy._inject_trace_into_args({}, None)
        return merged

    def test_recv_cursor_scrubbed_from_outbound(self):
        from _mcp_mesh.tracing.context import TraceContext

        TraceContext.set_propagated_headers(
            {
                "x-mesh-job-id": "job-1",
                "x-mesh-claim-epoch": "3",
                "x-mesh-recv-cursor": json.dumps({"work": 5}),
            }
        )
        merged = self._merged()
        assert "x-mesh-recv-cursor" not in merged

    def test_seed_still_readable_from_contextvar_after_scrub(self):
        # The inbound seed reads the cursor from the contextvar directly (before
        # any outbound call); the outbound scrub copies the contextvar, so the
        # source contextvar — and thus the seed path — is untouched.
        from _mcp_mesh.engine.job_dispatch import _read_job_headers
        from _mcp_mesh.tracing.context import TraceContext

        TraceContext.set_propagated_headers(
            {
                "x-mesh-job-id": "job-1",
                "x-mesh-recv-cursor": json.dumps({"work": 5}),
            }
        )
        merged = self._merged()
        assert "x-mesh-recv-cursor" not in merged
        # Contextvar still carries the cursor for the claim→handler read.
        _jid, _dl, _ep, recv = _read_job_headers()
        assert recv == {"work": 5}
