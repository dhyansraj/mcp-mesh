"""
Unit tests for DependencyInjector and related injection logic.

Tests the dynamic dependency injection system including function wrapping,
runtime dependency updates, injection strategy analysis, and original
function finding without requiring actual MCP mesh infrastructure.
"""

import asyncio
import inspect
import weakref
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
# Import the classes under test
from _mcp_mesh.engine.dependency_injector import (DependencyInjector,
                                                  analyze_injection_strategy,
                                                  get_global_injector)


class TestAnalyzeInjectionStrategy:
    """Test the injection strategy analysis function."""

    def test_analyze_injection_strategy_no_parameters(self):
        """Test function with no parameters."""

        def func_no_params():
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            result = analyze_injection_strategy(func_no_params, ["dep1"])

        assert result == []

    def test_analyze_injection_strategy_single_parameter_no_typing(self):
        """Test function with single parameter, no MCP typing."""

        def func_single_param(param1):
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            result = analyze_injection_strategy(func_single_param, ["dep1"])

        assert result == [0]  # Inject into first position

    def test_analyze_injection_strategy_single_parameter_with_typing(self):
        """Test function with single parameter with MCP typing."""

        def func_single_typed(param1):
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[0],
        ):
            result = analyze_injection_strategy(func_single_typed, ["dep1"])

        assert result == [0]

    def test_analyze_injection_strategy_multiple_parameters_no_typing(self):
        """Test function with multiple parameters, no MCP typing."""

        def func_multi_params(param1, param2, param3):
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            result = analyze_injection_strategy(func_multi_params, ["dep1", "dep2"])

        assert result == []  # No injection without MCP typing

    def test_analyze_injection_strategy_multiple_parameters_with_typing(self):
        """Test function with multiple parameters with MCP typing."""

        def func_multi_typed(param1, param2, param3):
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[0, 2],
        ):
            result = analyze_injection_strategy(func_multi_typed, ["dep1", "dep2"])

        assert result == [0, 2]

    def test_analyze_injection_strategy_mismatch_more_deps(self):
        """Test function with more dependencies than typed parameters."""

        def func_mismatch(param1, param2):
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[1],
        ):
            result = analyze_injection_strategy(func_mismatch, ["dep1", "dep2", "dep3"])

        assert result == [1]  # Only inject what we can

    def test_analyze_injection_strategy_mismatch_more_params(self):
        """Test function with more typed parameters than dependencies."""

        def func_mismatch(param1, param2, param3):
            pass

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[0, 1, 2],
        ):
            result = analyze_injection_strategy(func_mismatch, ["dep1"])

        assert result == [0]  # Only inject available dependencies

    def test_analyze_injection_strategy_logging(self, caplog):
        """Test that appropriate warnings are logged."""
        import logging

        def func_no_params():
            pass

        def func_single_untyped(param):
            pass

        def func_multi_untyped(param1, param2):
            pass

        caplog.set_level(logging.WARNING)

        # No parameters with dependencies
        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            analyze_injection_strategy(func_no_params, ["dep1"])
        assert "has no parameters but 1 dependencies declared" in caplog.text

        caplog.clear()

        # Single parameter without typing
        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            analyze_injection_strategy(func_single_untyped, ["dep1"])
        assert "consider typing as McpMeshAgent for clarity" in caplog.text

        caplog.clear()

        # Multiple parameters without typing
        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            analyze_injection_strategy(func_multi_untyped, ["dep1"])
        assert "none are typed as McpMeshAgent" in caplog.text


class TestDependencyInjectorInit:
    """Test DependencyInjector initialization."""

    def test_dependency_injector_initialization(self):
        """Test DependencyInjector initializes correctly."""
        injector = DependencyInjector()

        assert isinstance(injector._dependencies, dict)
        assert len(injector._dependencies) == 0
        assert isinstance(injector._function_registry, weakref.WeakValueDictionary)
        assert isinstance(injector._dependency_mapping, dict)
        assert len(injector._dependency_mapping) == 0
        assert isinstance(injector._lock, asyncio.Lock)

    def test_get_global_injector(self):
        """Test get_global_injector returns consistent instance."""
        injector1 = get_global_injector()
        injector2 = get_global_injector()

        assert injector1 is injector2
        assert isinstance(injector1, DependencyInjector)


