"""
Unit tests for dynamic dependency update functionality.

Tests the ability of MeshAgentDecorator to detect and apply
dependency changes during runtime without restarts.
"""

import asyncio
import os
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp_mesh.runtime.shared.types import AgentInfo


@pytest.fixture
def mock_registry_client():
    """Create a mock registry client."""
    client = AsyncMock()
    client.send_heartbeat = AsyncMock()
    return client


@pytest.fixture
def mock_service_discovery():
    """Create a mock service discovery service."""
    service = AsyncMock()
    service.get_agents_for_capability = AsyncMock()
    service.register_agent_capabilities = AsyncMock(return_value=True)
    return service


@pytest.fixture
def mock_fallback_chain():
    """Create a mock fallback chain."""
    chain = AsyncMock()
    chain.resolve_dependency = AsyncMock()
    return chain


@pytest.fixture
def mock_unified_resolver():
    """Create a mock unified resolver."""
    resolver = AsyncMock()
    resolver.resolve_multiple = AsyncMock()
    return resolver


class TestDynamicDependencyUpdates:
    """Test dynamic dependency update functionality."""

    async def test_dependency_change_detection(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that dependency changes are detected during heartbeat."""
        # Create decorator with dependencies
        decorator = mesh_agent(
            capability="test_capability",
            dependencies=["cache_service", "database_service"],
            health_interval=1,  # Short interval for testing
            registry_url="http://test-registry",
        )

        # Set up internal state
        # Mock registry injection not needed with new decorator_client
        decorator._service_discovery = mock_service_discovery
        # Initialization not needed with new decorator
        decorator._enable_dynamic_updates = True

        # Simulate existing dependency resolution
        decorator._resolved_dependencies = {
            "cache_service": {
                "agent_id": "agent-old-cache",
                "timestamp": datetime.now(),
            }
        }

        # Mock service discovery to return new agent
        mock_service_discovery.get_agents_for_capability.return_value = [
            AgentInfo(
                agent_id="agent-new-cache",
                capability="cache_service",
                endpoint="http://new-cache",
                status="healthy",
            )
        ]

        # Run dependency check
        await decorator._check_dependency_changes()

        # Verify change was detected
        assert decorator._resolved_dependencies["cache_service"]["needs_update"] is True
        assert (
            decorator._resolved_dependencies["cache_service"]["new_agent_id"]
            == "agent-new-cache"
        )

    async def test_immediate_update_strategy(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test immediate update strategy applies changes right away."""
        with patch.dict(os.environ, {"MCP_MESH_UPDATE_STRATEGY": "immediate"}):
            decorator = mesh_agent(
                capability="test_capability",
                dependencies=["cache_service"],
                health_interval=1,
            )

            # Set up internal state
            # Mock registry injection not needed with new decorator_client
            decorator._service_discovery = mock_service_discovery
            # Initialization not needed with new decorator
            decorator._enable_dynamic_updates = True

            # Set up dependency needing update
            decorator._resolved_dependencies = {
                "cache_service": {
                    "agent_id": "agent-old",
                    "needs_update": True,
                    "new_agent_id": "agent-new",
                    "timestamp": datetime.now(),
                }
            }

            # Add cache entry that should be cleared
            decorator._dependency_cache["cache_service"] = {
                "value": "old_instance",
                "timestamp": datetime.now(),
            }

            # Apply updates
            await decorator._apply_dependency_updates()

            # Verify update was applied
            assert (
                decorator._resolved_dependencies["cache_service"]["agent_id"]
                == "agent-new"
            )
            assert (
                decorator._resolved_dependencies["cache_service"]["needs_update"]
                is False
            )
            assert "cache_service" not in decorator._dependency_cache

    async def test_delayed_update_strategy(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test delayed update strategy schedules updates with grace period."""
        with patch.dict(
            os.environ,
            {
                "MCP_MESH_UPDATE_STRATEGY": "delayed",
                "MCP_MESH_UPDATE_GRACE_PERIOD": "1",  # 1 second for testing
            },
        ):
            decorator = mesh_agent(
                capability="test_capability",
                dependencies=["cache_service"],
                health_interval=1,
            )

            # Set up internal state
            # Mock registry injection not needed with new decorator_client
            decorator._service_discovery = mock_service_discovery
            # Initialization not needed with new decorator
            decorator._enable_dynamic_updates = True
            decorator._task_manager = AsyncMock()
            decorator._task_manager.create_task = MagicMock(
                return_value=asyncio.create_task(asyncio.sleep(0))
            )

            # Schedule update
            await decorator._schedule_dependency_updates()

            # Verify task was created
            decorator._task_manager.create_task.assert_called_once()
            args = decorator._task_manager.create_task.call_args
            assert "DependencyUpdate" in args[1]["name"]

    async def test_manual_update_strategy(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test manual update strategy only logs changes."""
        with patch.dict(os.environ, {"MCP_MESH_UPDATE_STRATEGY": "manual"}):
            decorator = mesh_agent(
                capability="test_capability",
                dependencies=["cache_service"],
                health_interval=1,
            )

            # Set up internal state
            # Mock registry injection not needed with new decorator_client
            decorator._service_discovery = mock_service_discovery
            # Initialization not needed with new decorator
            decorator._enable_dynamic_updates = True

            # Set up dependency needing update
            decorator._resolved_dependencies = {
                "cache_service": {
                    "agent_id": "agent-old",
                    "needs_update": True,
                    "new_agent_id": "agent-new",
                }
            }

            # Schedule update (should not apply changes)
            await decorator._schedule_dependency_updates()

            # Verify no changes were applied
            assert (
                decorator._resolved_dependencies["cache_service"]["needs_update"]
                is True
            )
            assert (
                decorator._resolved_dependencies["cache_service"]["agent_id"]
                == "agent-old"
            )

    async def test_dependency_update_callbacks(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that dependency update callbacks are notified."""
        decorator = mesh_agent(
            capability="test_capability",
            dependencies=["cache_service"],
            health_interval=1,
        )

        # Set up internal state
        # Mock registry injection not needed with new decorator_client
        decorator._service_discovery = mock_service_discovery
        # Initialization not needed with new decorator

        # Add callback
        callback_called = False
        callback_args = None

        async def test_callback(dep_name, new_agent_id):
            nonlocal callback_called, callback_args
            callback_called = True
            callback_args = (dep_name, new_agent_id)

        decorator.add_dependency_update_callback(test_callback)

        # Set up dependency update
        decorator._resolved_dependencies = {
            "cache_service": {
                "agent_id": "agent-old",
                "needs_update": True,
                "new_agent_id": "agent-new",
            }
        }

        # Apply updates
        await decorator._apply_dependency_updates()

        # Verify callback was called
        assert callback_called is True
        assert callback_args == ("cache_service", "agent-new")

    async def test_new_dependency_discovery(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that new dependencies are discovered when they become available."""
        decorator = mesh_agent(
            capability="test_capability",
            dependencies=["cache_service"],
            health_interval=1,
        )

        # Set up internal state
        # Mock registry injection not needed with new decorator_client
        decorator._service_discovery = mock_service_discovery
        # Initialization not needed with new decorator
        decorator._enable_dynamic_updates = True

        # No existing resolution for cache_service
        decorator._resolved_dependencies = {}

        # Mock new service discovery
        mock_service_discovery.get_agents_for_capability.return_value = [
            AgentInfo(
                agent_id="agent-new-cache",
                capability="cache_service",
                endpoint="http://new-cache",
                status="healthy",
            )
        ]

        # Run dependency check
        await decorator._check_dependency_changes()

        # Verify new dependency was discovered
        assert "cache_service" in decorator._resolved_dependencies
        assert decorator._resolved_dependencies["cache_service"]["needs_update"] is True
        assert (
            decorator._resolved_dependencies["cache_service"]["new_agent_id"]
            == "agent-new-cache"
        )

    async def test_dependency_removal_on_failure(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that failed dependencies are removed from injection."""
        decorator = mesh_agent(
            capability="test_capability",
            dependencies=["cache_service"],
            health_interval=1,
        )

        # Set up internal state
        # Mock registry injection not needed with new decorator_client
        decorator._service_discovery = mock_service_discovery
        # Initialization not needed with new decorator
        decorator._enable_dynamic_updates = True

        # Existing dependency
        decorator._resolved_dependencies = {
            "cache_service": {"agent_id": "agent-cache", "timestamp": datetime.now()}
        }

        # Mock service discovery returns no agents (service failed)
        mock_service_discovery.get_agents_for_capability.return_value = []

        # Run dependency check
        await decorator._check_dependency_changes()

        # Verify dependency marked for removal
        assert decorator._resolved_dependencies["cache_service"]["needs_update"] is True
        assert decorator._resolved_dependencies["cache_service"]["new_agent_id"] is None

    async def test_heartbeat_triggers_dependency_check(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that heartbeat triggers dependency change detection."""
        decorator = mesh_agent(
            capability="test_capability",
            dependencies=["cache_service"],
            health_interval=1,
        )

        # Set up internal state
        # Mock registry injection not needed with new decorator_client
        decorator._service_discovery = mock_service_discovery
        # Initialization not needed with new decorator
        decorator._enable_dynamic_updates = True

        # Mock check method
        decorator._check_dependency_changes = AsyncMock()

        # Send heartbeat
        await decorator._send_heartbeat()

        # Verify dependency check was called
        decorator._check_dependency_changes.assert_called_once()

    async def test_disabled_dynamic_updates(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that dynamic updates can be disabled."""
        with patch.dict(os.environ, {"MCP_MESH_DYNAMIC_UPDATES": "false"}):
            decorator = mesh_agent(
                capability="test_capability",
                dependencies=["cache_service"],
                health_interval=1,
            )

            # Verify dynamic updates are disabled
            assert decorator._enable_dynamic_updates is False

            # Set up internal state
            # Mock registry injection not needed with new decorator_client
            decorator._service_discovery = mock_service_discovery
            # Initialization not needed with new decorator

            # Mock check method
            decorator._check_dependency_changes = AsyncMock()

            # Send heartbeat
            await decorator._send_heartbeat()

            # Verify dependency check was NOT called
            decorator._check_dependency_changes.assert_not_called()

    async def test_concurrent_update_handling(
        self, mock_registry_client, mock_service_discovery
    ):
        """Test that concurrent updates are handled properly."""
        decorator = mesh_agent(
            capability="test_capability",
            dependencies=["service_a", "service_b"],
            health_interval=1,
        )

        # Set up internal state
        # Mock registry injection not needed with new decorator_client
        decorator._service_discovery = mock_service_discovery
        # Initialization not needed with new decorator
        decorator._enable_dynamic_updates = True

        # Multiple dependencies needing updates
        decorator._resolved_dependencies = {
            "service_a": {
                "agent_id": "old-a",
                "needs_update": True,
                "new_agent_id": "new-a",
            },
            "service_b": {
                "agent_id": "old-b",
                "needs_update": True,
                "new_agent_id": "new-b",
            },
        }

        # Apply updates
        await decorator._apply_dependency_updates()

        # Verify both were updated
        assert decorator._resolved_dependencies["service_a"]["agent_id"] == "new-a"
        assert decorator._resolved_dependencies["service_b"]["agent_id"] == "new-b"
        assert decorator._resolved_dependencies["service_a"]["needs_update"] is False
        assert decorator._resolved_dependencies["service_b"]["needs_update"] is False
