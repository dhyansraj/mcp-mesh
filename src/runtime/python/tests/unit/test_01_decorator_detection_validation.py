"""
Test decorator detection and validation for MCP Mesh decorators.

This module tests the basic functionality of @mesh.tool and @mesh.agent decorators
focusing on parameter validation, environment variable precedence, and decorator
registry integration.
"""

import os
from typing import Any
from unittest.mock import MagicMock, patch

# Import the decorators and registry
import mesh
import pytest
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.shared.config_resolver import get_config_value


class TestMeshToolDetection:
    """Test basic @mesh.tool decorator detection and metadata storage."""

    def setup_method(self):
        """Clear registry and debounce coordinator before each test."""
        DecoratorRegistry.clear_all()
        # Clear debounce coordinator to prevent background thread interference
        from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

        clear_debounce_coordinator()

    def test_basic_mesh_tool_no_parameters(self):
        """Test @mesh.tool with no parameters."""

        @mesh.tool()
        def sample_function():
            """Sample function docstring."""
            return "test"

        # Check function is registered
        tools = DecoratorRegistry.get_mesh_tools()
        assert "sample_function" in tools

        # Check metadata
        metadata = tools["sample_function"].metadata
        assert metadata["capability"] is None
        assert metadata["tags"] == []
        assert metadata["version"] == "1.0.0"
        assert metadata["dependencies"] == []
        assert metadata["description"] == "Sample function docstring."

    def test_mesh_tool_with_capability(self):
        """Test @mesh.tool with capability parameter."""

        @mesh.tool(capability="greeting")
        def hello_function():
            return "hello"

        tools = DecoratorRegistry.get_mesh_tools()
        metadata = tools["hello_function"].metadata
        assert metadata["capability"] == "greeting"

    def test_mesh_tool_with_all_parameters(self):
        """Test @mesh.tool with all parameters specified."""

        @mesh.tool(
            capability="test_capability",
            tags=["tag1", "tag2"],
            version="2.0.0",
            dependencies=["dep1", {"capability": "dep2", "tags": ["tag"]}],
            description="Custom description",
            extra_param="extra_value",
        )
        def full_function():
            return "full"

        tools = DecoratorRegistry.get_mesh_tools()
        metadata = tools["full_function"].metadata

        assert metadata["capability"] == "test_capability"
        assert metadata["tags"] == ["tag1", "tag2"]
        assert metadata["version"] == "2.0.0"
        assert len(metadata["dependencies"]) == 2
        assert metadata["dependencies"][0] == {"capability": "dep1", "tags": []}
        assert metadata["dependencies"][1] == {"capability": "dep2", "tags": ["tag"]}
        assert metadata["description"] == "Custom description"
        assert metadata["extra_param"] == "extra_value"

    def test_mesh_tool_preserves_function_callable(self):
        """Test that @mesh.tool preserves function callability."""

        @mesh.tool(capability="test")
        def callable_function(x: int) -> int:
            return x * 2

        # Function should still be callable
        result = callable_function(5)
        assert result == 10

    def test_mesh_tool_with_dependencies_creates_wrapper(self):
        """Test that @mesh.tool with dependencies creates injection wrapper."""
        from mesh.types import McpMeshTool

        @mesh.tool(capability="test", dependencies=["dependency1"])
        def dependent_function(agent: McpMeshTool):
            return "test"

        # Check that dependency injection was processed
        tools = DecoratorRegistry.get_mesh_tools()
        assert "dependent_function" in tools

        # Verify the function has the expected metadata
        metadata = tools["dependent_function"].metadata
        assert metadata["dependencies"] == [{"capability": "dependency1", "tags": []}]

        # The registered function should have the mesh tool metadata
        registered_func = tools["dependent_function"].function
        assert hasattr(registered_func, "_mesh_tool_metadata")


