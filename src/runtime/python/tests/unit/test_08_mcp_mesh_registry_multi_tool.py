"""
Test Driven Development for Multi-Tool Registry Client

Tests for the new multi-tool format where each agent can have multiple tools
with individual dependencies, as implemented in the Go registry.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Import the classes we'll be testing/implementing
# Try to use generated client first, fallback to manual client
try:
    from mcp_mesh.runtime.generated_registry_client import (
        GeneratedRegistryClient as RegistryClient,
    )

    USING_GENERATED_CLIENT = True
except ImportError:
    from mcp_mesh.runtime.registry_client import RegistryClient

    USING_GENERATED_CLIENT = False
from mcp_mesh.runtime.shared.types import HealthStatus


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

        # Mock the _make_request method directly since the session mocking is complex
        with patch.object(
            registry_client, "_make_request", return_value=mock_response
        ) as mock_make_request:
            # Act - Register the agent with new multi-tool format
            response = await registry_client.register_multi_tool_agent(
                agent_id, multi_tool_metadata
            )

            # Assert - Verify the request was made correctly
            assert response is not None
            assert response["status"] == "success"
            assert response["agent_id"] == agent_id

            # Verify the request was made correctly
            mock_make_request.assert_called_once()
            call_args = mock_make_request.call_args

            # Check method and endpoint
            assert call_args[0][0] == "POST"  # method
            assert call_args[0][1] == "/agents/register"  # endpoint

            # Check payload structure
            payload = call_args[0][2]  # payload is third argument
            assert payload["agent_id"] == agent_id
            assert "metadata" in payload
            assert "tools" in payload["metadata"]
            assert len(payload["metadata"]["tools"]) == 2

            # Verify first tool structure
            greet_tool = payload["metadata"]["tools"][0]
            assert greet_tool["function_name"] == "greet"
            assert greet_tool["capability"] == "greeting"
            assert greet_tool["version"] == "1.0.0"
            assert greet_tool["tags"] == ["demo", "v1"]
            assert len(greet_tool["dependencies"]) == 1
            assert greet_tool["dependencies"][0]["capability"] == "date_service"

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
            status="healthy",
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

        # Mock the _make_request method directly since the session mocking is complex
        with patch.object(
            registry_client, "_make_request", return_value=mock_response
        ) as mock_make_request:
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

            # Verify the request was made correctly
            mock_make_request.assert_called_once()
            call_args = mock_make_request.call_args

            # Check method and endpoint
            assert call_args[0][0] == "POST"  # method
            assert call_args[0][1] == "/heartbeat"  # endpoint

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

        with patch.object(registry_client, "_get_session", return_value=mock_session):
            mock_session.post.return_value.__aenter__.return_value.json = AsyncMock(
                return_value=mock_response
            )
            mock_session.post.return_value.__aenter__.return_value.status = 201

            # Act
            await registry_client.register_multi_tool_agent(
                "version-test-agent", agent_metadata
            )

            # Assert - Verify version constraints are preserved in payload
            payload = mock_session.post.call_args[1]["json"]
            dependencies = payload["metadata"]["tools"][0]["dependencies"]

            # Check each version constraint format
            version_constraints = {
                dep["capability"]: dep["version"] for dep in dependencies
            }
            assert version_constraints["cache_service"] == ">=1.0.0,<2.0.0"
            assert version_constraints["db_service"] == "~1.5"
            assert version_constraints["auth_service"] == ">2.0.0"
            assert version_constraints["log_service"] == "1.0.0"

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

        with patch.object(registry_client, "_get_session", return_value=mock_session):
            mock_session.post.return_value.__aenter__.return_value.json = AsyncMock(
                return_value=mock_response
            )
            mock_session.post.return_value.__aenter__.return_value.status = 201

            # Act
            await registry_client.register_multi_tool_agent(
                "tag-filter-agent", agent_metadata
            )

            # Assert - Verify tags are preserved in dependencies
            payload = mock_session.post.call_args[1]["json"]
            dependencies = payload["metadata"]["tools"][0]["dependencies"]

            db_dep = next(
                dep for dep in dependencies if dep["capability"] == "database"
            )
            cache_dep = next(
                dep for dep in dependencies if dep["capability"] == "cache"
            )

            assert db_dep["tags"] == ["production", "US-EAST", "mysql"]
            assert cache_dep["tags"] == ["high-performance"]

    @pytest.mark.asyncio
    async def test_health_state_transitions_integration(
        self, registry_client, mock_session
    ):
        """Test integration with registry health state transitions."""
        # Arrange - Health status for different states
        healthy_status = HealthStatus(
            agent_name="health-test-agent",
            status="healthy",
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
            registry_client, "_make_request", return_value=healthy_response
        ) as mock_make_request:
            response = await registry_client.send_heartbeat_with_dependency_resolution(
                healthy_status
            )
            assert response is not None
            assert len(response["dependencies_resolved"]["test_tool"]) > 0

        # Test degraded state - dependencies should be empty
        with patch.object(
            registry_client, "_make_request", return_value=degraded_response
        ) as mock_make_request:
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

        with patch.object(
            registry_client, "_make_request", return_value=mock_response
        ) as mock_make_request:
            # Should still work with old format
            result = await registry_client.register_agent(
                agent_name="legacy-agent",
                capabilities=["old_capability"],
                dependencies=["old_dependency"],
            )
            assert result is True

            # Verify the request was made correctly
            mock_make_request.assert_called_once()
            call_args = mock_make_request.call_args
            assert call_args[0][0] == "POST"  # method
            assert call_args[0][1] == "/agents/register"  # endpoint

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
        from mcp_mesh.runtime.exceptions import RegistryConnectionError

        # Mock _make_request to raise an exception (simulating registry error)
        with patch.object(
            registry_client,
            "_make_request",
            side_effect=RegistryConnectionError("Registry returned 400"),
        ):
            with pytest.raises(
                RegistryConnectionError
            ):  # Should raise appropriate exception
                await registry_client.register_multi_tool_agent(
                    "bad-agent", {"invalid": "config"}
                )

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
