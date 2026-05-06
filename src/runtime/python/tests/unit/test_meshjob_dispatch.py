"""Tests for the inbound MeshJob dispatch wrapper, the consumer-side
MeshJobSubmitter injection, and the helper-tool / cancel-route /
claim-dispatcher wiring (Phase 1 — MeshJob substrate).

The dispatch + submitter logic lives in pure Python so these tests
don't need the native ``mcp_mesh_core`` extension on the test machine —
the modules are written to fall back gracefully when the extension is
unavailable, and we use the Python-side fallbacks here.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _reset_decorator_registry_state():
    """Clear cached DecoratorRegistry / shared agent_id state between tests.

    The job-dispatch wrapper resolves ``instance_id`` via
    ``DecoratorRegistry.get_resolved_agent_config()["agent_id"]`` (the canonical
    source of truth shared with heartbeat + claim worker). That value is
    memoised in ``_cached_agent_config`` and ``_SHARED_AGENT_ID``, so without
    a reset between tests, a test that sets ``MCP_MESH_AGENT_ID`` to a
    different value would still see the previous test's id.
    """
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


# ===========================================================================
# job_dispatch — the inbound wrapper
# ===========================================================================


class TestIsTaskTool:
    """``is_task_tool`` reads the metadata stamped by @mesh.tool."""

    def test_task_true_returns_true(self):
        from _mcp_mesh.engine.job_dispatch import is_task_tool

        async def fn():
            pass

        fn._mesh_tool_metadata = {"task": True}
        assert is_task_tool(fn) is True

    def test_task_false_returns_false(self):
        from _mcp_mesh.engine.job_dispatch import is_task_tool

        async def fn():
            pass

        fn._mesh_tool_metadata = {"task": False}
        assert is_task_tool(fn) is False

    def test_no_metadata_returns_false(self):
        from _mcp_mesh.engine.job_dispatch import is_task_tool

        async def fn():
            pass

        # No metadata at all — must NOT be treated as task=True.
        assert is_task_tool(fn) is False

    def test_metadata_on_wrapped_original(self):
        """Wrapper chains stash metadata on _mesh_original_func — the
        helper must follow the chain."""
        from _mcp_mesh.engine.job_dispatch import is_task_tool

        async def original():
            pass

        original._mesh_tool_metadata = {"task": True}

        async def wrapper():
            pass

        wrapper._mesh_original_func = original
        assert is_task_tool(wrapper) is True


# Module-level fixture functions: ``get_type_hints`` resolves the
# annotation against the function's __globals__, which only sees module-
# level names — so ``MeshJob`` declared in a method body would fail
# resolution. Defining the test fixtures at module scope sidesteps that
# without changing the production code.
from mesh import MeshJob as _MeshJob  # noqa: E402


async def _fixture_with_job(user: str, job: _MeshJob = None):
    pass


async def _fixture_without_job(user: str):
    pass


# Consumer-style fixture: multi-param function with a MeshJob slot but no
# McpMeshTool slots — this is the shape that #bug 1 caused to silently
# skip the MeshJob auto-injection. Defined at module scope so
# get_type_hints can resolve _MeshJob.
async def _fixture_consumer_meshjob_only(
    user_id: str,
    sections: list,
    generate_report: _MeshJob = None,
):
    return {"user_id": user_id, "sections": sections, "submitter": generate_report}


class TestGetMeshJobParamName:
    def test_returns_param_name_when_declared(self):
        from _mcp_mesh.engine.job_dispatch import get_mesh_job_param_name

        assert get_mesh_job_param_name(_fixture_with_job) == "job"

    def test_returns_none_when_no_mesh_job_param(self):
        from _mcp_mesh.engine.job_dispatch import get_mesh_job_param_name

        assert get_mesh_job_param_name(_fixture_without_job) is None


class TestMaybeDispatchAsJob:
    """The ``maybe_dispatch_as_job`` orchestrator."""

    @pytest.mark.asyncio
    async def test_non_task_tool_passes_through(self):
        """A non-task tool MUST not pay the dispatch cost — invoke is
        called directly with the kwargs verbatim."""
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job

        async def fn():
            pass

        # No metadata → not a task tool.
        called_with: dict = {}

        async def invoke(kw):
            called_with.update(kw)
            return "result"

        out = await maybe_dispatch_as_job(fn, invoke, {"x": 1})
        assert out == "result"
        assert called_with == {"x": 1}

    @pytest.mark.asyncio
    async def test_task_true_no_header_runs_with_none_meshjob(self):
        """``task=True`` tool invoked without ``X-Mesh-Job-Id`` runs as
        a regular call; the MeshJob slot is set to ``None`` per
        contract."""
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job
        from mesh import MeshJob

        async def fn(user: str, job: MeshJob = None):
            pass

        fn._mesh_tool_metadata = {"task": True}

        captured: dict = {}

        async def invoke(kw):
            captured.update(kw)
            return "ok"

        # No propagated headers → no job_id available.
        await maybe_dispatch_as_job(fn, invoke, {"user": "alice"})
        assert captured.get("user") == "alice"
        assert captured.get("job") is None

    @pytest.mark.asyncio
    async def test_task_true_with_job_header_injects_controller(self, monkeypatch):
        """When X-Mesh-Job-Id is present and runtime identity is
        resolvable, the wrapper builds a JobController and overlays
        it into kwargs."""
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job
        from _mcp_mesh.tracing.context import TraceContext

        # Reuse the module-level fixture function so get_type_hints
        # resolves ``MeshJob`` against the test module's globals.
        fn = _fixture_with_job
        fn._mesh_tool_metadata = {"task": True}

        # Seed propagated headers as the FastMCP middleware would.
        TraceContext.set_propagated_headers(
            {
                "x-mesh-job-id": "job-test-123",
                "x-mesh-timeout": "60",
            }
        )
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "test-agent-1")

        try:
            captured: dict = {}

            async def invoke(kw):
                captured.update(kw)
                return "ok"

            # Patch the JobController class so we don't need a live
            # registry — the test just verifies the slot is filled.
            class _FakeController:
                def __init__(self, job_id, instance_id, registry_url):
                    self.job_id = job_id
                    self.instance_id = instance_id
                    self.registry_url = registry_url

            with mock.patch(
                "mcp_mesh_core.JobController", _FakeController, create=True
            ):
                # Patch with_job_async to call straight through (so we
                # don't need the Rust task-local in the test).
                async def _passthrough(job_id, deadline, awaitable):
                    return await awaitable

                with mock.patch(
                    "mcp_mesh_core.with_job_async", _passthrough, create=True
                ):
                    await maybe_dispatch_as_job(fn, invoke, {"user": "alice"})

            assert isinstance(captured.get("job"), _FakeController)
            assert captured["job"].job_id == "job-test-123"
            assert captured["job"].instance_id == "test-agent-1"
        finally:
            TraceContext.set_propagated_headers({})

    @pytest.mark.asyncio
    async def test_python_contextvar_set_during_invoke(self, monkeypatch):
        """The Python ``CURRENT_JOB`` contextvar must be visible
        inside the user function."""
        from _mcp_mesh.engine.job_context import current_job
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job
        from _mcp_mesh.tracing.context import TraceContext

        fn = _fixture_with_job
        fn._mesh_tool_metadata = {"task": True}

        TraceContext.set_propagated_headers(
            {"x-mesh-job-id": "job-ctx-test", "x-mesh-timeout": "30"}
        )
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://localhost:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "ctx-agent")

        observed: dict = {}

        async def invoke(_kw):
            snap = current_job()
            observed["snap"] = snap
            return "ok"

        try:
            class _FakeController:
                def __init__(self, *a, **kw):
                    pass

            async def _pass(_jid, _dl, awaitable):
                return await awaitable

            with mock.patch(
                "mcp_mesh_core.JobController", _FakeController, create=True
            ):
                with mock.patch(
                    "mcp_mesh_core.with_job_async", _pass, create=True
                ):
                    await maybe_dispatch_as_job(fn, invoke, {})

            assert observed["snap"] is not None
            assert observed["snap"].job_id == "job-ctx-test"
            assert observed["snap"].deadline_secs_remaining == 30.0

            # After exit, contextvar reset.
            assert current_job() is None
        finally:
            TraceContext.set_propagated_headers({})

    @pytest.mark.asyncio
    async def test_auto_complete_fires_when_handler_returns_without_explicit_complete(
        self, monkeypatch
    ):
        """A ``task=True`` tool whose body returns without calling
        ``await job.complete(...)`` must auto-complete with the return
        value. Otherwise the row sits in ``working`` until the lease
        expires — caller observes a hung job."""
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job
        from _mcp_mesh.tracing.context import TraceContext

        fn = _fixture_with_job
        fn._mesh_tool_metadata = {"task": True}

        TraceContext.set_propagated_headers(
            {"x-mesh-job-id": "job-auto-1", "x-mesh-timeout": "30"}
        )
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://r:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "auto-agent")

        try:
            completions: list = []

            class _FakeController:
                def __init__(self, *a, **kw):
                    self._terminal = False

                async def is_terminal(self):
                    return self._terminal

                async def complete(self, value):
                    completions.append(value)
                    self._terminal = True

                async def fail(self, _err):
                    self._terminal = True

            async def invoke(_kw):
                return {"answer": 42}

            async def _pass(_jid, _dl, awaitable):
                return await awaitable

            with mock.patch(
                "mcp_mesh_core.JobController", _FakeController, create=True
            ):
                with mock.patch(
                    "mcp_mesh_core.with_job_async", _pass, create=True
                ):
                    out = await maybe_dispatch_as_job(fn, invoke, {"user": "x"})
            assert out == {"answer": 42}
            assert completions == [{"answer": 42}], (
                "auto-complete must fire exactly once with the handler return"
            )
        finally:
            TraceContext.set_propagated_headers({})

    @pytest.mark.asyncio
    async def test_auto_complete_skipped_when_handler_called_complete_itself(
        self, monkeypatch
    ):
        """When the user explicitly calls ``await job.complete(...)``,
        the auto-complete path MUST NOT double-flush."""
        from _mcp_mesh.engine.job_dispatch import maybe_dispatch_as_job
        from _mcp_mesh.tracing.context import TraceContext

        fn = _fixture_with_job
        fn._mesh_tool_metadata = {"task": True}

        TraceContext.set_propagated_headers(
            {"x-mesh-job-id": "job-noauto", "x-mesh-timeout": "30"}
        )
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://r:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "noauto-agent")

        try:
            completions: list = []

            class _FakeController:
                def __init__(self, *a, **kw):
                    self._terminal = False

                async def is_terminal(self):
                    return self._terminal

                async def complete(self, value):
                    completions.append(value)
                    self._terminal = True

            async def invoke(kw):
                # Simulate the user explicitly closing the row.
                ctrl = kw.get("job")
                await ctrl.complete({"explicit": True})
                return {"return": "value"}

            async def _pass(_jid, _dl, awaitable):
                return await awaitable

            with mock.patch(
                "mcp_mesh_core.JobController", _FakeController, create=True
            ):
                with mock.patch(
                    "mcp_mesh_core.with_job_async", _pass, create=True
                ):
                    await maybe_dispatch_as_job(fn, invoke, {"user": "x"})
            assert completions == [{"explicit": True}], (
                "no double-flush — only the explicit complete call should land"
            )
        finally:
            TraceContext.set_propagated_headers({})


# ===========================================================================
# MeshJobSubmitter — consumer-side handle
# ===========================================================================


class TestMeshJobSubmitter:
    def test_construction_stores_fields(self):
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        s = MeshJobSubmitter(
            capability="generate_report",
            submitted_by="agent-1",
            registry_url="http://reg:9999",
        )
        assert s.capability == "generate_report"
        assert s.submitted_by == "agent-1"
        assert s.registry_url == "http://reg:9999"

    @pytest.mark.asyncio
    async def test_submit_invokes_core_submit_job(self):
        """``submit`` builds the right call to ``mcp_mesh_core.submit_job``."""
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        captured: dict = {}

        async def fake_submit_job(
            registry_url,
            capability,
            payload,
            submitted_by,
            owner,
            max_dur,
            max_retries,
            total_deadline,
        ):
            captured.update(
                dict(
                    registry_url=registry_url,
                    capability=capability,
                    payload=payload,
                    submitted_by=submitted_by,
                    owner=owner,
                    max_dur=max_dur,
                    max_retries=max_retries,
                    total_deadline=total_deadline,
                )
            )
            return mock.sentinel.proxy

        with mock.patch("mcp_mesh_core.submit_job", fake_submit_job, create=True):
            s = MeshJobSubmitter(
                "generate_report", "consumer-1", "http://reg:9999"
            )
            proxy = await s.submit(
                user_id="abc", sections=["a", "b"], max_duration=60
            )

        assert proxy is mock.sentinel.proxy
        assert captured["capability"] == "generate_report"
        assert captured["submitted_by"] == "consumer-1"
        assert captured["registry_url"] == "http://reg:9999"
        assert captured["max_dur"] == 60
        assert captured["payload"] == {"user_id": "abc", "sections": ["a", "b"]}

    @pytest.mark.asyncio
    async def test_submit_raises_on_missing_core(self):
        """When mcp_mesh_core is unavailable, submit raises a clear
        RuntimeError rather than silently swallowing the call."""
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        s = MeshJobSubmitter("x", "agent", "http://r")
        with mock.patch.dict("sys.modules", {"mcp_mesh_core": None}):
            with pytest.raises(RuntimeError) as exc_info:
                await s.submit()
            assert "submit_job" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_submit_retries_on_transient_then_succeeds(self, monkeypatch):
        """Transient errors (network drop, 5xx) should be retried up to
        the configured max-attempts before the call succeeds. Mirrors the
        behaviour we want during k8s rolling registry restarts."""
        from _mcp_mesh.engine import mesh_job_submitter as mjs
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        # Patch the per-attempt sleep to a no-op so the test is fast.
        monkeypatch.setattr(mjs.asyncio, "sleep", lambda _s: _noop())

        attempts = {"n": 0}

        async def flaky_submit_job(*_a, **_kw):
            attempts["n"] += 1
            if attempts["n"] < 3:
                # Mirror the Rust BackendError::Network message shape.
                raise RuntimeError(
                    "backend error: network error: connection refused"
                )
            return mock.sentinel.proxy

        with mock.patch(
            "mcp_mesh_core.submit_job", flaky_submit_job, create=True
        ):
            s = MeshJobSubmitter("cap", "agent", "http://r")
            proxy = await s.submit()

        assert proxy is mock.sentinel.proxy
        assert attempts["n"] == 3

    @pytest.mark.asyncio
    async def test_submit_gives_up_after_max_attempts(self, monkeypatch):
        """When the registry stays unreachable across all attempts, the
        last error propagates so callers see a clean failure (not an
        infinite hang)."""
        from _mcp_mesh.engine import mesh_job_submitter as mjs
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        monkeypatch.setattr(mjs.asyncio, "sleep", lambda _s: _noop())

        attempts = {"n": 0}

        async def always_503(*_a, **_kw):
            attempts["n"] += 1
            raise RuntimeError(
                "backend error: backend unavailable: registry restarting"
            )

        with mock.patch("mcp_mesh_core.submit_job", always_503, create=True):
            s = MeshJobSubmitter("cap", "agent", "http://r")
            with pytest.raises(RuntimeError) as exc_info:
                await s.submit()

        assert attempts["n"] == mjs._SUBMIT_MAX_ATTEMPTS
        assert "backend unavailable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_submit_does_not_retry_on_4xx(self, monkeypatch):
        """4xx errors (validation, capability not registered, etc.) must
        propagate immediately — retrying would just delay the user-facing
        failure."""
        from _mcp_mesh.engine import mesh_job_submitter as mjs
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        monkeypatch.setattr(mjs.asyncio, "sleep", lambda _s: _noop())

        attempts = {"n": 0}

        async def bad_request(*_a, **_kw):
            attempts["n"] += 1
            # Mirror the Rust BackendError::Other message shape for 4xx.
            raise RuntimeError(
                "backend error: backend error: HTTP 400: capability not task=True"
            )

        with mock.patch("mcp_mesh_core.submit_job", bad_request, create=True):
            s = MeshJobSubmitter("cap", "agent", "http://r")
            with pytest.raises(RuntimeError) as exc_info:
                await s.submit()

        assert attempts["n"] == 1, "must NOT retry on 4xx"
        assert "HTTP 400" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_submit_retries_on_5xx_server_error(self, monkeypatch):
        """5xx (other than 503) is also transient — registry might be
        rolling, hit by a downstream blip, etc."""
        from _mcp_mesh.engine import mesh_job_submitter as mjs
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        monkeypatch.setattr(mjs.asyncio, "sleep", lambda _s: _noop())

        attempts = {"n": 0}

        async def flaky_502(*_a, **_kw):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError(
                    "backend error: server error (HTTP 502): bad gateway"
                )
            return mock.sentinel.proxy

        with mock.patch("mcp_mesh_core.submit_job", flaky_502, create=True):
            s = MeshJobSubmitter("cap", "agent", "http://r")
            proxy = await s.submit()

        assert proxy is mock.sentinel.proxy
        assert attempts["n"] == 2


async def _noop() -> None:
    """Awaitable no-op used to stub asyncio.sleep in retry tests."""
    return None


# ===========================================================================
# Helper-tool registration — JobsHelperToolsStep
# ===========================================================================


class TestJobsHelperToolsStep:
    @pytest.mark.asyncio
    async def test_skipped_when_no_registry_url(self):
        from _mcp_mesh.pipeline.mcp_startup import JobsHelperToolsStep
        from _mcp_mesh.pipeline.shared import PipelineStatus

        step = JobsHelperToolsStep()
        # Ensure no env var leaks into the test.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MCP_MESH_REGISTRY_URL", None)
            result = await step.execute({})
        assert result.status == PipelineStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_skipped_when_no_fastmcp_servers(self, monkeypatch):
        from _mcp_mesh.pipeline.mcp_startup import JobsHelperToolsStep
        from _mcp_mesh.pipeline.shared import PipelineStatus

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://r")
        step = JobsHelperToolsStep()
        result = await step.execute({"fastmcp_servers": {}})
        assert result.status == PipelineStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_registers_three_helpers_per_server(self, monkeypatch):
        from _mcp_mesh.pipeline.mcp_startup import JobsHelperToolsStep

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://r")
        registered: list[str] = []

        # Stub FastMCP-shaped server: the .tool(name=...) call returns a
        # decorator that captures the function.
        class _StubServer:
            def tool(self, *, name: str, description: str = ""):
                def decorator(fn):
                    registered.append(name)
                    return fn

                return decorator

        step = JobsHelperToolsStep()
        await step.execute({"fastmcp_servers": {"main": _StubServer()}})
        # All three framework tools registered.
        assert "__mesh_job_status" in registered
        assert "__mesh_job_result" in registered
        assert "__mesh_job_cancel" in registered


# ===========================================================================
# Cancel-route registration — JobsCancelRouteStep
# ===========================================================================


class TestJobsCancelRouteStep:
    @pytest.mark.asyncio
    async def test_skipped_when_no_fastapi_app(self):
        from _mcp_mesh.pipeline.mcp_startup import JobsCancelRouteStep
        from _mcp_mesh.pipeline.shared import PipelineStatus

        step = JobsCancelRouteStep()
        result = await step.execute({})
        assert result.status == PipelineStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_registers_route_on_fastapi_app(self):
        """End-to-end: build a FastAPI app, run the step, hit the
        endpoint with TestClient, and confirm the response shape."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from _mcp_mesh.pipeline.mcp_startup import JobsCancelRouteStep

        app = FastAPI()
        step = JobsCancelRouteStep()

        # Patch cancel_active_job to a known stub so the test doesn't
        # need the native extension (just verifies wiring).
        with mock.patch(
            "mcp_mesh_core.cancel_active_job", lambda jid: True, create=True
        ):
            await step.execute({"fastapi_app": app})

            client = TestClient(app)
            resp = client.post("/jobs/job-abc/cancel")
            assert resp.status_code == 200
            body = resp.json()
            assert body == {"cancelled": True, "job_id": "job-abc"}

    @pytest.mark.asyncio
    async def test_route_reports_cancelled_false_when_no_token(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from _mcp_mesh.pipeline.mcp_startup import JobsCancelRouteStep

        app = FastAPI()
        step = JobsCancelRouteStep()

        with mock.patch(
            "mcp_mesh_core.cancel_active_job", lambda jid: False, create=True
        ):
            await step.execute({"fastapi_app": app})
            client = TestClient(app)
            resp = client.post("/jobs/no-such-job/cancel")
            assert resp.status_code == 200
            assert resp.json()["cancelled"] is False

    @pytest.mark.asyncio
    async def test_route_resolves_when_fastmcp_mounted_at_root(self):
        """Regression for #bug 4: ``FastAPIServerSetupStep`` mounts the
        FastMCP app at the root path (``app.mount("", fastmcp_app)``),
        which Starlette treats as a catch-all. The cancel route must be
        registered AT THE FRONT of the routes list so it's matched before
        the catch-all mount — otherwise every POST /jobs/.../cancel 404s."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        from _mcp_mesh.pipeline.mcp_startup import JobsCancelRouteStep

        app = FastAPI()

        # Simulate the FastMCP mount that FastAPIServerSetupStep adds
        # at root BEFORE JobsCancelRouteStep runs.
        sub_app = Starlette()

        async def mcp_root(request):
            return JSONResponse({"mcp": True})

        sub_app.add_route("/mcp", mcp_root, methods=["POST", "GET"])
        app.mount("", sub_app)

        step = JobsCancelRouteStep()
        with mock.patch(
            "mcp_mesh_core.cancel_active_job", lambda jid: True, create=True
        ):
            await step.execute({"fastapi_app": app})

            client = TestClient(app)
            # Cancel route must NOT be shadowed by the catch-all mount.
            resp = client.post("/jobs/abc-123/cancel")
            assert resp.status_code == 200
            assert resp.json() == {"cancelled": True, "job_id": "abc-123"}
            # And the FastMCP mount must still resolve.
            resp = client.post("/mcp")
            assert resp.status_code == 200


# ===========================================================================
# Python claim dispatcher
# ===========================================================================


class TestPythonClaimDispatcher:
    """The pure-Python claim dispatcher loop."""

    @pytest.mark.asyncio
    async def test_no_work_loop_backs_off_then_stops(self):
        """When the registry returns no work, the loop sleeps with
        backoff and stops cleanly on stop()."""
        from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

        async def handler(**kw):
            pass

        d = PythonClaimDispatcher(
            "cap", "inst", "http://nowhere", handler
        )

        # Patch _claim_once to always return [] (empty list) so the loop
        # never dispatches. Stop after a brief moment.
        async def no_work():
            return []

        d._claim_once = no_work  # type: ignore[assignment]
        d.start()
        await asyncio.sleep(0.05)
        await d.stop()
        # Task should be done.
        assert d._task is not None
        assert d._task.done()

    @pytest.mark.asyncio
    async def test_dispatches_claimed_job_to_handler(self):
        """When a claim succeeds, the handler is invoked with the
        submitted_payload as kwargs.

        Wire shape per OpenAPI ClaimJobsResponse: {"claimed": [...]}.
        ``_claim_once`` returns the list directly (#bug 3)."""
        from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

        invoked: list[dict] = []

        async def handler(**kw):
            invoked.append(kw)

        claims = [
            [{"id": "j1", "submitted_payload": {"x": 1}, "max_duration": 10}],
            [],  # subsequent calls return no work (empty list)
        ]
        idx = {"i": 0}

        async def fake_claim_once():
            v = claims[idx["i"]] if idx["i"] < len(claims) else []
            idx["i"] += 1
            return v

        d = PythonClaimDispatcher(
            "cap", "inst", "http://r", handler
        )
        d._claim_once = fake_claim_once  # type: ignore[assignment]

        d.start()
        # Give the dispatch task time to run handler.
        await asyncio.sleep(0.1)
        await d.stop()

        assert len(invoked) == 1
        assert invoked[0] == {"x": 1}

    @pytest.mark.asyncio
    async def test_dispatches_multiple_jobs_in_one_claim_response(self):
        """Future-safe: if the registry ever returns >1 claim per round-trip
        (Phase 1 caps at 1, but the schema allows more), each is dispatched."""
        from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

        invoked: list[dict] = []

        async def handler(**kw):
            invoked.append(kw)

        claims_seq = [
            [
                {"id": "j1", "submitted_payload": {"x": 1}},
                {"id": "j2", "submitted_payload": {"x": 2}},
            ],
            [],
        ]
        idx = {"i": 0}

        async def fake_claim_once():
            v = claims_seq[idx["i"]] if idx["i"] < len(claims_seq) else []
            idx["i"] += 1
            return v

        d = PythonClaimDispatcher("cap", "inst", "http://r", handler)
        d._claim_once = fake_claim_once  # type: ignore[assignment]
        d.start()
        await asyncio.sleep(0.1)
        await d.stop()

        # Both jobs dispatched.
        assert len(invoked) == 2
        assert {"x": 1} in invoked
        assert {"x": 2} in invoked

    @pytest.mark.asyncio
    async def test_claim_once_parses_openapi_claimed_array(self):
        """Verify ``_claim_once`` reads the ``claimed`` array per the
        registry's ClaimJobsResponse OpenAPI schema (#bug 3)."""
        import httpx

        from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

        async def handler(**kw):
            pass

        d = PythonClaimDispatcher("cap", "inst", "http://reg:9999", handler)

        # Mock httpx.AsyncClient.post to return ClaimJobsResponse shape.
        class _FakeResp:
            status_code = 200

            def json(self):
                return {
                    "claimed": [
                        {
                            "id": "job-abc",
                            "submitted_payload": {"u": "alice"},
                            "attempt_count": 1,
                        }
                    ]
                }

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None):
                return _FakeResp()

        with mock.patch.object(httpx, "AsyncClient", _FakeClient):
            out = await d._claim_once()

        assert isinstance(out, list)
        assert len(out) == 1
        assert out[0]["id"] == "job-abc"
        assert out[0]["submitted_payload"] == {"u": "alice"}

    @pytest.mark.asyncio
    async def test_claim_once_returns_empty_list_when_no_work(self):
        """Empty ``claimed`` array → empty list (NOT None) so the loop's
        truthiness check works the same way for both shapes."""
        import httpx

        from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

        async def handler(**kw):
            pass

        d = PythonClaimDispatcher("cap", "inst", "http://reg:9999", handler)

        class _FakeResp:
            status_code = 200

            def json(self):
                return {"claimed": []}

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None):
                return _FakeResp()

        with mock.patch.object(httpx, "AsyncClient", _FakeClient):
            out = await d._claim_once()

        assert out == []