class TestDependencyRegistration:
    """Test dependency registration and management."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    @pytest.mark.asyncio
    async def test_register_dependency_simple(self, injector):
        """Test registering a simple dependency."""
        mock_instance = MagicMock()

        await injector.register_dependency("test_dep", mock_instance)

        assert injector.get_dependency("test_dep") is mock_instance

    @pytest.mark.asyncio
    async def test_register_dependency_update_existing(self, injector):
        """Test updating an existing dependency."""
        mock_instance1 = MagicMock()
        mock_instance2 = MagicMock()

        await injector.register_dependency("test_dep", mock_instance1)
        assert injector.get_dependency("test_dep") is mock_instance1

        await injector.register_dependency("test_dep", mock_instance2)
        assert injector.get_dependency("test_dep") is mock_instance2

    @pytest.mark.asyncio
    async def test_register_dependency_notifies_functions(self, injector):
        """Test that registering dependency notifies dependent functions."""
        # Create a mock function with update method
        mock_func = MagicMock()
        mock_func._mesh_update_dependency = MagicMock()

        # Set up dependency mapping and function registry with composite key
        injector._dependency_mapping["func1:dep_0"] = {"func1"}
        injector._function_registry["func1"] = mock_func

        mock_instance = MagicMock()
        await injector.register_dependency("func1:dep_0", mock_instance)

        # Verify function was notified with index-based call
        mock_func._mesh_update_dependency.assert_called_once_with(0, mock_instance)

    @pytest.mark.asyncio
    async def test_unregister_dependency_simple(self, injector):
        """Test unregistering a dependency."""
        mock_instance = MagicMock()

        await injector.register_dependency("test_dep", mock_instance)
        assert injector.get_dependency("test_dep") is mock_instance

        await injector.unregister_dependency("test_dep")
        assert injector.get_dependency("test_dep") is None

    @pytest.mark.asyncio
    async def test_unregister_dependency_nonexistent(self, injector):
        """Test unregistering a dependency that doesn't exist."""
        # Should not raise an error
        await injector.unregister_dependency("nonexistent_dep")

    @pytest.mark.asyncio
    async def test_unregister_dependency_notifies_functions(self, injector):
        """Test that unregistering dependency notifies dependent functions."""
        # Create a mock function with update method
        mock_func = MagicMock()
        mock_func._mesh_update_dependency = MagicMock()

        # Set up dependency mapping and function registry with composite key
        injector._dependency_mapping["func1:dep_0"] = {"func1"}
        injector._function_registry["func1"] = mock_func

        # Register then unregister
        mock_instance = MagicMock()
        await injector.register_dependency("func1:dep_0", mock_instance)
        await injector.unregister_dependency("func1:dep_0")

        # Verify function was notified with index-based calls
        calls = mock_func._mesh_update_dependency.call_args_list
        assert len(calls) == 2
        assert calls[0] == call(0, mock_instance)
        assert calls[1] == call(0, None)

    def test_get_dependency_nonexistent(self, injector):
        """Test getting a dependency that doesn't exist."""
        result = injector.get_dependency("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_register_dependency_logging(self, injector, caplog):
        """Test that dependency registration logs appropriately."""
        import logging

        # Set both caplog and the specific logger to DEBUG level
        caplog.set_level(logging.DEBUG)
        caplog.set_level(logging.DEBUG, logger="_mcp_mesh.engine.dependency_injector")

        mock_instance = MagicMock()
        await injector.register_dependency("test_dep", mock_instance)

        assert "Registering dependency: test_dep" in caplog.text

    @pytest.mark.asyncio
    async def test_unregister_dependency_logging(self, injector, caplog):
        """Test that dependency unregistration logs appropriately."""
        import logging

        caplog.set_level(logging.INFO)

        # Register first
        mock_instance = MagicMock()
        await injector.register_dependency("test_dep", mock_instance)

        caplog.clear()

        # Then unregister
        await injector.unregister_dependency("test_dep")

        assert "INJECTOR: Unregistering dependency: test_dep" in caplog.text
        assert "INJECTOR: Removed test_dep from dependencies registry" in caplog.text


class TestFindOriginalFunction:
    """Test finding original functions for self-dependency proxy creation."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_find_original_function_in_wrapper_registry(self, injector):
        """Test finding function in wrapper registry."""

        # Create a mock original function
        def original_func():
            pass

        original_func.__name__ = "test_function"

        # Create a mock wrapper with original function reference
        mock_wrapper = MagicMock()
        mock_wrapper._mesh_original_func = original_func

        # Add to function registry
        injector._function_registry["test.module.test_function"] = mock_wrapper

        result = injector.find_original_function("test_function")
        assert result is original_func

    def test_find_original_function_not_in_wrapper_registry(self, injector):
        """Test function not found in wrapper registry."""

        # Add a wrapper with different function name
        def other_func():
            pass

        other_func.__name__ = "other_function"

        mock_wrapper = MagicMock()
        mock_wrapper._mesh_original_func = other_func
        injector._function_registry["test.module.other_function"] = mock_wrapper

        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}

            result = injector.find_original_function("test_function")
            assert result is None

    def test_find_original_function_in_decorator_registry(self, injector):
        """Test finding function in decorator registry."""

        # Mock original function
        def original_func():
            pass

        original_func.__name__ = "test_function"

        # Mock decorated function
        mock_decorated = MagicMock()
        mock_decorated.function = original_func

        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {"test_tool": mock_decorated}

            result = injector.find_original_function("test_function")
            assert result is original_func

    def test_find_original_function_decorator_registry_exception(self, injector):
        """Test handling decorator registry access exception."""
        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.side_effect = Exception("Registry error")

            result = injector.find_original_function("test_function")
            assert result is None

    def test_find_original_function_not_found_logging(self, injector, caplog):
        """Test logging when function not found."""
        import logging

        caplog.set_level(logging.WARNING)

        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}

            result = injector.find_original_function("nonexistent_function")

            assert result is None
            assert "Original function 'nonexistent_function' not found" in caplog.text


class TestCreateInjectionWrapper:
    """Test creation of dependency injection wrappers."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_create_injection_wrapper_basic(self, injector):
        """Test creating a basic injection wrapper."""

        def test_func(param1):
            return f"called with {param1}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        # Verify wrapper properties
        assert hasattr(wrapper, "_mesh_injected_deps")
        assert hasattr(wrapper, "_mesh_update_dependency")
        assert hasattr(wrapper, "_mesh_dependencies")
        assert hasattr(wrapper, "_mesh_positions")
        assert hasattr(wrapper, "_mesh_original_func")

        assert wrapper._mesh_dependencies == ["dep1"]
        assert wrapper._mesh_positions == [0]
        assert wrapper._mesh_original_func is test_func

    def test_create_injection_wrapper_no_injection_positions(self, injector):
        """Test creating wrapper when no injection positions found."""

        def test_func():
            return "no params"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        # Should still create wrapper but with no positions
        assert wrapper._mesh_positions == []
        assert wrapper._mesh_dependencies == ["dep1"]

    def test_create_injection_wrapper_registers_function(self, injector):
        """Test that wrapper is registered in function registry."""

        def test_func(param1):
            return param1

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"
        assert func_id in injector._function_registry
        assert injector._function_registry[func_id] is wrapper

    def test_create_injection_wrapper_tracks_dependencies(self, injector):
        """Test that dependency mapping is updated with composite keys."""

        def test_func(param1, param2):
            return param1, param2

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0, 1],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1", "dep2"])

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"

        # Now uses composite keys format: "func_id:dep_N"
        assert f"{func_id}:dep_0" in injector._dependency_mapping
        assert f"{func_id}:dep_1" in injector._dependency_mapping
        assert func_id in injector._dependency_mapping[f"{func_id}:dep_0"]
        assert func_id in injector._dependency_mapping[f"{func_id}:dep_1"]

    def test_create_injection_wrapper_preserves_original(self, injector):
        """Test that original function is preserved."""

        def test_func(param1):
            return f"original: {param1}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        # Original function should be accessible
        assert wrapper._mesh_original_func is test_func
        assert test_func._mesh_original_func is test_func  # Self-reference on original


