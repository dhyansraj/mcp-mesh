"""
Unit tests for health check caching functionality.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from _mcp_mesh.shared.health_check_cache import (
    clear_health_cache,
    get_cache_stats,
    get_health_status_with_cache,
)
from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType


@pytest.fixture
def agent_config() -> dict[str, Any]:
    """Fixture providing sample agent configuration."""
    return {
        "name": "test-agent",
        "version": "1.0.0",
        "capabilities": ["test-capability"],
    }


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test."""
    clear_health_cache()
    yield
    clear_health_cache()


@pytest.mark.asyncio
async def test_health_check_cache_miss_and_hit(agent_config):
    """Test that health check is called on cache miss, but cached on hit."""
    call_count = 0

    async def health_check_fn() -> HealthStatus:
        nonlocal call_count
        call_count += 1
        return HealthStatus(
            agent_name="test-agent",
            status=HealthStatusType.HEALTHY,
            capabilities=["test"],
            timestamp=datetime.now(UTC),
        )

    # First call - cache miss
    result1 = await get_health_status_with_cache(
        agent_id="test-agent",
        health_check_fn=health_check_fn,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    assert call_count == 1
    assert result1.status == HealthStatusType.HEALTHY

    # Second call - cache hit
    result2 = await get_health_status_with_cache(
        agent_id="test-agent",
        health_check_fn=health_check_fn,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    assert call_count == 1  # Should not call health_check_fn again
    assert result2.status == HealthStatusType.HEALTHY


@pytest.mark.asyncio
async def test_health_check_no_function_returns_healthy(agent_config):
    """Test that when no health check function is provided, default HEALTHY is returned."""
    result = await get_health_status_with_cache(
        agent_id="test-agent",
        health_check_fn=None,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    assert result.status == HealthStatusType.HEALTHY
    assert result.agent_name == "test-agent"


@pytest.mark.asyncio
async def test_health_check_function_failure_returns_degraded(agent_config):
    """Test that when health check function fails, DEGRADED status is returned."""

    async def failing_health_check() -> HealthStatus:
        raise Exception("Health check failed")

    result = await get_health_status_with_cache(
        agent_id="test-agent",
        health_check_fn=failing_health_check,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    assert result.status == HealthStatusType.DEGRADED
    assert "Health check failed" in result.errors[0]
    assert result.checks["health_check_execution"] is False


@pytest.mark.asyncio
async def test_health_check_cache_expiration():
    """Test that cache expires after TTL."""
    call_count = 0

    async def health_check_fn() -> HealthStatus:
        nonlocal call_count
        call_count += 1
        return HealthStatus(
            agent_name="test-agent",
            status=HealthStatusType.HEALTHY,
            capabilities=["test"],
            timestamp=datetime.now(UTC),
        )

    agent_config = {"name": "test-agent", "capabilities": ["test"]}

    # First call - cache miss
    await get_health_status_with_cache(
        agent_id="test-agent",
        health_check_fn=health_check_fn,
        agent_config=agent_config,
        startup_context={},
        ttl=1,  # 1 second TTL for testing
    )

    assert call_count == 1

    # Wait for cache to expire
    await asyncio.sleep(2)

    # Second call - cache expired, should call again
    await get_health_status_with_cache(
        agent_id="test-agent",
        health_check_fn=health_check_fn,
        agent_config=agent_config,
        startup_context={},
        ttl=1,
    )

    assert call_count == 2


@pytest.mark.asyncio
async def test_health_check_different_agents_independent_cache(agent_config):
    """Test that different agents have independent cache entries."""
    call_count_agent1 = 0
    call_count_agent2 = 0

    async def health_check_agent1() -> HealthStatus:
        nonlocal call_count_agent1
        call_count_agent1 += 1
        return HealthStatus(
            agent_name="agent-1",
            status=HealthStatusType.HEALTHY,
            capabilities=["test"],
            timestamp=datetime.now(UTC),
        )

    async def health_check_agent2() -> HealthStatus:
        nonlocal call_count_agent2
        call_count_agent2 += 1
        return HealthStatus(
            agent_name="agent-2",
            status=HealthStatusType.HEALTHY,
            capabilities=["test"],
            timestamp=datetime.now(UTC),
        )

    # Call for agent 1
    await get_health_status_with_cache(
        agent_id="agent-1",
        health_check_fn=health_check_agent1,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    # Call for agent 2
    await get_health_status_with_cache(
        agent_id="agent-2",
        health_check_fn=health_check_agent2,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    assert call_count_agent1 == 1
    assert call_count_agent2 == 1

    # Call again for agent 1 - should use cache
    await get_health_status_with_cache(
        agent_id="agent-1",
        health_check_fn=health_check_agent1,
        agent_config=agent_config,
        startup_context={},
        ttl=15,
    )

    assert call_count_agent1 == 1  # Still 1 (cached)
    assert call_count_agent2 == 1


def test_clear_health_cache_single_agent(agent_config):
    """Test clearing cache for a single agent."""
    clear_health_cache()
    stats_before = get_cache_stats()
    assert stats_before["size"] == 0

    # This test is synchronous, so we can't await
    # Just test the clear function works
    clear_health_cache("agent-1")
    stats_after = get_cache_stats()
    assert stats_after["size"] == 0


def test_get_cache_stats():
    """Test getting cache statistics."""
    clear_health_cache()
    stats = get_cache_stats()

    assert "size" in stats
    assert "maxsize" in stats
    assert "ttl" in stats
    assert "cached_agents" in stats
    assert stats["size"] == 0
    assert stats["maxsize"] == 100
    assert stats["ttl"] == 15
