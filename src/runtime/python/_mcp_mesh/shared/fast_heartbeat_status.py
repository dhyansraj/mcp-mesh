"""
Fast Heartbeat Status Utility for MCP Mesh.

Provides semantic labels for fast heartbeat HTTP status codes and resilient
decision-making logic for pipeline optimization and error handling.
"""

from enum import Enum
from typing import Union


class FastHeartbeatStatus(Enum):
    """
    Semantic labels for fast heartbeat responses.

    Maps HTTP status codes to meaningful labels that indicate
    the required action for the heartbeat pipeline.
    """

    NO_CHANGES = "no_changes"  # 200 OK - continue with HEAD requests
    TOPOLOGY_CHANGED = "topology_changed"  # 202 Accepted - send full POST
    AGENT_UNKNOWN = "agent_unknown"  # 410 Gone - re-register with POST
    REGISTRY_ERROR = "registry_error"  # 503 Service Unavailable - SKIP for resilience
    NETWORK_ERROR = "network_error"  # Exception handling - SKIP for resilience


class FastHeartbeatStatusUtil:
    """
    Utility class for fast heartbeat status conversion and decision logic.

    Provides methods to convert HTTP codes to semantic labels and determine
    appropriate pipeline actions with resilient error handling.
    """

    @staticmethod
    def from_http_code(status_code: int) -> FastHeartbeatStatus:
        """
        Convert HTTP status code to semantic FastHeartbeatStatus.

        Args:
            status_code: HTTP status code from fast heartbeat response

        Returns:
            Corresponding FastHeartbeatStatus enum value

        Raises:
            ValueError: For unknown/unsupported status codes
        """
        status_map = {
            200: FastHeartbeatStatus.NO_CHANGES,
            202: FastHeartbeatStatus.TOPOLOGY_CHANGED,
            410: FastHeartbeatStatus.AGENT_UNKNOWN,
            503: FastHeartbeatStatus.REGISTRY_ERROR,
        }

        if status_code not in status_map:
            raise ValueError(f"Unsupported fast heartbeat status code: {status_code}")

        return status_map[status_code]

    @staticmethod
    def requires_full_heartbeat(status: FastHeartbeatStatus) -> bool:
        """
        Determine if status requires full POST heartbeat execution.

        Only TOPOLOGY_CHANGED and AGENT_UNKNOWN require full heartbeat.
        Other statuses should skip for optimization or resilience.

        Args:
            status: FastHeartbeatStatus to evaluate

        Returns:
            True if full heartbeat should be executed, False otherwise
        """
        return status in {
            FastHeartbeatStatus.TOPOLOGY_CHANGED,
            FastHeartbeatStatus.AGENT_UNKNOWN,
        }

    @staticmethod
    def should_skip_for_resilience(status: FastHeartbeatStatus) -> bool:
        """
        Determine if pipeline should skip for resilience (preserve existing state).

        Registry and network errors should skip to preserve existing dependencies
        rather than attempting doomed full requests.

        Args:
            status: FastHeartbeatStatus to evaluate

        Returns:
            True if pipeline should skip for resilience, False otherwise
        """
        return status in {
            FastHeartbeatStatus.REGISTRY_ERROR,
            FastHeartbeatStatus.NETWORK_ERROR,
        }

    @staticmethod
    def should_skip_for_optimization(status: FastHeartbeatStatus) -> bool:
        """
        Determine if pipeline should skip for optimization (no changes detected).

        NO_CHANGES status means topology is unchanged, so full heartbeat
        can be skipped for performance optimization.

        Args:
            status: FastHeartbeatStatus to evaluate

        Returns:
            True if pipeline should skip for optimization, False otherwise
        """
        return status == FastHeartbeatStatus.NO_CHANGES

    @staticmethod
    def from_exception(exception: Exception) -> FastHeartbeatStatus:
        """
        Convert exception to appropriate FastHeartbeatStatus.

        All exceptions during fast heartbeat are treated as network errors
        for resilient handling (preserve existing state).

        Args:
            exception: Exception that occurred during fast heartbeat

        Returns:
            FastHeartbeatStatus.NETWORK_ERROR for resilient handling
        """
        # All exceptions treated as network errors for resilience
        return FastHeartbeatStatus.NETWORK_ERROR

    @staticmethod
    def get_action_description(status: FastHeartbeatStatus) -> str:
        """
        Get human-readable description of action for given status.

        Args:
            status: FastHeartbeatStatus to describe

        Returns:
            Human-readable description of the action
        """
        descriptions = {
            FastHeartbeatStatus.NO_CHANGES: "Continue with HEAD requests (no changes)",
            FastHeartbeatStatus.TOPOLOGY_CHANGED: "Send full POST heartbeat (topology changed)",
            FastHeartbeatStatus.AGENT_UNKNOWN: "Send full POST heartbeat (agent re-registration)",
            FastHeartbeatStatus.REGISTRY_ERROR: "Skip for resilience (registry error)",
            FastHeartbeatStatus.NETWORK_ERROR: "Skip for resilience (network error)",
        }
        return descriptions.get(status, f"Unknown status: {status}")
