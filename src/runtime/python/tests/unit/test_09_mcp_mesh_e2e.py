"""
End-to-end test for McpMeshAgent positional dependency injection with @mesh.tool and @mesh.agent.
"""

import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

import mesh
from mcp_mesh import DecoratorRegistry
from mcp_mesh.runtime.registry_client import RegistryClient
from mcp_mesh.types import McpMeshAgent


@pytest.fixture(autouse=True)
def disable_background_services():
    """Disable background services for all tests in this module."""
    with patch.dict(
        os.environ, {"MCP_MESH_AUTO_RUN": "false", "MCP_MESH_ENABLE_HTTP": "false"}
    ):
        yield


class TestMcpMeshAgentE2E:
    """End-to-end test for McpMeshAgent positional dependency injection."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        client = Mock(spec=RegistryClient)
        return client

    @pytest.fixture
    def sample_registry_response(self):
        """Sample registry response with dependencies_resolved."""
        return {
            "status": "success",
            "agent_id": "test-agent-123",
            "dependencies_resolved": {
                "time_greet": [
                    {
                        "agent_id": "date-provider-123",
                        "function_name": "get_current_date",  # ← Actual function to call
                        "endpoint": "http://date-service:8080",
                        "capability": "advanced_date_service",  # ← Capability name (can be different!)
                        "status": "available",
                    }
                ],
                "weather_greet": [
                    {
                        "agent_id": "date-provider-123",
                        "function_name": "get_current_date",  # ← Actual function to call
                        "endpoint": "http://date-service:8080",
                        "capability": "advanced_date_service",  # ← Capability name for matching
                        "status": "available",
                    },
                    {
                        "agent_id": "weather-provider-456",
                        "function_name": "fetch_weather_data",  # ← Actual function to call
                        "endpoint": "http://weather-service:8080",
                        "capability": "premium_weather_service",  # ← Capability name for matching
                        "status": "available",
                    },
                ],
            },
        }

    @pytest.mark.asyncio
    async def test_mesh_tool_with_mcp_mesh_agent_injection(
        self, mock_registry_client, sample_registry_response
    ):
        """Test complete @mesh.tool workflow with McpMeshAgent dependency injection."""

        # Clear any existing decorators
        DecoratorRegistry.clear_all()

        # Define test functions using the decorators
        @mesh.agent(name="greeting-agent", version="1.0.0")
        class GreetingAgent:
            pass

        @mesh.tool(
            capability="time_greeting",
            dependencies=[{"capability": "advanced_date_service"}],
        )
        def time_greet(name: str, date_getter: McpMeshAgent) -> str:
            """Greet someone with the current date."""
            # date_getter proxy is bound to actual function "get_current_date"
            # but dependency matches capability "advanced_date_service"
            current_date = date_getter()
            return f"Hello {name}, today is {current_date}"

        @mesh.tool(
            capability="weather_greeting",
            dependencies=[
                {"capability": "advanced_date_service"},  # Custom capability name
                {"capability": "premium_weather_service"},  # Custom capability name
            ],
        )
        def weather_greet(
            name: str, date_getter: McpMeshAgent, weather_getter: McpMeshAgent
        ) -> str:
            """Greet someone with date and weather."""
            # date_getter calls actual function "get_current_date"
            # weather_getter calls actual function "fetch_weather_data"
            current_date = date_getter()
            current_weather = weather_getter()
            return f"Hello {name}, today is {current_date} and it's {current_weather}"

        # Verify decorators were registered
        mesh_tools = DecoratorRegistry.get_mesh_tools()
        mesh_agents = DecoratorRegistry.get_mesh_agents()

        assert len(mesh_tools) == 2
        assert "time_greet" in mesh_tools
        assert "weather_greet" in mesh_tools
        assert len(mesh_agents) == 1

        # Mock the registry registration call
        mock_registry_client.post = AsyncMock()

        async def mock_post_response(endpoint, json=None):
            response_mock = Mock()
            response_mock.status = 201
            response_mock.json = AsyncMock(return_value=sample_registry_response)
            return response_mock

        mock_registry_client.post.side_effect = mock_post_response

        # Create processor and process tools
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor("http://localhost:8080")
        processor.registry_client = mock_registry_client
        processor.mesh_tool_processor.registry_client = mock_registry_client

        # Mock HTTP proxy creation to return single-function bound proxies
        async def mock_create_http_proxy(dep_name, dep_info):
            function_name = dep_info.get("function_name", "unknown")
            capability = dep_info.get("capability", "unknown")
            mock_proxy = Mock()

            # Bind proxy to actual function name (not capability name)
            if function_name == "get_current_date":
                mock_proxy.return_value = "2023-12-25"  # Calls get_current_date
                mock_proxy.invoke.return_value = "2023-12-25"
            elif (
                function_name == "fetch_weather_data"
            ):  # Different from capability name!
                mock_proxy.return_value = "sunny"  # Calls fetch_weather_data
                mock_proxy.invoke.return_value = "sunny"
            else:
                mock_proxy.return_value = f"unknown_function({function_name})"

            print(
                f"🔧 Created HTTP proxy: capability='{capability}' → function='{function_name}'"
            )
            return mock_proxy

        processor.mesh_tool_processor._create_http_proxy_for_tool = (
            mock_create_http_proxy
        )

        def mock_create_stdio_proxy(dep_name, dep_info):
            function_name = dep_info.get("function_name", "unknown")
            capability = dep_info.get("capability", "unknown")
            mock_proxy = Mock()

            # Bind proxy to actual function name (not capability name)
            if function_name == "get_current_date":
                mock_proxy.return_value = "2023-12-25"  # Calls get_current_date
                mock_proxy.invoke.return_value = "2023-12-25"
            elif (
                function_name == "fetch_weather_data"
            ):  # Different from capability name!
                mock_proxy.return_value = "sunny"  # Calls fetch_weather_data
                mock_proxy.invoke.return_value = "sunny"
            else:
                mock_proxy.return_value = f"unknown_function({function_name})"

            print(
                f"🔧 Created stdio proxy: capability='{capability}' → function='{function_name}'"
            )
            return mock_proxy

        processor.mesh_tool_processor._create_stdio_proxy_for_tool = (
            mock_create_stdio_proxy
        )

        # Process the tools
        await processor.process_all_decorators()

        # Wait for asynchronous heartbeat to complete
        import asyncio

        await asyncio.sleep(0.1)

        # Verify registry was called (heartbeat, not registration)
        mock_registry_client.post.assert_called_once()
        call_args = mock_registry_client.post.call_args
        assert (
            call_args[0][0] == "/heartbeat"
        )  # endpoint (registration now via heartbeat)

        # Verify the heartbeat payload (same format as registration)
        registration_data = call_args[1]["json"]
        assert registration_data["agent_id"]
        assert len(registration_data["tools"]) == 2

        # Find the tools in the registration
        tools_by_name = {
            tool["function_name"]: tool for tool in registration_data["tools"]
        }

        time_greet_tool = tools_by_name["time_greet"]
        assert time_greet_tool["capability"] == "time_greeting"
        assert len(time_greet_tool["dependencies"]) == 1
        assert (
            time_greet_tool["dependencies"][0]["capability"] == "advanced_date_service"
        )  # Custom capability name

        weather_greet_tool = tools_by_name["weather_greet"]
        assert weather_greet_tool["capability"] == "weather_greeting"
        assert len(weather_greet_tool["dependencies"]) == 2
        dep_capabilities = [
            dep["capability"] for dep in weather_greet_tool["dependencies"]
        ]
        assert "advanced_date_service" in dep_capabilities  # Custom capability names
        assert "premium_weather_service" in dep_capabilities

        # Test that the functions now have dependency injection
        decorated_time_greet = mesh_tools["time_greet"]
        decorated_weather_greet = mesh_tools["weather_greet"]

        # Verify functions are enhanced with dependency injection
        assert hasattr(decorated_time_greet.function, "_mesh_processor_enhanced")
        assert hasattr(decorated_weather_greet.function, "_mesh_processor_enhanced")

        # Test calling the enhanced functions
        result1 = decorated_time_greet.function("Alice")
        assert result1 == "Hello Alice, today is 2023-12-25"

        result2 = decorated_weather_greet.function("Bob")
        assert result2 == "Hello Bob, today is 2023-12-25 and it's sunny"

    @pytest.mark.asyncio
    async def test_mesh_tool_with_optional_parameters(
        self, mock_registry_client, sample_registry_response
    ):
        """Test @mesh.tool with McpMeshAgent injection and optional parameters."""

        # Clear any existing decorators
        DecoratorRegistry.clear_all()

        @mesh.tool(
            capability="flexible_greeting",
            dependencies=[{"capability": "simple_date_service"}],
        )
        def flexible_greet(
            name: str, date_getter: McpMeshAgent, age: int = 30, greeting: str = "Hello"
        ) -> str:
            """Greet someone with flexible parameters."""
            current_date = date_getter()  # Single-function proxy call
            return f"{greeting} {name}, you are {age} years old and today is {current_date}"

        # Mock the registry client
        mock_registry_client.post = AsyncMock()

        async def mock_post_response(endpoint, json=None):
            response_mock = Mock()
            response_mock.status = 201
            response_mock.json = AsyncMock(
                return_value={
                    "status": "success",
                    "agent_id": "test-agent-123",
                    "dependencies_resolved": {
                        "flexible_greet": [
                            {
                                "agent_id": "date-provider-123",
                                "function_name": "get_current_date",  # Actual function
                                "endpoint": "http://date-service:8080",
                                "capability": "simple_date_service",  # Custom capability name
                                "status": "available",
                            }
                        ]
                    },
                }
            )
            return response_mock

        mock_registry_client.post.side_effect = mock_post_response

        # Create processor
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor("http://localhost:8080")
        processor.registry_client = mock_registry_client
        processor.mesh_tool_processor.registry_client = mock_registry_client

        # Mock proxy creation to return single-function bound proxies
        def mock_create_stdio_proxy(dep_name, dep_info):
            function_name = dep_info.get("function_name", "unknown")
            mock_proxy = Mock()
            if function_name == "get_current_date":
                mock_proxy.return_value = "2023-12-25"
                mock_proxy.invoke.return_value = "2023-12-25"
            return mock_proxy

        async def mock_create_http_proxy(dep_name, dep_info):
            function_name = dep_info.get("function_name", "unknown")
            mock_proxy = Mock()
            if function_name == "get_current_date":
                mock_proxy.return_value = "2023-12-25"
                mock_proxy.invoke.return_value = "2023-12-25"
            return mock_proxy

        processor.mesh_tool_processor._create_stdio_proxy_for_tool = (
            mock_create_stdio_proxy
        )
        processor.mesh_tool_processor._create_http_proxy_for_tool = (
            mock_create_http_proxy
        )

        # Process the tools
        await processor.process_all_decorators()

        # Wait for asynchronous heartbeat to complete
        import asyncio

        await asyncio.sleep(0.1)

        # Test the enhanced function with different argument patterns
        mesh_tools = DecoratorRegistry.get_mesh_tools()
        decorated_func = mesh_tools["flexible_greet"]

        # Test with minimal arguments (using defaults)
        result1 = decorated_func.function("Charlie")
        assert result1 == "Hello Charlie, you are 30 years old and today is 2023-12-25"

        # Test with custom age (using keyword arguments to avoid positional conflicts with McpMeshAgent)
        result2 = decorated_func.function("Diana", age=25)
        assert result2 == "Hello Diana, you are 25 years old and today is 2023-12-25"

        # Test with custom greeting (using keyword arguments)
        result3 = decorated_func.function("Eve", age=28, greeting="Hi")
        assert result3 == "Hi Eve, you are 28 years old and today is 2023-12-25"

    def test_mcp_mesh_agent_type_validation(self):
        """Test that McpMeshAgent type validation works correctly."""
        from mcp_mesh.runtime.signature_analyzer import validate_mesh_dependencies

        def valid_func(
            name: str, date_svc: McpMeshAgent, weather_svc: McpMeshAgent
        ) -> str:
            return f"Hello {name}"

        def invalid_func(name: str, date_svc: McpMeshAgent) -> str:
            return f"Hello {name}"

        # Valid case: 2 dependencies, 2 McpMeshAgent parameters
        is_valid, error = validate_mesh_dependencies(
            valid_func,
            [{"capability": "date_service"}, {"capability": "weather_service"}],
        )
        assert is_valid
        assert error == ""

        # Invalid case: 2 dependencies, 1 McpMeshAgent parameter
        is_valid, error = validate_mesh_dependencies(
            invalid_func,
            [{"capability": "date_service"}, {"capability": "weather_service"}],
        )
        assert not is_valid
        assert "has 1 McpMeshAgent parameters but 2 dependencies" in error
