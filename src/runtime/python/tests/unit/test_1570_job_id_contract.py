"""Issue #1570 — the cross-runtime ``x-mesh-job-id`` contract.

``x-mesh-job-id`` is the push-mode dispatch DISCRIMINATOR. It is read from the
RAW inbound request (or seeded by the claim dispatcher) and is never emitted on
an outbound call: forwarding it makes a nested ``task=True`` call self-dispatch
as the CALLER's job (owner + epoch match) and auto-complete it with the wrong
result. Calling identity rides the dedicated ``x-mesh-calling-*`` pair.

Two properties are pinned here:

1. **Inbound capture works.** A raw ``X-Mesh-Job-Id`` HTTP header reaches
   ``job_dispatch`` even though it is not on the propagate allowlist — push-mode
   dispatch over HTTP used to be unreachable because the dispatch gate read the
   allowlist-FILTERED map.
2. **Outbound never carries it.** Neither the propagated-header base nor the
   active job context puts ``x-mesh-job-id`` on a downstream request.
"""

import json
from unittest import mock

import pytest

from _mcp_mesh.engine.job_context import CURRENT_JOB, JobContextSnapshot
from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy
from _mcp_mesh.tracing.context import (
    DISPATCH_HEADERS,
    TraceContext,
    matches_propagate_header,
)


class TestAllowlistExcludesTheDispatchTrio:
    def test_dispatch_headers_are_not_allowlisted(self):
        for name in DISPATCH_HEADERS:
            assert matches_propagate_header(name) is False, name


class TestInboundCapture:
    """The MCP session middleware must capture the dispatch trio from the RAW
    inbound request, independently of the propagate allowlist."""

    def teardown_method(self):
        TraceContext.set_propagated_headers({})
        TraceContext.clear_dispatch_headers()

    def _middleware_class(self):
        from _mcp_mesh.engine.http_wrapper import HttpMcpWrapper

        class _CapturingApp:
            def __init__(self):
                self.middleware_cls = None

            def add_middleware(self, cls, **kwargs):
                self.middleware_cls = cls

        wrapper = HttpMcpWrapper.__new__(HttpMcpWrapper)
        wrapper._mcp_app = _CapturingApp()
        wrapper._add_session_routing_middleware()
        return wrapper._mcp_app.middleware_cls

    def test_raw_job_headers_reach_the_dispatch_gate(self):
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from _mcp_mesh.engine.job_dispatch import _read_job_headers

        seen: dict = {}

        async def endpoint(request):
            seen["job"] = _read_job_headers()
            seen["propagated"] = dict(TraceContext.get_propagated_headers())
            return JSONResponse({"ok": True})

        class _StubWrapper:
            async def _extract_session_id_from_body(self, body):
                return None

        app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
        app.add_middleware(self._middleware_class(), http_wrapper=_StubWrapper())

        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
        )
        with TestClient(app) as client:
            resp = client.post(
                "/mcp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Mesh-Job-Id": "job-inbound-1570",
                    "X-Mesh-Claim-Epoch": "7",
                    "X-Mesh-Timeout": "30",
                },
            )
        assert resp.status_code == 200

        job_id, deadline, claim_epoch, _cursor = seen["job"]
        assert job_id == "job-inbound-1570"
        assert deadline == 30.0
        assert claim_epoch == 7
        # …and the allowlist-filtered map that rides outbound never sees it.
        assert "x-mesh-job-id" not in seen["propagated"]
        assert "x-mesh-claim-epoch" not in seen["propagated"]


class TestGateIsRawOnly:
    """The gate reads the dispatch store and nothing else — matching Java and
    TypeScript. An operator who widens ``MCP_MESH_PROPAGATE_HEADERS`` must not
    be able to re-arm self-dispatch through the propagated map."""

    def teardown_method(self):
        TraceContext.set_propagated_headers({})
        TraceContext.clear_dispatch_headers()

    def test_propagated_job_id_alone_does_not_dispatch(self):
        from _mcp_mesh.engine.job_dispatch import _read_job_headers

        TraceContext.set_propagated_headers({"x-mesh-job-id": "job-widened"})
        assert _read_job_headers() == (None, None, None, None)

    def test_dispatch_store_job_id_dispatches(self):
        from _mcp_mesh.engine.job_dispatch import _read_job_headers

        TraceContext.set_dispatch_headers({"x-mesh-job-id": "job-raw"})
        TraceContext.set_propagated_headers({"x-mesh-timeout": "42"})
        job_id, deadline, _epoch, _cursor = _read_job_headers()
        assert job_id == "job-raw"
        assert deadline == 42.0


