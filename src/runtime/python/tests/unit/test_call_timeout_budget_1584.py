"""Issue #1584 — one per-call budget, enforced locally and advertised on the wire.

The budget a proxy enforces (the httpx client timeout) and the budget it
advertises downstream (``X-Mesh-Timeout``) must be the same number, and the
default must be identical in Python, TypeScript and Java.

Before the fix Python computed them from two different expressions::

    enhanced_timeout = max(self.timeout, 300)
    X-Mesh-Timeout   = MCP_MESH_CALL_TIMEOUT or str(int(enhanced_timeout))

so setting ``MCP_MESH_CALL_TIMEOUT`` overrode the header only, advertising a
budget this client would not itself wait out.

A note on what "explicit" means in Python, because it is the trap this file
exists to pin down: ``UnifiedMCPProxy.kwargs_config`` is the **producer's**
``@mesh.tool`` kwargs, shipped back from the registry on the resolved
dependency (``rust_heartbeat._handle_dependency_change``), NOT the consumer's
dependency declaration. So there is no consumer-side per-call timeout the
runtime reads, and a ``timeout`` appearing in that map must NOT become the
consumer's budget — otherwise a provider (or, worse, an ``@mesh.llm`` provider
whose ``timeout`` means the vendor SDK's timeout) would cap every caller.
Python therefore matches Java: env, else 300.
"""

import itertools
import json
import os
from unittest import mock

import pytest

from _mcp_mesh.engine.unified_mcp_proxy import (
    FALLBACK_CALL_TIMEOUT_SECS,
    UnifiedMCPProxy,
    _default_call_timeout_secs,
)


@pytest.fixture(autouse=True)
def _clear_env():
    saved = os.environ.pop("MCP_MESH_CALL_TIMEOUT", None)
    yield
    os.environ.pop("MCP_MESH_CALL_TIMEOUT", None)
    if saved is not None:
        os.environ["MCP_MESH_CALL_TIMEOUT"] = saved


class TestDefaultCallTimeoutSecs:
    def test_unset_and_blank_fall_back_to_300(self):
        assert _default_call_timeout_secs() == 300
        assert FALLBACK_CALL_TIMEOUT_SECS == 300
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "   "
        assert _default_call_timeout_secs() == 300

    def test_valid_value_is_used(self):
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "600"
        assert _default_call_timeout_secs() == 600

    @pytest.mark.parametrize("bad", ["abc", "0", "-5", "nan", "inf"])
    def test_unparseable_or_non_positive_falls_back(self, bad):
        os.environ["MCP_MESH_CALL_TIMEOUT"] = bad
        assert _default_call_timeout_secs() == 300

    def test_read_at_call_time_not_import_time(self):
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "120"
        assert _default_call_timeout_secs() == 120
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "45"
        assert _default_call_timeout_secs() == 45

    def test_rounds_half_up_like_typescript_and_java(self):
        # Python's built-in round() is banker's rounding — round(2.5) == 2 —
        # while Math.round is half-up in both TS and Java. The three runtimes
        # have to agree on what MCP_MESH_CALL_TIMEOUT=2.5 means.
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "2.5"
        assert _default_call_timeout_secs() == 3
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "3.5"
        assert _default_call_timeout_secs() == 4
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "0.4"
        assert _default_call_timeout_secs() == 1


_DI_SEQ = itertools.count()


async def _build_proxy_through_di(producer_kwargs: dict | None):
    """Build a dependency proxy the way the runtime actually builds one.

    Goes through ``_handle_dependency_change``, so ``kwargs_config`` is
    populated from the PRODUCER kwargs JSON exactly as the Rust core delivers
    it. Constructing ``UnifiedMCPProxy`` directly is what hid the
    producer-vs-consumer confusion in the first place.

    Each call uses a fresh ``requesting_function`` so the #1314 idempotency
    guard (which skips a rebuild when endpoint/function/kwargs/agent_id are
    unchanged) doesn't swallow the second and later builds in this file.
    """
    from _mcp_mesh.engine.dependency_injector import get_global_injector
    from _mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat import (
        _handle_dependency_change,
    )

    injector = get_global_injector()
    captured: dict = {}

    real_register = injector.register_dependency

    async def _capture(dep_key, proxy):
        captured["proxy"] = proxy
        return await real_register(dep_key, proxy)

    with mock.patch.object(injector, "register_dependency", _capture):
        await _handle_dependency_change(
            capability="downstream_cap",
            endpoint="http://downstream:8000",
            function_name="some_tool",
            agent_id="provider-agent",
            available=True,
            context={},
            requesting_function=f"consumer_tool_{next(_DI_SEQ)}",
            dep_index=0,
            producer_kwargs=json.dumps(producer_kwargs) if producer_kwargs else None,
        )
    assert "proxy" in captured, "DI did not register a proxy"
    return captured["proxy"]


