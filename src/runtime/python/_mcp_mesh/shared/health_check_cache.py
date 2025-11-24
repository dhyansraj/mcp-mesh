"""
Health check caching with TTL support.

Provides a TTL-based cache for health check results to avoid expensive
health check operations on every heartbeat and /health endpoint call.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Optional

from .support_types import HealthStatus, HealthStatusType

logger = logging.getLogger(__name__)

# Global cache instance for health status
# Stores tuples of (health_status, expiry_timestamp) for per-key TTL support
# Format: {"health:agent_id": (HealthStatus, expiry_timestamp)}
_health_cache: dict[str, tuple[HealthStatus, float]] = {}
_max_cache_size = 100


async def get_health_status_with_cache(
    agent_id: str,
    health_check_fn: Optional[Callable[[], Awaitable[Any]]],
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
    ttl: int = 15,
) -> HealthStatus:
    """
    Get health status with TTL caching.

    This function synchronously returns from cache if available, otherwise
    calls the user's health check function and caches the result.

    User health check can return:
    - bool: True = HEALTHY, False = UNHEALTHY
    - dict: {"status": "healthy/degraded/unhealthy", "checks": {...}, "errors": [...]}
    - HealthStatus: Full object (fields will be overridden with correct values)

    Args:
        agent_id: Unique identifier for the agent
        health_check_fn: Optional async function that returns bool, dict, or HealthStatus
        agent_config: Agent configuration dict for building default health status
        startup_context: Full startup context with capabilities
        ttl: Cache TTL in seconds (default: 15)

    Returns:
        HealthStatus: Current health status (from cache or fresh check)

    Note:
        - Cache key is based on agent_id
        - If health_check_fn is None, returns default HEALTHY status
        - If health_check_fn raises an exception, returns DEGRADED status
        - TTL is enforced per-key with manual expiry tracking
    """
    cache_key = f"health:{agent_id}"
    current_time = time.time()

    # Try to get from cache and check if expired
    if cache_key in _health_cache:
        cached_status, expiry_time = _health_cache[cache_key]
        if current_time < expiry_time:
            logger.debug(f"✅ Health check cache HIT for agent '{agent_id}'")
            return cached_status
        else:
            # Cache entry expired, remove it
            logger.debug(
                f"⏰ Health check cache EXPIRED for agent '{agent_id}' (TTL exceeded)"
            )
            del _health_cache[cache_key]

    logger.debug(f"❌ Health check cache MISS for agent '{agent_id}'")

    # Cache miss - call user's health check if provided
    if health_check_fn:
        try:
            logger.debug(
                f"🔍 Executing health check function for agent '{agent_id}'..."
            )
            user_result = await health_check_fn()

            # Parse user result into status, checks, and errors
            status_type = HealthStatusType.HEALTHY
            checks = {}
            errors = []

            if isinstance(user_result, bool):
                # Simple boolean: True = HEALTHY, False = UNHEALTHY
                status_type = (
                    HealthStatusType.HEALTHY
                    if user_result
                    else HealthStatusType.UNHEALTHY
                )
                checks["health_check"] = user_result
                if not user_result:
                    errors.append("Health check returned False")

            elif isinstance(user_result, dict):
                # Dictionary with status, checks, errors
                status_str = user_result.get("status", "healthy").lower()
                if status_str == "healthy":
                    status_type = HealthStatusType.HEALTHY
                elif status_str == "degraded":
                    status_type = HealthStatusType.DEGRADED
                elif status_str == "unhealthy":
                    status_type = HealthStatusType.UNHEALTHY
                else:
                    status_type = HealthStatusType.UNKNOWN

                checks = user_result.get("checks", {})
                errors = user_result.get("errors", [])

            elif isinstance(user_result, HealthStatus):
                # Full HealthStatus object - extract status, checks, errors
                status_type = user_result.status
                checks = user_result.checks
                errors = user_result.errors

            else:
                logger.warning(
                    f"⚠️ Health check for '{agent_id}' returned unexpected type {type(user_result)}, treating as unhealthy"
                )
                status_type = HealthStatusType.UNHEALTHY
                checks = {"health_check_return_type": False}
                errors = [f"Invalid return type: {type(user_result)}"]

            # Build complete HealthStatus with resolved values
            # Get capabilities from startup_context (from registered tools)
            capabilities = startup_context.get("capabilities", [])
            if not capabilities:
                # Fallback: try to get from agent_config
                capabilities = agent_config.get("capabilities", [])
            if not capabilities:
                # Last resort: use a default to satisfy validation
                capabilities = ["default"]

            health_status = HealthStatus(
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

            logger.info(
                f"💚 Health check function executed successfully for '{agent_id}': {health_status.status.value}"
            )

        except Exception as e:
            # Health check function failed - return DEGRADED
            logger.warning(
                f"⚠️ Health check function failed for agent '{agent_id}': {e}"
            )

            # Get capabilities from startup_context
            capabilities = startup_context.get("capabilities", [])
            if not capabilities:
                capabilities = agent_config.get("capabilities", ["default"])

            health_status = HealthStatus(
                agent_name=agent_id,
                status=HealthStatusType.DEGRADED,
                capabilities=capabilities,
                checks={"health_check_execution": False},
                errors=[f"Health check failed: {str(e)}"],
                timestamp=datetime.now(UTC),
                version=agent_config.get("version", "1.0.0"),
                metadata=agent_config,
                uptime_seconds=0,
            )
    else:
        # No health check provided - default to HEALTHY
        logger.debug(
            f"ℹ️ No health check function provided for '{agent_id}', using default HEALTHY status"
        )

        # Get capabilities from startup_context
        capabilities = startup_context.get("capabilities", [])
        if not capabilities:
            capabilities = agent_config.get("capabilities", ["default"])

        health_status = HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=capabilities,
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=agent_config,
            uptime_seconds=0,
        )

    # Store in cache with TTL (manual expiry tracking)
    expiry_time = current_time + ttl
    _health_cache[cache_key] = (health_status, expiry_time)
    logger.debug(f"💾 Cached health status for '{agent_id}' with TTL={ttl}s")

    # Enforce max cache size by removing oldest entry if needed
    if len(_health_cache) > _max_cache_size:
        # Remove the entry with earliest expiry time
        oldest_key = min(_health_cache.keys(), key=lambda k: _health_cache[k][1])
        del _health_cache[oldest_key]
        logger.debug("🗑️ Evicted oldest cache entry to maintain max size")

    return health_status


def clear_health_cache(agent_id: Optional[str] = None) -> None:
    """
    Clear health cache for a specific agent or all agents.

    Args:
        agent_id: Optional agent ID to clear. If None, clears entire cache.

    Note:
        This is useful for testing or forcing a fresh health check.
    """
    if agent_id:
        cache_key = f"health:{agent_id}"
        if cache_key in _health_cache:
            del _health_cache[cache_key]
            logger.debug(f"🗑️ Cleared health cache for agent '{agent_id}'")
    else:
        _health_cache.clear()
        logger.debug("🗑️ Cleared entire health cache")


def get_cache_stats() -> dict[str, Any]:
    """
    Get cache statistics for monitoring and debugging.

    Returns:
        dict: Cache statistics including size, maxsize, and current keys
    """
    return {
        "size": len(_health_cache),
        "maxsize": _max_cache_size,
        "ttl": 15,  # Default TTL (for backward compatibility)
        "cached_agents": [key.replace("health:", "") for key in _health_cache.keys()],
    }
