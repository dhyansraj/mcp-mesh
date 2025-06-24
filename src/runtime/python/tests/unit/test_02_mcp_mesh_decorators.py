"""
Test suite for mesh decorators: mesh.tool and mesh.agent

Comprehensive tests covering the dual decorator architecture:
- @mesh.tool: Function-level tool registration and capabilities
- @mesh.agent: Agent-level configuration and metadata
"""

import pytest


class TestMeshToolDecorator:
    """Test cases for the @mesh.tool decorator (renamed from @mesh_agent)."""

    def test_basic_mesh_tool_usage_with_capability(self):
        """Test basic mesh.tool decorator usage with capability."""
        import mesh

        @mesh.tool(capability="test_capability")
        def test_function():
            """Test function."""
            return "test"

        # Should have tool metadata
        assert hasattr(test_function, "_mesh_tool_metadata")
        metadata = test_function._mesh_tool_metadata

        assert metadata["capability"] == "test_capability"
        assert metadata["tags"] == []
        assert metadata["version"] == "1.0.0"  # default
        assert metadata["dependencies"] == []
        assert metadata["description"] == "Test function."

        # Function should still work
        assert test_function() == "test"

    def test_basic_mesh_tool_usage_without_capability(self):
        """Test basic mesh.tool decorator usage without capability (optional)."""
        import mesh

        @mesh.tool()
        def test_function():
            """Test function without capability."""
            return "test"

        # Should have tool metadata
        assert hasattr(test_function, "_mesh_tool_metadata")
        metadata = test_function._mesh_tool_metadata

        assert metadata["capability"] is None  # capability is optional
        assert metadata["tags"] == []
        assert metadata["version"] == "1.0.0"  # default
        assert metadata["dependencies"] == []
        assert metadata["description"] == "Test function without capability."

        # Function should still work
        assert test_function() == "test"

    def test_mesh_tool_all_parameters(self):
        """Test mesh.tool with all parameters."""
        import mesh

        @mesh.tool(
            capability="advanced_test",
            tags=["system", "test"],
            version="2.1.0",
            dependencies=[
                {"capability": "auth", "tags": ["security"]},
                {"capability": "logger"},
            ],
            description="Advanced test capability",
        )
        def advanced_function():
            return "advanced"

        metadata = advanced_function._mesh_tool_metadata
        assert metadata["capability"] == "advanced_test"
        assert metadata["tags"] == ["system", "test"]
        assert metadata["version"] == "2.1.0"
        assert len(metadata["dependencies"]) == 2
        assert metadata["dependencies"][0]["capability"] == "auth"
        assert metadata["dependencies"][0]["tags"] == ["security"]
        assert metadata["dependencies"][1]["capability"] == "logger"
        assert metadata["dependencies"][1]["tags"] == []  # default
        assert metadata["description"] == "Advanced test capability"

    def test_mesh_tool_capability_validation(self):
        """Test mesh.tool capability parameter validation."""
        import mesh

        # Capability can be None (optional)
        @mesh.tool(capability=None)
        def no_capability():
            pass

        assert no_capability._mesh_tool_metadata["capability"] is None

        # Capability can be a string
        @mesh.tool(capability="test_capability")
        def with_capability():
            pass

        assert with_capability._mesh_tool_metadata["capability"] == "test_capability"

        # Invalid capability type should raise error
        with pytest.raises(ValueError, match="capability must be a string"):

            @mesh.tool(capability=123)
            def invalid_capability_number():
                pass

        with pytest.raises(ValueError, match="capability must be a string"):

            @mesh.tool(capability=["list"])
            def invalid_capability_list():
                pass

    def test_mesh_tool_tags_validation(self):
        """Test mesh.tool tags parameter validation."""
        import mesh

        # Tags can be None (defaults to empty list)
        @mesh.tool(tags=None)
        def no_tags():
            pass

        assert no_tags._mesh_tool_metadata["tags"] == []

        # Tags can be empty list
        @mesh.tool(tags=[])
        def empty_tags():
            pass

        assert empty_tags._mesh_tool_metadata["tags"] == []

        # Tags can be list of strings
        @mesh.tool(tags=["tag1", "tag2", "tag3"])
        def with_tags():
            pass

        assert with_tags._mesh_tool_metadata["tags"] == ["tag1", "tag2", "tag3"]

        # Invalid tags type should raise error
        with pytest.raises(ValueError, match="tags must be a list"):

            @mesh.tool(tags="not_list")
            def invalid_tags_string():
                pass

        with pytest.raises(ValueError, match="tags must be a list"):

            @mesh.tool(tags=123)
            def invalid_tags_number():
                pass

        # Invalid tag items should raise error
        with pytest.raises(ValueError, match="all tags must be strings"):

            @mesh.tool(tags=["valid", 123, "also_valid"])
            def invalid_tag_items():
                pass

    def test_mesh_tool_version_validation(self):
        """Test mesh.tool version parameter validation."""
        import mesh

        # Version defaults to "1.0.0"
        @mesh.tool()
        def default_version():
            pass

        assert default_version._mesh_tool_metadata["version"] == "1.0.0"

        # Version can be custom string
        @mesh.tool(version="2.1.3")
        def custom_version():
            pass

        assert custom_version._mesh_tool_metadata["version"] == "2.1.3"

        # Invalid version type should raise error
        with pytest.raises(ValueError, match="version must be a string"):

            @mesh.tool(version=1.0)
            def invalid_version_float():
                pass

        with pytest.raises(ValueError, match="version must be a string"):

            @mesh.tool(version=123)
            def invalid_version_int():
                pass

    def test_mesh_tool_dependencies_validation(self):
        """Test mesh.tool dependencies parameter validation."""
        import mesh

        # Dependencies can be None (defaults to empty list)
        @mesh.tool(dependencies=None)
        def no_dependencies():
            pass

        assert no_dependencies._mesh_tool_metadata["dependencies"] == []

        # Dependencies can be empty list
        @mesh.tool(dependencies=[])
        def empty_dependencies():
            pass

        assert empty_dependencies._mesh_tool_metadata["dependencies"] == []

        # Dependencies can be list of strings (simple format)
        @mesh.tool(dependencies=["dep1", "dep2"])
        def string_dependencies():
            pass

        expected = [
            {"capability": "dep1", "tags": [], "version": None},
            {"capability": "dep2", "tags": [], "version": None},
        ]
        assert string_dependencies._mesh_tool_metadata["dependencies"] == expected

        # Dependencies can be list of dicts (complex format)
        @mesh.tool(
            dependencies=[
                {"capability": "complex_dep", "tags": ["prod"], "version": ">=1.0.0"}
            ]
        )
        def complex_dependencies():
            pass

        expected = [
            {"capability": "complex_dep", "tags": ["prod"], "version": ">=1.0.0"}
        ]
        assert complex_dependencies._mesh_tool_metadata["dependencies"] == expected

        # Mixed simple and complex dependencies
        @mesh.tool(
            dependencies=[
                "simple_dep",
                {"capability": "complex_dep", "tags": ["test"], "version": "2.0.0"},
            ]
        )
        def mixed_dependencies():
            pass

        expected = [
            {"capability": "simple_dep", "tags": [], "version": None},
            {"capability": "complex_dep", "tags": ["test"], "version": "2.0.0"},
        ]
        assert mixed_dependencies._mesh_tool_metadata["dependencies"] == expected

        # Invalid dependencies type should raise error
        with pytest.raises(ValueError, match="dependencies must be a list"):

            @mesh.tool(dependencies="not_list")
            def invalid_deps_string():
                pass

        with pytest.raises(ValueError, match="dependencies must be a list"):

            @mesh.tool(dependencies={"not": "list"})
            def invalid_deps_dict():
                pass

        # Invalid dependency item type should raise error
        with pytest.raises(
            ValueError, match="dependencies must be strings or dictionaries"
        ):

            @mesh.tool(dependencies=[123])
            def invalid_dep_item():
                pass

        # Missing capability in dict dependency should raise error
        with pytest.raises(ValueError, match="dependency must have 'capability' field"):

            @mesh.tool(dependencies=[{"tags": ["system"]}])
            def missing_dep_capability():
                pass

        # Invalid capability type in dict dependency should raise error
        with pytest.raises(ValueError, match="dependency capability must be a string"):

            @mesh.tool(dependencies=[{"capability": 123}])
            def invalid_dep_capability_type():
                pass

        # Invalid tags in dependency should raise error
        with pytest.raises(ValueError, match="dependency tags must be a list"):

            @mesh.tool(dependencies=[{"capability": "test", "tags": "not_list"}])
            def invalid_dep_tags():
                pass

        # Invalid tag items in dependency should raise error
        with pytest.raises(ValueError, match="all dependency tags must be strings"):

            @mesh.tool(dependencies=[{"capability": "test", "tags": ["valid", 123]}])
            def invalid_dep_tag_items():
                pass

        # Invalid version type in dependency should raise error
        with pytest.raises(ValueError, match="dependency version must be a string"):

            @mesh.tool(dependencies=[{"capability": "test", "version": 1.0}])
            def invalid_dep_version():
                pass

    def test_mesh_tool_description_validation(self):
        """Test mesh.tool description parameter validation."""
        import mesh

        # Description can be None (defaults to function docstring)
        @mesh.tool(description=None)
        def no_description():
            """Function docstring."""
            pass

        assert (
            no_description._mesh_tool_metadata["description"] == "Function docstring."
        )

        # Description can be custom string
        @mesh.tool(description="Custom description")
        def custom_description():
            """Function docstring."""
            pass

        assert (
            custom_description._mesh_tool_metadata["description"]
            == "Custom description"
        )

        # Invalid description type should raise error
        with pytest.raises(ValueError, match="description must be a string"):

            @mesh.tool(description=123)
            def invalid_description_number():
                pass

        with pytest.raises(ValueError, match="description must be a string"):

            @mesh.tool(description=["list"])
            def invalid_description_list():
                pass

    def test_mesh_tool_parameter_combinations(self):
        """Test mesh.tool with various parameter combinations."""
        import mesh

        # All parameters None/default
        @mesh.tool()
        def minimal_tool():
            """Minimal tool."""
            pass

        metadata = minimal_tool._mesh_tool_metadata
        assert metadata["capability"] is None
        assert metadata["tags"] == []
        assert metadata["version"] == "1.0.0"
        assert metadata["dependencies"] == []
        assert metadata["description"] == "Minimal tool."

        # All parameters specified
        @mesh.tool(
            capability="comprehensive",
            tags=["test", "demo"],
            version="3.2.1",
            dependencies=["dep1", {"capability": "dep2", "version": ">=2.0"}],
            description="Comprehensive tool",
            custom_field="custom_value",
        )
        def comprehensive_tool():
            pass

        metadata = comprehensive_tool._mesh_tool_metadata
        assert metadata["capability"] == "comprehensive"
        assert metadata["tags"] == ["test", "demo"]
        assert metadata["version"] == "3.2.1"
        assert len(metadata["dependencies"]) == 2
        assert metadata["dependencies"][0] == {
            "capability": "dep1",
            "tags": [],
            "version": None,
        }
        assert metadata["dependencies"][1] == {
            "capability": "dep2",
            "version": ">=2.0",
            "tags": [],
        }
        assert metadata["description"] == "Comprehensive tool"
        assert metadata["custom_field"] == "custom_value"

    def test_mesh_tool_no_environment_variable_support(self):
        """Test that mesh.tool is NOT affected by environment variables."""
        from unittest.mock import patch

        import mesh

        # Set environment variables that should NOT affect mesh.tool
        with patch.dict(
            "os.environ",
            {
                "MCP_MESH_HTTP_HOST": "should_be_ignored.com",
                "MCP_MESH_HTTP_PORT": "9999",
                "MCP_MESH_HEALTH_INTERVAL": "60",
            },
        ):

            @mesh.tool(
                capability="test_tool",
                tags=["demo"],
                version="1.5.0",
                description="Test tool",
            )
            def environment_test_tool():
                pass

            metadata = environment_test_tool._mesh_tool_metadata

            # Verify mesh.tool parameters are exactly as specified in decorator
            assert metadata["capability"] == "test_tool"
            assert metadata["tags"] == ["demo"]
            assert metadata["version"] == "1.5.0"
            assert metadata["description"] == "Test tool"

            # Verify no environment variable fields leaked in
            assert "http_host" not in metadata
            assert "http_port" not in metadata
            assert "health_interval" not in metadata

    def test_mesh_tool_preserves_function_attributes(self):
        """Test that mesh.tool preserves function attributes."""
        import mesh

        def original_function(x: int, y: int) -> int:
            """Adds two numbers."""
            return x + y

        decorated = mesh.tool(capability="math")(original_function)

        assert decorated.__name__ == "original_function"
        assert decorated.__doc__ == "Adds two numbers."
        assert decorated(5, 3) == 8