class TestMeshAgentDetection:
    """Test basic @mesh.agent decorator detection and metadata storage."""

    def setup_method(self):
        """Clear registry, environment, and debounce coordinator before each test."""
        DecoratorRegistry.clear_all()
        # Clear debounce coordinator to prevent background thread interference
        from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

        clear_debounce_coordinator()

        # Clear environment variables that may be auto-set by runtime initialization
        # CRITICAL: Don't clear MCP_MESH_AUTO_RUN or MCP_MESH_HTTP_ENABLED - conftest.py
        # sets these to "false" to prevent server startups during tests. Removing them
        # causes decorators to fall back to MeshDefaults.AUTO_RUN = True, starting
        # uvicorn servers and making tests take 2-3s each (19+ minutes for 750 tests).
        env_vars = [
            "MCP_MESH_NAMESPACE",
            # "MCP_MESH_AUTO_RUN",  # Don't clear - needed to prevent server startup
            "MCP_MESH_AUTO_RUN_INTERVAL",
            "MCP_MESH_HEALTH_INTERVAL",
            # "MCP_MESH_HTTP_ENABLED",  # Don't clear - needed to prevent HTTP server
        ]
        for var in env_vars:
            os.environ.pop(var, None)

    def test_mesh_agent_with_required_name(self):
        """Test @mesh.agent with required name parameter."""

        @mesh.agent(name="test-agent")
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        assert "TestAgent" in agents

        metadata = agents["TestAgent"].metadata
        assert metadata["name"] == "test-agent"
        assert metadata["version"] == "1.0.0"  # default
        # Note: enable_http is False in test environment due to conftest.py setting MCP_MESH_HTTP_ENABLED=false
        assert metadata["enable_http"] is False

    @patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "custom.host"})
    def test_mesh_agent_with_all_parameters(self):
        """Test @mesh.agent with all parameters specified."""

        @mesh.agent(
            name="full-agent",
            version="2.0.0",
            description="Full agent description",
            http_host="custom.host",  # This parameter is now ignored, HostResolver used instead
            http_port=8080,
            enable_http=False,
            namespace="custom",
            health_interval=60,
            auto_run=False,
            auto_run_interval=20,
            custom_param="custom_value",
        )
        class FullAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["FullAgent"].metadata

        assert metadata["name"] == "full-agent"
        assert metadata["version"] == "2.0.0"
        assert metadata["description"] == "Full agent description"
        assert (
            metadata["http_host"] == "custom.host"
        )  # Now comes from HostResolver via env var
        assert metadata["http_port"] == 8080
        assert metadata["enable_http"] is False
        assert metadata["namespace"] == "custom"
        assert metadata["health_interval"] == 60
        assert metadata["auto_run"] is False
        assert metadata["auto_run_interval"] == 20
        assert metadata["custom_param"] == "custom_value"

    def test_mesh_agent_on_function(self):
        """Test that @mesh.agent can be applied to functions."""

        @mesh.agent(name="function-agent")
        def agent_function():
            return "agent"

        agents = DecoratorRegistry.get_mesh_agents()
        assert "agent_function" in agents
        metadata = agents["agent_function"].metadata
        assert metadata["name"] == "function-agent"


