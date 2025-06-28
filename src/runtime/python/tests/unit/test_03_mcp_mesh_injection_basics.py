"""
Test for McpMeshAgent positional dependency injection.
"""

from unittest.mock import Mock

import pytest

from _mcp_mesh.engine.dependency_injector import DependencyInjector
from _mcp_mesh.engine.signature_analyzer import (
    get_mesh_agent_parameter_names,
    get_mesh_agent_positions,
    validate_mesh_dependencies,
)
from mesh.types import McpMeshAgent


class TestMcpMeshAgentInjection:
    """Test McpMeshAgent positional dependency injection."""

    def test_get_mesh_agent_positions_single_param(self):
        """Test finding McpMeshAgent parameter positions - single parameter."""

        def test_func(name: str, date_svc: McpMeshAgent) -> str:
            return f"Hello {name}"

        positions = get_mesh_agent_positions(test_func)
        assert positions == [1]  # Second parameter

    def test_get_mesh_agent_positions_multiple_params(self):
        """Test finding McpMeshAgent parameter positions - multiple parameters."""

        def test_func(
            name: str, date_svc: McpMeshAgent, weather_svc: McpMeshAgent, count: int
        ) -> str:
            return f"Hello {name}"

        positions = get_mesh_agent_positions(test_func)
        assert positions == [1, 2]  # Second and third parameters

    def test_get_mesh_agent_positions_no_params(self):
        """Test finding McpMeshAgent parameter positions - no McpMeshAgent parameters."""

        def test_func(name: str, count: int) -> str:
            return f"Hello {name}"

        positions = get_mesh_agent_positions(test_func)
        assert positions == []

    def test_get_mesh_agent_parameter_names(self):
        """Test getting McpMeshAgent parameter names."""

        def test_func(
            name: str, date_svc: McpMeshAgent, weather_svc: McpMeshAgent
        ) -> str:
            return f"Hello {name}"

        names = get_mesh_agent_parameter_names(test_func)
        assert names == ["date_svc", "weather_svc"]

    def test_validate_mesh_dependencies_valid(self):
        """Test validation - valid dependency count."""

        def test_func(
            name: str, date_svc: McpMeshAgent, weather_svc: McpMeshAgent
        ) -> str:
            return f"Hello {name}"

        dependencies = [
            {"capability": "date_service"},
            {"capability": "weather_service"},
        ]

        is_valid, error = validate_mesh_dependencies(test_func, dependencies)
        assert is_valid
        assert error == ""

    def test_validate_mesh_dependencies_invalid_count(self):
        """Test validation - invalid dependency count."""

        def test_func(name: str, date_svc: McpMeshAgent) -> str:
            return f"Hello {name}"

        dependencies = [
            {"capability": "date_service"},
            {"capability": "weather_service"},  # Too many
        ]

        is_valid, error = validate_mesh_dependencies(test_func, dependencies)
        assert not is_valid
        assert "has 1 McpMeshAgent parameters but 2 dependencies" in error

    @pytest.mark.asyncio
    async def test_dependency_injection_wrapper_single_param(self):
        """Test that dependency injection wrapper works with single McpMeshAgent parameter."""
        # Create a mock single-function proxy
        mock_proxy = Mock()
        mock_proxy.return_value = "2023-12-25"  # __call__ returns date

        # Create test function using new single-function proxy approach
        def greet_with_date(name: str, date_getter: McpMeshAgent) -> str:
            current_date = date_getter()  # Simple call, no function name needed
            return f"Hello {name}, today is {current_date}"

        # Set up injector
        injector = DependencyInjector()
        await injector.register_dependency(
            "get_current_date", mock_proxy
        )  # Function name as capability

        # Create wrapper
        wrapped_func = injector.create_injection_wrapper(
            greet_with_date, ["get_current_date"]
        )

        # Test the wrapped function
        result = wrapped_func("Alice")
        assert result == "Hello Alice, today is 2023-12-25"
        mock_proxy.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_dependency_injection_wrapper_multiple_params(self):
        """Test that dependency injection wrapper works with multiple McpMeshAgent parameters."""
        # Create mock single-function proxies
        mock_date_proxy = Mock()
        mock_date_proxy.return_value = "2023-12-25"  # get_current_date proxy

        mock_weather_proxy = Mock()
        mock_weather_proxy.return_value = "sunny"  # get_weather_info proxy

        # Create test function using function names as capabilities
        def greet_with_info(
            name: str, date_getter: McpMeshAgent, weather_getter: McpMeshAgent
        ) -> str:
            current_date = date_getter()  # Bound to get_current_date function
            current_weather = weather_getter()  # Bound to get_weather_info function
            return f"Hello {name}, today is {current_date} and it's {current_weather}"

        # Set up injector with function names as capabilities
        injector = DependencyInjector()
        await injector.register_dependency("get_current_date", mock_date_proxy)
        await injector.register_dependency("get_weather_info", mock_weather_proxy)

        # Create wrapper
        wrapped_func = injector.create_injection_wrapper(
            greet_with_info,
            ["get_current_date", "get_weather_info"],  # Function names as capabilities
        )

        # Test the wrapped function
        result = wrapped_func("Bob")
        assert result == "Hello Bob, today is 2023-12-25 and it's sunny"
        mock_date_proxy.assert_called_once_with()
        mock_weather_proxy.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_dependency_injection_wrapper_async_function(self):
        """Test that dependency injection wrapper works with async functions."""
        # Create a mock single-function proxy
        mock_proxy = Mock()
        mock_proxy.return_value = "2023-12-25"

        # Create async test function
        async def async_greet_with_date(name: str, date_getter: McpMeshAgent) -> str:
            current_date = date_getter()  # Simple call to bound function
            return f"Hello {name}, today is {current_date}"

        # Set up injector
        injector = DependencyInjector()
        await injector.register_dependency("get_current_date", mock_proxy)

        # Create wrapper
        wrapped_func = injector.create_injection_wrapper(
            async_greet_with_date, ["get_current_date"]
        )

        # Test the wrapped function
        result = await wrapped_func("Charlie")
        assert result == "Hello Charlie, today is 2023-12-25"
        mock_proxy.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_dependency_injection_wrapper_missing_dependency(self):
        """Test that dependency injection wrapper handles missing dependencies gracefully."""

        # Create test function
        def greet_with_date(name: str, date_svc: McpMeshAgent) -> str:
            if date_svc is None:
                return f"Hello {name}, date service unavailable"
            current_date = date_svc.get_date()
            return f"Hello {name}, today is {current_date}"

        # Set up injector (no dependencies registered)
        injector = DependencyInjector()

        # Create wrapper
        wrapped_func = injector.create_injection_wrapper(
            greet_with_date, ["date_service"]
        )

        # Test the wrapped function
        result = wrapped_func("David")
        assert result == "Hello David, date service unavailable"

    @pytest.mark.asyncio
    async def test_dependency_injection_wrapper_preserves_other_args(self):
        """Test that dependency injection wrapper preserves other arguments and kwargs."""
        # Create a mock dependency
        mock_proxy = Mock()
        mock_proxy.get_date.return_value = "2023-12-25"

        # Create test function with multiple args and kwargs
        def complex_greet(
            name: str, age: int, date_svc: McpMeshAgent, greeting: str = "Hello"
        ) -> str:
            current_date = date_svc.get_date()
            return f"{greeting} {name}, you are {age} years old and today is {current_date}"

        # Set up injector
        injector = DependencyInjector()
        await injector.register_dependency("date_service", mock_proxy)

        # Create wrapper
        wrapped_func = injector.create_injection_wrapper(
            complex_greet, ["date_service"]
        )

        # Test the wrapped function with positional args
        # Note: We need to provide all non-default args except the McpMeshAgent
        result = wrapped_func("Eve", 25)
        assert result == "Hello Eve, you are 25 years old and today is 2023-12-25"

        # Test the wrapped function with kwargs
        result = wrapped_func("Frank", 30, greeting="Hi")
        assert result == "Hi Frank, you are 30 years old and today is 2023-12-25"

    @pytest.mark.asyncio
    async def test_dependency_update_mechanism(self):
        """Test that dependency updates are reflected in wrapped functions."""
        # Create mock dependencies
        mock_proxy_v1 = Mock()
        mock_proxy_v1.get_date.return_value = "2023-12-25"

        mock_proxy_v2 = Mock()
        mock_proxy_v2.get_date.return_value = "2023-12-26"

        # Create test function
        def greet_with_date(name: str, date_svc: McpMeshAgent) -> str:
            current_date = date_svc.get_date()
            return f"Hello {name}, today is {current_date}"

        # Set up injector
        injector = DependencyInjector()
        await injector.register_dependency("date_service", mock_proxy_v1)

        # Create wrapper
        wrapped_func = injector.create_injection_wrapper(
            greet_with_date, ["date_service"]
        )

        # Test with first dependency version
        result = wrapped_func("Grace")
        assert result == "Hello Grace, today is 2023-12-25"

        # Update dependency
        await injector.register_dependency("date_service", mock_proxy_v2)

        # Test with updated dependency
        result = wrapped_func("Henry")
        assert result == "Hello Henry, today is 2023-12-26"

    def test_signature_analyzer_handles_no_type_hints(self):
        """Test that signature analyzer handles functions without type hints gracefully."""

        def test_func(name, date_svc):  # No type hints
            return f"Hello {name}"

        positions = get_mesh_agent_positions(test_func)
        assert positions == []  # Should return empty list

        names = get_mesh_agent_parameter_names(test_func)
        assert names == []  # Should return empty list

    def test_signature_analyzer_handles_partial_type_hints(self):
        """Test that signature analyzer handles partial type hints correctly."""

        def test_func(name: str, date_svc, weather_svc: McpMeshAgent):
            return f"Hello {name}"

        positions = get_mesh_agent_positions(test_func)
        assert positions == [2]  # Only the third parameter has McpMeshAgent type

        names = get_mesh_agent_parameter_names(test_func)
        assert names == ["weather_svc"]