class TestProducerKwargsCannotDictateTheBudget:
    """The regression this file is named for.

    ``kwargs_config`` carries the producer's kwargs. A ``timeout`` in it must
    not become the consumer's client timeout or advertised header.
    """

    @pytest.mark.asyncio
    async def test_producer_timeout_does_not_override_the_default(self):
        proxy = await _build_proxy_through_di({"timeout": 45})
        # The producer's value is visible as advertised metadata...
        assert proxy.kwargs_config.get("timeout") == 45
        # ...but it is NOT this consumer's budget.
        assert proxy.effective_call_timeout_secs() == 300

    @pytest.mark.asyncio
    async def test_producer_timeout_does_not_override_the_env_var(self):
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "600"
        proxy = await _build_proxy_through_di({"timeout": 45})
        assert proxy.effective_call_timeout_secs() == 600

    @pytest.mark.asyncio
    async def test_env_var_governs_when_producer_declares_nothing(self):
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "600"
        proxy = await _build_proxy_through_di(None)
        assert proxy.effective_call_timeout_secs() == 600

    @pytest.mark.asyncio
    async def test_default_when_neither_is_set(self):
        proxy = await _build_proxy_through_di(None)
        assert proxy.effective_call_timeout_secs() == 300


class _CapturingClient:
    """Minimal stand-in for the pooled httpx client: records what was sent.

    ``post`` raises a sentinel once it has captured, and every caller asserts
    on THAT sentinel rather than a bare ``Exception``: a failure earlier in
    ``_http_call`` would otherwise satisfy the assertion and leave the
    remaining checks reading a client that captured nothing.
    """

    def __init__(self):
        self.headers = None
        self.timeout = None

    async def post(self, url, content=None, headers=None, timeout=None):
        self.headers = dict(headers or {})
        self.timeout = timeout
        raise RuntimeError("stop-after-capture")


async def _capture_call(proxy):
    client = _CapturingClient()
    with mock.patch(
        "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
        return_value=client,
    ):
        with pytest.raises(RuntimeError, match="stop-after-capture"):
            await proxy._http_call("some_tool", {})
    return client


class TestOutboundHeaderMatchesClientTimeout:
    """The two halves of the budget are read off the same real call."""

    @pytest.mark.asyncio
    async def test_default_is_300_on_both_halves(self):
        client = await _capture_call(await _build_proxy_through_di(None))
        assert client.headers["X-Mesh-Timeout"] == "300"
        assert client.timeout.read == 300

    @pytest.mark.asyncio
    async def test_env_var_moves_both_halves(self):
        os.environ["MCP_MESH_CALL_TIMEOUT"] = "600"
        client = await _capture_call(await _build_proxy_through_di(None))
        assert client.headers["X-Mesh-Timeout"] == "600"
        assert client.timeout.read == 600

    @pytest.mark.asyncio
    async def test_producer_timeout_moves_neither_half(self):
        client = await _capture_call(await _build_proxy_through_di({"timeout": 45}))
        assert client.headers["X-Mesh-Timeout"] == "300"
        assert client.timeout.read == 300

    @pytest.mark.asyncio
    async def test_inbound_header_wins_over_the_local_default(self):
        from _mcp_mesh.tracing.context import TraceContext

        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool", {})
        TraceContext.set_propagated_headers({})
        try:
            proxy._inject_trace_headers  # noqa: B018 — attribute presence check
            client = _CapturingClient()
            with mock.patch(
                "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
                return_value=client,
            ):
                with mock.patch.object(
                    proxy,
                    "_inject_trace_headers",
                    lambda h: {**h, "X-Mesh-Timeout": "12"},
                ):
                    with pytest.raises(RuntimeError, match="stop-after-capture"):
                        await proxy._http_call("some_tool", {})
            assert client.headers["X-Mesh-Timeout"] == "12"
            assert client.timeout.read == 12
        finally:
            TraceContext.set_propagated_headers({})