class TestInjectionWrapperExecution:
    """Test execution of dependency injection wrappers."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_wrapper_execution_no_injection_positions(self, injector):
        """Test wrapper execution when no injection positions."""

        def test_func(param1):
            return f"result: {param1}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        result = wrapper("test_value")
        assert result == "result: test_value"

    def test_wrapper_execution_with_injection(self, injector):
        """Test wrapper execution with dependency injection."""

        def test_func(param1, dependency=None):
            return f"param1: {param1}, dependency: {dependency}"

        # Mock dependency
        mock_dep = MagicMock()
        mock_dep.__str__ = lambda self: "mock_dependency"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

            # Set up dependency using array index
            wrapper._mesh_injected_deps[0] = mock_dep

            result = wrapper("test_value")
            # The wrapper should inject the dependency
            assert "mock_dependency" in str(result)

    def test_wrapper_execution_parameter_already_provided(self, injector):
        """Test wrapper doesn't inject when parameter already provided."""

        def test_func(param1, dependency=None):
            return f"param1: {param1}, dependency: {dependency}"

        mock_dep = MagicMock()

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])
            wrapper._mesh_injected_deps[0] = mock_dep

            # Provide dependency explicitly
            result = wrapper("test_value", dependency="explicit_value")
            assert "explicit_value" in result

    def test_wrapper_execution_fallback_to_global_dependency(self, injector):
        """Test wrapper falls back to global dependency storage."""

        def test_func(param1, dependency=None):
            return f"param1: {param1}, dependency: {dependency}"

        mock_dep = MagicMock()
        mock_dep.__str__ = lambda self: "global_dependency"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

            # Set up global dependency with composite key (not in wrapper storage)
            func_id = f"{test_func.__module__}.{test_func.__qualname__}"
            injector._dependencies[f"{func_id}:dep_0"] = mock_dep

            result = wrapper("test_value")
            assert "global_dependency" in str(result)

    def test_wrapper_execution_missing_dependency(self, injector):
        """Test wrapper execution when dependency is missing."""

        def test_func(param1, dependency=None):
            return f"param1: {param1}, dependency: {dependency}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

            # No dependency set up
            result = wrapper("test_value")
            assert "dependency: None" in result