class TestVersionSkewGuard:
    """A pre-3.8 peer forwarded x-mesh-job-id on ordinary nested calls, and
    only ever from inside a bound job context — which seeds
    x-mesh-calling-job-id on the same request. A genuine push dispatch carries
    the job id WITHOUT calling identity, so the pair arriving together is a
    leaked nested call from an old caller, not a dispatch."""

    def teardown_method(self):
        TraceContext.set_propagated_headers({})
        TraceContext.clear_dispatch_headers()

    def test_job_id_with_calling_identity_is_refused(self, caplog):
        from _mcp_mesh.engine.job_dispatch import _read_job_headers

        TraceContext.set_dispatch_headers({"x-mesh-job-id": "job-caller"})
        TraceContext.set_propagated_headers(
            {"x-mesh-calling-job-id": "job-caller", "x-mesh-timeout": "30"}
        )
        with caplog.at_level("WARNING"):
            assert _read_job_headers() == (None, None, None, None)
        assert "pre-3.8 caller leaking its own job id" in caplog.text

    def test_job_id_without_calling_identity_still_dispatches(self):
        from _mcp_mesh.engine.job_dispatch import _read_job_headers

        TraceContext.set_dispatch_headers({"x-mesh-job-id": "job-push"})
        TraceContext.set_propagated_headers({"x-mesh-timeout": "30"})
        assert _read_job_headers()[0] == "job-push"


class TestSkewWireEndToEnd(TestInboundCapture):
    """The exact request a 3.7 peer emits, driven through the real inbound
    middleware. A 3.7 caller under job J sent BOTH x-mesh-job-id: J (from its
    job context / its claim seed) and x-mesh-calling-job-id: J (from #1263's
    carrier) on every nested call. A 3.8 callee captures raw job ids where it
    used to drop them, so without the guard this request would bind the callee
    to J and auto-complete the caller's row."""

    def test_a_37_shaped_nested_call_does_not_dispatch(self):
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from _mcp_mesh.engine.job_dispatch import _read_job_headers

        seen: dict = {}

        async def endpoint(request):
            seen["job"] = _read_job_headers()
            return JSONResponse({"ok": True})

        class _StubWrapper:
            async def _extract_session_id_from_body(self, body):
                return None

        app = Starlette(routes=[Route("/mcp", endpoint, methods=["POST"])])
        app.add_middleware(self._middleware_class(), http_wrapper=_StubWrapper())

        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
        )
        with TestClient(app) as client:
            resp = client.post(
                "/mcp",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Mesh-Job-Id": "job-caller",
                    "X-Mesh-Calling-Job-Id": "job-caller",
                    "X-Mesh-Calling-Claim-Epoch": "2",
                    "X-Mesh-Timeout": "30",
                },
            )
        assert resp.status_code == 200
        assert seen["job"] == (None, None, None, None)


class _CapturingClient:
    """Minimal httpx client stand-in: records headers, then aborts the call."""

    def __init__(self):
        self.headers = None

    async def post(self, url, content=None, headers=None, timeout=None):
        self.headers = dict(headers or {})
        raise RuntimeError("stop-after-capture")


class TestOutboundNeverCarriesTheDispatchTrio:
    def teardown_method(self):
        TraceContext.set_propagated_headers({})
        TraceContext.clear_dispatch_headers()

    async def _capture(self):
        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool", {})
        client = _CapturingClient()
        with mock.patch(
            "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
            return_value=client,
        ):
            with pytest.raises(RuntimeError, match="stop-after-capture"):
                await proxy._http_call("some_tool", {})
        return client

    @pytest.mark.asyncio
    async def test_active_job_context_does_not_stamp_the_job_id(self):
        """The self-dispatch hazard: a task=True handler executing job J calls
        a downstream task=True tool. If J rides along, the downstream binds a
        controller for J and auto-completes the CALLER's row with its own
        result."""
        token = CURRENT_JOB.set(
            JobContextSnapshot(
                job_id="job-caller",
                deadline_secs_remaining=None,
                claim_epoch=3,
            )
        )
        try:
            client = await self._capture()
        finally:
            CURRENT_JOB.reset(token)

        lowered = {k.lower() for k in client.headers}
        assert "x-mesh-job-id" not in lowered
        assert "x-mesh-claim-epoch" not in lowered

    @pytest.mark.asyncio
    async def test_calling_identity_still_travels_on_its_own_carrier(self):
        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool")
        token = CURRENT_JOB.set(
            JobContextSnapshot(
                job_id="job-caller",
                deadline_secs_remaining=None,
                claim_epoch=3,
            )
        )
        try:
            _args, merged = proxy._inject_trace_into_args({}, None)
        finally:
            CURRENT_JOB.reset(token)

        assert merged["x-mesh-calling-job-id"] == "job-caller"
        assert merged["x-mesh-calling-claim-epoch"] == "3"
        assert "x-mesh-job-id" not in merged

    @pytest.mark.asyncio
    async def test_propagated_store_is_scrubbed_of_the_dispatch_trio(self):
        """Defense in depth: even if the trio somehow lands in the propagated
        store (a hand-seeded contextvar, an operator-widened allowlist), the
        outbound header build drops it."""
        TraceContext.set_propagated_headers(
            {
                "x-mesh-job-id": "job-leaked",
                "x-mesh-claim-epoch": "9",
                "x-mesh-recv-cursor": '{"work": 4}',
                "x-mesh-timeout": "30",
            }
        )
        client = await self._capture()

        lowered = {k.lower() for k in client.headers}
        assert "x-mesh-job-id" not in lowered
        assert "x-mesh-claim-epoch" not in lowered
        assert "x-mesh-recv-cursor" not in lowered
        # A genuinely propagated header is untouched.
        assert client.headers["x-mesh-timeout"] == "30"
