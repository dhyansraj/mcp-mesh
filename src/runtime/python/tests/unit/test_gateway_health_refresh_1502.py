"""``health_check`` on a Python gateway — RFC #1502, step 3.

``@mesh.route`` (api) and ``@mesh.a2a`` (a2a) gateways had no health-refresh
loop at all: that absence WAS #1473's exemption in Python, so a declared
``health_check`` never ran and could never withdraw the gateway.

Step 2 removed the harm the exemption existed to prevent. Suppressing the
heartbeat stops registry traffic ONLY — the user's uvicorn keeps serving,
resolved dependencies are retained (#1131), and ``/ready`` reports the mesh
runtime rather than the verdict, so the pod stays in its Service endpoints and
keeps taking ingress. A withdrawn gateway stops being *discovered*; it does not
go dark.

What is pinned here:

* the loop is the SHARED one (``pipeline/shared/health_refresh.py``), driven by
  the provider pipeline and both gateway heartbeats — not a second copy;
* a gateway that declares no check starts no loop, so nothing changes for it;
* a failing check reaches ``publish_health_status_to_core``, which is what
  pauses the heartbeat;
* the seed never publishes: a check that fails at boot must not withdraw an
  agent that has only just registered;
* both gateway heartbeats start the loop after ``start_agent()`` and cancel it
  on teardown.
"""

import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest

from _mcp_mesh.pipeline.shared import health_refresh as refresh_mod


@pytest.fixture
def published(monkeypatch):
    """Record every verdict handed to the Rust core."""
    from _mcp_mesh.shared import health_check_manager

    seen: list[str] = []
    monkeypatch.setattr(
        health_check_manager,
        "publish_health_status_to_core",
        lambda status: seen.append(status) or True,
    )
    return seen


@pytest.fixture
def declared(monkeypatch):
    """Install an agent config the way ``@mesh.agent(health_check=...)`` does."""
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
    from _mcp_mesh.shared import health_check_manager

    def declare(check, ttl=1):
        config = {"agent_id": "gateway-abcd1234", "name": "gateway"}
        if check is not None:
            config["health_check"] = check
            config["health_check_ttl"] = ttl
        monkeypatch.setattr(DecoratorRegistry, "_cached_agent_config", config)
        health_check_manager.clear_health_cache()
        health_check_manager.clear_health_check_result()

    yield declare
    health_check_manager.clear_health_check_result()
    health_check_manager.clear_health_cache()