class TestJobDeadlineOverride:
    """The parent-scope deadline cap tightens the header, and never renders
    as the "0" every receiver reads as "unset".

    ``deadline_secs_remaining`` is a STATIC dispatch-time snapshot of the
    inbound ``X-Mesh-Timeout`` (``job_dispatch`` reads it once and never
    decrements it), so these cases are about the value the parent GRANTED, not
    live remaining time.
    """

    async def _capture_under_job(self, deadline_secs_remaining):
        from _mcp_mesh.engine.job_context import CURRENT_JOB, JobContextSnapshot

        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool", {})
        client = _CapturingClient()
        token = CURRENT_JOB.set(
            JobContextSnapshot(
                job_id="job-1584",
                deadline_secs_remaining=deadline_secs_remaining,
                claim_epoch=None,
            )
        )
        try:
            with mock.patch(
                "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
                return_value=client,
            ):
                with pytest.raises(RuntimeError, match="stop-after-capture"):
                    await proxy._http_call("some_tool", {})
        finally:
            CURRENT_JOB.reset(token)
        return client

    @pytest.mark.asyncio
    async def test_tighter_deadline_replaces_the_default(self):
        client = await self._capture_under_job(20.0)
        assert client.headers["X-Mesh-Timeout"] == "20"
        # Issue #1570: the dispatch discriminator never rides outbound.
        assert "X-Mesh-Job-Id" not in client.headers
        assert "x-mesh-job-id" not in client.headers

    @pytest.mark.asyncio
    async def test_sub_second_grant_advertises_one_not_zero(self):
        # An inbound header of "0.5" reaches the snapshot intact (job_dispatch
        # only normalises `<= 0`). `int(0.5)` is 0, and 0 reads as "unset"
        # downstream — which handed the child an unbounded budget instead of
        # the tightest one the wire can express.
        client = await self._capture_under_job(0.5)
        assert client.headers["X-Mesh-Timeout"] == "1"

    @pytest.mark.asyncio
    async def test_expired_grant_omits_the_header_entirely(self):
        # Defensive rather than dispatch-reachable: job_dispatch normalises a
        # `<= 0` header to None. CURRENT_JOB is public API, so user code and
        # tests can still produce this snapshot directly.
        client = await self._capture_under_job(-3.0)
        assert "X-Mesh-Timeout" not in client.headers
        assert "x-mesh-timeout" not in client.headers


class TestTightenedBudgetIsNotDuplicated:
    """The parent-scope cap must leave exactly ONE timeout header on the wire.

    The propagated store is lowercased, so an inbound budget arrives as
    ``x-mesh-timeout``. The expired branch pops both casings; the tighten
    branch only assigned the canonical name, so a tightened call went out
    carrying the parent's larger ``x-mesh-timeout`` AND the tightened
    ``X-Mesh-Timeout``. A receiver taking the first header wins loses the
    parent's cap — the same duplicate-header class as issue #1611.
    """

    async def _capture(self, *, inbound: dict, deadline_secs_remaining: float):
        from _mcp_mesh.engine.job_context import CURRENT_JOB, JobContextSnapshot
        from _mcp_mesh.engine.unified_mcp_proxy import _outbound_headers_var

        proxy = UnifiedMCPProxy("http://downstream:8000", "some_tool", {})
        client = _CapturingClient()
        hdr_token = _outbound_headers_var.set(dict(inbound))
        job_token = CURRENT_JOB.set(
            JobContextSnapshot(
                job_id="job-1613",
                deadline_secs_remaining=deadline_secs_remaining,
                claim_epoch=None,
            )
        )
        try:
            with mock.patch(
                "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
                return_value=client,
            ):
                with pytest.raises(RuntimeError, match="stop-after-capture"):
                    await proxy._http_call("some_tool", {})
        finally:
            CURRENT_JOB.reset(job_token)
            _outbound_headers_var.reset(hdr_token)
        return client

    @pytest.mark.asyncio
    async def test_tightening_a_lowercase_inbound_leaves_one_header(self):
        client = await self._capture(
            inbound={"x-mesh-timeout": "30"}, deadline_secs_remaining=20.0
        )
        assert client.headers["X-Mesh-Timeout"] == "20"
        assert "x-mesh-timeout" not in client.headers
        assert client.timeout.read == 20

    @pytest.mark.asyncio
    async def test_a_tighter_lowercase_inbound_is_not_widened(self):
        # The inbound cap is already tighter than what this job has left, so
        # the tighten branch must not fire at all. Reading only the canonical
        # casing saw "0" here — "unset" — and replaced a 5s parent cap with a
        # 20s advertisement.
        client = await self._capture(
            inbound={"x-mesh-timeout": "5"}, deadline_secs_remaining=20.0
        )
        assert client.headers.get("x-mesh-timeout") == "5"
        assert "X-Mesh-Timeout" not in client.headers
        assert client.timeout.read == 5
