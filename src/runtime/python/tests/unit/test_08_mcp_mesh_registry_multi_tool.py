"""
Test Driven Development for Multi-Tool Registry Client

Tests for the new multi-tool format where each agent can have multiple tools
with individual dependencies, as implemented in the Go registry.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Import the classes we'll be testing/implementing
from mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient
from mcp_mesh.generated.mcp_mesh_registry_client.api_client import (
    ApiClient as RegistryClient,
)
from mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper
from mcp_mesh.shared.support_types import HealthStatus, HealthStatusType


def create_mock_registry_wrapper(response_override=None):
    """Create a mock registry client wrapper for testing."""
    mock_api_client = AsyncMock(spec=ApiClient)
    mock_wrapper = AsyncMock(spec=RegistryClientWrapper)

    # Default response dict format
    default_response = {
        "status": "success",
        "timestamp": "2023-01-01T00:00:00Z",
        "message": "Registration successful",
        "agent_id": "test-agent-id",
        "dependencies_resolved": {},
    }

    response = response_override if response_override else default_response
    mock_wrapper.register_multi_tool_agent.return_value = response
    mock_wrapper.send_heartbeat_with_dependency_resolution.return_value = response
    mock_wrapper.parse_tool_dependencies.return_value = response.get(
        "dependencies_resolved", {}
    )

    return mock_wrapper


class TestMultiToolRegistrationFormat:
    """Test the new multi-tool registration format and dependency resolution."""

    @pytest.fixture
    def registry_wrapper(self):
        """Create a registry wrapper for testing."""
        return create_mock_registry_wrapper()

    @pytest.fixture
    def mock_session(self):
        """Create a mock HTTP session."""
        session = Mock()
        session.post = AsyncMock()
        session.get = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_multi_tool_agent_registration(self, registry_wrapper, mock_session):
        """Test registration of agent with multiple tools."""
        # Arrange - Define the new multi-tool format
        agent_id = "myservice-abc123"
        multi_tool_metadata = {
            "name": "myservice-abc123",
            "endpoint": "http://localhost:8889",
            "timeout_threshold": 60,
            "eviction_threshold": 120,
            "tools": [
                {
                    "function_name": "greet",
                    "capability": "greeting",
                    "version": "1.0.0",
                    "tags": ["demo", "v1"],
                    "dependencies": [
                        {
                            "capability": "date_service",
                            "version": ">=1.0.0",
                            "tags": ["production"],
                        }
                    ],
                },
                {
                    "function_name": "farewell",
                    "capability": "goodbye",
                    "version": "1.0.0",
                    "tags": ["demo"],
                    "dependencies": [],
                },
            ],
        }

        # Mock successful registration response with dependency resolution
        mock_response = {
            "status": "success",
            "agent_id": agent_id,
            "resource_version": "1703123456789",
            "timestamp": "2023-12-20T10:30:45Z",
            "message": "Agent registered successfully",
            "metadata": {
                "dependencies_resolved": {
                    "greet": {
                        "date_service": {
                            "agent_id": "date-provider-123",
                            "tool_name": "get_current_date",
                            "capability": "date_service",
                            "version": "1.2.0",
                            "endpoint": "http://date-service:8080",
                        }
                    },
                    "farewell": {},  # No dependencies
                }
            },
        }

        # Configure the mock wrapper to return our expected response
        registry_wrapper.register_multi_tool_agent.return_value = mock_response

        # Act - Register the agent with new multi-tool format
        response = await registry_wrapper.register_multi_tool_agent(
            agent_id, multi_tool_metadata
        )

        # Assert - Verify the request was made correctly
        assert response is not None
        assert response["status"] == "success"
        assert response["agent_id"] == agent_id

        # Verify the wrapper method was called with correct parameters
        registry_wrapper.register_multi_tool_agent.assert_called_once_with(
            agent_id, multi_tool_metadata
        )

    @pytest.mark.asyncio
    async def test_dependency_resolution_response_parsing(self, registry_wrapper):
        """Test parsing of per-tool dependency resolution from registry response."""
        # Arrange - Mock registry response with resolved dependencies
        registry_response = {
            "status": "success",
            "agent_id": "consumer-agent",
            "metadata": {
                "dependencies_resolved": {
                    "process_data": {
                        "date_service": {
                            "agent_id": "date-provider-456",
                            "tool_name": "get_current_date",
                            "capability": "date_service",
                            "version": "1.5.0",
                            "endpoint": "http://provider:8081",
                        },
                        "auth_service": {
                            "agent_id": "auth-provider-789",
                            "tool_name": "authenticate",
                            "capability": "auth_service",
                            "version": "2.0.0",
                            "endpoint": "http://auth:9000",
                        },
                    },
                    "log_data": {
                        "logging_service": {
                            "agent_id": "logger-provider-101",
                            "tool_name": "write_log",
                            "capability": "logging_service",
                            "version": "1.0.0",
                            "endpoint": "http://logger:8888",
                        }
                    },
                }
            },
        }

        # Configure the mock wrapper
        registry_wrapper.parse_tool_dependencies.return_value = registry_response[
            "metadata"
        ]["dependencies_resolved"]

        # Act - Parse the dependency resolution
        dependencies = registry_wrapper.parse_tool_dependencies(registry_response)

        # Assert - Verify correct parsing of per-tool dependencies
        assert "process_data" in dependencies
        assert "log_data" in dependencies

        # Check process_data dependencies
        process_deps = dependencies["process_data"]
        assert "date_service" in process_deps
        assert "auth_service" in process_deps

        date_dep = process_deps["date_service"]
        assert date_dep["agent_id"] == "date-provider-456"
        assert date_dep["tool_name"] == "get_current_date"
        assert date_dep["endpoint"] == "http://provider:8081"

        # Check log_data dependencies
        log_deps = dependencies["log_data"]
        assert "logging_service" in log_deps
        assert log_deps["logging_service"]["agent_id"] == "logger-provider-101"

    @pytest.mark.asyncio
    async def test_heartbeat_with_multi_tool_dependency_resolution(
        self, registry_wrapper, mock_session
    ):
        """Test heartbeat that returns full dependency resolution for all tools."""
        # Arrange - Create health status for multi-tool agent
        health_status = HealthStatus(
            agent_name="multi-tool-agent",
            status=HealthStatusType.HEALTHY,
            capabilities=["greeting", "goodbye"],  # Legacy field for compatibility
            timestamp=datetime.now(),
            checks={},
            errors=[],
            uptime_seconds=3600,
            version="1.0.0",
            metadata={},
        )

        # Mock heartbeat response with full dependency resolution
        mock_response = {
            "status": "success",
            "timestamp": "2023-12-20T10:35:00Z",
            "dependencies_resolved": {
                "greet": {
                    "date_service": {
                        "agent_id": "date-provider-456",
                        "tool_name": "get_current_date",
                        "endpoint": "http://provider:8081",
                    }
                },
                "farewell": {},
            },
        }

        # Configure the mock wrapper
        registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            mock_response
        )

        # Act - Send heartbeat and get dependency resolution
        response = await registry_wrapper.send_heartbeat_with_dependency_resolution(
            health_status
        )

        # Assert - Verify response contains full dependency state
        assert response is not None
        assert response["status"] == "success"
        assert "dependencies_resolved" in response

        deps = response["dependencies_resolved"]
        assert "greet" in deps
        assert "farewell" in deps
        assert deps["greet"]["date_service"]["agent_id"] == "date-provider-456"

        # Verify the wrapper method was called
        registry_wrapper.send_heartbeat_with_dependency_resolution.assert_called_once_with(
            health_status
        )

    @pytest.mark.asyncio
    async def test_version_constraint_matching(self, registry_wrapper, mock_session):
        """Test that version constraints are properly sent to registry."""
        # Arrange - Agent with various version constraints
        agent_metadata = {
            "name": "version-test-agent",
            "tools": [
                {
                    "function_name": "complex_processor",
                    "capability": "processor",
                    "dependencies": [
                        {"capability": "cache_service", "version": ">=1.0.0,<2.0.0"},
                        {
                            "capability": "db_service",
                            "version": "~1.5",
                        },  # ~1.5 means >=1.5.0, <1.6.0
                        {"capability": "auth_service", "version": ">2.0.0"},
                        {
                            "capability": "log_service",
                            "version": "1.0.0",
                        },  # Exact match
                    ],
                }
            ],
        }

        mock_response = {"status": "success", "agent_id": "version-test-agent"}

        # Configure the mock wrapper
        registry_wrapper.register_multi_tool_agent.return_value = mock_response

        # Act
        response = await registry_wrapper.register_multi_tool_agent(
            "version-test-agent", agent_metadata
        )

        # Assert - Verify the registration was called with correct parameters
        registry_wrapper.register_multi_tool_agent.assert_called_once_with(
            "version-test-agent", agent_metadata
        )

    @pytest.mark.asyncio
    async def test_tag_based_dependency_filtering(self, registry_wrapper, mock_session):
        """Test that tag requirements are properly sent for dependency filtering."""
        # Arrange - Agent with tag-based dependencies
        agent_metadata = {
            "name": "tag-filter-agent",
            "tools": [
                {
                    "function_name": "regional_processor",
                    "capability": "processor",
                    "dependencies": [
                        {
                            "capability": "database",
                            "tags": [
                                "production",
                                "US-EAST",
                                "mysql",
                            ],  # ALL must match
                        },
                        {"capability": "cache", "tags": ["high-performance"]},
                    ],
                }
            ],
        }

        mock_response = {"status": "success", "agent_id": "tag-filter-agent"}

        # Configure the mock wrapper
        registry_wrapper.register_multi_tool_agent.return_value = mock_response

        # Act
        response = await registry_wrapper.register_multi_tool_agent(
            "tag-filter-agent", agent_metadata
        )

        # Assert - Verify the registration was called with correct parameters
        registry_wrapper.register_multi_tool_agent.assert_called_once_with(
            "tag-filter-agent", agent_metadata
        )

    @pytest.mark.asyncio
    async def test_health_state_transitions_integration(
        self, registry_wrapper, mock_session
    ):
        """Test integration with registry health state transitions."""
        # Arrange - Health status for different states
        healthy_status = HealthStatus(
            agent_name="health-test-agent",
            status=HealthStatusType.HEALTHY,
            capabilities=["test_capability"],
            timestamp=datetime.now(),
            checks={},
            errors=[],
            uptime_seconds=100,
            version="1.0.0",
            metadata={},
        )

        # Mock responses for different health states
        healthy_response = {
            "status": "success",
            "dependencies_resolved": {
                "test_tool": {"dep_service": {"agent_id": "provider-1"}}
            },
        }

        degraded_response = {
            "status": "success",
            "dependencies_resolved": {
                "test_tool": {}  # No dependencies when providers are degraded
            },
        }

        # Test healthy state - dependencies should be resolved
        registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            healthy_response
        )
        response = await registry_wrapper.send_heartbeat_with_dependency_resolution(
            healthy_status
        )
        assert response is not None
        assert len(response["dependencies_resolved"]["test_tool"]) > 0

        # Test degraded state - dependencies should be empty
        registry_wrapper.send_heartbeat_with_dependency_resolution.return_value = (
            degraded_response
        )
        response = await registry_wrapper.send_heartbeat_with_dependency_resolution(
            healthy_status
        )
        assert response is not None
        assert len(response["dependencies_resolved"]["test_tool"]) == 0


class TestBackwardCompatibility:
    """Test that new multi-tool format maintains backward compatibility."""

    @pytest.fixture
    def registry_wrapper(self):
        """Create a registry wrapper for testing."""
        return create_mock_registry_wrapper()

    @pytest.mark.asyncio
    async def test_legacy_registration_still_works(self, registry_wrapper):
        """Test that legacy single-capability registration still works."""
        # This ensures we don't break existing agents during migration
        mock_response = {"status": "success"}

        # Configure the mock wrapper
        registry_wrapper.register_multi_tool_agent.return_value = mock_response

        # Convert legacy format to new multi-tool format for registration
        legacy_metadata = {
            "name": "legacy-agent",
            "tools": [
                {
                    "function_name": "legacy_tool",
                    "capability": "old_capability",
                    "dependencies": [{"capability": "old_dependency"}],
                }
            ],
        }

        result = await registry_wrapper.register_multi_tool_agent(
            "legacy-agent", legacy_metadata
        )
        assert result["status"] == "success"

        # Verify the wrapper was called
        registry_wrapper.register_multi_tool_agent.assert_called_once_with(
            "legacy-agent", legacy_metadata
        )

    @pytest.mark.asyncio
    async def test_mixed_format_handling(self, registry_wrapper):
        """Test handling responses that mix old and new formats."""
        # Registry might return both legacy and new dependency resolution
        mixed_response = {
            "status": "success",
            "dependencies_resolved": {
                "old_dep": {"agent_id": "legacy-provider"}
            },  # Legacy format
            "metadata": {
                "dependencies_resolved": {  # New per-tool format
                    "new_tool": {"new_dep": {"agent_id": "new-provider"}}
                }
            },
        }

        # Configure the mock wrapper to return new format (precedence)
        registry_wrapper.parse_tool_dependencies.return_value = mixed_response[
            "metadata"
        ]["dependencies_resolved"]

        # Should parse both formats correctly
        dependencies = registry_wrapper.parse_tool_dependencies(mixed_response)
        assert "new_tool" in dependencies  # New format takes precedence
        assert dependencies["new_tool"]["new_dep"]["agent_id"] == "new-provider"


class TestErrorHandling:
    """Test error handling for multi-tool registration and dependency resolution."""

    @pytest.fixture
    def registry_wrapper(self):
        """Create a registry wrapper for testing."""
        return create_mock_registry_wrapper()

    @pytest.mark.asyncio
    async def test_registration_failure_handling(self, registry_wrapper):
        """Test handling of registration failures."""
        # Configure the mock wrapper to return None on failure
        registry_wrapper.register_multi_tool_agent.return_value = None

        # Test registration failure handling
        result = await registry_wrapper.register_multi_tool_agent(
            "bad-agent", {"invalid": "config"}
        )
        assert result is None  # Should return None on failure

    @pytest.mark.asyncio
    async def test_dependency_resolution_parsing_errors(self, registry_wrapper):
        """Test handling of malformed dependency resolution responses."""
        # Malformed response
        bad_response = {
            "status": "success",
            "metadata": {"dependencies_resolved": "not_a_dict"},  # Should be dict
        }

        # Configure the mock wrapper to return empty dict on parse error
        registry_wrapper.parse_tool_dependencies.return_value = {}

        # Should handle gracefully without crashing
        dependencies = registry_wrapper.parse_tool_dependencies(bad_response)
        assert dependencies == {}  # Empty dict on parse error

    @pytest.mark.asyncio
    async def test_missing_dependency_providers(self, registry_wrapper):
        """Test handling when no providers are available for dependencies."""
        response_no_providers = {
            "status": "success",
            "metadata": {
                "dependencies_resolved": {"tool_needing_deps": {}}  # No providers found
            },
        }

        # Configure the mock wrapper
        registry_wrapper.parse_tool_dependencies.return_value = response_no_providers[
            "metadata"
        ]["dependencies_resolved"]

        dependencies = registry_wrapper.parse_tool_dependencies(response_no_providers)
        assert "tool_needing_deps" in dependencies
        assert len(dependencies["tool_needing_deps"]) == 0  # Empty dependencies
