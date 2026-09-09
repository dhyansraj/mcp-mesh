"""Unit tests for issue #1591: fixes that landed on one Python pipeline or
loop and not its twin.

Each class covers one independent item. They are grouped because they share a
review lesson, not a mechanism.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

# ---------------------------------------------------------------------------
# Item 1: #1314 idempotent re-emit guard, missing from the A2A heartbeat.
# ---------------------------------------------------------------------------


class _A2AWrapper:
    """Stand-in for a @mesh.a2a injection wrapper."""

    def __init__(self):
        self.updates: list = []

    def _mesh_update_dependency(self, index, proxy):
        self.updates.append((index, proxy))


def _register_a2a_surface():
    """Register one ``mesh_a2a`` surface with a single ``chat`` dependency."""
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    DecoratorRegistry.clear_all()

    wrapper = _A2AWrapper()

    async def surface(prompt: str, chat=None):
        return chat

    surface._mesh_injection_wrapper = wrapper

    DecoratorRegistry.register_custom_decorator(
        "mesh_a2a",
        surface,
        {"capability": "surface", "dependencies": [{"capability": "chat"}]},
    )
    return wrapper


async def _apply_a2a(*, endpoint, agent_id, producer_kwargs=None, available=True):
    from _mcp_mesh.pipeline.a2a_heartbeat import rust_a2a_heartbeat

    await rust_a2a_heartbeat._handle_a2a_dependency_change(
        capability="chat",
        endpoint=endpoint,
        function_name="chat",
        agent_id=agent_id,
        available=available,
        context={"service_id": "a2a-consumer"},
        producer_kwargs=producer_kwargs,
    )


class TestA2AIdempotentReemit:
    """The MCP and API dependency-apply paths skip an unchanged re-emit; the
    A2A path rebuilt every proxy — and every connection pool behind it — on
    every reconcile tick."""

    def _clear_signatures(self, wrapper):
        from _mcp_mesh.engine.dependency_injector import get_global_injector

        injector = get_global_injector()
        for i in range(4):
            injector.clear_applied_dependency_signature(f"a2a:surface:dep_{i}")

    @pytest.mark.asyncio
    async def test_identical_reemit_does_not_rebuild(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        wrapper = _register_a2a_surface()
        self._clear_signatures(wrapper)
        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_a2a(
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"stream_type": "text"}),
                )
                await _apply_a2a(
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"stream_type": "text"}),
                )

            assert len(builds) == 1
            assert len(wrapper.updates) == 1
        finally:
            self._clear_signatures(wrapper)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_equal_but_reordered_kwargs_do_not_rebuild(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        wrapper = _register_a2a_surface()
        self._clear_signatures(wrapper)
        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_a2a(
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"a": 1, "b": 2}),
                )
                await _apply_a2a(
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"b": 2, "a": 1}),
                )

            assert len(builds) == 1
        finally:
            self._clear_signatures(wrapper)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_genuine_change_still_rebuilds(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        wrapper = _register_a2a_surface()
        self._clear_signatures(wrapper)
        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_a2a(
                    endpoint="http://producer:9170", agent_id="producer-id"
                )
                # endpoint change
                await _apply_a2a(
                    endpoint="http://producer-2:9170", agent_id="producer-id"
                )
                # agent_id-only change must ALSO rebuild (#1315 composition)
                await _apply_a2a(
                    endpoint="http://producer-2:9170", agent_id="producer-id-2"
                )

            assert len(builds) == 3
        finally:
            self._clear_signatures(wrapper)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_unavailable_clears_signature_so_readd_rebuilds(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        wrapper = _register_a2a_surface()
        self._clear_signatures(wrapper)
        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_a2a(
                    endpoint="http://producer:9170", agent_id="producer-id"
                )
                await _apply_a2a(
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    available=False,
                )
                await _apply_a2a(
                    endpoint="http://producer:9170", agent_id="producer-id"
                )

            # down/up must NOT be skipped as an "unchanged" re-emit
            assert len(builds) == 2
            assert wrapper.updates[1][1] is None
        finally:
            self._clear_signatures(wrapper)
            DecoratorRegistry.clear_all()


# ---------------------------------------------------------------------------
# Item 2: event-source failure backoff in the MCP and API heartbeats.
# ---------------------------------------------------------------------------


class TestHeartbeatFailureBackoff:
    """A persistently-failing event source used to tight-loop on
    ``logger.error`` in the MCP and API heartbeats; only the A2A twin backed
    off."""

    ALL_LOOPS = [
        (
            "_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat",
            "rust_heartbeat_task",
        ),
        (
            "_mcp_mesh.pipeline.api_heartbeat.rust_api_heartbeat",
            "rust_api_heartbeat_task",
        ),
        (
            "_mcp_mesh.pipeline.a2a_heartbeat.rust_a2a_heartbeat",
            "rust_a2a_heartbeat_task",
        ),
    ]

    @staticmethod
    def _loop_source(module_path, loop_name):
        import importlib
        import inspect

        return inspect.getsource(
            getattr(importlib.import_module(module_path), loop_name)
        )

    @pytest.mark.parametrize("module_path,loop_name", ALL_LOOPS[:2])
    def test_loop_body_sleeps_between_failures(self, module_path, loop_name):
        import importlib
        import inspect

        module = importlib.import_module(module_path)
        source = inspect.getsource(getattr(module, loop_name))

        assert "consecutive_failures" in source
        assert "asyncio.sleep(backoff)" in source
        # Capped, not unbounded.
        assert "min(0.5 * (2 ** (consecutive_failures - 1)), 5.0)" in source

    def test_backoff_schedule_is_bounded(self):
        # The shared formula: 0.5, 1, 2, 4, then flat at 5s.
        schedule = [min(0.5 * (2 ** (n - 1)), 5.0) for n in range(1, 12)]
        assert schedule[:4] == [0.5, 1.0, 2.0, 4.0]
        assert max(schedule) == 5.0

    @pytest.mark.parametrize("module_path,loop_name", ALL_LOOPS)
    def test_liveness_tick_resets_the_run(self, module_path, loop_name):
        # ``if event is None: continue`` used to skip the reset, so the counter
        # was CUMULATIVE, not consecutive: on a low-traffic agent ten unrelated
        # failures days apart escalated as though they were a burst. A liveness
        # tick proves the event source is healthy, so it must reset.
        source = self._loop_source(module_path, loop_name)
        tick = source.index("if event is None:")
        reset = source.index("consecutive_failures = 0", tick)
        nxt = source.index("continue", tick)
        assert reset < nxt, "the liveness tick does not reset the failure run"

    @pytest.mark.parametrize("module_path,loop_name", ALL_LOOPS)
    def test_no_loop_takes_the_service_down_on_repeated_failure(
        self, module_path, loop_name
    ):
        # #1591 review: an A2A surface is a FAN-OUT point serving many
        # consumers, and this project holds that such a service must never
        # withdraw itself (health gating is provider-only for the same
        # reason). Exiting any of these loops runs ``finally`` ->
        # ``handle.shutdown()`` -> unregistration. All three soft-fail.
        source = self._loop_source(module_path, loop_name)
        failure_arm = source[source.index("consecutive_failures += 1") :]
        # up to the end of the except block (the outer CancelledError handler)
        failure_arm = failure_arm[: failure_arm.index("except asyncio.CancelledError")]
        assert "raise" not in failure_arm
        assert "MAX_CONSECUTIVE" not in source

    @pytest.mark.parametrize("module_path,loop_name", ALL_LOOPS)
    def test_all_three_loops_share_the_backoff_formula(self, module_path, loop_name):
        source = self._loop_source(module_path, loop_name)
        assert "min(0.5 * (2 ** (consecutive_failures - 1)), 5.0)" in source
        assert "BACKOFF_LOG_ESCALATION" in source


# ---------------------------------------------------------------------------
# Item 3: TracePublisherInitStep missing from the A2A pipeline.
# ---------------------------------------------------------------------------


class TestA2ATracePublisherInit:
    def test_a2a_pipeline_includes_trace_publisher_init(self):
        from _mcp_mesh.pipeline.a2a_startup.a2a_pipeline import A2APipeline

        names = [s.name for s in A2APipeline().steps]
        assert "trace-publisher-init" in names

    def test_step_runs_before_server_setup(self):
        # The eager Redis connect has to happen before the heartbeat (and
        # therefore any traffic) starts, exactly as in the API pipeline.
        from _mcp_mesh.pipeline.a2a_startup.a2a_pipeline import A2APipeline

        names = [s.name for s in A2APipeline().steps]
        assert names.index("trace-publisher-init") < names.index("a2a-server-setup")

    def test_matches_the_api_pipeline(self):
        from _mcp_mesh.pipeline.api_startup.api_pipeline import APIPipeline

        assert "trace-publisher-init" in [s.name for s in APIPipeline().steps]


# ---------------------------------------------------------------------------
# Item 4: slugify_service_name bypassed by the API service-id fallback.
# ---------------------------------------------------------------------------


class TestApiServiceIdFallbackSlug:
    """``DecoratorRegistry._generate_api_service_id_fallback`` inlined a
    weaker copy of the slug transform that never stripped characters outside
    ``[a-z0-9-]``, so it could emit a service id the registry rejects — and one
    that disagreed with the id ``APIServerSetupStep`` derives from the same
    env var."""

    @pytest.mark.parametrize(
        "raw",
        [
            "Payments!! ✨",
            "my_service@v2",
            "Ünïcödé Naming",
            "trailing---punctuation!!!",
        ],
    )
    def test_generated_id_is_registry_safe(self, monkeypatch, raw):
        import re

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        monkeypatch.setenv("MCP_MESH_API_NAME", raw)
        service_id = DecoratorRegistry._generate_api_service_id_fallback()

        assert re.fullmatch(r"[a-z0-9-]+", service_id), service_id

    def test_agrees_with_the_api_pipeline_transform(self, monkeypatch):
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.shared.slug import slugify_service_name

        monkeypatch.setenv("MCP_MESH_API_NAME", "Payments!! ✨")
        service_id = DecoratorRegistry._generate_api_service_id_fallback()

        expected_stem = slugify_service_name("Payments!! ✨", "")
        assert service_id.startswith(f"{expected_stem}-api-")

    def test_all_punctuation_name_falls_back_to_api_prefix(self, monkeypatch):
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        monkeypatch.setenv("MCP_MESH_API_NAME", "✨✨✨")
        service_id = DecoratorRegistry._generate_api_service_id_fallback()

        assert service_id.startswith("api-")

    def test_ordinary_name_is_unchanged(self, monkeypatch):
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        monkeypatch.setenv("MCP_MESH_API_NAME", "Order Service")
        service_id = DecoratorRegistry._generate_api_service_id_fallback()

        assert service_id.startswith("order-service-api-")


# ---------------------------------------------------------------------------
# Item 5: claim dispatchers started on one loop and stopped from another.
# ---------------------------------------------------------------------------


def _make_dispatcher():
    from _mcp_mesh.engine.claim_dispatcher import PythonClaimDispatcher

    async def handler(**kwargs):
        return None

    return PythonClaimDispatcher(
        capability="work",
        instance_id="agent-1",
        registry_url="http://registry:8000",
        handler=handler,
    )


class TestClaimDispatcherLoopAffinity:
    """The SAME dispatcher objects are staged both on the pipeline context
    (started on the heartbeat loop) and on ``app.state`` (started by the
    uvicorn lifespan). ``start()`` was idempotent but not loop-aware, so the
    second starter claimed ownership of a task belonging to the first
    starter's loop and its shutdown path then awaited a foreign-loop Task."""

    def test_start_reports_ownership(self):
        d = _make_dispatcher()

        async def go():
            assert d.start() is True
            # Same loop, already running -> still ours, still one task.
            first_task = d._task
            assert d.start() is True
            assert d._task is first_task
            d._task.cancel()
            try:
                await d._task
            except asyncio.CancelledError:
                pass

        asyncio.run(go())

    def test_second_loop_does_not_claim_ownership(self):
        d = _make_dispatcher()
        owner_ready = threading.Event()
        release = threading.Event()
        owner_loop_result = {}

        def owner_thread():
            async def go():
                owner_loop_result["owned"] = d.start()
                owner_loop_result["loop"] = asyncio.get_running_loop()
                owner_ready.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)
                d._task.cancel()
                try:
                    await d._task
                except asyncio.CancelledError:
                    pass

            asyncio.run(go())

        t = threading.Thread(target=owner_thread)
        t.start()
        assert owner_ready.wait(timeout=5)

        async def other_loop():
            # A second starter on a DIFFERENT loop must decline ownership
            # rather than silently adopting the first loop's task.
            return d.start()

        try:
            assert owner_loop_result["owned"] is True
            assert asyncio.run(other_loop()) is False
            assert d._loop is owner_loop_result["loop"]
        finally:
            release.set()
            t.join(timeout=5)

    def test_stop_from_a_foreign_loop_does_not_raise(self):
        d = _make_dispatcher()
        owner_ready = threading.Event()
        release = threading.Event()

        def owner_thread():
            async def go():
                d.start()
                owner_ready.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)
                d._task.cancel()
                try:
                    await d._task
                except asyncio.CancelledError:
                    pass

            asyncio.run(go())

        t = threading.Thread(target=owner_thread)
        t.start()
        assert owner_ready.wait(timeout=5)

        async def foreign_stop():
            # Awaiting the owner's Task from here would raise
            # "got Future attached to a different loop".
            await d.stop(drain_timeout=0)

        try:
            # Must not raise "Task ... got Future ... attached to a different
            # loop"; the owning loop is signalled instead of drained here.
            asyncio.run(foreign_stop())
            # The signal is delivered via call_soon_threadsafe, so give the
            # owning loop a moment to run it.
            deadline = time.monotonic() + 2.0
            while not d._stop.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert d._stop.is_set()
        finally:
            release.set()
            t.join(timeout=5)

    def test_foreign_loop_stop_completes_the_real_shutdown(self):
        # Signalling and returning would skip the in-flight drain (handlers
        # lose their terminal complete/fail reports) and leave _http_client
        # open, while the caller's `await d.stop(...)` believed shutdown had
        # finished. The whole stop has to run on the owning loop.
        d = _make_dispatcher()

        class _Client:
            def __init__(self):
                self.closed = False

            async def aclose(self):
                self.closed = True

        client = _Client()
        d._http_client = client

        owner_ready = threading.Event()
        release = threading.Event()

        def owner_thread():
            async def go():
                d.start()
                owner_ready.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)

            asyncio.run(go())

        t = threading.Thread(target=owner_thread)
        t.start()
        assert owner_ready.wait(timeout=5)

        try:
            asyncio.run(d.stop(drain_timeout=0))
            assert d._stop.is_set()
            assert d._task.done(), "the poll task was not actually stopped"
            assert client.closed is True, "the dispatcher HTTP client leaked"
        finally:
            release.set()
            t.join(timeout=5)

    def test_stop_on_a_dead_owner_loop_returns_quietly(self):
        d = _make_dispatcher()

        async def make_owner():
            d.start()
            d._task.cancel()
            try:
                await d._task
            except asyncio.CancelledError:
                pass

        asyncio.run(make_owner())  # owner loop is now closed

        async def foreign_stop():
            await d.stop(drain_timeout=0)

        asyncio.run(foreign_stop())  # must not raise or hang

    def test_same_loop_stop_still_drains(self):
        d = _make_dispatcher()

        async def go():
            d.start()
            await asyncio.sleep(0)
            await d.stop(drain_timeout=0)
            assert d._stop.is_set()
            assert d._task.done()

        asyncio.run(go())