class TestParameterValidation:
    """Test parameter validation for both decorators."""

    def setup_method(self):
        """Clear registry and debounce coordinator before each test."""
        DecoratorRegistry.clear_all()
        # Clear debounce coordinator to prevent background thread interference
        from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

        clear_debounce_coordinator()

    # @mesh.tool validation tests
    def test_mesh_tool_invalid_capability_type(self):
        """Test @mesh.tool raises error for invalid capability type."""
        with pytest.raises(ValueError, match="capability must be a string"):

            @mesh.tool(capability=123)
            def invalid_function():
                pass

    def test_mesh_tool_invalid_tags_type(self):
        """Test @mesh.tool raises error for invalid tags type."""
        with pytest.raises(ValueError, match="tags must be a list"):

            @mesh.tool(tags="not_a_list")
            def invalid_function():
                pass

    def test_mesh_tool_invalid_tag_item_type(self):
        """Test @mesh.tool raises error for invalid tag item type."""
        with pytest.raises(ValueError, match="all tags must be strings"):

            @mesh.tool(tags=["valid", 123])
            def invalid_function():
                pass

    def test_mesh_tool_invalid_version_type(self):
        """Test @mesh.tool raises error for invalid version type."""
        with pytest.raises(ValueError, match="version must be a string"):

            @mesh.tool(version=123)
            def invalid_function():
                pass

    def test_mesh_tool_invalid_dependencies_type(self):
        """Test @mesh.tool raises error for invalid dependencies type."""
        with pytest.raises(ValueError, match="dependencies must be a list"):

            @mesh.tool(dependencies="not_a_list")
            def invalid_function():
                pass

    def test_mesh_tool_invalid_dependency_format(self):
        """Test @mesh.tool raises error for invalid dependency format."""
        with pytest.raises(
            ValueError, match="dependencies must be strings or dictionaries"
        ):

            @mesh.tool(dependencies=[123])
            def invalid_function():
                pass

    def test_mesh_tool_missing_capability_in_dict_dependency(self):
        """Test @mesh.tool raises error for missing capability in dict dependency."""
        with pytest.raises(ValueError, match="dependency must have 'capability' field"):

            @mesh.tool(dependencies=[{"tags": ["test"]}])
            def invalid_function():
                pass

    # @mesh.agent validation tests
    def test_mesh_agent_missing_name(self):
        """Test @mesh.agent raises error when name is missing."""
        with pytest.raises(ValueError, match="name is required for @mesh.agent"):

            @mesh.agent()
            class InvalidAgent:
                pass

    def test_mesh_agent_invalid_name_type(self):
        """Test @mesh.agent raises error for invalid name type."""
        with pytest.raises(ValueError, match="name must be a string"):

            @mesh.agent(name=123)
            class InvalidAgent:
                pass

    def test_mesh_agent_invalid_http_port_range(self):
        """Test @mesh.agent raises error for invalid http_port range."""
        with pytest.raises(ValueError, match="http_port must be between 0 and 65535"):

            @mesh.agent(name="test", http_port=70000)
            class InvalidAgent:
                pass

    def test_mesh_agent_invalid_health_interval_minimum(self):
        """Test @mesh.agent raises error for invalid health_interval minimum."""
        with pytest.raises(
            ValueError, match="health_interval must be at least 1 second"
        ):

            @mesh.agent(name="test", health_interval=0)
            class InvalidAgent:
                pass

    def test_mesh_agent_invalid_auto_run_interval_minimum(self):
        """Test @mesh.agent raises error for invalid auto_run_interval minimum."""
        with pytest.raises(
            ValueError, match="auto_run_interval must be at least 1 second"
        ):

            @mesh.agent(name="test", auto_run_interval=0)
            class InvalidAgent:
                pass


class TestEnvironmentVariablePrecedence:
    """Test environment variable precedence over decorator parameters."""

    def setup_method(self):
        """Clear registry, environment, and debounce coordinator before each test."""
        DecoratorRegistry.clear_all()
        # Clear debounce coordinator to prevent background thread interference
        from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

        clear_debounce_coordinator()
        # Clear relevant environment variables, but preserve MCP_MESH_AUTO_RUN=false for tests
        env_vars = [
            "MCP_MESH_AGENT_NAME",
            "MCP_MESH_HTTP_HOST",
            "MCP_MESH_HTTP_PORT",
            "MCP_MESH_HTTP_ENABLED",
            "MCP_MESH_NAMESPACE",
            "MCP_MESH_HEALTH_INTERVAL",
            # "MCP_MESH_AUTO_RUN",  # CRITICAL: Don't clear this in tests to prevent runtime initialization
            "MCP_MESH_AUTO_RUN_INTERVAL",
        ]
        for var in env_vars:
            os.environ.pop(var, None)

    def teardown_method(self):
        """Clean up environment after each test."""
        env_vars = [
            "MCP_MESH_AGENT_NAME",
            "MCP_MESH_HTTP_HOST",
            "MCP_MESH_HTTP_PORT",
            "MCP_MESH_HTTP_ENABLED",
            "MCP_MESH_NAMESPACE",
            "MCP_MESH_HEALTH_INTERVAL",
            # "MCP_MESH_AUTO_RUN",  # CRITICAL: Don't clear this in tests to preserve test environment
            "MCP_MESH_AUTO_RUN_INTERVAL",
        ]
        for var in env_vars:
            os.environ.pop(var, None)

    def test_http_host_env_var_precedence(self):
        """Test MCP_MESH_HTTP_HOST environment variable takes precedence."""
        os.environ["MCP_MESH_HTTP_HOST"] = "env.host.com"

        @mesh.agent(name="test", http_host="decorator.host.com")
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert metadata["http_host"] == "env.host.com"

    def test_http_port_env_var_precedence(self):
        """Test MCP_MESH_HTTP_PORT environment variable takes precedence."""
        os.environ["MCP_MESH_HTTP_PORT"] = "9090"

        @mesh.agent(name="test", http_port=8080)
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert metadata["http_port"] == 9090

    def test_enable_http_env_var_precedence(self):
        """Test MCP_MESH_HTTP_ENABLED environment variable takes precedence."""
        os.environ["MCP_MESH_HTTP_ENABLED"] = "false"

        @mesh.agent(name="test", enable_http=True)
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert metadata["enable_http"] is False

    def test_health_interval_env_var_precedence(self):
        """Test MCP_MESH_HEALTH_INTERVAL environment variable takes precedence."""
        os.environ["MCP_MESH_HEALTH_INTERVAL"] = "120"

        @mesh.agent(name="test", health_interval=60)
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert metadata["health_interval"] == 120

    def test_multiple_env_vars_together(self):
        """Test multiple environment variables work together."""
        os.environ["MCP_MESH_HTTP_HOST"] = "multi.host.com"
        os.environ["MCP_MESH_HTTP_PORT"] = "7070"
        os.environ["MCP_MESH_HEALTH_INTERVAL"] = "90"

        @mesh.agent(
            name="test",
            http_host="decorator.host.com",
            http_port=8080,
            health_interval=30,
        )
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert metadata["http_host"] == "multi.host.com"
        assert metadata["http_port"] == 7070
        assert metadata["health_interval"] == 90

    def test_env_var_vs_default_precedence(self):
        """Test environment variable takes precedence over default values."""
        os.environ["MCP_MESH_HTTP_HOST"] = "env.override.com"

        @mesh.agent(name="test")  # Use default http_host
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert metadata["http_host"] == "env.override.com"

    @patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "decorator.host.com"})
    def test_decorator_vs_default_precedence(self):
        """Test HostResolver is used regardless of decorator parameters."""

        @mesh.agent(name="test", http_host="decorator.host.com")  # This is now ignored
        class TestAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        metadata = agents["TestAgent"].metadata
        assert (
            metadata["http_host"] == "decorator.host.com"
        )  # Now comes from HostResolver via env var