async def _wait_for(predicate, timeout=10.0):
    """Poll until ``predicate()`` is truthy, or fail with the reason."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"condition not met within {timeout}s")


# (module path, heartbeat task, the service_type it must report)
GATEWAY_HEARTBEATS = [
    (
        "_mcp_mesh.pipeline.api_heartbeat.rust_api_heartbeat",
        "rust_api_heartbeat_task",
        "api",
    ),
    (
        "_mcp_mesh.pipeline.a2a_heartbeat.rust_a2a_heartbeat",
        "rust_a2a_heartbeat_task",
        "a2a",
    ),
]


def _drive_gateway_heartbeat(
    monkeypatch, module_path, task_name, fake_start, on_start_agent=None
):
    """Run one gateway heartbeat task to completion against a stubbed core.

    ``fake_start`` is installed on ``refresh_mod`` — the SHARED module — and
    both heartbeats resolve ``start_gateway_health_refresh`` from there at call
    time, so a heartbeat that grew its own copy of the loop would never reach
    this stub and the caller's assertions would go red.
    """
    import importlib

    module = importlib.import_module(module_path)
    spec_builder = (
        "_build_api_agent_spec"
        if hasattr(module, "_build_api_agent_spec")
        else "_build_a2a_agent_spec"
    )
    monkeypatch.setattr(module, spec_builder, lambda context, service_id=None: object())

    # A core handle that reports one ``shutdown`` event and stops.
    handle = SimpleNamespace(
        next_event=lambda: asyncio.sleep(
            0, result=SimpleNamespace(event_type="shutdown")
        ),
        shutdown=lambda: None,
    )
    core = SimpleNamespace(
        start_agent=lambda spec: (on_start_agent and on_start_agent(), handle)[1]
    )
    monkeypatch.setattr(module, "_get_rust_core", lambda: core)
    monkeypatch.setattr(refresh_mod, "start_gateway_health_refresh", fake_start)

    asyncio.run(
        getattr(module, task_name)(
            {"service_id": "gw-1", "context": {}, "standalone_mode": False}
        )
    )


class TestSharedLoopIsShared:
    def test_the_provider_pipeline_uses_it(self, monkeypatch):
        """The MCP path must not keep its own copy — a second loop is how the
        provider and gateway behaviours drift apart.

        Patching the shared module and watching the pipeline drive it is the
        only way to show that: a source grep passes on a comment, and on an
        import that nothing ever calls.
        """
        from unittest.mock import MagicMock

        from _mcp_mesh.pipeline.mcp_startup.fastapiserver_setup import (
            FastAPIServerSetupStep,
        )
        from _mcp_mesh.shared import tool_executor, user_loop_hooks

        seeded: list[dict] = []
        looped: list[dict] = []

        async def fake_once(**kwargs):
            seeded.append(kwargs)
            return {"status": "healthy"}

        async def fake_loop(**kwargs):
            looped.append(kwargs)

        monkeypatch.setattr(refresh_mod, "refresh_health_once", fake_once)
        monkeypatch.setattr(refresh_mod, "health_refresh_loop", fake_loop)

        # The provider runs the loop on the user loop, behind the
        # lifespan-ready gate; none of that machinery is under test here, so
        # run the scheduled coroutine inline instead.
        scheduled: list = []
        monkeypatch.setattr(tool_executor, "_start_workers", lambda: None)
        monkeypatch.setattr(
            tool_executor, "get_worker_loops", lambda: [asyncio.get_event_loop()]
        )
        monkeypatch.setattr(
            user_loop_hooks,
            "get_or_create_lifespan_ready_future",
            lambda app: concurrent.futures.Future(),
        )
        monkeypatch.setattr(
            user_loop_hooks,
            "schedule_on_user_loop",
            lambda app, user_loop, coro_factory, **kw: scheduled.append(
                asyncio.ensure_future(coro_factory())
            ),
        )

        async def check():
            return True

        async def run():
            await FastAPIServerSetupStep()._add_k8s_endpoints(
                MagicMock(),
                {"name": "provider", "health_check": check, "health_check_ttl": 1},
                {},
                {},
            )
            await asyncio.gather(*scheduled)

        asyncio.run(run())

        assert [kw["publish_to_core"] for kw in seeded] == [False], (
            "the provider seed must go through the shared refresh_health_once, "
            "and must not publish"
        )
        assert len(looped) == 1, "the shared loop was never driven"
        assert looped[0]["agent_name"] == "provider"
        assert looped[0]["health_check_fn"] is check

        # And no second copy of the extracted body was left behind.
        import inspect

        from _mcp_mesh.pipeline.mcp_startup import fastapiserver_setup

        assert "publish_health_status_to_core" not in inspect.getsource(
            fastapiserver_setup
        )

    @pytest.mark.parametrize("module_path,task_name,service_type", GATEWAY_HEARTBEATS)
    def test_both_gateway_heartbeats_use_it(
        self, monkeypatch, module_path, task_name, service_type
    ):
        """Same argument for the two gateway paths: the heartbeat must actually
        call the shared starter, not merely mention or import it."""
        called: list[str] = []

        def fake_start(*, service_type, service_id, context, log=None):
            called.append(service_type)
            return SimpleNamespace(cancel=lambda: None)

        _drive_gateway_heartbeat(monkeypatch, module_path, task_name, fake_start)

        assert called == [service_type], "the shared starter was never invoked"


class TestStartGatewayHealthRefresh:
    def test_no_check_declared_starts_nothing(self, declared):
        declared(None)

        async def run():
            return refresh_mod.start_gateway_health_refresh(
                service_type="api", service_id="gateway-abcd1234", context={}
            )

        assert asyncio.run(run()) is None

    def test_a_declared_check_starts_a_task(self, declared):
        declared(lambda: True)

        async def run():
            task = refresh_mod.start_gateway_health_refresh(
                service_type="api", service_id="gateway-abcd1234", context={}
            )
            assert task is not None
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run())

    def test_a_failing_check_pauses_the_gateways_heartbeat(self, declared, published):
        """The whole of step 3: ``unhealthy`` reaches the core, which stops
        heartbeating, and the registry stops advertising this gateway."""

        async def unhealthy():
            return {"status": "unhealthy", "errors": ["upstream down"]}

        declared(unhealthy, ttl=1)

        async def run():
            task = refresh_mod.start_gateway_health_refresh(
                service_type="api", service_id="gateway-abcd1234", context={}
            )
            try:
                await _wait_for(lambda: published)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert published[0] == "unhealthy"

        asyncio.run(run())

    def test_a2a_gateways_get_the_same_treatment(self, declared, published):
        async def unhealthy():
            return False

        declared(unhealthy, ttl=1)

        async def run():
            task = refresh_mod.start_gateway_health_refresh(
                service_type="a2a", service_id="gateway-abcd1234", context={}
            )
            try:
                await _wait_for(lambda: published)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert published[0] == "unhealthy"

        asyncio.run(run())

    def test_the_seed_feeds_health_but_never_publishes(self, declared, published):
        """A check that fails at boot — a client built lazily, a pool not warm
        — must not withdraw a gateway that has only just registered."""
        from _mcp_mesh.shared import health_check_manager

        async def unhealthy():
            return {"status": "unhealthy", "errors": ["not warm yet"]}

        # A long TTL keeps the first scheduled refresh out of the window, so
        # anything observed here came from the seed.
        declared(unhealthy, ttl=300)

        async def run():
            task = refresh_mod.start_gateway_health_refresh(
                service_type="api", service_id="gateway-abcd1234", context={}
            )
            try:
                await _wait_for(
                    lambda: health_check_manager.get_health_check_result() is not None
                )
                stored = health_check_manager.get_health_check_result()
                assert stored["status"] == "unhealthy"
                assert published == []
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        asyncio.run(run())

    def test_a_throwing_check_degrades_rather_than_withdrawing(
        self, declared, published
    ):
        """Same rule as a provider's: a buggy check must not be able to remove
        a working agent from the mesh."""

        async def boom():
            raise RuntimeError("probe is broken")

        declared(boom, ttl=1)

        async def run():
            task = refresh_mod.start_gateway_health_refresh(
                service_type="api", service_id="gateway-abcd1234", context={}
            )
            try:
                await _wait_for(lambda: published)
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert published[0] == "degraded"

        asyncio.run(run())


class TestHeartbeatWiring:
    """The gateway heartbeats start the loop and cancel it on teardown."""

    @pytest.mark.parametrize("module_path,task_name,service_type", GATEWAY_HEARTBEATS)
    def test_started_after_registration_and_cancelled_on_teardown(
        self, monkeypatch, module_path, task_name, service_type
    ):
        order: list[str] = []
        cancelled: list[bool] = []

        def fake_start(*, service_type, service_id, context, log=None):
            order.append(f"health_refresh:{service_type}")
            return SimpleNamespace(cancel=lambda: cancelled.append(True))

        _drive_gateway_heartbeat(
            monkeypatch,
            module_path,
            task_name,
            fake_start,
            on_start_agent=lambda: order.append("start_agent"),
        )

        assert order == ["start_agent", f"health_refresh:{service_type}"], (
            "the refresh must start AFTER start_agent — the gateway registers "
            "and becomes visible before anything can withdraw it"
        )
        assert cancelled == [True], "the loop must be cancelled on teardown"