# ---------------------------------------------------------------------------
# Item 6: DependencyInjector._lock was an asyncio.Lock on a global singleton.
# ---------------------------------------------------------------------------


class TestInjectorLockIsLoopAgnostic:
    def test_lock_is_not_an_asyncio_lock(self):
        from _mcp_mesh.engine.dependency_injector import DependencyInjector

        assert not isinstance(DependencyInjector()._lock, asyncio.Lock)

    def test_register_from_two_different_loops(self):
        # The #1565 shape: an asyncio.Lock binds to the first loop that awaits
        # it and raises "bound to a different event loop" on the second.
        from _mcp_mesh.engine.dependency_injector import DependencyInjector

        injector = DependencyInjector()

        class _Proxy:
            pass

        async def register(key):
            await injector.register_dependency(key, _Proxy())

        asyncio.run(register("mod.fn:dep_0"))
        asyncio.run(register("mod.fn:dep_1"))  # a different loop

        assert injector.get_dependency("mod.fn:dep_0") is not None
        assert injector.get_dependency("mod.fn:dep_1") is not None

    def test_signature_store_is_usable_from_a_plain_thread(self):
        from _mcp_mesh.engine.dependency_injector import DependencyInjector

        injector = DependencyInjector()
        errors: list = []

        def worker(n):
            try:
                for i in range(50):
                    injector.set_applied_dependency_signature(f"k{n}:{i}", (n, i))
                    injector.get_applied_dependency_signature(f"k{n}:{i}")
                    injector.clear_applied_dependency_signature(f"k{n}:{i}")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# Item 7: close_connection_pools dropped clients owned by unknown loops.