class TestMeshAgentDecorator:
    """Test cases for the @mesh.agent decorator (new agent-level decorator)."""

    def test_basic_mesh_agent_usage(self):
        """Test basic mesh.agent decorator usage with mandatory name."""
        import mesh

        @mesh.agent(name="test-agent", auto_run=False)
        class TestAgent:
            pass

        # Should have agent metadata
        assert hasattr(TestAgent, "_mesh_agent_metadata")
        metadata = TestAgent._mesh_agent_metadata

        assert metadata["name"] == "test-agent"
        assert metadata["version"] == "1.0.0"  # default
        assert metadata["description"] is None  # default
        assert metadata["http_host"] == "0.0.0.0"  # default
        assert metadata["http_port"] == 0  # default
        assert metadata["enable_http"] == True  # default
        assert metadata["namespace"] == "default"  # default
        assert metadata["health_interval"] == 30  # default

    def test_mesh_agent_name_is_mandatory(self):
        """Test that name is mandatory for mesh.agent."""
        import mesh

        # Missing name should raise error
        with pytest.raises(ValueError, match="name is required"):

            @mesh.agent()
            class NoNameAgent:
                pass

        # Invalid name type
        with pytest.raises(ValueError, match="name must be a string"):

            @mesh.agent(name=123)
            class InvalidNameAgent:
                pass

    def test_mesh_agent_all_optional_parameters(self):
        """Test mesh.agent with all optional parameters."""
        import mesh

        @mesh.agent(
            name="full-agent",
            version="2.0.0",
            description="Full featured agent",
            http_host="127.0.0.1",
            http_port=8080,
            enable_http=True,
            namespace="production",
            health_interval=60,
            auto_run=False,
            custom_field="custom_value",
        )
        class FullAgent:
            pass

        metadata = FullAgent._mesh_agent_metadata
        assert metadata["name"] == "full-agent"
        assert metadata["version"] == "2.0.0"
        assert metadata["description"] == "Full featured agent"
        assert metadata["http_host"] == "127.0.0.1"
        assert metadata["http_port"] == 8080
        assert metadata["enable_http"] == True
        assert metadata["namespace"] == "production"
        assert metadata["health_interval"] == 60
        assert metadata["custom_field"] == "custom_value"


