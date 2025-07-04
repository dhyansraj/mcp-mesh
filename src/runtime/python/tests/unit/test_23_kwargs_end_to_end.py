import asyncio
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.pipeline.heartbeat.dependency_resolution import DependencyResolutionStep
from _mcp_mesh.shared.registry_client_wrapper import RegistryClientWrapper


class TestKwargsEndToEndUnit:
    """Unit tests for kwargs preservation from decorator to client proxy (fully mocked)."""

    @pytest.mark.asyncio
    async def test_kwargs_extraction_in_registry_client(self):
        """Test kwargs extraction from metadata in registry client wrapper."""

        # Test tool metadata with kwargs spread into the dict (from @mesh.tool decorator)
        test_metadata = {
            "capability": "enhanced_service",
            "function_name": "enhanced_function",
            "timeout": 45,
            "retry_count": 3,
            "streaming": True,
            "custom_headers": {"X-Version": "v2"},
        }

        from _mcp_mesh.generated.mcp_mesh_registry_client.api.agents_api import (
            AgentsApi,
        )
        from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient

        # Mock the API client
        mock_api_client = MagicMock(spec=ApiClient)
        wrapper = RegistryClientWrapper(mock_api_client)

        # Mock the agents API
        mock_agents_api = MagicMock(spec=AgentsApi)
        wrapper.agents_api = mock_agents_api

        # Mock registry accepting kwargs
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "status": "success",
            "agent_id": "test-agent",
            "dependencies_resolved": {},
        }
        mock_agents_api.send_heartbeat.return_value = mock_response

        # Create a mock health status
        from datetime import UTC, datetime

        from _mcp_mesh.shared.support_types import HealthStatus

        health_status = HealthStatus(
            agent_name="test-agent",
            status="healthy",
            capabilities=["enhanced_service"],
            timestamp=datetime.now(UTC),
            version="1.0.0",
            metadata={"http_host": "localhost", "http_port": 8080},
        )

        # Mock the decorator registry to return our test metadata
        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_mesh_tools"
        ) as mock_get_tools:
            mock_decorated_func = MagicMock()
            mock_decorated_func.metadata = test_metadata
            mock_get_tools.return_value = {"enhanced_function": mock_decorated_func}

            # Call send_heartbeat_with_dependency_resolution
            result = await wrapper.send_heartbeat_with_dependency_resolution(
                health_status
            )

            # Verify the call was made
            mock_agents_api.send_heartbeat.assert_called_once()
            call_args = mock_agents_api.send_heartbeat.call_args[0][0]

            # Verify kwargs are properly extracted and included in the registration
            assert len(call_args.tools) == 1
            tool_reg = call_args.tools[0]
            assert tool_reg.kwargs is not None
            assert tool_reg.kwargs["timeout"] == 45
            assert tool_reg.kwargs["retry_count"] == 3
            assert tool_reg.kwargs["streaming"] is True
            assert tool_reg.kwargs["custom_headers"]["X-Version"] == "v2"

        # Test that standard fields are NOT included in kwargs
        assert "capability" not in tool_reg.kwargs
        assert "function_name" not in tool_reg.kwargs
        assert "version" not in tool_reg.kwargs
        assert "tags" not in tool_reg.kwargs
        assert "dependencies" not in tool_reg.kwargs
        assert "description" not in tool_reg.kwargs

    def test_proxy_constructor_kwargs_support(self):
        """Test that proxy constructors accept and store kwargs_config."""
        from _mcp_mesh.engine.mcp_client_proxy import MCPClientProxy
        from _mcp_mesh.engine.full_mcp_proxy import FullMCPProxy

        # Test MCPClientProxy with kwargs
        kwargs_config = {
            "timeout": 60,
            "retry_count": 5,
            "custom_headers": {"X-Test": "true"},
        }

        mcp_proxy = MCPClientProxy(
            "http://test:8080", "test_function", kwargs_config=kwargs_config
        )

        assert mcp_proxy.kwargs_config == kwargs_config
        assert mcp_proxy.kwargs_config["timeout"] == 60
        assert mcp_proxy.kwargs_config["retry_count"] == 5

        # Test FullMCPProxy with kwargs
        full_proxy = FullMCPProxy(
            "http://test:8080", "test_function", kwargs_config=kwargs_config
        )

        assert full_proxy.kwargs_config == kwargs_config
        assert full_proxy.kwargs_config["timeout"] == 60
        assert full_proxy.kwargs_config["custom_headers"]["X-Test"] == "true"

        # Test proxies without kwargs (backward compatibility)
        simple_mcp_proxy = MCPClientProxy("http://test:8080", "simple_function")
        assert simple_mcp_proxy.kwargs_config == {}

        simple_full_proxy = FullMCPProxy("http://test:8080", "simple_function")
        assert simple_full_proxy.kwargs_config == {}

    def test_kwargs_backward_compatibility_unit(self):
        """Test that tools without kwargs continue to work (unit test)."""
        simple_metadata = {
            "capability": "simple_service",
            "function_name": "simple_function",
        }

        # Mock the API client
        from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient

        mock_api_client = MagicMock(spec=ApiClient)
        wrapper = RegistryClientWrapper(mock_api_client)

        # Test parse_tool_dependencies with no kwargs
        simple_response = {
            "dependencies_resolved": {
                "simple_function": [
                    {
                        "capability": "simple_service",
                        "endpoint": "http://simple:8080",
                        "function_name": "simple_function",
                        "status": "available",
                        # No kwargs field
                    }
                ]
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(simple_response)

        assert "simple_function" in parsed_deps
        dep = parsed_deps["simple_function"][0]
        assert "kwargs" in dep
        assert dep["kwargs"] == {}  # Should default to empty dict

    def test_kwargs_json_parsing_edge_cases(self):
        """Test edge cases in kwargs JSON parsing."""
        from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient

        mock_api_client = MagicMock(spec=ApiClient)
        wrapper = RegistryClientWrapper(mock_api_client)

        # Test with JSON string kwargs (from database)
        heartbeat_response_with_json = {
            "dependencies_resolved": {
                "test_function": [
                    {
                        "capability": "test_service",
                        "endpoint": "http://test:8080",
                        "function_name": "test_function",
                        "kwargs": '{"timeout": 30, "streaming": false}',  # JSON string
                    }
                ]
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(heartbeat_response_with_json)

        assert "test_function" in parsed_deps
        dep = parsed_deps["test_function"][0]
        assert "kwargs" in dep
        assert dep["kwargs"]["timeout"] == 30
        assert dep["kwargs"]["streaming"] is False

        # Test with malformed JSON
        heartbeat_response_bad_json = {
            "dependencies_resolved": {
                "test_function": [
                    {
                        "capability": "test_service",
                        "kwargs": '{"invalid": json}',  # Invalid JSON
                    }
                ]
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(heartbeat_response_bad_json)
        dep = parsed_deps["test_function"][0]
        assert dep["kwargs"] == {}  # Should fallback to empty dict

    def test_kwargs_extraction_from_metadata(self):
        """Test kwargs extraction from tool metadata."""
        metadata_with_kwargs = {
            "capability": "test_capability",
            "function_name": "test_function",
            "version": "1.0.0",
            "description": "Test function",
            # Non-standard fields should become kwargs
            "timeout": 60,
            "retry_count": 5,
            "custom_config": {"nested": "value"},
            "boolean_flag": True,
            "number_value": 3.14,
        }

        # Mock the kwargs extraction logic that would happen in registry client
        standard_fields = {
            "capability",
            "function_name",
            "version",
            "description",
            "tags",
            "dependencies",
        }
        kwargs = {
            k: v for k, v in metadata_with_kwargs.items() if k not in standard_fields
        }

        assert kwargs["timeout"] == 60
        assert kwargs["retry_count"] == 5
        assert kwargs["custom_config"]["nested"] == "value"
        assert kwargs["boolean_flag"] is True
        assert kwargs["number_value"] == 3.14

    def test_parse_tool_dependencies_with_dict_kwargs(self):
        """Test parsing when kwargs is already a dict (not JSON string)."""
        from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient

        mock_api_client = MagicMock(spec=ApiClient)
        wrapper = RegistryClientWrapper(mock_api_client)

        # Test with dict kwargs (already parsed)
        response_with_dict_kwargs = {
            "dependencies_resolved": {
                "dict_function": [
                    {
                        "capability": "dict_service",
                        "endpoint": "http://dict:8080",
                        "function_name": "dict_function",
                        "kwargs": {  # Already a dict
                            "timeout": 120,
                            "streaming": True,
                            "nested": {"key": "value"},
                        },
                    }
                ]
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(response_with_dict_kwargs)

        assert "dict_function" in parsed_deps
        dep = parsed_deps["dict_function"][0]
        assert dep["kwargs"]["timeout"] == 120
        assert dep["kwargs"]["streaming"] is True
        assert dep["kwargs"]["nested"]["key"] == "value"

    def test_parse_tool_dependencies_legacy_format(self):
        """Test parsing with legacy response format."""
        from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient

        mock_api_client = MagicMock(spec=ApiClient)
        wrapper = RegistryClientWrapper(mock_api_client)

        # Test legacy format with metadata wrapper
        legacy_response = {
            "metadata": {
                "dependencies_resolved": {
                    "legacy_function": [
                        {
                            "capability": "legacy_service",
                            "endpoint": "http://legacy:8080",
                            "function_name": "legacy_function",
                            "kwargs": {"legacy_setting": True},
                        }
                    ]
                }
            }
        }

        parsed_deps = wrapper.parse_tool_dependencies(legacy_response)

        assert "legacy_function" in parsed_deps
        dep = parsed_deps["legacy_function"][0]
        assert dep["kwargs"]["legacy_setting"] is True

    def test_empty_dependencies_resolved(self):
        """Test parsing with empty or missing dependencies_resolved."""
        from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient

        mock_api_client = MagicMock(spec=ApiClient)
        wrapper = RegistryClientWrapper(mock_api_client)

        # Test empty dependencies_resolved
        empty_response = {"dependencies_resolved": {}}
        parsed_deps = wrapper.parse_tool_dependencies(empty_response)
        assert parsed_deps == {}

        # Test missing dependencies_resolved
        missing_response = {"status": "success"}
        parsed_deps = wrapper.parse_tool_dependencies(missing_response)
        assert parsed_deps == {}

        # Test malformed response
        malformed_response = {"dependencies_resolved": "not_a_dict"}
        parsed_deps = wrapper.parse_tool_dependencies(malformed_response)
        assert parsed_deps == {}
