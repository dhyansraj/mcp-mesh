"""
Health check manager with TTL caching and K8s response helpers.

Consolidates health check storage, caching, and Kubernetes endpoint response
generation into a single module.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .support_types import HealthStatus, HealthStatusType

logger = logging.getLogger(__name__)

# =============================================================================
# Health Result Storage (moved from DecoratorRegistry)
# =============================================================================

# Simple storage for the latest health check result dict
# Format: {"status": "healthy/degraded/unhealthy", "agent": "...", ...}
_health_check_result: dict | None = None


def store_health_check_result(result: dict) -> None:
    """Store health check result for K8s endpoints."""
    global _health_check_result
    _health_check_result = result
    logger.debug(f"Stored health check result: {result.get('status', 'unknown')}")


def get_health_check_result() -> dict | None:
    """Get stored health check result."""
    return _health_check_result


def clear_health_check_result() -> None:
    """Clear stored health check result."""
    global _health_check_result
    _health_check_result = None
    logger.debug("Cleared health check result")


# =============================================================================
# TTL-Based Health Cache
# =============================================================================

# Global cache for HealthStatus objects with per-key TTL
# Format: {"health:agent_id": (HealthStatus, expiry_timestamp)}
_health_cache: dict[str, tuple[HealthStatus, float]] = {}
_max_cache_size = 100


async def get_health_status_with_cache(
    agent_id: str,
    health_check_fn: Callable[[], Awaitable[Any]] | None,
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
    ttl: int = 15,
) -> HealthStatus:
    """
    Get health status with TTL caching.

    User health check can return:
    - bool: True = HEALTHY, False = UNHEALTHY
    - dict: {"status": "healthy/degraded/unhealthy", "checks": {...}, "errors": [...]}
    - HealthStatus: Full object

    Args:
        agent_id: Unique identifier for the agent
        health_check_fn: Optional async function for health check
        agent_config: Agent configuration dict
        startup_context: Full startup context with capabilities
        ttl: Cache TTL in seconds (default: 15)

    Returns:
        HealthStatus from cache or fresh check
    """
    cache_key = f"health:{agent_id}"
    current_time = time.time()

    # Check cache
    if cache_key in _health_cache:
        cached_status, expiry_time = _health_cache[cache_key]
        if current_time < expiry_time:
            logger.debug(f"Health check cache HIT for agent '{agent_id}'")
            return cached_status
        else:
            logger.debug(f"Health check cache EXPIRED for agent '{agent_id}'")
            del _health_cache[cache_key]

    logger.debug(f"Health check cache MISS for agent '{agent_id}'")

    # Execute health check
    health_status = await _execute_health_check(
        agent_id, health_check_fn, agent_config, startup_context
    )

    # Store in cache
    expiry_time = current_time + ttl
    _health_cache[cache_key] = (health_status, expiry_time)
    logger.debug(f"Cached health status for '{agent_id}' with TTL={ttl}s")

    # Enforce max cache size
    if len(_health_cache) > _max_cache_size:
        oldest_key = min(_health_cache.keys(), key=lambda k: _health_cache[k][1])
        del _health_cache[oldest_key]
        logger.debug("Evicted oldest cache entry to maintain max size")

    return health_status


async def _execute_health_check(
    agent_id: str,
    health_check_fn: Callable[[], Awaitable[Any]] | None,
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
) -> HealthStatus:
    """Execute health check function and build HealthStatus."""
    capabilities = _get_capabilities(startup_context, agent_config)

    if health_check_fn:
        try:
            logger.debug(f"Executing health check for agent '{agent_id}'")
            user_result = await health_check_fn()
            status_type, checks, errors = _parse_health_result(user_result)

            logger.info(f"Health check for '{agent_id}': {status_type.value}")

        except Exception as e:
            logger.warning(f"Health check failed for agent '{agent_id}': {e}")
            status_type = HealthStatusType.DEGRADED
            checks = {"health_check_execution": False}
            errors = [f"Health check failed: {str(e)}"]
    else:
        # No health check provided - default to HEALTHY
        logger.debug(f"No health check for '{agent_id}', using default HEALTHY")
        status_type = HealthStatusType.HEALTHY
        checks = {}
        errors = []

    return HealthStatus(
        agent_name=agent_id,
        status=status_type,
        capabilities=capabilities,
        checks=checks,
        errors=errors,
        timestamp=datetime.now(UTC),
        version=agent_config.get("version", "1.0.0"),
        metadata=agent_config,
        uptime_seconds=0,
    )


def _get_capabilities(
    startup_context: dict[str, Any],
    agent_config: dict[str, Any],
) -> list[str]:
    """Get capabilities from context with fallbacks."""
    capabilities = startup_context.get("capabilities", [])
    if not capabilities:
        capabilities = agent_config.get("capabilities", [])
    if not capabilities:
        capabilities = ["default"]
    return capabilities


def _parse_health_result(
    user_result: Any,
) -> tuple[HealthStatusType, dict, list]:
    """Parse user health check result into status, checks, errors."""
    if isinstance(user_result, bool):
        status_type = (
            HealthStatusType.HEALTHY if user_result else HealthStatusType.UNHEALTHY
        )
        checks = {"health_check": user_result}
        errors = [] if user_result else ["Health check returned False"]

    elif isinstance(user_result, dict):
        status_str = user_result.get("status", "healthy").lower()
        status_map = {
            "healthy": HealthStatusType.HEALTHY,
            "degraded": HealthStatusType.DEGRADED,
            "unhealthy": HealthStatusType.UNHEALTHY,
        }
        status_type = status_map.get(status_str, HealthStatusType.UNKNOWN)
        checks = user_result.get("checks", {})
        errors = user_result.get("errors", [])

    elif isinstance(user_result, HealthStatus):
        status_type = user_result.status
        checks = user_result.checks
        errors = user_result.errors

    else:
        logger.warning(f"Unexpected health check result type: {type(user_result)}")
        status_type = HealthStatusType.UNHEALTHY
        checks = {"health_check_return_type": False}
        errors = [f"Invalid return type: {type(user_result)}"]

    return status_type, checks, errors


def clear_health_cache(agent_id: str | None = None) -> None:
    """Clear health cache for a specific agent or all agents."""
    if agent_id:
        cache_key = f"health:{agent_id}"
        if cache_key in _health_cache:
            del _health_cache[cache_key]
            logger.debug(f"Cleared health cache for agent '{agent_id}'")
    else:
        _health_cache.clear()
        logger.debug("Cleared entire health cache")


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    return {
        "size": len(_health_cache),
        "maxsize": _max_cache_size,
        "ttl": 15,
        "cached_agents": [key.replace("health:", "") for key in _health_cache.keys()],
    }


# =============================================================================
# K8s Response Helpers
# =============================================================================


def build_health_response(
    agent_name: str,
    health_status: HealthStatus | None = None,
) -> tuple[dict, int]:
    """
    Build /health endpoint response with appropriate HTTP status code.

    Returns:
        Tuple of (response_dict, http_status_code)
    """
    if health_status:
        status = health_status.status.value
        response = {
            "status": status,
            "agent": agent_name,
            "checks": health_status.checks,
            "errors": health_status.errors,
            "timestamp": health_status.timestamp.isoformat(),
        }
    else:
        # Use stored result if available
        stored = get_health_check_result()
        if stored:
            status = stored.get("status", "starting")
            response = stored
        else:
            status = "starting"
            response = {"status": "starting", "message": "Agent is starting"}

    # K8s expects 200 for healthy, 503 for everything else
    http_status = 200 if status == "healthy" else 503
    return response, http_status


def build_ready_response(
    agent_name: str,
    mcp_wrappers_count: int = 0,
) -> tuple[dict, int]:
    """
    Build /ready endpoint response with appropriate HTTP status code.

    Returns:
        Tuple of (response_dict, http_status_code)
    """
    stored = get_health_check_result()

    if stored:
        status = stored.get("status", "starting")
        if status == "healthy":
            return {
                "ready": True,
                "agent": agent_name,
                "status": status,
                "mcp_wrappers": mcp_wrappers_count,
                "timestamp": datetime.now(UTC).isoformat(),
            }, 200
        else:
            return {
                "ready": False,
                "agent": agent_name,
                "status": status,
                "reason": f"Service is {status}",
                "errors": stored.get("errors", []),
            }, 503
    else:
        # No health check configured - assume ready
        return {
            "ready": True,
            "agent": agent_name,
            "mcp_wrappers": mcp_wrappers_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }, 200


def build_livez_response(agent_name: str) -> dict:
    """Build /livez endpoint response (always returns 200)."""
    return {
        "alive": True,
        "agent": agent_name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
