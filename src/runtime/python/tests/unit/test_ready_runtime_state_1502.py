"""``/ready`` reports the mesh runtime, never the health verdict — RFC #1502.

Step 2 of the RFC. Until this landed, a Python ``@mesh.agent`` provider's
``/ready`` answered 503 whenever the stored ``health_check`` result was
anything but ``healthy``, while its gateway pipelines (#1491) already reported
runtime state alone. Providers now adopt the gateway's rule, so the two agree.

WHY THE VERDICT MUST NOT DRIVE READINESS

``agent.advertisedHost`` defaults to the per-agent Service DNS name and the
chart ships a ``service.yaml``, so mesh traffic traverses the Service. A
failing check already withdraws the agent by pausing the heartbeat — the
registry ages it out and resolution stops selecting it. Answering 503 here as
well drops the pod from its Service endpoints, and during the window where the
registry has not swept yet a consumer gets a connection error instead of a
failover. Readiness removal without heartbeat suppression is strictly worse
than either alone.

WHY IT IS NOT UNCONDITIONAL EITHER

``startup_check`` defaults to true, so ``/startupz`` answers 200 before the
runtime is up: an unconditional ``/ready`` would let a pod go Ready with no
mesh runtime behind it. The runtime floor keeps that window closed and still
removes every verdict-driven readiness transition.

``/health`` is deliberately NOT part of this: it keeps answering 503 for a
non-healthy verdict. Nothing probes it, so the status code is free to carry
information, and it is where an operator sees what the check reports.
"""

import pytest

from _mcp_mesh.shared import health_check_manager, simple_shutdown
from _mcp_mesh.shared.health_check_manager import (
    build_health_response,
    build_livez_response,
    build_ready_response,
)

# ``runtime_state`` is imported inside the one test that needs it, not here:
# a module-level import of a name this change introduces would make the whole
# file red on an ImportError against the pre-change tree, and an ImportError
# proves nothing about what ``/ready`` answered.


@pytest.fixture(autouse=True)
def _clean_stored_result():
    """No stored verdict leaks between tests (the store is module global)."""
    health_check_manager.clear_health_check_result()
    yield
    health_check_manager.clear_health_check_result()


@pytest.fixture
def runtime_up(monkeypatch):
    """A live Rust core handle exists — the mesh runtime is up."""
    monkeypatch.setattr(
        simple_shutdown, "get_active_rust_agent_handles", lambda: [object()]
    )
    monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: False)


@pytest.fixture
def runtime_starting(monkeypatch):
    """No handle yet — start_agent() has not returned."""
    monkeypatch.setattr(simple_shutdown, "get_active_rust_agent_handles", list)
    monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: False)


@pytest.fixture
def runtime_shutting_down(monkeypatch):
    """Shutdown requested — the handle may still exist for a moment."""
    monkeypatch.setattr(
        simple_shutdown, "get_active_rust_agent_handles", lambda: [object()]
    )
    monkeypatch.setattr(simple_shutdown, "should_stop_heartbeat", lambda: True)


def _store(status: str, **extra):
    health_check_manager.store_health_check_result(
        {"status": status, "agent": "provider", **extra}
    )


# ---------------------------------------------------------------------------
# The change: a non-healthy verdict no longer makes a provider unready
# ---------------------------------------------------------------------------