# ---------------------------------------------------------------------------


class TestCloseConnectionPoolsCoversEveryOwningLoop:
    """``close_connection_pools`` rebuilt the owner set from {current loop} ∪
    {tool-executor worker loops} and silently dropped — without ``aclose()`` —
    any client keyed to a loop outside it. The MeshJob claim dispatchers run
    on the heartbeat-thread loop, so that is a live third loop."""

    def test_client_created_on_a_third_loop_is_closed(self, monkeypatch):
        from _mcp_mesh.engine import unified_mcp_proxy as ump

        closed: list = []

        class _FakeClient:
            is_closed = False

            async def aclose(self):
                closed.append(self)

        # Simulate a client cached by a loop that is neither the caller's nor
        # a tool-executor worker's (i.e. the heartbeat thread's).
        ready = threading.Event()
        release = threading.Event()
        state = {}

        def foreign_owner():
            async def go():
                # Exactly what _get_httpx_client_sync does: register the owner
                # and publish the client under the SAME lock acquisition.
                loop = asyncio.get_running_loop()
                key = (id(loop), "http://producer:8080")
                with ump._pool_lock:
                    ump._pool_loops[id(loop)] = loop
                    ump._httpx_pool[key] = _FakeClient()
                state["key"] = key
                ready.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)

            asyncio.run(go())

        t = threading.Thread(target=foreign_owner)
        t.start()
        assert ready.wait(timeout=5)

        monkeypatch.setattr(
            "_mcp_mesh.shared.tool_executor.get_worker_loops", lambda: []
        )
        try:
            asyncio.run(ump.close_connection_pools())
            assert len(closed) == 1, "client on the heartbeat-style loop was dropped"
            assert ump._httpx_pool == {}
        finally:
            release.set()
            t.join(timeout=5)
            with ump._pool_lock:
                ump._httpx_pool.clear()
                ump._pool_loops.clear()

    def test_creating_a_pooled_client_registers_its_owner(self):
        from unittest.mock import patch

        from _mcp_mesh.engine import unified_mcp_proxy as ump

        class _FakeAsyncClient:
            is_closed = False

            def __init__(self, **kwargs):
                pass

        async def go():
            with patch("httpx.AsyncClient", _FakeAsyncClient):
                ump._get_httpx_client_sync("http://producer:8080")
            loop = asyncio.get_running_loop()
            assert ump._pool_loops.get(id(loop)) is loop

        try:
            asyncio.run(go())
        finally:
            with ump._pool_lock:
                ump._httpx_pool.clear()
                ump._pool_loops.clear()

    def test_loop_registry_does_not_retain_dead_loops(self):
        import gc
        from unittest.mock import patch

        from _mcp_mesh.engine import unified_mcp_proxy as ump

        class _FakeAsyncClient:
            is_closed = False

            def __init__(self, **kwargs):
                pass

        async def go():
            with patch("httpx.AsyncClient", _FakeAsyncClient):
                ump._get_httpx_client_sync("http://producer:8080")
            return id(asyncio.get_running_loop())

        try:
            loop_id = asyncio.run(go())  # loop is closed + dropped afterwards
            with ump._pool_lock:
                ump._httpx_pool.clear()
            gc.collect()
            assert loop_id not in ump._pool_loops, (
                "a strong map would keep every past loop alive"
            )
        finally:
            with ump._pool_lock:
                ump._httpx_pool.clear()
                ump._pool_loops.clear()


