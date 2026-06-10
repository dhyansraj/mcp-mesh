"""
Unit tests for DependencyInjector and related injection logic.

Tests the dynamic dependency injection system including function wrapping,
runtime dependency updates, injection strategy analysis, and original
function finding without requiring actual MCP mesh infrastructure.
"""

import asyncio
import inspect
import logging
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
        assert "consider typing as McpMeshTool for clarity" in caplog.text

        caplog.clear()

        # Multiple parameters without typing
        with patch(
            "_mcp_mesh.engine.dependency_injector.get_mesh_agent_positions",
            return_value=[],
        ):
            analyze_injection_strategy(func_multi_untyped, ["dep1"])
        assert "none are typed as McpMeshTool" in caplog.text


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
            mock_registry.get_mesh_tools.side_effect = AttributeError("Registry error")

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


class TestUnifiedPositionalInjection:
    """Cover the unified positional injection contract — McpMeshTool and
    MeshJob parameters share a single ``dep_index`` namespace in
    declaration order. Each ``dependencies[i]`` strictly pairs with ONE
    parameter position; unresolved deps leave the slot ``None`` without
    shifting later positions.

    The tests exercise :func:`_prepare_injection_kwargs` directly so the
    assertions don't have to navigate the async wrapper plumbing — the
    function under test is the contract surface.
    """

    @pytest.fixture(autouse=True)
    def _registry_url(self, monkeypatch):
        # MeshJob injection requires MCP_MESH_REGISTRY_URL to construct a
        # MeshJobSubmitter; without it the framework logs a warning and
        # leaves the slot None. Set it once for the whole class.
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://registry.local:8000")

    @staticmethod
    def _prep(func, dependencies, injected_deps_array=None):
        """Invoke _prepare_injection_kwargs against a user function.

        Mirrors what the real wrapper does during runtime injection so
        we can assert each slot receives exactly the right value type.
        """
        import logging as _log
        from _mcp_mesh.engine.dependency_injector import _prepare_injection_kwargs
        from _mcp_mesh.engine.signature_analyzer import get_mesh_agent_positions

        if injected_deps_array is None:
            injected_deps_array = [None] * len(dependencies)
        mesh_positions = get_mesh_agent_positions(func)
        return _prepare_injection_kwargs(
            func,
            {},
            mesh_positions,
            dependencies,
            injected_deps_array,
            lambda _key: None,
            _log.getLogger("test"),
        )

    def test_mesh_job_first_then_mesh_tool(self):
        """The exact #1075 shape: MeshJob dep listed FIRST in deps[],
        McpMeshTool dep second. Each param must receive the RIGHT slot
        type — submitter into MeshJob, proxy into McpMeshTool."""
        from mesh import MeshJob
        from mesh.types import McpMeshTool
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        async def consumer(
            user_id: str,
            job: MeshJob = None,         # sig pos 1 → dep_index 0
            tool: McpMeshTool = None,    # sig pos 2 → dep_index 1
        ):
            return (user_id, job, tool)

        mock_proxy = MagicMock(name="fetch_data_proxy")
        # The McpMeshTool's dep_index is 1 — slot 1 of the cache array.
        final_kwargs, count = self._prep(
            consumer,
            ["run_workflow", "fetch_data"],
            injected_deps_array=[None, mock_proxy],
        )

        assert isinstance(final_kwargs["job"], MeshJobSubmitter)
        assert final_kwargs["job"].capability == "run_workflow"
        assert final_kwargs["tool"] is mock_proxy
        assert count == 2

    def test_mesh_tool_first_then_mesh_job(self):
        """Reversed order: McpMeshTool first, MeshJob second. Same
        per-slot type assertion — confirms the binding is positional,
        not type-prioritised."""
        from mesh import MeshJob
        from mesh.types import McpMeshTool
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        async def consumer(
            user_id: str,
            tool: McpMeshTool = None,   # sig pos 1 → dep_index 0
            job: MeshJob = None,        # sig pos 2 → dep_index 1
        ):
            return (user_id, tool, job)

        mock_proxy = MagicMock(name="fetch_data_proxy")
        final_kwargs, count = self._prep(
            consumer,
            ["fetch_data", "run_workflow"],
            injected_deps_array=[mock_proxy, None],
        )

        assert final_kwargs["tool"] is mock_proxy
        assert isinstance(final_kwargs["job"], MeshJobSubmitter)
        assert final_kwargs["job"].capability == "run_workflow"
        assert count == 2

    def test_unresolved_middle_dependency_does_not_shift(self):
        """Three McpMeshTool params; the middle dep is unresolved (no
        proxy registered). Positions 0 and 2 must still receive their
        proxies — position 1 stays ``None`` rather than shifting up to
        consume the position-2 proxy."""
        from mesh.types import McpMeshTool

        async def fan_out(
            a: str,
            dep0: McpMeshTool = None,
            dep1: McpMeshTool = None,
            dep2: McpMeshTool = None,
        ):
            return (dep0, dep1, dep2)

        proxy_a = MagicMock(name="proxy_a")
        proxy_c = MagicMock(name="proxy_c")
        # Position 1 stays None (unresolved); positions 0 and 2 have proxies.
        final_kwargs, _ = self._prep(
            fan_out,
            ["cap_a", "cap_b", "cap_c"],
            injected_deps_array=[proxy_a, None, proxy_c],
        )

        assert final_kwargs["dep0"] is proxy_a
        assert final_kwargs["dep1"] is None   # No shifting
        assert final_kwargs["dep2"] is proxy_c

    def test_unresolved_mixed_mesh_tool_with_mesh_job(self):
        """MeshJob + McpMeshTool; the McpMeshTool dep is unresolved.
        MeshJob still gets its submitter (registry URL set, name
        free-form), McpMeshTool param stays ``None``."""
        from mesh import MeshJob
        from mesh.types import McpMeshTool
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        async def consumer(
            a: str,
            job: MeshJob = None,        # sig pos 1 → dep_index 0
            tool: McpMeshTool = None,   # sig pos 2 → dep_index 1
        ):
            return (job, tool)

        # No proxy for the McpMeshTool slot — leave None.
        final_kwargs, _ = self._prep(
            consumer,
            ["run_workflow", "missing_tool"],
            injected_deps_array=[None, None],
        )

        assert isinstance(final_kwargs["job"], MeshJobSubmitter)
        assert final_kwargs["job"].capability == "run_workflow"
        assert final_kwargs["tool"] is None

    def test_mesh_job_param_name_is_free_form(self):
        """The MeshJob param name no longer must match a capability —
        positional binding only. A param named ``workflow`` paired with
        dependency capability ``run_my_thing`` MUST receive a
        MeshJobSubmitter with ``capability='run_my_thing'``."""
        from mesh import MeshJob
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        async def consumer(
            user_id: str,
            workflow: MeshJob = None,
        ):
            return workflow

        final_kwargs, _ = self._prep(
            consumer,
            ["run_my_thing"],
            injected_deps_array=[None],
        )

        assert isinstance(final_kwargs["workflow"], MeshJobSubmitter)
        # Name mismatch is fine — binding is positional.
        assert final_kwargs["workflow"].capability == "run_my_thing"

    def test_pure_mesh_tool_positional_unchanged(self):
        """Regression: a pure-McpMeshTool function still injects each
        proxy into its positional slot exactly as before the
        unification."""
        from mesh.types import McpMeshTool

        async def fan_out(
            a: str, dep0: McpMeshTool = None, dep1: McpMeshTool = None
        ):
            return (dep0, dep1)

        proxy0 = MagicMock(name="proxy0")
        proxy1 = MagicMock(name="proxy1")
        final_kwargs, count = self._prep(
            fan_out,
            ["cap0", "cap1"],
            injected_deps_array=[proxy0, proxy1],
        )

        assert final_kwargs["dep0"] is proxy0
        assert final_kwargs["dep1"] is proxy1
        assert count == 2

    def test_explicit_kwarg_skips_meshjob_injection(self):
        """Test-friendly contract: when the caller passes an explicit
        value for a MeshJob param (e.g. a fake), the framework MUST NOT
        overwrite it with a MeshJobSubmitter."""
        import logging as _log
        from mesh import MeshJob
        from _mcp_mesh.engine.dependency_injector import _prepare_injection_kwargs
        from _mcp_mesh.engine.signature_analyzer import get_mesh_agent_positions

        async def consumer(a: str, job: MeshJob = None):
            return job

        fake_job = MagicMock(name="fake_job")
        mesh_positions = get_mesh_agent_positions(consumer)
        final_kwargs, injected_count = _prepare_injection_kwargs(
            consumer,
            {"job": fake_job},  # caller-supplied
            mesh_positions,
            ["run_workflow"],
            [None],
            lambda _key: None,
            _log.getLogger("test"),
        )

        assert final_kwargs["job"] is fake_job
        # Framework MUST NOT have injected anything — the caller-supplied
        # value was preserved verbatim, no MeshJobSubmitter constructed.
        assert injected_count == 0

    def test_meshjob_slot_is_none_when_registry_url_unset(self, monkeypatch):
        """When MCP_MESH_REGISTRY_URL is missing, the MeshJob slot must
        be explicitly set to None (not omitted from final_kwargs) so the
        consumer function's call signature is satisfied. Mirrors the
        McpMeshTool branch's behavior of always assigning into kwargs."""
        from mesh import MeshJob

        # Override the class-wide _registry_url fixture for this test.
        monkeypatch.delenv("MCP_MESH_REGISTRY_URL", raising=False)

        async def consumer(user_id: str, job: MeshJob = None):
            return job

        final_kwargs, injected_count = self._prep(
            consumer,
            ["run_workflow"],
            injected_deps_array=[None],
        )

        # The job slot is present in final_kwargs and is None — not
        # missing-from-dict, which would surface as TypeError on call
        # if the user's MeshJob param had no default.
        assert "job" in final_kwargs
        assert final_kwargs["job"] is None
        # Framework didn't construct a MeshJobSubmitter (registry URL
        # was unavailable), so injected_count stays at 0.
        assert injected_count == 0

    def test_hidden_wrapper_param_diagnostic_does_not_raise(self, caplog):
        """Regression for #1104 (from #1082): when a decorator like
        @mesh.a2a_consumer rewrites the WRAPPER ``__signature__`` to hide
        an injected param (``_a2a``), the wrapper signature has FEWER
        params than the resolved/original function. The MeshJob position
        is derived from the ORIGINAL signature, so the untouched-positional
        diagnostic must NOT index the shorter wrapper signature with an
        original-derived position (IndexError). With zero declared
        dependencies the diagnostic always runs for such handlers.
        """
        from functools import wraps as _wraps
        import inspect as _inspect

        from mesh import MeshJob

        # Original func: (user_id, sections, _a2a, job) — _a2a is the
        # consumer-injected client; job is the MeshJob at ORIGINAL pos 3.
        async def original(user_id: str, sections: list, _a2a=None, job: MeshJob = None):
            return (user_id, sections, _a2a, job)

        # Mimic the @mesh.a2a_consumer bridge: @wraps sets __wrapped__ to
        # the original; __signature__ hides _a2a so the wrapper exposes
        # only (user_id, sections, job) — three params, vs original's four.
        # The MeshJob position (3) is resolved through __wrapped__ to the
        # ORIGINAL signature, while the wrapper signature has only 3 params.
        @_wraps(original)
        async def bridge(*args, **call_kwargs):
            call_kwargs.setdefault("_a2a", object())
            return await original(*args, **call_kwargs)

        user_sig = _inspect.signature(original)
        cleaned = [p for n, p in user_sig.parameters.items() if n != "_a2a"]
        bridge.__signature__ = user_sig.replace(parameters=cleaned)

        # Sanity-check the precondition the regression depends on: the
        # MeshJob is resolved (through __wrapped__) at ORIGINAL position 3,
        # beyond the 3-param wrapper signature. This is what made the
        # pre-fix diagnostic index out of bounds.
        from _mcp_mesh.engine.signature_analyzer import analyze_mesh_job_signature

        assert analyze_mesh_job_signature(original).mesh_job_param_index == 3

        # a2a_consumer passes NO dependencies to the inner tool. Position 3
        # (MeshJob, from the original sig) would index the 3-element wrapper
        # signature → IndexError in the pre-fix diagnostic. Must not raise.
        with caplog.at_level(logging.WARNING):
            final_kwargs, count = self._prep(bridge, [], injected_deps_array=[])

        # With zero declared dependencies the functional loop breaks before
        # injecting; the diagnostic simply must not crash dispatch.
        assert count == 0

        # Positively confirm the formerly-crashing diagnostic branch ran:
        # ``len(eligible_positions) > len(dependencies)`` was true (MeshJob
        # slot present, zero deps), so the "untouched positional slots"
        # warning fired without raising. Without this assertion a future
        # signature-analysis regression could skip the branch and the test
        # would still pass green while no longer guarding #1104.
        assert any(
            "injection-eligible parameters (McpMeshTool/MeshJob)" in r.message
            and "will remain None" in r.message
            for r in caplog.records
        )


