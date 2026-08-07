"""
Unit tests for FastHeartbeatStatus utility class.

Tests the conversion between HTTP status codes and semantic labels,
as well as resilient decision-making logic for pipeline optimization.
"""

import pytest

from _mcp_mesh.shared.fast_heartbeat_status import (
    FastHeartbeatStatus,
    FastHeartbeatStatusUtil,
)


class TestFastHeartbeatStatus:
    """Test FastHeartbeatStatus enum values."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert FastHeartbeatStatus.NO_CHANGES.value == "no_changes"
        assert FastHeartbeatStatus.TOPOLOGY_CHANGED.value == "topology_changed"
        assert FastHeartbeatStatus.AGENT_UNKNOWN.value == "agent_unknown"
        assert FastHeartbeatStatus.REGISTRY_ERROR.value == "registry_error"
        assert FastHeartbeatStatus.NETWORK_ERROR.value == "network_error"


class TestFastHeartbeatStatusUtil:
    """Test FastHeartbeatStatusUtil utility methods."""

    def test_from_http_code_200_ok(self):
        """Test conversion of HTTP 200 to NO_CHANGES."""
        result = FastHeartbeatStatusUtil.from_http_code(200)
        assert result == FastHeartbeatStatus.NO_CHANGES

    def test_from_http_code_202_accepted(self):
        """Test conversion of HTTP 202 to TOPOLOGY_CHANGED."""
        result = FastHeartbeatStatusUtil.from_http_code(202)
        assert result == FastHeartbeatStatus.TOPOLOGY_CHANGED

    def test_from_http_code_410_gone(self):
        """Test conversion of HTTP 410 to AGENT_UNKNOWN."""
        result = FastHeartbeatStatusUtil.from_http_code(410)
        assert result == FastHeartbeatStatus.AGENT_UNKNOWN

    def test_from_http_code_503_service_unavailable(self):
        """Test conversion of HTTP 503 to REGISTRY_ERROR."""
        result = FastHeartbeatStatusUtil.from_http_code(503)
        assert result == FastHeartbeatStatus.REGISTRY_ERROR

    def test_from_http_code_unknown_raises_error(self):
        """Test that unknown HTTP codes raise ValueError."""
        with pytest.raises(
            ValueError, match="Unsupported fast heartbeat status code: 404"
        ):
            FastHeartbeatStatusUtil.from_http_code(404)

        with pytest.raises(
            ValueError, match="Unsupported fast heartbeat status code: 500"
        ):
            FastHeartbeatStatusUtil.from_http_code(500)

    def test_requires_full_heartbeat_topology_changed(self):
        """Test that TOPOLOGY_CHANGED requires full heartbeat."""
        result = FastHeartbeatStatusUtil.requires_full_heartbeat(
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        assert result is True

    def test_requires_full_heartbeat_agent_unknown(self):
        """Test that AGENT_UNKNOWN requires full heartbeat."""
        result = FastHeartbeatStatusUtil.requires_full_heartbeat(
            FastHeartbeatStatus.AGENT_UNKNOWN
        )
        assert result is True

    def test_requires_full_heartbeat_no_changes(self):
        """Test that NO_CHANGES does not require full heartbeat."""
        result = FastHeartbeatStatusUtil.requires_full_heartbeat(
            FastHeartbeatStatus.NO_CHANGES
        )
        assert result is False

    def test_requires_full_heartbeat_registry_error(self):
        """Test that REGISTRY_ERROR does not require full heartbeat."""
        result = FastHeartbeatStatusUtil.requires_full_heartbeat(
            FastHeartbeatStatus.REGISTRY_ERROR
        )
        assert result is False

    def test_requires_full_heartbeat_network_error(self):
        """Test that NETWORK_ERROR does not require full heartbeat."""
        result = FastHeartbeatStatusUtil.requires_full_heartbeat(
            FastHeartbeatStatus.NETWORK_ERROR
        )
        assert result is False

    def test_should_skip_for_resilience_registry_error(self):
        """Test that REGISTRY_ERROR should skip for resilience."""
        result = FastHeartbeatStatusUtil.should_skip_for_resilience(
            FastHeartbeatStatus.REGISTRY_ERROR
        )
        assert result is True

    def test_should_skip_for_resilience_network_error(self):
        """Test that NETWORK_ERROR should skip for resilience."""
        result = FastHeartbeatStatusUtil.should_skip_for_resilience(
            FastHeartbeatStatus.NETWORK_ERROR
        )
        assert result is True

    def test_should_skip_for_resilience_no_changes(self):
        """Test that NO_CHANGES should not skip for resilience."""
        result = FastHeartbeatStatusUtil.should_skip_for_resilience(
            FastHeartbeatStatus.NO_CHANGES
        )
        assert result is False

    def test_should_skip_for_resilience_topology_changed(self):
        """Test that TOPOLOGY_CHANGED should not skip for resilience."""
        result = FastHeartbeatStatusUtil.should_skip_for_resilience(
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        assert result is False

    def test_should_skip_for_resilience_agent_unknown(self):
        """Test that AGENT_UNKNOWN should not skip for resilience."""
        result = FastHeartbeatStatusUtil.should_skip_for_resilience(
            FastHeartbeatStatus.AGENT_UNKNOWN
        )
        assert result is False

    def test_should_skip_for_optimization_no_changes(self):
        """Test that NO_CHANGES should skip for optimization."""
        result = FastHeartbeatStatusUtil.should_skip_for_optimization(
            FastHeartbeatStatus.NO_CHANGES
        )
        assert result is True

    def test_should_skip_for_optimization_topology_changed(self):
        """Test that TOPOLOGY_CHANGED should not skip for optimization."""
        result = FastHeartbeatStatusUtil.should_skip_for_optimization(
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        assert result is False

    def test_should_skip_for_optimization_agent_unknown(self):
        """Test that AGENT_UNKNOWN should not skip for optimization."""
        result = FastHeartbeatStatusUtil.should_skip_for_optimization(
            FastHeartbeatStatus.AGENT_UNKNOWN
        )
        assert result is False

    def test_should_skip_for_optimization_registry_error(self):
        """Test that REGISTRY_ERROR should not skip for optimization."""
        result = FastHeartbeatStatusUtil.should_skip_for_optimization(
            FastHeartbeatStatus.REGISTRY_ERROR
        )
        assert result is False

    def test_should_skip_for_optimization_network_error(self):
        """Test that NETWORK_ERROR should not skip for optimization."""
        result = FastHeartbeatStatusUtil.should_skip_for_optimization(
            FastHeartbeatStatus.NETWORK_ERROR
        )
        assert result is False

    def test_from_exception_any_exception(self):
        """Test that any exception converts to NETWORK_ERROR."""
        # Test various exception types
        exceptions = [
            Exception("Generic error"),
            ConnectionError("Network failure"),
            TimeoutError("Request timeout"),
            ValueError("Invalid response"),
            RuntimeError("Runtime issue"),
        ]

        for exc in exceptions:
            result = FastHeartbeatStatusUtil.from_exception(exc)
            assert result == FastHeartbeatStatus.NETWORK_ERROR

    def test_get_action_description_no_changes(self):
        """Test action description for NO_CHANGES."""
        result = FastHeartbeatStatusUtil.get_action_description(
            FastHeartbeatStatus.NO_CHANGES
        )
        assert result == "Continue with HEAD requests (no changes)"

    def test_get_action_description_topology_changed(self):
        """Test action description for TOPOLOGY_CHANGED."""
        result = FastHeartbeatStatusUtil.get_action_description(
            FastHeartbeatStatus.TOPOLOGY_CHANGED
        )
        assert result == "Send full POST heartbeat (topology changed)"

    def test_get_action_description_agent_unknown(self):
        """Test action description for AGENT_UNKNOWN."""
        result = FastHeartbeatStatusUtil.get_action_description(
            FastHeartbeatStatus.AGENT_UNKNOWN
        )
        assert result == "Send full POST heartbeat (agent re-registration)"

    def test_get_action_description_registry_error(self):
        """Test action description for REGISTRY_ERROR."""
        result = FastHeartbeatStatusUtil.get_action_description(
            FastHeartbeatStatus.REGISTRY_ERROR
        )
        assert result == "Skip for resilience (registry error)"

    def test_get_action_description_network_error(self):
        """Test action description for NETWORK_ERROR."""
        result = FastHeartbeatStatusUtil.get_action_description(
            FastHeartbeatStatus.NETWORK_ERROR
        )
        assert result == "Skip for resilience (network error)"


class TestFastHeartbeatStatusLogic:
    """Test comprehensive logic combinations for resilient decision making."""

    def test_resilience_logic_comprehensive(self):
        """Test that resilience logic is mutually exclusive and comprehensive."""
        all_statuses = [
            FastHeartbeatStatus.NO_CHANGES,
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
            FastHeartbeatStatus.AGENT_UNKNOWN,
            FastHeartbeatStatus.REGISTRY_ERROR,
            FastHeartbeatStatus.NETWORK_ERROR,
        ]

        for status in all_statuses:
            requires_full = FastHeartbeatStatusUtil.requires_full_heartbeat(status)
            skip_resilience = FastHeartbeatStatusUtil.should_skip_for_resilience(status)
            skip_optimization = FastHeartbeatStatusUtil.should_skip_for_optimization(
                status
            )

            # Each status should have exactly one action
            action_count = sum([requires_full, skip_resilience, skip_optimization])
            assert action_count == 1, f"Status {status} should have exactly one action"

    def test_http_code_to_action_mapping(self):
        """Test complete HTTP code to action mapping."""
        test_cases = [
            (200, "skip_optimization"),
            (202, "requires_full"),
            (410, "requires_full"),
            (503, "skip_resilience"),
        ]

        for http_code, expected_action in test_cases:
            status = FastHeartbeatStatusUtil.from_http_code(http_code)

            if expected_action == "skip_optimization":
                assert FastHeartbeatStatusUtil.should_skip_for_optimization(status)
                assert not FastHeartbeatStatusUtil.requires_full_heartbeat(status)
                assert not FastHeartbeatStatusUtil.should_skip_for_resilience(status)
            elif expected_action == "requires_full":
                assert FastHeartbeatStatusUtil.requires_full_heartbeat(status)
                assert not FastHeartbeatStatusUtil.should_skip_for_optimization(status)
                assert not FastHeartbeatStatusUtil.should_skip_for_resilience(status)
            elif expected_action == "skip_resilience":
                assert FastHeartbeatStatusUtil.should_skip_for_resilience(status)
                assert not FastHeartbeatStatusUtil.requires_full_heartbeat(status)
                assert not FastHeartbeatStatusUtil.should_skip_for_optimization(status)