# ===========================================================================
# Discover task handlers
# ===========================================================================


class TestDiscoverTaskHandlers:
    def test_returns_empty_when_no_task_tools(self):
        from _mcp_mesh.engine.claim_dispatcher import discover_task_handlers

        # Patch DecoratorRegistry.get_mesh_tools to return only non-task tools.
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        with mock.patch.object(
            DecoratorRegistry, "get_mesh_tools", return_value={}
        ):
            ds = discover_task_handlers("inst", "http://r")
        assert ds == []

    def test_returns_dispatcher_for_each_task_tool(self):
        from _mcp_mesh.engine.claim_dispatcher import discover_task_handlers
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        async def handler():
            pass

        class _Decorated:
            def __init__(self, fn, meta):
                self.function = fn
                self.metadata = meta

        tools = {
            "long_task": _Decorated(
                handler,
                {"capability": "long_task", "task": True},
            ),
            "regular": _Decorated(
                handler,
                {"capability": "regular", "task": False},
            ),
        }
        with mock.patch.object(
            DecoratorRegistry, "get_mesh_tools", return_value=tools
        ):
            ds = discover_task_handlers("inst-id", "http://r")
        # Only the task=True tool yields a dispatcher.
        assert len(ds) == 1
        assert ds[0].capability == "long_task"
        assert ds[0].instance_id == "inst-id"