class TestDecoratorRegistry:
    """Test DecoratorRegistry integration and storage."""

    def setup_method(self):
        """Clear registry and debounce coordinator before each test."""
        DecoratorRegistry.clear_all()
        # Clear debounce coordinator to prevent background thread interference
        from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

        clear_debounce_coordinator()

    def test_registry_stores_mesh_tools(self):
        """Test that DecoratorRegistry properly stores @mesh.tool decorators."""

        @mesh.tool(capability="test1")
        def tool1():
            pass

        @mesh.tool(capability="test2")
        def tool2():
            pass

        tools = DecoratorRegistry.get_mesh_tools()
        assert len(tools) == 2
        assert "tool1" in tools
        assert "tool2" in tools
        assert tools["tool1"].decorator_type == "mesh_tool"
        assert tools["tool2"].decorator_type == "mesh_tool"

    def test_registry_stores_mesh_agents(self):
        """Test that DecoratorRegistry properly stores @mesh.agent decorators."""

        @mesh.agent(name="agent1")
        class Agent1:
            pass

        @mesh.agent(name="agent2")
        def agent2():
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        assert len(agents) == 2
        assert "Agent1" in agents
        assert "agent2" in agents
        assert agents["Agent1"].decorator_type == "mesh_agent"
        assert agents["agent2"].decorator_type == "mesh_agent"

    def test_registry_get_all_decorators(self):
        """Test DecoratorRegistry.get_all_decorators() includes both types."""

        @mesh.agent(name="test-agent")
        class TestAgent:
            pass

        @mesh.tool(capability="test-tool")
        def test_tool():
            pass

        all_decorators = DecoratorRegistry.get_all_decorators()
        assert len(all_decorators) == 2
        assert "TestAgent" in all_decorators
        assert "test_tool" in all_decorators

    def test_registry_stats(self):
        """Test DecoratorRegistry statistics."""

        @mesh.agent(name="agent")
        class Agent:
            pass

        @mesh.tool(capability="tool1")
        def tool1():
            pass

        @mesh.tool(capability="tool2")
        def tool2():
            pass

        stats = DecoratorRegistry.get_stats()
        assert stats["mesh_agent"] == 1
        assert stats["mesh_tool"] == 2
        assert stats["total"] == 3

    def test_registry_clear_all(self):
        """Test DecoratorRegistry.clear_all() clears everything."""

        @mesh.agent(name="agent")
        class Agent:
            pass

        @mesh.tool(capability="tool")
        def tool():
            pass

        # Verify items exist
        assert len(DecoratorRegistry.get_all_decorators()) == 2

        # Clear and verify empty
        DecoratorRegistry.clear_all()
        assert len(DecoratorRegistry.get_all_decorators()) == 0
        assert len(DecoratorRegistry.get_mesh_agents()) == 0
        assert len(DecoratorRegistry.get_mesh_tools()) == 0


