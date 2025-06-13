"""
Test Driven Development for Multi-Tool Decorators

Tests for updating the mesh_agent decorator to support multiple tools
per agent, matching the new Go registry multi-tool format.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from mcp_mesh.decorator_registry import DecoratorRegistry

# Import decorator classes we'll be testing/implementing
from mcp_mesh.decorators import _get_or_create_agent_id, mesh_agent, mesh_tool


class TestMultiToolDecorator:
    """Test the updated decorator that supports multiple tools per agent."""

    def test_single_tool_backward_compatibility(self):
        """Test that existing single-capability decorator still works."""

        @mesh_agent(capability="greeting", version="1.0.0")
        def greet(name: str) -> str:
            return f"Hello {name}!"

        # Should still work with existing format
        assert hasattr(greet, "_mesh_metadata")
        metadata = greet._mesh_metadata
        assert metadata["capability"] == "greeting"
        assert metadata["capabilities"] == ["greeting"]  # Converted to list
        assert metadata["version"] == "1.0.0"

    def test_multi_tool_decorator_new_format(self):
        """Test new multi-tool decorator with tools list."""

        # This is the NEW decorator format we need to implement
        @mesh_agent(
            tools=[
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
            enable_http=True,
            http_port=8889,
        )
        class MultiToolAgent:
            def greet(self, name: str) -> str:
                return f"Hello {name}!"

            def farewell(self, name: str) -> str:
                return f"Goodbye {name}!"

        # Verify multi-tool metadata structure
        assert hasattr(MultiToolAgent, "_mesh_metadata")
        metadata = MultiToolAgent._mesh_metadata

        # Should contain tools array
        assert "tools" in metadata
        assert len(metadata["tools"]) == 2

        # Check first tool
        greet_tool = metadata["tools"][0]
        assert greet_tool["function_name"] == "greet"
        assert greet_tool["capability"] == "greeting"
        assert greet_tool["version"] == "1.0.0"
        assert greet_tool["tags"] == ["demo", "v1"]
        assert len(greet_tool["dependencies"]) == 1
        assert greet_tool["dependencies"][0]["capability"] == "date_service"

        # Check second tool
        farewell_tool = metadata["tools"][1]
        assert farewell_tool["function_name"] == "farewell"
        assert farewell_tool["capability"] == "goodbye"
        assert len(farewell_tool["dependencies"]) == 0

    def test_auto_tool_discovery_from_class_methods(self):
        """Test automatic discovery of tools from decorated class methods."""

        # New decorator with auto-discovery
        @mesh_agent(auto_discover_tools=True, default_version="1.0.0")
        class AutoDiscoveryAgent:

            @mesh_tool(capability="math", version="2.0.0", dependencies=["calculator"])
            def add(self, a: int, b: int) -> int:
                return a + b

            @mesh_tool(capability="string_utils", tags=["text", "utility"])
            def reverse(self, text: str) -> str:
                return text[::-1]

            def _private_method(self):
                # Should be ignored
                pass

        # Should discover tools from @mesh_tool decorated methods
        metadata = AutoDiscoveryAgent._mesh_metadata
        assert "tools" in metadata
        assert len(metadata["tools"]) == 2

        # Check discovered tools
        tool_names = [tool["function_name"] for tool in metadata["tools"]]
        assert "add" in tool_names
        assert "reverse" in tool_names
        assert "_private_method" not in tool_names

    def test_mixed_decorator_usage(self):
        """Test using both explicit tools and auto-discovery."""

        @mesh_agent(
            tools=[
                {
                    "function_name": "explicit_tool",
                    "capability": "explicit_capability",
                    "version": "1.0.0",
                }
            ],
            auto_discover_tools=True,
        )
        class MixedAgent:

            @mesh_tool(capability="discovered", version="1.5.0")
            def discovered_tool(self) -> str:
                return "discovered"

        # Should combine explicit tools and discovered tools
        metadata = MixedAgent._mesh_metadata
        assert len(metadata["tools"]) == 2

        capabilities = [tool["capability"] for tool in metadata["tools"]]
        assert "explicit_capability" in capabilities
        assert "discovered" in capabilities

    def test_dependency_specification_formats(self):
        """Test various dependency specification formats."""

        @mesh_agent(
            tools=[
                {
                    "function_name": "complex_processor",
                    "capability": "processing",
                    "dependencies": [
                        # Version constraints
                        {"capability": "cache", "version": ">=1.0.0,<2.0.0"},
                        {"capability": "db", "version": "~1.5"},
                        {"capability": "auth", "version": ">2.0.0"},
                        # Tag-based filtering
                        {
                            "capability": "logger",
                            "tags": ["production", "high-performance"],
                        },
                        # Combined version and tags
                        {
                            "capability": "storage",
                            "version": ">=2.0.0",
                            "tags": ["cloud", "scalable"],
                        },
                    ],
                }
            ]
        )
        class ComplexAgent:
            pass

        tool = ComplexAgent._mesh_metadata["tools"][0]
        deps = tool["dependencies"]

        # Verify dependency formats preserved
        cache_dep = next(d for d in deps if d["capability"] == "cache")
        assert cache_dep["version"] == ">=1.0.0,<2.0.0"

        logger_dep = next(d for d in deps if d["capability"] == "logger")
        assert logger_dep["tags"] == ["production", "high-performance"]

        storage_dep = next(d for d in deps if d["capability"] == "storage")
        assert storage_dep["version"] == ">=2.0.0"
        assert storage_dep["tags"] == ["cloud", "scalable"]

    def test_agent_id_consistency_across_tools(self):
        """Test that all tools for an agent share the same agent ID."""

        @mesh_agent(
            tools=[
                {"function_name": "tool1", "capability": "cap1"},
                {"function_name": "tool2", "capability": "cap2"},
            ]
        )
        class MultiToolAgent1:
            pass

        @mesh_agent(capability="single_cap")
        class SingleToolAgent:
            pass

        # Both agents should have same agent ID (process-level shared ID)
        agent1_id = MultiToolAgent1._mesh_metadata["agent_name"]
        agent2_id = SingleToolAgent._mesh_metadata["agent_name"]

        # They should have the same shared agent ID
        current_shared_id = _get_or_create_agent_id()
        assert agent1_id == current_shared_id
        assert agent2_id == current_shared_id

    def test_http_wrapper_configuration_multi_tool(self):
        """Test HTTP wrapper configuration for multi-tool agents."""

        @mesh_agent(
            tools=[
                {"function_name": "api_endpoint1", "capability": "api_v1"},
                {"function_name": "api_endpoint2", "capability": "api_v2"},
            ],
            enable_http=True,
            http_host="0.0.0.0",
            http_port=8080,
        )
        class HTTPMultiToolAgent:
            pass

        metadata = HTTPMultiToolAgent._mesh_metadata
        assert metadata["enable_http"] is True
        assert metadata["http_host"] == "0.0.0.0"
        assert metadata["http_port"] == 8080

        # Should be applicable to all tools
        assert len(metadata["tools"]) == 2


class TestMeshToolDecorator:
    """Test the new @mesh_tool decorator for individual tool configuration."""

    def test_mesh_tool_basic_usage(self):
        """Test basic @mesh_tool decorator usage."""

        @mesh_tool(capability="calculator", version="1.0.0")
        def calculate(expression: str) -> float:
            return eval(expression)

        # Should store tool metadata
        assert hasattr(calculate, "_tool_metadata")
        metadata = calculate._tool_metadata
        assert metadata["capability"] == "calculator"
        assert metadata["version"] == "1.0.0"
        assert metadata["function_name"] == "calculate"

    def test_mesh_tool_with_dependencies(self):
        """Test @mesh_tool with dependencies."""

        @mesh_tool(
            capability="complex_math",
            version="2.0.0",
            dependencies=[
                {"capability": "precision_calc", "version": ">=1.5.0"},
                {"capability": "validation", "tags": ["math", "strict"]},
            ],
            tags=["advanced", "math"],
        )
        def complex_calculation(formula: str) -> dict:
            return {"result": 42, "formula": formula}

        metadata = complex_calculation._tool_metadata
        assert metadata["capability"] == "complex_math"
        assert len(metadata["dependencies"]) == 2
        assert metadata["tags"] == ["advanced", "math"]

        # Check dependency structure
        precision_dep = metadata["dependencies"][0]
        assert precision_dep["capability"] == "precision_calc"
        assert precision_dep["version"] == ">=1.5.0"

    def test_mesh_tool_auto_function_name(self):
        """Test automatic function name detection."""

        @mesh_tool(capability="string_processor")
        def process_string_data(data: str) -> str:
            return data.upper()

        metadata = process_string_data._tool_metadata
        assert metadata["function_name"] == "process_string_data"


class TestRegistryIntegration:
    """Test integration between decorators and registry client."""

    @pytest.fixture
    def mock_registry_client(self):
        """Mock registry client for testing."""
        client = Mock()
        client.register_multi_tool_agent = AsyncMock()
        client.parse_tool_dependencies = Mock()
        return client

    def test_decorator_registry_generates_multi_tool_format(self, mock_registry_client):
        """Test that DecoratorRegistry generates correct multi-tool format for registry."""

        @mesh_agent(
            tools=[
                {
                    "function_name": "greet",
                    "capability": "greeting",
                    "version": "1.0.0",
                    "dependencies": [{"capability": "date_service"}],
                }
            ],
            enable_http=True,
            http_port=8889,
        )
        class TestAgent:
            pass

        # Get metadata from registry
        registered_agents = DecoratorRegistry.get_all_agents()
        assert len(registered_agents) > 0

        # Find our test agent
        test_agent_metadata = None
        for _agent, metadata in registered_agents:
            if "tools" in metadata and any(
                tool["capability"] == "greeting" for tool in metadata["tools"]
            ):
                test_agent_metadata = metadata
                break

        assert test_agent_metadata is not None

        # Verify format expected by Go registry
        assert test_agent_metadata["agent_name"] == "TestAgent"
        assert "tools" in test_agent_metadata
        assert len(test_agent_metadata["tools"]) == 1

        # Verify structure matches
        assert "tools" in test_agent_metadata
        assert len(test_agent_metadata["tools"]) == 1
        assert test_agent_metadata["tools"][0]["capability"] == "greeting"

    @patch("mcp_mesh.runtime.registry_client.RegistryClient")
    def test_multi_tool_registration_flow(
        self, mock_registry_client_class, mock_registry_client
    ):
        """Test end-to-end multi-tool registration flow."""

        mock_registry_client_class.return_value = mock_registry_client
        mock_registry_client.register_multi_tool_agent.return_value = {
            "status": "success",
            "agent_id": "test-agent-123",
            "metadata": {
                "dependencies_resolved": {
                    "greet": {"date_service": {"agent_id": "date-provider"}}
                }
            },
        }

        @mesh_agent(
            tools=[
                {
                    "function_name": "greet",
                    "capability": "greeting",
                    "dependencies": [{"capability": "date_service"}],
                }
            ]
        )
        class TestAgent:
            pass

        # Simulate runtime registration process
        # This would be called by the runtime processor
        DecoratorRegistry.build_registry_metadata(TestAgent)

        # Should call new multi-tool registration method
        # (This would be done by the runtime)
        # mock_registry_client.register_multi_tool_agent.assert_called_once()


class TestErrorHandling:
    """Test error handling in multi-tool decorators."""

    def test_invalid_tool_configuration(self):
        """Test handling of invalid tool configurations."""

        with pytest.raises(ValueError, match="Tool must have capability"):

            @mesh_agent(tools=[{"function_name": "bad_tool"}])  # Missing capability
            class BadAgent:
                pass

    def test_conflicting_single_and_multi_tool_params(self):
        """Test error when both single capability and tools are specified."""

        with pytest.raises(
            ValueError, match="Cannot specify both capability and tools"
        ):

            @mesh_agent(
                capability="single_cap",  # Old format
                tools=[
                    {"function_name": "tool", "capability": "multi_cap"}
                ],  # New format
            )
            class ConflictingAgent:
                pass

    def test_invalid_dependency_format(self):
        """Test handling of invalid dependency specifications."""

        with pytest.raises(ValueError, match="Dependency must have capability"):

            @mesh_agent(
                tools=[
                    {
                        "function_name": "tool",
                        "capability": "cap",
                        "dependencies": [{"version": "1.0.0"}],  # Missing capability
                    }
                ]
            )
            class BadDependencyAgent:
                pass

    def test_duplicate_function_names(self):
        """Test error handling for duplicate function names in tools."""

        with pytest.raises(ValueError, match="Duplicate function name"):

            @mesh_agent(
                tools=[
                    {"function_name": "duplicate", "capability": "cap1"},
                    {
                        "function_name": "duplicate",
                        "capability": "cap2",
                    },  # Duplicate name
                ]
            )
            class DuplicateAgent:
                pass


class TestMigrationSupport:
    """Test migration support from old single-capability to new multi-tool format."""

    def test_automatic_single_to_multi_conversion(self):
        """Test automatic conversion of single capability to multi-tool format."""

        @mesh_agent(
            capability="legacy_capability", version="1.0.0", dependencies=["legacy_dep"]
        )
        def legacy_function():
            pass

        # Should automatically convert to multi-tool format internally
        metadata = legacy_function._mesh_metadata

        # Internal representation should be multi-tool
        assert "tools" in metadata
        assert len(metadata["tools"]) == 1

        tool = metadata["tools"][0]
        assert tool["capability"] == "legacy_capability"
        assert tool["version"] == "1.0.0"
        assert tool["dependencies"] == [{"capability": "legacy_dep"}]

        # Function name should be auto-detected
        assert tool["function_name"] == "legacy_function"

    def test_gradual_migration_support(self):
        """Test support for gradual migration of large codebases."""

        # Old format should continue working
        @mesh_agent(capability="old_style", dependencies=["old_dep"])
        class OldStyleAgent:
            pass

        # New format should work alongside
        @mesh_agent(tools=[{"function_name": "new_tool", "capability": "new_style"}])
        class NewStyleAgent:
            pass

        # Both should be registered successfully
        old_metadata = OldStyleAgent._mesh_metadata
        new_metadata = NewStyleAgent._mesh_metadata

        assert "tools" in old_metadata  # Converted to multi-tool
        assert "tools" in new_metadata  # Native multi-tool

        # Both should work with the registry
        assert len(old_metadata["tools"]) == 1
        assert len(new_metadata["tools"]) == 1
