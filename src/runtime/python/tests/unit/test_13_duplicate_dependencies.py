"""
Unit tests for duplicate capability dependency injection.

Tests the new array-based dependency injection system that supports multiple
dependencies with the same capability name but different tags/versions.
This ensures the registry's positional matching is correctly applied.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.engine.dependency_injector import DependencyInjector


class TestDuplicateCapabilities:
    """Test injection of multiple dependencies with same capability name."""

    @pytest.fixture
    def injector(self):
        """Create a fresh DependencyInjector for each test."""
        return DependencyInjector()

    def test_create_wrapper_with_duplicate_capabilities(self, injector):
        """Test creating wrapper for function with duplicate capability names."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return f"data: {data}, v1: {time_v1}, v2: {time_v2}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],  # Both time_v1 and time_v2 positions
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]  # Same capability name!
            )

        # Verify wrapper created with array-based storage
        assert hasattr(wrapper, "_mesh_injected_deps")
        assert isinstance(wrapper._mesh_injected_deps, list)
        assert len(wrapper._mesh_injected_deps) == 2
        assert wrapper._mesh_dependencies == ["time_service", "time_service"]
        assert wrapper._mesh_positions == [1, 2]

    def test_dependency_mapping_uses_composite_keys(self, injector):
        """Test that dependency mapping uses composite keys for duplicate capabilities."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return f"data: {data}, v1: {time_v1}, v2: {time_v2}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"

        # Verify composite keys in dependency mapping
        expected_key_0 = f"{func_id}:dep_0"
        expected_key_1 = f"{func_id}:dep_1"

        assert expected_key_0 in injector._dependency_mapping
        assert expected_key_1 in injector._dependency_mapping
        assert func_id in injector._dependency_mapping[expected_key_0]
        assert func_id in injector._dependency_mapping[expected_key_1]

    @pytest.mark.asyncio
    async def test_register_duplicate_dependencies_with_different_instances(
        self, injector
    ):
        """Test registering two different instances for same capability name."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return f"data: {data}, v1: {time_v1}, v2: {time_v2}"

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        # Create two different mock instances for the same capability
        mock_v1 = MagicMock()
        mock_v1.__str__ = lambda self: "time_v1_instance"

        mock_v2 = MagicMock()
        mock_v2.__str__ = lambda self: "time_v2_instance"

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"

        # Register with composite keys (as the dependency resolution does)
        await injector.register_dependency(f"{func_id}:dep_0", mock_v1)
        await injector.register_dependency(f"{func_id}:dep_1", mock_v2)

        # Verify both instances are stored separately
        assert injector.get_dependency(f"{func_id}:dep_0") is mock_v1
        assert injector.get_dependency(f"{func_id}:dep_1") is mock_v2

        # Verify wrapper received both updates
        assert wrapper._mesh_injected_deps[0] is mock_v1
        assert wrapper._mesh_injected_deps[1] is mock_v2

    def test_wrapper_execution_with_duplicate_dependencies(self, injector):
        """Test wrapper correctly injects different instances for duplicate capabilities."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return {
                "data": data,
                "v1": str(time_v1) if time_v1 else None,
                "v2": str(time_v2) if time_v2 else None,
            }

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        # Create two different mock instances
        mock_v1 = MagicMock()
        mock_v1.__str__ = lambda self: "v1_proxy"

        mock_v2 = MagicMock()
        mock_v2.__str__ = lambda self: "v2_proxy"

        # Inject both dependencies
        wrapper._mesh_injected_deps[0] = mock_v1
        wrapper._mesh_injected_deps[1] = mock_v2

        # Execute wrapper
        result = wrapper("test_data")

        # Verify both dependencies were injected correctly
        assert result["data"] == "test_data"
        assert result["v1"] == "v1_proxy"
        assert result["v2"] == "v2_proxy"
        assert result["v1"] != result["v2"]  # Critical: different instances

    def test_update_dependency_by_index(self, injector):
        """Test updating dependency using index-based approach."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return {"v1": time_v1, "v2": time_v2}

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        # Update first instance
        mock_v1 = MagicMock()
        wrapper._mesh_update_dependency(0, mock_v1)
        assert wrapper._mesh_injected_deps[0] is mock_v1
        assert wrapper._mesh_injected_deps[1] is None

        # Update second instance
        mock_v2 = MagicMock()
        wrapper._mesh_update_dependency(1, mock_v2)
        assert wrapper._mesh_injected_deps[0] is mock_v1
        assert wrapper._mesh_injected_deps[1] is mock_v2

        # Verify they are different instances
        assert wrapper._mesh_injected_deps[0] is not wrapper._mesh_injected_deps[1]

    def test_remove_dependency_by_index(self, injector):
        """Test removing dependency using index-based approach."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return {"v1": time_v1, "v2": time_v2}

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        # Set up both dependencies
        mock_v1 = MagicMock()
        mock_v2 = MagicMock()
        wrapper._mesh_injected_deps[0] = mock_v1
        wrapper._mesh_injected_deps[1] = mock_v2

        # Remove first dependency
        wrapper._mesh_update_dependency(0, None)
        assert wrapper._mesh_injected_deps[0] is None
        assert wrapper._mesh_injected_deps[1] is mock_v2  # Second one still there

        # Remove second dependency
        wrapper._mesh_update_dependency(1, None)
        assert wrapper._mesh_injected_deps[0] is None
        assert wrapper._mesh_injected_deps[1] is None

    @pytest.mark.asyncio
    async def test_composite_key_extraction_in_register(self, injector):
        """Test that register_dependency correctly extracts index from composite key."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return {"v1": time_v1, "v2": time_v2}

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"

        mock_instance = MagicMock()

        # Register with composite key
        await injector.register_dependency(f"{func_id}:dep_1", mock_instance)

        # Verify the correct index was updated
        assert wrapper._mesh_injected_deps[0] is None  # Index 0 not updated
        assert wrapper._mesh_injected_deps[1] is mock_instance  # Index 1 updated

    @pytest.mark.asyncio
    async def test_composite_key_extraction_in_unregister(self, injector):
        """Test that unregister_dependency correctly extracts index from composite key."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return {"v1": time_v1, "v2": time_v2}

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"

        # Set up both dependencies
        mock_v1 = MagicMock()
        mock_v2 = MagicMock()

        await injector.register_dependency(f"{func_id}:dep_0", mock_v1)
        await injector.register_dependency(f"{func_id}:dep_1", mock_v2)

        # Verify both are set
        assert wrapper._mesh_injected_deps[0] is mock_v1
        assert wrapper._mesh_injected_deps[1] is mock_v2

        # Unregister first dependency
        await injector.unregister_dependency(f"{func_id}:dep_0")

        # Verify only first is removed
        assert wrapper._mesh_injected_deps[0] is None
        assert wrapper._mesh_injected_deps[1] is mock_v2

    def test_wrapper_execution_fallback_to_global_storage(self, injector):
        """Test wrapper falls back to global storage with composite keys."""

        def test_func(data: str, time_v1=None, time_v2=None):
            return {
                "data": data,
                "v1": str(time_v1) if time_v1 else "None",
                "v2": str(time_v2) if time_v2 else "None",
            }

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func, ["time_service", "time_service"]
            )

        func_id = f"{test_func.__module__}.{test_func.__qualname__}"

        # Set up global dependencies (not in wrapper storage)
        mock_v1 = MagicMock()
        mock_v1.__str__ = lambda self: "global_v1"

        mock_v2 = MagicMock()
        mock_v2.__str__ = lambda self: "global_v2"

        injector._dependencies[f"{func_id}:dep_0"] = mock_v1
        injector._dependencies[f"{func_id}:dep_1"] = mock_v2

        # Execute - should fall back to global storage
        result = wrapper("test_data")

        assert result["v1"] == "global_v1"
        assert result["v2"] == "global_v2"

    def test_three_duplicate_dependencies(self, injector):
        """Test function with three dependencies of the same capability."""

        def test_func(time_v1=None, time_v2=None, time_v3=None):
            return {
                "v1": str(time_v1) if time_v1 else None,
                "v2": str(time_v2) if time_v2 else None,
                "v3": str(time_v3) if time_v3 else None,
            }

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0, 1, 2],
        ):
            wrapper = injector.create_injection_wrapper(
                test_func,
                ["time_service", "time_service", "time_service"],  # Three!
            )

        # Set up three different instances
        mock_v1 = MagicMock()
        mock_v1.__str__ = lambda self: "v1"

        mock_v2 = MagicMock()
        mock_v2.__str__ = lambda self: "v2"

        mock_v3 = MagicMock()
        mock_v3.__str__ = lambda self: "v3"

        wrapper._mesh_injected_deps[0] = mock_v1
        wrapper._mesh_injected_deps[1] = mock_v2
        wrapper._mesh_injected_deps[2] = mock_v3

        result = wrapper()

        # Verify all three are injected correctly
        assert result["v1"] == "v1"
        assert result["v2"] == "v2"
        assert result["v3"] == "v3"

        # Verify they are all different
        assert result["v1"] != result["v2"]
        assert result["v2"] != result["v3"]
        assert result["v1"] != result["v3"]

    def test_update_dependency_out_of_range_index(self, injector, caplog):
        """Test updating dependency with out of range index."""
        import logging

        caplog.set_level(logging.WARNING)

        def test_func(time_v1=None):
            return time_v1

        with patch(
            "_mcp_mesh.engine.dependency_injector.analyze_injection_strategy",
            return_value=[0],
        ):
            wrapper = injector.create_injection_wrapper(test_func, ["time_service"])

        # Try to update index 5 when wrapper only has 1 dependency
        wrapper._mesh_update_dependency(5, MagicMock())

        assert "Attempted to update dependency at index 5" in caplog.text
        assert "wrapper only has 1 dependencies" in caplog.text