class TestVerdictDoesNotDriveReadiness:
    @pytest.mark.parametrize("status", ["unhealthy", "degraded", "unknown"])
    def test_ready_stays_200_for_every_non_healthy_verdict(self, runtime_up, status):
        _store(status, errors=["simulated vendor outage"])

        body, code = build_ready_response(agent_name="provider")

        assert code == 200
        assert body["ready"] is True

    def test_ready_carries_the_runtime_state_not_the_verdict(self, runtime_up):
        """The body reports what the endpoint actually consulted.

        A ``status`` key echoing the health verdict would invite exactly the
        misreading this change exists to remove — ``status: unhealthy`` beside
        a 200 reads as a contradiction rather than as two separate facts.
        """
        _store("unhealthy", errors=["vendor 503"])

        body, _ = build_ready_response(agent_name="provider")

        assert body["runtime"] == "up"
        assert "status" not in body
        assert "errors" not in body

    def test_a_healthy_verdict_is_200_as_before(self, runtime_up):
        _store("healthy")

        body, code = build_ready_response(agent_name="provider")

        assert code == 200
        assert body["ready"] is True

    def test_no_stored_result_at_all_is_200(self, runtime_up):
        """An agent with no ``health_check`` is unaffected, as it always was."""
        body, code = build_ready_response(agent_name="provider")

        assert code == 200
        assert body["ready"] is True
        assert body["agent"] == "provider"
        assert body["mcp_wrappers"] == 0

    def test_ready_never_reads_the_stored_result(self, runtime_up, monkeypatch):
        """Not just "the verdict does not change the answer" — it is not read.

        A builder that still consulted the store and happened to map every
        verdict to 200 would pass the assertions above and reintroduce the
        coupling the moment someone re-added a branch.
        """

        def exploding_getter():
            raise AssertionError("/ready must not consult the health verdict")

        monkeypatch.setattr(
            health_check_manager, "get_health_check_result", exploding_getter
        )

        assert build_ready_response(agent_name="provider")[1] == 200


# ---------------------------------------------------------------------------
# The floor: the runtime state still decides
# ---------------------------------------------------------------------------


class TestRuntimeStateIsTheFloor:
    def test_no_handle_yet_is_503_even_with_a_healthy_verdict(self, runtime_starting):
        _store("healthy")

        body, code = build_ready_response(agent_name="provider")

        assert code == 503
        assert body["ready"] is False
        assert body["runtime"] == "starting"
        assert body["reason"] == "Mesh runtime has not started yet"

    def test_shutting_down_is_503(self, runtime_shutting_down):
        _store("healthy")

        body, code = build_ready_response(agent_name="provider")

        assert code == 503
        assert body["runtime"] == "shutting_down"
        assert body["reason"] == "Mesh runtime is shutting down"

    def test_standalone_is_ready_without_any_handle(
        self, runtime_starting, monkeypatch
    ):
        """Standalone never starts a Rust core; that is configuration, not a
        startup that has not finished."""
        monkeypatch.setenv("MCP_MESH_STANDALONE", "true")

        body, code = build_ready_response(agent_name="provider")

        assert code == 200
        assert body["runtime"] == "standalone"

    def test_runtime_state_is_one_definition_shared_with_the_gateway(self):
        """The gateway pipeline must resolve the SAME function.

        Two copies of "the runtime is up" is how a gateway and a provider end
        up disagreeing about what readiness means.
        """
        from _mcp_mesh.pipeline.shared import health_endpoints
        from _mcp_mesh.shared.health_check_manager import runtime_state

        assert health_endpoints.runtime_state is runtime_state


# ---------------------------------------------------------------------------
# What did NOT change
# ---------------------------------------------------------------------------


class TestOtherEndpointsAreUnchanged:
    @pytest.mark.parametrize("status", ["unhealthy", "degraded"])
    def test_health_still_answers_503_for_a_non_healthy_verdict(self, status):
        """``/health`` is the diagnostic view and nothing probes it, so the
        status code is free to carry the verdict. It must keep doing so —
        ``/ready`` and ``/health`` now diverge, deliberately."""
        _store(status, errors=["vendor 503"])

        body, code = build_health_response(agent_name="provider")

        assert code == 503
        assert body["status"] == status

    def test_health_is_200_when_healthy(self):
        _store("healthy")

        assert build_health_response(agent_name="provider")[1] == 200

    def test_livez_consults_nothing(self, runtime_starting):
        _store("unhealthy")

        assert build_livez_response(agent_name="provider")["alive"] is True