class TestMeshAgentHttpEndpointBehavior:
    """Test cases for understanding HTTP endpoint configuration behavior."""

    def test_pod_ip_environment_variable_effect(self):
        """Test that POD_IP environment variable affects endpoint construction."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {
                "POD_IP": "10.244.1.5",
                "MCP_MESH_HTTP_HOST": "0.0.0.0",
                "MCP_MESH_HTTP_PORT": "8080",
            },
        ):

            @mesh.agent(name="pod-ip-agent", auto_run=False)
            class PodIpAgent:
                pass

            metadata = PodIpAgent._mesh_agent_metadata
            # Check that the host is still what we configured
            assert metadata["http_host"] == "0.0.0.0"
            assert metadata["http_port"] == 8080

    def test_mcp_mesh_http_host_service_name(self):
        """Test setting MCP_MESH_HTTP_HOST to a service name."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {"MCP_MESH_HTTP_HOST": "hello-world-agent", "MCP_MESH_HTTP_PORT": "8080"},
        ):

            @mesh.agent(name="service-name-agent", auto_run=False)
            class ServiceNameAgent:
                pass

            metadata = ServiceNameAgent._mesh_agent_metadata
            # The configured host should be the service name
            assert metadata["http_host"] == "hello-world-agent"
            assert metadata["http_port"] == 8080

    def test_docker_network_ip_as_pod_ip(self):
        """Test using a Docker network IP as POD_IP."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {
                "POD_IP": "172.18.0.3",
                "MCP_MESH_HTTP_HOST": "0.0.0.0",
                "MCP_MESH_HTTP_PORT": "8080",
            },
        ):

            @mesh.agent(name="docker-ip-agent", auto_run=False)
            class DockerIpAgent:
                pass

            metadata = DockerIpAgent._mesh_agent_metadata
            # Server should bind to 0.0.0.0 but POD_IP should be available for endpoint resolution
            assert metadata["http_host"] == "0.0.0.0"
            assert metadata["http_port"] == 8080

    def test_kubernetes_service_host_detection(self):
        """Test Kubernetes environment detection."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {
                "KUBERNETES_SERVICE_HOST": "kubernetes",
                "MCP_MESH_HTTP_HOST": "0.0.0.0",
                "MCP_MESH_HTTP_PORT": "8080",
            },
        ):

            @mesh.agent(name="k8s-agent", auto_run=False)
            class K8sAgent:
                pass

            metadata = K8sAgent._mesh_agent_metadata
            # Should still bind to configured host
            assert metadata["http_host"] == "0.0.0.0"
            assert metadata["http_port"] == 8080

    def test_combined_docker_environment_variables(self):
        """Test the combination of environment variables we use in Docker."""
        from unittest.mock import patch

        import mesh

        docker_env = {
            "MCP_MESH_HTTP_HOST": "0.0.0.0",
            "MCP_MESH_HTTP_PORT": "8080",
            "POD_IP": "hello-world-agent",  # Using service name as POD_IP
            "MCP_MESH_REGISTRY_URL": "http://registry:8000",
            "MCP_MESH_AGENT_NAME": "hello-world",
            "MCP_MESH_NAMESPACE": "default",
        }

        with patch.dict("os.environ", docker_env):

            @mesh.agent(name="docker-agent", auto_run=False)
            class DockerAgent:
                pass

            metadata = DockerAgent._mesh_agent_metadata
            # Verify all configurations are applied correctly
            assert metadata["http_host"] == "0.0.0.0"
            assert metadata["http_port"] == 8080
            assert metadata["namespace"] == "default"

    def test_http_wrapper_endpoint_with_pod_ip(self):
        """Test that HTTP wrapper uses POD_IP for endpoint construction."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {
                "POD_IP": "10.244.1.5",
                "MCP_MESH_HTTP_HOST": "0.0.0.0",
                "MCP_MESH_HTTP_PORT": "8080",
            },
        ):

            @mesh.agent(name="endpoint-test-agent", enable_http=True, auto_run=False)
            class EndpointTestAgent:
                @mesh.tool()
                def test_tool(self):
                    return "test response"

            # This test verifies that the decorator properly configures the agent
            metadata = EndpointTestAgent._mesh_agent_metadata
            assert metadata["http_host"] == "0.0.0.0"
            assert metadata["http_port"] == 8080
            assert metadata["enable_http"] == True

    def test_static_ip_as_pod_ip(self):
        """Test using a static IP as POD_IP like Docker networks."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {
                "POD_IP": "172.18.0.10",
                "MCP_MESH_HTTP_HOST": "0.0.0.0",
                "MCP_MESH_HTTP_PORT": "8080",
            },
        ):

            @mesh.agent(name="static-ip-agent", enable_http=True, auto_run=False)
            class StaticIpAgent:
                @mesh.tool()
                def get_info(self):
                    return "agent info"

            metadata = StaticIpAgent._mesh_agent_metadata
            # Decorator should still use the configured values
            assert metadata["http_host"] == "0.0.0.0"  # Server binding
            assert metadata["http_port"] == 8080
            # POD_IP should be available for endpoint resolution (tested in http_wrapper)

    def test_service_name_as_http_host_binding(self):
        """Test what happens when HTTP_HOST is set to service name."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {"MCP_MESH_HTTP_HOST": "my-service-name", "MCP_MESH_HTTP_PORT": "8080"},
        ):

            @mesh.agent(name="service-host-agent", enable_http=True, auto_run=False)
            class ServiceHostAgent:
                @mesh.tool()
                def service_tool(self):
                    return "service response"

            metadata = ServiceHostAgent._mesh_agent_metadata
            # When HTTP_HOST is set to service name, that's what the server will try to bind to
            assert metadata["http_host"] == "my-service-name"
            assert metadata["http_port"] == 8080

    def test_mesh_agent_parameter_validation(self):
        """Test mesh.agent parameter validation."""
        import mesh

        # Invalid version type
        with pytest.raises(ValueError, match="version must be a string"):

            @mesh.agent(name="test", version=2.0)
            class InvalidVersionAgent:
                pass

        # Invalid http_port range
        with pytest.raises(ValueError, match="http_port must be between 0 and 65535"):

            @mesh.agent(name="test", http_port=70000)
            class InvalidPortAgent:
                pass

        # Invalid health_interval type
        with pytest.raises(ValueError, match="health_interval must be an integer"):

            @mesh.agent(name="test", health_interval="30")
            class InvalidHealthAgent:
                pass

        # Invalid enable_http type
        with pytest.raises(ValueError, match="enable_http must be a boolean"):

            @mesh.agent(name="test", enable_http="true")
            class InvalidEnableHttpAgent:
                pass

        # Invalid namespace type
        with pytest.raises(ValueError, match="namespace must be a string"):

            @mesh.agent(name="test", namespace=123)
            class InvalidNamespaceAgent:
                pass

    def test_mesh_agent_works_with_functions(self):
        """Test that mesh.agent can also be applied to functions."""
        import mesh

        @mesh.agent(name="function-agent", auto_run=False)
        def agent_function():
            return "agent function"

        assert hasattr(agent_function, "_mesh_agent_metadata")
        assert agent_function._mesh_agent_metadata["name"] == "function-agent"
        assert agent_function() == "agent function"


class TestMeshAgentIDGeneration:
    """Test agent ID generation functionality in mesh.agent decorator."""

    def test_agent_id_format_with_env_var(self):
        """Test agent ID format when MCP_MESH_AGENT_NAME is set."""
        from unittest.mock import patch

        from mesh.decorators import _get_or_create_agent_id

        with patch.dict("os.environ", {"MCP_MESH_AGENT_NAME": "myservice"}):
            # Reset global to test
            import mesh.decorators

            mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id()

            # Should be format: myservice-{8chars}
            assert agent_id.startswith("myservice-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_format_without_env_var(self):
        """Test agent ID format when no env var is set."""
        from unittest.mock import patch

        from mesh.decorators import _get_or_create_agent_id

        with patch.dict("os.environ", {}, clear=True):
            # Reset global to test
            import mesh.decorators

            mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id()

            # Should be format: agent-{8chars}
            assert agent_id.startswith("agent-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_format_with_decorator_name_only(self):
        """Test agent ID format when only decorator name is provided."""
        from unittest.mock import patch

        from mesh.decorators import _get_or_create_agent_id

        with patch.dict("os.environ", {}, clear=True):
            # Reset global to test
            import mesh.decorators

            mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id(agent_name="myagent")

            # Should be format: myagent-{8chars}
            assert agent_id.startswith("myagent-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_env_var_takes_precedence_over_decorator_name(self):
        """Test that env var takes precedence over decorator name."""
        from unittest.mock import patch

        from mesh.decorators import _get_or_create_agent_id

        with patch.dict("os.environ", {"MCP_MESH_AGENT_NAME": "envservice"}):
            # Reset global to test
            import mesh.decorators

            mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id(agent_name="decoratorname")

            # Should use env var, not decorator name
            assert agent_id.startswith("envservice-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_fallback_to_default_when_neither_provided(self):
        """Test fallback to 'agent' when neither env var nor decorator name provided."""
        from unittest.mock import patch

        from mesh.decorators import _get_or_create_agent_id

        with patch.dict("os.environ", {}, clear=True):
            # Reset global to test
            import mesh.decorators

            mesh.decorators._SHARED_AGENT_ID = None

            agent_id = _get_or_create_agent_id(agent_name=None)

            # Should fallback to default "agent"
            assert agent_id.startswith("agent-")
            assert len(agent_id.split("-")[-1]) == 8

    def test_agent_id_is_shared_across_functions(self):
        """Test that all functions in a process share the same agent ID."""
        # Reset for clean test
        import mesh.decorators
        from mesh.decorators import _get_or_create_agent_id

        mesh.decorators._SHARED_AGENT_ID = None

        id1 = _get_or_create_agent_id()
        id2 = _get_or_create_agent_id()
        id3 = _get_or_create_agent_id()

        assert id1 == id2 == id3


class TestMeshAgentEnvironmentVariables:
    """Test cases for mesh.agent environment variable support."""

    def test_http_host_environment_variable_precedence(self):
        """Test that MCP_MESH_HTTP_HOST environment variable takes precedence."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HTTP_HOST": "192.168.1.1"}):

            @mesh.agent(name="test-agent", http_host="127.0.0.1", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_host"] == "192.168.1.1"  # env var takes precedence

    def test_http_host_decorator_value_when_no_env_var(self):
        """Test that decorator value is used when no environment variable is set."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", http_host="10.0.0.1", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_host"] == "10.0.0.1"  # decorator value used

    def test_http_host_default_value_when_neither_provided(self):
        """Test that default value is used when neither env var nor decorator value provided."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_host"] == "0.0.0.0"  # default value

    def test_http_port_environment_variable_precedence(self):
        """Test that MCP_MESH_HTTP_PORT environment variable takes precedence."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HTTP_PORT": "9090"}):

            @mesh.agent(name="test-agent", http_port=8080, auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_port"] == 9090  # env var takes precedence

    def test_http_port_decorator_value_when_no_env_var(self):
        """Test that decorator value is used when no environment variable is set."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", http_port=3000, auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_port"] == 3000  # decorator value used

    def test_http_port_default_value_when_neither_provided(self):
        """Test that default value is used when neither env var nor decorator value provided."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_port"] == 0  # default value

    def test_health_interval_environment_variable_precedence(self):
        """Test that MCP_MESH_HEALTH_INTERVAL environment variable takes precedence."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HEALTH_INTERVAL": "60"}):

            @mesh.agent(name="test-agent", health_interval=45, auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["health_interval"] == 60  # env var takes precedence

    def test_health_interval_decorator_value_when_no_env_var(self):
        """Test that decorator value is used when no environment variable is set."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", health_interval=120, auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["health_interval"] == 120  # decorator value used

    def test_health_interval_default_value_when_neither_provided(self):
        """Test that default value is used when neither env var nor decorator value provided."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["health_interval"] == 30  # default value

    def test_multiple_environment_variables_together(self):
        """Test that multiple environment variables work together."""
        from unittest.mock import patch

        import mesh

        with patch.dict(
            "os.environ",
            {
                "MCP_MESH_HTTP_HOST": "example.com",
                "MCP_MESH_HTTP_PORT": "8888",
                "MCP_MESH_ENABLE_HTTP": "false",
                "MCP_MESH_NAMESPACE": "prod-env",
                "MCP_MESH_HEALTH_INTERVAL": "90",
            },
        ):

            @mesh.agent(
                name="test-agent",
                http_host="localhost",
                http_port=5000,
                enable_http=True,
                namespace="dev",
                health_interval=15,
                auto_run=False,
            )
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["http_host"] == "example.com"  # env var precedence
            assert metadata["http_port"] == 8888  # env var precedence
            assert metadata["enable_http"] == False  # env var precedence
            assert metadata["namespace"] == "prod-env"  # env var precedence
            assert metadata["health_interval"] == 90  # env var precedence

    def test_http_port_environment_variable_validation_range(self):
        """Test that http_port environment variable is validated for range."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HTTP_PORT": "70000"}):
            with pytest.raises(
                ValueError, match="http_port must be between 0 and 65535"
            ):

                @mesh.agent(name="test-agent", auto_run=False)
                class TestAgent:
                    pass

    def test_http_port_environment_variable_validation_type(self):
        """Test that http_port environment variable is validated for type."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HTTP_PORT": "not_a_number"}):
            with pytest.raises(
                ValueError,
                match="MCP_MESH_HTTP_PORT environment variable must be a valid integer",
            ):

                @mesh.agent(name="test-agent", auto_run=False)
                class TestAgent:
                    pass

    def test_health_interval_environment_variable_validation_minimum(self):
        """Test that health_interval environment variable is validated for minimum value."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HEALTH_INTERVAL": "0"}):
            with pytest.raises(
                ValueError, match="health_interval must be at least 1 second"
            ):

                @mesh.agent(name="test-agent", auto_run=False)
                class TestAgent:
                    pass

    def test_health_interval_environment_variable_validation_type(self):
        """Test that health_interval environment variable is validated for type."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_HEALTH_INTERVAL": "invalid"}):
            with pytest.raises(
                ValueError,
                match="MCP_MESH_HEALTH_INTERVAL environment variable must be a valid integer",
            ):

                @mesh.agent(name="test-agent", auto_run=False)
                class TestAgent:
                    pass

    def test_http_port_edge_cases(self):
        """Test http_port edge cases with environment variables."""
        from unittest.mock import patch

        import mesh

        # Test port 0 (valid)
        with patch.dict("os.environ", {"MCP_MESH_HTTP_PORT": "0"}):

            @mesh.agent(name="test-agent-0", auto_run=False)
            class TestAgent0:
                pass

            assert TestAgent0._mesh_agent_metadata["http_port"] == 0

        # Test port 65535 (valid)
        with patch.dict("os.environ", {"MCP_MESH_HTTP_PORT": "65535"}):

            @mesh.agent(name="test-agent-max", auto_run=False)
            class TestAgentMax:
                pass

            assert TestAgentMax._mesh_agent_metadata["http_port"] == 65535

    def test_health_interval_edge_cases(self):
        """Test health_interval edge cases with environment variables."""
        from unittest.mock import patch

        import mesh

        # Test minimum valid value (1)
        with patch.dict("os.environ", {"MCP_MESH_HEALTH_INTERVAL": "1"}):

            @mesh.agent(name="test-agent-min", auto_run=False)
            class TestAgentMin:
                pass

            assert TestAgentMin._mesh_agent_metadata["health_interval"] == 1

    def test_enable_http_environment_variable_precedence(self):
        """Test that MCP_MESH_ENABLE_HTTP environment variable takes precedence."""
        from unittest.mock import patch

        import mesh

        # Test true values
        for true_value in ["true", "1", "yes", "on", "TRUE", "True"]:
            with patch.dict("os.environ", {"MCP_MESH_ENABLE_HTTP": true_value}):

                @mesh.agent(
                    name=f"test-agent-{true_value}", enable_http=False, auto_run=False
                )
                class TestAgentTrue:
                    pass

                metadata = TestAgentTrue._mesh_agent_metadata
                assert metadata["enable_http"] == True  # env var takes precedence

        # Test false values
        for false_value in ["false", "0", "no", "off", "FALSE", "False"]:
            with patch.dict("os.environ", {"MCP_MESH_ENABLE_HTTP": false_value}):

                @mesh.agent(
                    name=f"test-agent-{false_value}", enable_http=True, auto_run=False
                )
                class TestAgentFalse:
                    pass

                metadata = TestAgentFalse._mesh_agent_metadata
                assert metadata["enable_http"] == False  # env var takes precedence

    def test_enable_http_decorator_value_when_no_env_var(self):
        """Test that decorator value is used when no environment variable is set."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent-true", enable_http=True, auto_run=False)
            class TestAgentTrue:
                pass

            @mesh.agent(name="test-agent-false", enable_http=False, auto_run=False)
            class TestAgentFalse:
                pass

            assert TestAgentTrue._mesh_agent_metadata["enable_http"] == True
            assert TestAgentFalse._mesh_agent_metadata["enable_http"] == False

    def test_enable_http_default_value(self):
        """Test that default value is True when neither env var nor decorator value provided."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["enable_http"] == True  # default value

    def test_enable_http_environment_variable_validation(self):
        """Test that enable_http environment variable is validated."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_ENABLE_HTTP": "invalid_value"}):
            with pytest.raises(
                ValueError,
                match="MCP_MESH_ENABLE_HTTP environment variable must be a boolean value",
            ):

                @mesh.agent(name="test-agent", auto_run=False)
                class TestAgent:
                    pass

    def test_namespace_environment_variable_precedence(self):
        """Test that MCP_MESH_NAMESPACE environment variable takes precedence."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {"MCP_MESH_NAMESPACE": "production-env"}):

            @mesh.agent(name="test-agent", namespace="development", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["namespace"] == "production-env"  # env var takes precedence

    def test_namespace_decorator_value_when_no_env_var(self):
        """Test that decorator value is used when no environment variable is set."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", namespace="custom-namespace", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["namespace"] == "custom-namespace"  # decorator value used

    def test_namespace_default_value(self):
        """Test that default value is 'default' when neither env var nor decorator value provided."""
        from unittest.mock import patch

        import mesh

        with patch.dict("os.environ", {}, clear=True):

            @mesh.agent(name="test-agent", auto_run=False)
            class TestAgent:
                pass

            metadata = TestAgent._mesh_agent_metadata
            assert metadata["namespace"] == "default"  # default value


class TestDualDecoratorIntegration:
    """Test cases for mesh.tool and mesh.agent working together."""

    def test_combined_usage_on_class(self):
        """Test using both decorators on the same class."""
        import mesh

        @mesh.agent(name="combined-agent", version="1.5.0", auto_run=False)
        class CombinedAgent:
            @mesh.tool(capability="test_capability")
            def test_method(self):
                return "test method"

        # Should have both metadata types
        assert hasattr(CombinedAgent, "_mesh_agent_metadata")
        assert hasattr(CombinedAgent.test_method, "_mesh_tool_metadata")

        # Check agent metadata
        agent_meta = CombinedAgent._mesh_agent_metadata
        assert agent_meta["name"] == "combined-agent"
        assert agent_meta["version"] == "1.5.0"

        # Check tool metadata
        tool_meta = CombinedAgent.test_method._mesh_tool_metadata
        assert tool_meta["capability"] == "test_capability"

        # Methods should still work
        instance = CombinedAgent()
        assert instance.test_method() == "test method"

    def test_multiple_tools_in_agent(self):
        """Test agent with multiple mesh.tool decorated methods."""
        import mesh

        @mesh.agent(name="multi-tool-agent", auto_run=False)
        class MultiToolAgent:
            @mesh.tool(capability="capability1", tags=["tag1"])
            def tool1(self):
                return "tool1"

            @mesh.tool(capability="capability2", tags=["tag2"])
            def tool2(self):
                return "tool2"

            def regular_method(self):
                return "regular"

        # Agent should have metadata
        assert hasattr(MultiToolAgent, "_mesh_agent_metadata")
        assert MultiToolAgent._mesh_agent_metadata["name"] == "multi-tool-agent"

        # Both tools should have metadata
        assert hasattr(MultiToolAgent.tool1, "_mesh_tool_metadata")
        assert hasattr(MultiToolAgent.tool2, "_mesh_tool_metadata")

        # Regular method should not have tool metadata
        assert not hasattr(MultiToolAgent.regular_method, "_mesh_tool_metadata")

        # Check tool metadata
        assert MultiToolAgent.tool1._mesh_tool_metadata["capability"] == "capability1"
        assert MultiToolAgent.tool2._mesh_tool_metadata["capability"] == "capability2"

    def test_standalone_tools_without_agent(self):
        """Test that mesh.tool can work without mesh.agent."""
        import mesh

        @mesh.tool(capability="standalone_capability")
        def standalone_tool():
            return "standalone"

        # Should have tool metadata but no agent metadata
        assert hasattr(standalone_tool, "_mesh_tool_metadata")
        assert not hasattr(standalone_tool, "_mesh_agent_metadata")

        assert (
            standalone_tool._mesh_tool_metadata["capability"] == "standalone_capability"
        )
        assert standalone_tool() == "standalone"

    def test_agent_discovery_of_tools(self):
        """Test that processor can discover tools within an agent."""
        import mesh

        @mesh.agent(name="discoverable-agent", auto_run=False)
        class DiscoverableAgent:
            @mesh.tool(capability="discover_me", tags=["discoverable"])
            def discoverable_tool(self):
                return "discovered"

            @mesh.tool(capability="discover_me_too")
            def another_tool(self):
                return "also discovered"

            def not_a_tool(self):
                return "not discoverable"

        # Should be able to find all tools in the agent
        tools = []
        for attr_name in dir(DiscoverableAgent):
            attr = getattr(DiscoverableAgent, attr_name)
            if hasattr(attr, "_mesh_tool_metadata"):
                tools.append(attr)

        assert len(tools) == 2
        capabilities = [tool._mesh_tool_metadata["capability"] for tool in tools]
        assert "discover_me" in capabilities
        assert "discover_me_too" in capabilities


class TestDecoratorRegistryCompatibility:
    """Test that DecoratorRegistry works with new decorators."""

    def test_decorator_registry_compatibility(self):
        """Test that DecoratorRegistry works with new decorators."""
        import mesh
        from mcp_mesh.decorator_registry import DecoratorRegistry

        # Clear registry
        DecoratorRegistry.clear_all()

        @mesh.tool(capability="registry_test")
        def test_tool():
            return "test"

        @mesh.agent(name="registry-agent", auto_run=False)
        class TestAgent:
            pass

        # Registry should have registered both
        tools = DecoratorRegistry.get_mesh_tools()
        agents = DecoratorRegistry.get_mesh_agents()

        assert len(tools) == 1
        assert len(agents) == 1
        assert "test_tool" in tools
        assert "TestAgent" in agents


class TestImportStructure:
    """Test the new import structure."""

    def test_mesh_module_structure(self):
        """Test that mesh module has correct structure."""
        import mesh

        # Should have both decorators
        assert hasattr(mesh, "tool")
        assert hasattr(mesh, "agent")

        # Should be callable
        assert callable(mesh.tool)
        assert callable(mesh.agent)

    def test_import_variants(self):
        """Test that only mesh.tool and mesh.agent patterns work."""

        # Module import (preferred pattern)
        import mesh

        assert callable(mesh.tool)
        assert callable(mesh.agent)

        # Aliased import (also supported)
        import mesh as m

        assert callable(m.tool)
        assert callable(m.agent)

    def test_mcp_mesh_compatibility(self):
        """Test that mcp_mesh still exports necessary components."""
        from mcp_mesh import DecoratedFunction, DecoratorRegistry

        # Should still be available for processor
        assert DecoratorRegistry is not None
        assert DecoratedFunction is not None
