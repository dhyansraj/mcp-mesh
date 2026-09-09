"""Regression test for the ``/metadata`` endpoint's session-affinity block.

``HttpMcpWrapper.get_session_stats`` became ``async`` in #1590 (its Redis
client is ``redis.asyncio`` now). The one caller — the ``@app.get("/metadata")``
handler in ``fastapiserver_setup`` — was not awaited, and calling an async
function raises nothing, so the surrounding ``except Exception`` never fired:
the coroutine is truthy, lands in ``metadata_response["session_affinity"]``,
and FastAPI fails to encode it. ``/metadata`` returned 500 on every Python MCP
agent.

This exercises the ROUTE, not the method, because that is the only level at
which the un-awaited coroutine is observable.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from _mcp_mesh.pipeline.mcp_startup.fastapiserver_setup import FastAPIServerSetupStep


class _FakeWrapper:
    """Stand-in for HttpMcpWrapper with the post-#1590 async stats method."""

    def __init__(self):
        self.calls = 0

    async def get_session_stats(self) -> dict:
        self.calls += 1
        return {
            "pod_ip": "10.0.0.1",
            "storage_backend": "memory",
            "redis_available": False,
            "total_sessions": 2,
            "active_sessions": ["session:a", "session:b"],
        }


async def _build_app(wrapper) -> tuple[FastAPI, FastAPIServerSetupStep]:
    from unittest.mock import AsyncMock, patch

    app = FastAPI()
    step = FastAPIServerSetupStep()
    step._current_context = {
        "agent_id": "metadata-agent",
        "mcp_wrappers": {"srv": {"wrapper": wrapper}},
    }

    with (
        patch(
            "_mcp_mesh.shared.health_check_manager.get_health_status_with_cache",
            new_callable=AsyncMock,
        ),
        patch("_mcp_mesh.shared.tool_executor._start_workers"),
        patch("_mcp_mesh.shared.tool_executor.get_worker_loops", return_value=[]),
    ):
        await step._add_k8s_endpoints(
            app, {"name": "metadata-agent"}, {"srv": {"wrapper": wrapper}}, {}
        )
    return app, step


class TestMetadataEndpointSessionAffinity:
    @pytest.mark.asyncio
    async def test_metadata_returns_200_with_encodable_session_stats(self):
        wrapper = _FakeWrapper()
        app, _ = await _build_app(wrapper)

        with TestClient(app) as client:
            response = client.get("/metadata")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["session_affinity"]["total_sessions"] == 2
        assert body["session_affinity"]["storage_backend"] == "memory"
        assert wrapper.calls == 1

    @pytest.mark.asyncio
    async def test_no_coroutine_leaks_into_the_response(self):
        # The precise failure shape: an un-awaited coroutine is truthy, so it
        # passes the `if session_affinity_stats:` gate and reaches the encoder.
        wrapper = _FakeWrapper()
        app, _ = await _build_app(wrapper)

        with TestClient(app) as client:
            response = client.get("/metadata")

        assert "coroutine" not in response.text.lower()

    @pytest.mark.asyncio
    async def test_a_failing_stats_call_degrades_instead_of_500ing(self):
        class _BrokenWrapper:
            async def get_session_stats(self):
                raise RuntimeError("redis exploded")

        app, _ = await _build_app(_BrokenWrapper())

        with TestClient(app) as client:
            response = client.get("/metadata")

        assert response.status_code == 200, response.text
        assert response.json()["session_affinity"] == {
            "error": "session stats unavailable"
        }

    @pytest.mark.asyncio
    async def test_metadata_works_without_any_wrappers(self):
        app = FastAPI()
        step = FastAPIServerSetupStep()
        step._current_context = {"agent_id": "metadata-agent", "mcp_wrappers": {}}

        from unittest.mock import AsyncMock, patch

        with (
            patch(
                "_mcp_mesh.shared.health_check_manager.get_health_status_with_cache",
                new_callable=AsyncMock,
            ),
            patch("_mcp_mesh.shared.tool_executor._start_workers"),
            patch("_mcp_mesh.shared.tool_executor.get_worker_loops", return_value=[]),
        ):
            await step._add_k8s_endpoints(app, {"name": "metadata-agent"}, {}, {})

        with TestClient(app) as client:
            response = client.get("/metadata")

        assert response.status_code == 200, response.text
        assert "session_affinity" not in response.json()