class TestConstraintValidation:
    """Test system constraints: 0-1 agents, 0-N tools."""

    def setup_method(self):
        """Clear registry and debounce coordinator before each test."""
        DecoratorRegistry.clear_all()
        # Clear debounce coordinator to prevent background thread interference
        from _mcp_mesh.pipeline.mcp_startup import clear_debounce_coordinator

        clear_debounce_coordinator()

    def test_zero_agents_allowed(self):
        """Test that zero agents is allowed."""

        @mesh.tool(capability="standalone")
        def standalone_tool():
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        tools = DecoratorRegistry.get_mesh_tools()

        assert len(agents) == 0
        assert len(tools) == 1

    def test_one_agent_allowed(self):
        """Test that one agent is allowed."""

        @mesh.agent(name="single-agent")
        class SingleAgent:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        assert len(agents) == 1

    def test_multiple_agents_detection(self):
        """Test detection of multiple agents (should be tracked)."""

        @mesh.agent(name="agent1")
        class Agent1:
            pass

        @mesh.agent(name="agent2")
        class Agent2:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        # Registry allows storage of multiple agents - constraint enforcement
        # is handled at the pipeline level, not decorator level
        assert len(agents) == 2

    def test_zero_tools_allowed(self):
        """Test that zero tools is allowed."""

        @mesh.agent(name="agent-only")
        class AgentOnly:
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        tools = DecoratorRegistry.get_mesh_tools()

        assert len(agents) == 1
        assert len(tools) == 0

    def test_multiple_tools_allowed(self):
        """Test that multiple tools are allowed."""

        @mesh.tool(capability="tool1")
        def tool1():
            pass

        @mesh.tool(capability="tool2")
        def tool2():
            pass

        @mesh.tool(capability="tool3")
        def tool3():
            pass

        tools = DecoratorRegistry.get_mesh_tools()
        assert len(tools) == 3

    def test_agent_with_multiple_tools(self):
        """Test agent with multiple tools combination."""

        @mesh.agent(name="multi-tool-agent")
        class MultiToolAgent:
            pass

        @mesh.tool(capability="capability1")
        def capability1():
            pass

        @mesh.tool(capability="capability2")
        def capability2():
            pass

        agents = DecoratorRegistry.get_mesh_agents()
        tools = DecoratorRegistry.get_mesh_tools()

        assert len(agents) == 1
        assert len(tools) == 2
        assert agents["MultiToolAgent"].metadata["name"] == "multi-tool-agent"

    def test_agent_id_shared_across_process(self):
        """Test that agent ID is shared across the process."""
        # Clear any existing agent ID
        from mesh.decorators import (_clear_shared_agent_id,
                                     _get_or_create_agent_id)

        _clear_shared_agent_id()

        # Generate agent IDs with the same name
        id1 = _get_or_create_agent_id("test-agent")
        id2 = _get_or_create_agent_id("test-agent")  # Should be same
        id3 = _get_or_create_agent_id("other-agent")  # Should still be same

        assert id1 == id2 == id3  # All should return the same shared ID
        assert id1.startswith("test-agent-")  # Should use first provided name

    def test_agent_id_generation_precedence(self):
        """Test agent ID generation precedence: env > name > default."""
        from mesh.decorators import (_clear_shared_agent_id,
                                     _get_or_create_agent_id)

        # Test with environment variable
        os.environ["MCP_MESH_AGENT_NAME"] = "env-agent"
        _clear_shared_agent_id()

        id_with_env = _get_or_create_agent_id("decorator-agent")
        assert id_with_env.startswith("env-agent-")

        # Clean up
        os.environ.pop("MCP_MESH_AGENT_NAME", None)
        _clear_shared_agent_id()

        # Test with decorator parameter
        id_with_decorator = _get_or_create_agent_id("decorator-agent")
        assert id_with_decorator.startswith("decorator-agent-")

        _clear_shared_agent_id()

        # Test with default
        id_with_default = _get_or_create_agent_id(None)
        assert id_with_default.startswith("agent-")