# ---------------------------------------------------------------------------
# Item 8: JSON-RPC null result, and usage on the buffered exhaustion envelope.
# ---------------------------------------------------------------------------


class _FakeHttpResponse:
    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None


class _FakeHttpxClient:
    def __init__(self, text):
        self._text = text
        self.post_calls = 0

    async def post(self, url, content=None, headers=None, timeout=None):
        self.post_calls += 1
        return _FakeHttpResponse(self._text)


class TestNullJsonRpcResult:
    """``"result": null`` used to come back as the fabricated envelope
    ``{"content":[{"type":"text","text":"No result returned"}]}`` — a truthy
    dict returned as a SUCCESS, where the FastMCP path's converter yields
    ``None`` for the same input (the #1250 "null round-trips as null"
    contract)."""

    def _call(self, payload_text):
        from unittest.mock import AsyncMock, patch

        from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy

        proxy = UnifiedMCPProxy("http://provider:8080", "lookup")
        client = _FakeHttpxClient(payload_text)
        with (
            patch(
                "_mcp_mesh.engine.unified_mcp_proxy._get_httpx_client_sync",
                return_value=client,
            ),
            patch.object(proxy, "_get_or_create_fastmcp_client", AsyncMock()),
        ):
            return asyncio.run(proxy.call_tool("lookup", {}))

    def test_explicit_null_result_is_none(self):
        assert (
            self._call(json.dumps({"jsonrpc": "2.0", "id": 1, "result": None})) is None
        )

    def test_absent_result_member_is_none(self):
        assert self._call(json.dumps({"jsonrpc": "2.0", "id": 1})) is None

    def test_matches_the_fastmcp_converter_for_the_same_value(self):
        from _mcp_mesh.engine.unified_mcp_proxy import UnifiedMCPProxy

        proxy = UnifiedMCPProxy("http://provider:8080", "lookup")
        assert proxy._convert_mcp_result_to_python(None) is None