# ===========================================================================
# Consumer-side MeshJob auto-injection (#bug 1)
#
# The consumer pattern is::
#
#     @mesh.tool(capability="commission_report",
#                dependencies=["generate_report"])
#     async def commission_report(user_id: str, sections: list,
#                                 generate_report: MeshJob = None):
#         ...
#
# Pre-fix: ``analyze_injection_strategy`` returned ``[]`` (no McpMeshTool
# params), the wrapper fell through to ``minimal_wrapper``, and the
# MeshJob auto-injection block at ``_prepare_injection_kwargs`` never
# fired. The user function got ``generate_report=None`` and surfaced the
# "submitter not injected" error.
# ===========================================================================


class TestConsumerSideMeshJobInjection:
    @pytest.mark.asyncio
    async def test_full_di_path_used_when_only_meshjob_param_present(
        self, monkeypatch
    ):
        """A function with no McpMeshTool params but a MeshJob param MUST
        route through the FULL DI path so ``_prepare_injection_kwargs``
        runs and the MeshJobSubmitter auto-injection block fires.

        Pre-fix this test would receive ``submitter=None`` because the
        ``minimal_wrapper`` path was used."""
        from _mcp_mesh.engine.dependency_injector import DependencyInjector
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://reg:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "consumer-1")

        injector = DependencyInjector()
        wrapped = injector.create_injection_wrapper(
            _fixture_consumer_meshjob_only, ["generate_report"]
        )

        result = await wrapped(user_id="alice", sections=["a", "b"])
        assert result["user_id"] == "alice"
        assert result["sections"] == ["a", "b"]
        # The injected MeshJob slot must hold a real submitter, not None.
        assert isinstance(result["submitter"], MeshJobSubmitter)
        assert result["submitter"].capability == "generate_report"
        assert result["submitter"].submitted_by == "consumer-1"
        assert result["submitter"].registry_url == "http://reg:9999"

    @pytest.mark.asyncio
    async def test_explicit_meshjob_arg_overrides_auto_injection(
        self, monkeypatch
    ):
        """Test contract: passing an explicit MeshJob in kwargs (e.g. a
        fake from a test) preserves it instead of overwriting with the
        framework's submitter."""
        from _mcp_mesh.engine.dependency_injector import DependencyInjector

        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://reg:9999")
        monkeypatch.setenv("MCP_MESH_AGENT_ID", "consumer-2")

        injector = DependencyInjector()
        wrapped = injector.create_injection_wrapper(
            _fixture_consumer_meshjob_only, ["generate_report"]
        )

        sentinel = object()
        result = await wrapped(
            user_id="bob",
            sections=["x"],
            generate_report=sentinel,  # type: ignore[arg-type]
        )
        # Caller's explicit value preserved verbatim.
        assert result["submitter"] is sentinel

    def test_analyze_does_not_warn_for_meshjob_only_consumer(self, caplog):
        """The "no McpMeshTool typed params" WARNING must NOT fire just
        because the function uses the consumer pattern (MeshJob-only).
        Pre-fix this surfaced as a noisy WARNING in every consumer log."""
        import logging

        from _mcp_mesh.engine.dependency_injector import (
            analyze_injection_strategy,
        )

        caplog.set_level(logging.WARNING)
        positions = analyze_injection_strategy(
            _fixture_consumer_meshjob_only, ["generate_report"]
        )
        # Still returns [] (no McpMeshTool slots) — but no WARNING.
        assert positions == []
        assert "none are typed as McpMeshTool" not in caplog.text

    def test_clean_signature_strips_meshjob_param(self):
        """FastMCP must not see the MeshJob slot in the user-facing
        signature (else it advertises ``generate_report`` as a callable
        arg). ``_build_clean_signature`` strips both McpMeshTool AND
        MeshJob params."""
        from _mcp_mesh.engine.dependency_injector import _build_clean_signature

        sig = _build_clean_signature(_fixture_consumer_meshjob_only)
        assert sig is not None
        assert "generate_report" not in sig.parameters
        # User-visible params remain.
        assert "user_id" in sig.parameters
        assert "sections" in sig.parameters
