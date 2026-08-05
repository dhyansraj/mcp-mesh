"""The health refresh publishes to the Rust core; the startup seed does not.

Issue #1472. ``_add_k8s_endpoints`` runs during pipeline setup — before the
lifespan task calls ``start_agent()`` — and seeds the stored ``/health``
result by invoking the user's ``health_check`` once on the framework loop.
That seed result is known-unreliable (loop-affine resources created in the
user's lifespan are not usable yet, see the comment at the call site), so it
must never be able to withdraw the agent from dependency resolution.

Only the periodic refresh, which runs on the user loop one TTL later, is
allowed to report to the core.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from _mcp_mesh.pipeline.mcp_startup.fastapiserver_setup import FastAPIServerSetupStep
from _mcp_mesh.shared import health_check_manager


@pytest.fixture(autouse=True)
def clean_health_state():
    """The TTL cache and stored result are module globals — reset both."""
    health_check_manager.clear_health_cache()
    health_check_manager.clear_health_check_result()
    yield
    health_check_manager.clear_health_cache()
    health_check_manager.clear_health_check_result()


@pytest.fixture
def published(monkeypatch):
    """Capture every status handed to the Rust core."""
    calls: list[str] = []
    monkeypatch.setattr(
        health_check_manager,
        "publish_health_status_to_core",
        lambda status: calls.append(status) or True,
    )
    return calls


@pytest.fixture
def no_user_loop(monkeypatch):
    """Skip the user-loop refresh scheduling — this test is about the seed.

    Without this the step would start real worker threads and schedule a
    long-lived coroutine; the seed call happens before any of that.
    """
    from _mcp_mesh.shared import tool_executor

    monkeypatch.setattr(tool_executor, "_start_workers", lambda *a, **k: None)
    monkeypatch.setattr(tool_executor, "get_worker_loops", lambda: [])


async def _run_seed(step: FastAPIServerSetupStep, health_check_fn) -> None:
    await step._add_k8s_endpoints(
        FastAPI(),
        {
            "name": "seed-agent",
            "health_check": health_check_fn,
            "health_check_ttl": 15,
        },
        {},
        {},
    )


@pytest.mark.asyncio
async def test_failing_seed_health_check_does_not_withdraw_the_agent(
    published, no_user_loop
):
    """A health check that fails at startup must NOT suppress the heartbeat.

    The agent should register and be visible; if the failure is real, the
    first periodic refresh withdraws it one TTL later.
    """
    step = FastAPIServerSetupStep()

    async def failing_health_check():
        return False

    await _run_seed(step, failing_health_check)

    # The stored result reflects the failure (so /health and /ready 503)...
    stored = health_check_manager.get_health_check_result()
    assert stored["status"] == "unhealthy"
    # ...but nothing was reported to the core.
    assert published == []


@pytest.mark.asyncio
async def test_passing_seed_health_check_also_stays_local(published, no_user_loop):
    """Same for the happy path — the seed never talks to the core at all,
    so the rule is one branch, not two.
    """
    step = FastAPIServerSetupStep()

    async def passing_health_check():
        return True

    await _run_seed(step, passing_health_check)

    assert health_check_manager.get_health_check_result()["status"] == "healthy"
    assert published == []