class TestBufferedExhaustionUsage:
    """On ``max_iterations`` the buffered provider loop reported no token
    usage on any channel; its streaming twin at least publishes cumulative
    counts via ``set_llm_metadata``."""

    def test_exhaustion_envelope_carries_cumulative_usage(self, monkeypatch):
        import mesh.helpers as helpers

        class _Usage:
            def __init__(self, p, c):
                self.prompt_tokens = p
                self.completion_tokens = c

        class _Function:
            name = "lookup"
            arguments = "{}"

        class _ToolCall:
            id = "tc-1"
            type = "function"
            function = _Function()

        class _Message:
            role = "assistant"
            content = "still thinking"
            tool_calls = [_ToolCall()]

        class _Choice:
            message = _Message()

        class _Response:
            def __init__(self, p, c):
                self.choices = [_Choice()]
                self.usage = _Usage(p, c)

        async def fake_dispatch(*args, **kwargs):
            return _Response(10, 5)

        async def fake_execute(*args, **kwargs):
            return ([{"role": "tool", "tool_call_id": "tc-1", "content": "ok"}], [])

        monkeypatch.setattr(helpers, "_dispatch_completion", fake_dispatch)
        monkeypatch.setattr(helpers, "_execute_tool_calls_for_iteration", fake_execute)

        result = asyncio.run(
            helpers._provider_agentic_loop(
                effective_model="anthropic/claude",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_endpoints={},
                model_params={},
                litellm_kwargs={},
                max_iterations=3,
            )
        )

        assert result[helpers.STOP_REASON_KEY] == helpers.STOP_REASON_MAX_ITERATIONS
        # The loop ran 3 iterations at (10 prompt, 5 completion) each; before
        # #1591 the exhaustion envelope reported no usage at all.
        assert result["_mesh_usage"]["prompt_tokens"] == 30
        assert result["_mesh_usage"]["completion_tokens"] == 15
        assert result["_mesh_usage"]["model"] == "anthropic/claude"
        # The last genuine assistant text still rides `content` (#1355).
        assert result["content"] == "still thinking"

    def test_no_usage_key_when_the_provider_reported_none(self, monkeypatch):
        import mesh.helpers as helpers

        class _Function:
            name = "lookup"
            arguments = "{}"

        class _ToolCall:
            id = "tc-1"
            type = "function"
            function = _Function()

        class _Message:
            role = "assistant"
            content = ""
            tool_calls = [_ToolCall()]

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]
            usage = None

        async def fake_dispatch(*args, **kwargs):
            return _Response()

        async def fake_execute(*args, **kwargs):
            return ([{"role": "tool", "tool_call_id": "tc-1", "content": "ok"}], [])

        monkeypatch.setattr(helpers, "_dispatch_completion", fake_dispatch)
        monkeypatch.setattr(helpers, "_execute_tool_calls_for_iteration", fake_execute)

        result = asyncio.run(
            helpers._provider_agentic_loop(
                effective_model="anthropic/claude",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                tool_endpoints={},
                model_params={},
                litellm_kwargs={},
                max_iterations=2,
            )
        )

        assert "_mesh_usage" not in result
