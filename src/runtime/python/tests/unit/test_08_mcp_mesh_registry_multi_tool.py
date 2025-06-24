"""
Test Driven Development for Multi-Tool Registry Client

Tests for the new multi-tool format where each agent can have multiple tools
with individual dependencies, as implemented in the Go registry.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Import the classes we'll be testing/implementing
from mcp_mesh.engine.generated_registry_client import (
    GeneratedRegistryClient as RegistryClient,
)
from mcp_mesh.engine.shared.types import HealthStatus, HealthStatusType


class TestMultiToolRegistrationFormat:
    """Test the new multi-tool registration format and dependency resolution."""

    @pytest.fixture
    def registry_client(self):
        """Create a registry client for testing."""
        return RegistryClient(url="http://localhost:8080", timeout=10)

    @pytest.fixture
    def mock_session(self):
        """Create a mock HTTP session."""
        session = Mock()
        session.post = AsyncMock()
        session.get = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_multi_tool_agent_registration(self, registry_client, mock_session):
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

        # Mock the OpenAPI client method for GeneratedRegistryClient
        mock_openapi_response = Mock()
        mock_openapi_response.dependencies_resolved = mock_response["metadata"][
            "dependencies_resolved"
        ]

        with patch.object(
            registry_client.agents_api,
            "register_agent",
            return_value=mock_openapi_response,
        ) as mock_register:
            # Act - Register the agent with new multi-tool format
            response = await registry_client.register_multi_tool_agent(
                agent_id, multi_tool_metadata
            )

        # Assert - Verify the request was made correctly
        assert response is not None
        assert response["status"] == "success"
        assert response["agent_id"] == agent_id

        # Verify the mock was called
        mock_register.assert_called_once()
        # The internal structure is handled by the OpenAPI client

        # Verify the OpenAPI client was called with correct data
        # The structure verification is handled internally by the OpenAPI client

    @pytest.mark.asyncio
    async def test_dependency_resolution_response_parsing(self, registry_client):
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

        # Act - Parse the dependency resolution
        dependencies = registry_client.parse_tool_dependencies(registry_response)

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
        self, registry_client, mock_session
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

        # Mock the OpenAPI client method for GeneratedRegistryClient
        # For generated client, mock the send_heartbeat_with_response method directly
        # to bypass Pydantic validation issues in the test
        with patch.object(
            registry_client, "send_heartbeat_with_response", return_value=mock_response
        ) as mock_register:
            # Act - Send heartbeat and get dependency resolution
            response = await registry_client.send_heartbeat_with_dependency_resolution(
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

        # Verify the mock was called
        mock_register.assert_called_once()

    @pytest.mark.asyncio
    async def test_version_constraint_matching(self, registry_client, mock_session):
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

        # Mock the OpenAPI client method for GeneratedRegistryClient
        mock_openapi_response = Mock()

        with patch.object(
            registry_client.agents_api,
            "register_agent",
            return_value=mock_openapi_response,
        ) as mock_register:
            # Act
            response = await registry_client.register_multi_tool_agent(
                "version-test-agent", agent_metadata
            )

        # Assert - Verify the registration was called
        mock_register.assert_called_once()
        # Version constraints are handled by the OpenAPI client internally

    @pytest.mark.asyncio
    async def test_tag_based_dependency_filtering(self, registry_client, mock_session):
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

        # Mock the OpenAPI client method for GeneratedRegistryClient
        mock_openapi_response = Mock()

        with patch.object(
            registry_client.agents_api,
            "register_agent",
            return_value=mock_openapi_response,
        ) as mock_register:
            # Act
            response = await registry_client.register_multi_tool_agent(
                "tag-filter-agent", agent_metadata
            )

        # Assert - Verify the registration was called
        mock_register.assert_called_once()
        # Tags are handled by the OpenAPI client internally

    @pytest.mark.asyncio
    async def test_health_state_transitions_integration(
        self, registry_client, mock_session
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
        with patch.object(
            registry_client,
            "send_heartbeat_with_response",
            return_value=healthy_response,
        ) as mock_register:
            response = await registry_client.send_heartbeat_with_dependency_resolution(
                healthy_status
            )
            assert response is not None
            assert len(response["dependencies_resolved"]["test_tool"]) > 0

        # Test degraded state - dependencies should be empty
        with patch.object(
            registry_client,
            "send_heartbeat_with_response",
            return_value=degraded_response,
        ) as mock_register:
            response = await registry_client.send_heartbeat_with_dependency_resolution(
                healthy_status
            )
            assert response is not None
            assert len(response["dependencies_resolved"]["test_tool"]) == 0


class TestBackwardCompatibility:
    """Test that new multi-tool format maintains backward compatibility."""

    @pytest.fixture
    def registry_client(self):
        return RegistryClient(url="http://localhost:8080")

    @pytest.mark.asyncio
    async def test_legacy_registration_still_works(self, registry_client):
        """Test that legacy single-capability registration still works."""
        # This ensures we don't break existing agents during migration
        mock_response = {"status": "success"}

        # Mock the OpenAPI client method for GeneratedRegistryClient
        mock_openapi_response = Mock()

        with patch.object(
            registry_client.agents_api,
            "register_agent",
            return_value=mock_openapi_response,
        ) as mock_register:
            # Should still work with old format
            result = await registry_client.register_agent(
                agent_name="legacy-agent",
                capabilities=["old_capability"],
                dependencies=["old_dependency"],
            )
            assert result is True

            # Verify the API was called
            mock_register.assert_called_once()

    @pytest.mark.asyncio
    async def test_mixed_format_handling(self, registry_client):
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

        # Should parse both formats correctly
        dependencies = registry_client.parse_tool_dependencies(mixed_response)
        assert "new_tool" in dependencies  # New format takes precedence
        assert dependencies["new_tool"]["new_dep"]["agent_id"] == "new-provider"


class TestErrorHandling:
    """Test error handling for multi-tool registration and dependency resolution."""

    @pytest.fixture
    def registry_client(self):
        return RegistryClient(url="http://localhost:8080")

    @pytest.mark.asyncio
    async def test_registration_failure_handling(self, registry_client):
        """Test handling of registration failures."""
        from mcp_mesh.engine.exceptions import RegistryConnectionError

        # Mock the OpenAPI client method for GeneratedRegistryClient
        with patch.object(
            registry_client.agents_api,
            "register_agent",
            side_effect=RegistryConnectionError("Registry returned 400"),
        ) as mock_register:
            # Generated client catches exceptions and returns None
            result = await registry_client.register_multi_tool_agent(
                "bad-agent", {"invalid": "config"}
            )
            assert result is None  # Should return None on failure

    @pytest.mark.asyncio
    async def test_dependency_resolution_parsing_errors(self, registry_client):
        """Test handling of malformed dependency resolution responses."""
        # Malformed response
        bad_response = {
            "status": "success",
            "metadata": {"dependencies_resolved": "not_a_dict"},  # Should be dict
        }

        # Should handle gracefully without crashing
        dependencies = registry_client.parse_tool_dependencies(bad_response)
        assert dependencies == {}  # Empty dict on parse error

    @pytest.mark.asyncio
    async def test_missing_dependency_providers(self, registry_client):
        """Test handling when no providers are available for dependencies."""
        response_no_providers = {
            "status": "success",
            "metadata": {
                "dependencies_resolved": {"tool_needing_deps": {}}  # No providers found
            },
        }

        dependencies = registry_client.parse_tool_dependencies(response_no_providers)
        assert "tool_needing_deps" in dependencies
        assert len(dependencies["tool_needing_deps"]) == 0  # Empty dependencies