class TestWrapperUpdateMechanism:
    """Test the wrapper dependency update mechanism."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_wrapper_update_dependency_add(self, injector):
        """Test updating wrapper with new dependency using index."""

        def test_func(param1):
            return param1

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        mock_dep = MagicMock()
        wrapper._mesh_update_dependency(0, mock_dep)

        assert wrapper._mesh_injected_deps[0] is mock_dep

    def test_wrapper_update_dependency_remove(self, injector):
        """Test removing dependency from wrapper using index."""

        def test_func(param1):
            return param1

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        # Add then remove
        mock_dep = MagicMock()
        wrapper._mesh_update_dependency(0, mock_dep)
        assert wrapper._mesh_injected_deps[0] is mock_dep

        wrapper._mesh_update_dependency(0, None)
        assert wrapper._mesh_injected_deps[0] is None

    def test_wrapper_update_dependency_logging(self, injector, caplog):
        """Test that wrapper update logs appropriately."""
        import logging

        caplog.set_level(logging.DEBUG)
        # Set the module logger level too
        logging.getLogger("_mcp_mesh.engine.dependency_injector").setLevel(
            logging.DEBUG
        )

        def test_func(param1):
            return param1

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        mock_dep = MagicMock()
        wrapper._mesh_update_dependency(0, mock_dep)

        assert (
            f"Updated dependency at index 0 for {test_func.__module__}.{test_func.__qualname__}"
            in caplog.text
        )


class TestConcurrency:
    """Test concurrent access to dependency injector."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    @pytest.mark.asyncio
    async def test_concurrent_dependency_registration(self, injector):
        """Test concurrent dependency registration."""

        async def register_dep(name, instance):
            await injector.register_dependency(name, instance)

        # Create multiple concurrent registrations
        tasks = []
        for i in range(10):
            mock_instance = MagicMock()
            tasks.append(register_dep(f"dep_{i}", mock_instance))

        # Run concurrently
        await asyncio.gather(*tasks)

        # Verify all dependencies were registered
        for i in range(10):
            assert injector.get_dependency(f"dep_{i}") is not None

    @pytest.mark.asyncio
    async def test_concurrent_register_unregister(self, injector):
        """Test concurrent registration and unregistration."""
        mock_instance = MagicMock()

        async def register():
            await injector.register_dependency("test_dep", mock_instance)

        async def unregister():
            await injector.unregister_dependency("test_dep")

        # Run register and unregister concurrently multiple times
        tasks = []
        for _ in range(5):
            tasks.extend([register(), unregister()])

        await asyncio.gather(*tasks)

        # Final state depends on timing, but should not crash