class TestHiddenWrapperParamFunctionalInjection:
    """Regression for #1162 MED-1 (functional sibling of #1104/#1105).

    Decorators like ``@mesh.a2a_consumer`` rewrite the wrapper's
    ``__signature__`` to hide a framework-bound param (``_a2a``) while
    ``__wrapped__`` still points at the original function. Injection
    positions are derived from the ORIGINAL signature, so the param-name
    list they index must come from that SAME view — pre-fix, the
    functional path indexed the SHORTER wrapper signature, raising
    IndexError or injecting the proxy into the WRONG parameter.

    Mesh deps bind strictly by POSITION (deliberate design); these tests
    assert the positions resolve against a consistent view, never that
    names are matched.
    """

    @pytest.fixture(autouse=True)
    def _registry_url(self, monkeypatch):
        # MeshJob slots need MCP_MESH_REGISTRY_URL to construct a
        # MeshJobSubmitter.
        monkeypatch.setenv("MCP_MESH_REGISTRY_URL", "http://registry.local:8000")

    # Sentinel standing in for the A2AClient the bridge binds itself.
    _CLIENT = object()

    @classmethod
    def _make_bridge(cls, original):
        """Mimic the @mesh.a2a_consumer bridge: forward **kwargs to the
        original, bind ``_a2a`` when the caller didn't, and hide ``_a2a``
        from the advertised signature (decorators.py:2221-2226)."""
        from functools import wraps as _wraps

        @_wraps(original)
        async def bridge(*args, **call_kwargs):
            if "_a2a" not in call_kwargs:
                call_kwargs["_a2a"] = cls._CLIENT
            return await original(*args, **call_kwargs)

        user_sig = inspect.signature(original)
        cleaned = [p for n, p in user_sig.parameters.items() if n != "_a2a"]
        bridge.__signature__ = user_sig.replace(parameters=cleaned)
        return bridge

    @pytest.mark.asyncio
    async def test_a2a_consumer_dependency_injects_into_db(self):
        """`(_a2a, db)` with dependencies=['db_cap']: the proxy must land
        in ``db`` (original position 1), the bridge must still bind its
        own client into ``_a2a``, and dispatch must not raise."""
        from mesh.types import McpMeshTool

        async def original(_a2a=None, db: McpMeshTool = None):
            return (_a2a, db)

        bridge = self._make_bridge(original)
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bridge, ["db_cap"])

        proxy = MagicMock(name="db_proxy")
        wrapper._mesh_update_dependency(0, proxy)

        a2a, db = await wrapper()

        assert db is proxy
        # The hidden slot stays bridge-bound — the proxy must NOT have
        # displaced the client at position 0.
        assert a2a is self._CLIENT

    @pytest.mark.asyncio
    async def test_a2a_consumer_proxy_lands_in_db_not_y(self):
        """`(_a2a, db, y)`: pre-fix the wrapper-view list ['db', 'y']
        indexed with original position 1 put the proxy into ``y`` and left
        ``db`` None. The proxy must land in ``db``; ``y`` keeps the
        caller's value."""
        from mesh.types import McpMeshTool

        async def original(_a2a=None, db: McpMeshTool = None, y: str = ""):
            return (_a2a, db, y)

        bridge = self._make_bridge(original)
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bridge, ["db_cap"])

        proxy = MagicMock(name="db_proxy")
        wrapper._mesh_update_dependency(0, proxy)

        a2a, db, y = await wrapper(y="hello")

        assert db is proxy
        assert y == "hello"
        assert a2a is self._CLIENT

    @pytest.mark.asyncio
    async def test_multiple_deps_pair_by_declaration_order_not_name(self):
        """DESIGN PIN: deps pair with params by declaration order
        (position), NEVER by name — name-matching must fail this test.

        The params are named ADVERSARIALLY: the FIRST McpMeshTool param
        is named ``cap_b`` and the SECOND is named ``cap_a``, while
        ``dependencies=["cap_a", "cap_b"]``. Declaration-order pairing
        puts the cap_a proxy in the first typed slot (param ``cap_b``)
        and the cap_b proxy in the second (param ``cap_a``). Any future
        dependency-name<->parameter-name matcher produces the exact
        OPPOSITE pairing and must fail here loudly.
        """
        from mesh.types import McpMeshTool

        async def original(
            _a2a=None, cap_b: McpMeshTool = None, cap_a: McpMeshTool = None
        ):
            # Slots returned in DECLARATION order: (hidden, first, second).
            return (_a2a, cap_b, cap_a)

        bridge = self._make_bridge(original)
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bridge, ["cap_a", "cap_b"])

        proxy_a = MagicMock(name="cap_a_proxy")
        proxy_b = MagicMock(name="cap_b_proxy")
        wrapper._mesh_update_dependency(0, proxy_a)  # dependency "cap_a"
        wrapper._mesh_update_dependency(1, proxy_b)  # dependency "cap_b"

        a2a, first_slot, second_slot = await wrapper()

        # deps pair with params by declaration order (position), NEVER by
        # name — name-matching must fail this test: it would route
        # proxy_a into the param NAMED ``cap_a`` (the second slot).
        assert first_slot is proxy_a  # param named cap_b ← dep[0] "cap_a"
        assert second_slot is proxy_b  # param named cap_a ← dep[1] "cap_b"
        assert a2a is self._CLIENT

    @pytest.mark.asyncio
    async def test_a2a_consumer_meshjob_dep_no_indexerror(self):
        """`(_a2a, job: MeshJob)` with one dependency: the MeshJob position
        (1, original view) exceeded the 1-param wrapper view pre-fix →
        IndexError on every invocation. Must inject a MeshJobSubmitter."""
        from mesh import MeshJob
        from _mcp_mesh.engine.mesh_job_submitter import MeshJobSubmitter

        async def original(_a2a=None, job: MeshJob = None):
            return (_a2a, job)

        bridge = self._make_bridge(original)
        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(bridge, ["jobs.run"])

        a2a, job = await wrapper()

        assert isinstance(job, MeshJobSubmitter)
        assert job.capability == "jobs.run"
        assert a2a is self._CLIENT

    def test_strategy_counts_original_view_for_hidden_param_wrapper(self):
        """analyze_injection_strategy on the bridge must classify by the
        ORIGINAL signature: `(_a2a, db)` is two params, McpMeshTool at
        original position 1 — not 'single param, position 0'."""
        from mesh.types import McpMeshTool

        async def original(_a2a=None, db: McpMeshTool = None):
            return (_a2a, db)

        bridge = self._make_bridge(original)

        assert analyze_injection_strategy(bridge, ["db_cap"]) == [1]

    def test_strategy_hidden_single_param_stays_silent(self, caplog):
        """`(_a2a)`-only with zero deps: the single-param 'inject
        regardless of typing' heuristic must NOT fire for a hidden,
        framework-bound slot — no injection target, no warning (matches
        pre-fix behavior the __signature__ hiding was added for)."""

        async def original(_a2a=None):
            return _a2a

        bridge = self._make_bridge(original)

        with caplog.at_level(logging.WARNING):
            result = analyze_injection_strategy(bridge, [])

        assert result == []
        assert not caplog.records

    def test_bounds_guard_skips_out_of_range_position(self, caplog):
        """Defensive guard: a position beyond the resolved param list must
        log a warning and skip that one injection — no crash, and other
        deps still inject into their own positional slots."""
        import logging as _log
        from mesh.types import McpMeshTool
        from _mcp_mesh.engine.dependency_injector import _prepare_injection_kwargs

        async def f(a: str, db: McpMeshTool = None):
            return db

        proxy0 = MagicMock(name="proxy0")
        with caplog.at_level(logging.WARNING):
            final_kwargs, count = _prepare_injection_kwargs(
                f,
                {},
                [1, 7],  # position 7 is synthetic skew — out of bounds
                ["cap0", "cap1"],
                [proxy0, MagicMock(name="proxy1")],
                lambda _key: None,
                _log.getLogger("test"),
            )

        assert final_kwargs["db"] is proxy0
        assert count == 1
        assert any(
            "out of bounds" in r.message and "'cap1'" in r.message
            for r in caplog.records
        )

    def test_plain_mesh_tool_positional_injection_unchanged(self):
        """Common-path guard: a plain function (no __signature__ rewrite)
        injects exactly as before — wrapper and original views are the
        same view."""
        from mesh.types import McpMeshTool

        def f(a: str, db: McpMeshTool = None):
            return (a, db)

        injector = DependencyInjector()
        wrapper = injector.create_injection_wrapper(f, ["db_cap"])

        proxy = MagicMock(name="db_proxy")
        wrapper._mesh_update_dependency(0, proxy)

        a, db = wrapper("x")

        assert a == "x"
        assert db is proxy

    def test_plain_single_param_heuristic_unchanged(self):
        """The untyped single-parameter heuristic still applies to plain
        functions (no hidden params): position 0 is selected."""

        def f(anything):
            return anything

        assert analyze_injection_strategy(f, ["dep1"]) == [0]