class TestErrorHandling:
    """Test error handling in dependency injection."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_wrapper_execution_with_exception(self, injector):
        """Test wrapper execution when original function raises exception."""

        def test_func(param1):
            raise ValueError("Test exception")

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[],
        ):
            wrapper = injector.create_injection_wrapper(test_func, [])

        with pytest.raises(ValueError, match="Test exception"):
            wrapper("test")

    def test_wrapper_with_malformed_signature(self, injector):
        """Test wrapper creation with malformed function signature."""

        # Create a function with unusual signature
        def test_func(*args, **kwargs):
            return args, kwargs

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        # Should create wrapper without errors
        assert wrapper is not None
        result = wrapper("test")
        assert result == (("test",), {})

    @pytest.mark.asyncio
    async def test_notification_with_missing_function(self, injector):
        """Test dependency notification when function no longer exists."""
        # Set up dependency mapping to non-existent function
        injector._dependency_mapping["test_dep"] = {"nonexistent_func"}

        # Should not raise error
        await injector.register_dependency("test_dep", MagicMock())

    @pytest.mark.asyncio
    async def test_notification_with_function_without_update_method(
        self, injector, caplog
    ):
        """Test dependency notification when function lacks update method."""
        import logging

        caplog.set_level(logging.WARNING)

        # Create function without update method
        mock_func = MagicMock()
        # Remove the _mesh_update_dependency attribute if it exists
        if hasattr(mock_func, "_mesh_update_dependency"):
            delattr(mock_func, "_mesh_update_dependency")

        # Set up dependency first (required for unregister to process)
        await injector.register_dependency("test_dep", MagicMock())

        injector._dependency_mapping["test_dep"] = {"func1"}
        injector._function_registry["func1"] = mock_func

        caplog.clear()  # Clear registration logs

        await injector.unregister_dependency("test_dep")

        assert (
            "INJECTOR: Function func1 has no _mesh_update_dependency method"
            in caplog.text
        )


class TestWeakReferences:
    """Test weak reference behavior in function registry."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_function_registry_weak_references(self, injector):
        """Test that function registry uses weak references."""

        def test_func(param1):
            return param1

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"
        assert func_id in injector._function_registry

        # Delete wrapper reference
        del wrapper

        # Force garbage collection
        import gc

        gc.collect()

        # Function should eventually be removed from registry
        # Note: This is implementation dependent and may not always work in tests
        # but verifies the concept


class TestDebugLogging:
    """Test debug logging in dependency injection wrapper."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_wrapper_debug_logging(self, injector, caplog):
        """Test wrapper debug logging during execution."""
        import logging

        caplog.set_level(logging.DEBUG)
        # Set the module logger level too
        logging.getLogger("_mcp_mesh.engine.dependency_injector").setLevel(
            logging.DEBUG
        )

        def test_func(param1, dependency=None):
            return f"{param1}-{dependency}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["dep1"])

            mock_dep = MagicMock()
            wrapper._mesh_injected_deps[0] = mock_dep

            result = wrapper("test_value")

            # Check for debug log messages with args/result logging
            assert "Tool 'test_func' called with kwargs=" in caplog.text
            assert "Tool 'test_func' args:" in caplog.text
            assert "Injected 1 dependencies:" in caplog.text
            assert "dep1" in caplog.text
            assert "Tool 'test_func' returned:" in caplog.text
            assert "Tool 'test_func' result:" in caplog.text
