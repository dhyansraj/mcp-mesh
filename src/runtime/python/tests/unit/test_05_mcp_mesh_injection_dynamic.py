"""
Unit tests for dynamic dependency injection in MCP Mesh.

Tests both static injection and runtime topology changes.
"""

import asyncio
from unittest.mock import Mock

import pytest

from mcp_mesh.runtime.dependency_injector import DependencyInjector
from mcp_mesh.types import McpMeshAgent


class TestDependencyInjection:
    """Test suite for dependency injection functionality."""

    @pytest.fixture
    def injector(self):
        """Create a fresh injector for each test."""
        return DependencyInjector()

    @pytest.fixture
    def mock_services(self):
        """Create mock services for testing."""
        return {
            "Database": Mock(query=Mock(return_value="DB query result"), version="1.0"),
            "Cache": Mock(get=Mock(return_value="Cached value"), set=Mock()),
            "Logger": Mock(log=Mock()),
        }

    def test_injection_wrapper_creation(self, injector):
        """Test that injection wrapper is created correctly."""

        def original_func(name: str = "test", Database=None) -> str:
            if Database:
                return f"Hello {name}, DB says: {Database.query('test')}"
            return f"Hello {name}, no DB"

        # Create wrapper
        wrapped = injector.create_injection_wrapper(original_func, ["Database"])

        # Verify wrapper attributes
        assert hasattr(wrapped, "_update_dependency")
        assert hasattr(wrapped, "_original_func")
        assert wrapped._original_func is original_func
        assert wrapped._dependencies == ["Database"]
        assert wrapped.__name__ == original_func.__name__

    def test_explicit_override(self, injector, mock_services):
        """Test that explicit arguments override injection."""

        injector._dependencies["Database"] = mock_services["Database"]

        custom_db = Mock(query=Mock(return_value="Custom DB"))

        def test_func(Database=None) -> str:
            return Database.query("test") if Database else "No DB"

        wrapped = injector.create_injection_wrapper(test_func, ["Database"])

        # Call with explicit Database
        result = wrapped(Database=custom_db)

        # Should use the explicit argument, not injected
        assert result == "Custom DB"
        custom_db.query.assert_called_with("test")
        mock_services["Database"].query.assert_not_called()

    def test_weakref_cleanup(self, injector):
        """Test that functions are cleaned up when no longer referenced."""
        import gc

        def temp_func(Database=None) -> str:
            return "temp"

        # Create wrapper
        wrapped = injector.create_injection_wrapper(temp_func, ["Database"])
        func_id = f"{temp_func.__module__}.{temp_func.__qualname__}"

        # Verify registration
        assert func_id in injector._function_registry
        assert "Database" in injector._dependency_mapping
        assert func_id in injector._dependency_mapping["Database"]

        # Delete reference and force garbage collection
        del wrapped
        del temp_func
        gc.collect()

        # Verify cleanup
        assert func_id not in injector._function_registry


class TestDynamicTopologyChanges:
    """Test suite for handling topology changes."""

    @pytest.mark.asyncio
    async def test_service_failover(self):
        """Test handling service failover scenarios."""

        injector = DependencyInjector()

        # Track which database is used
        call_log = []

        def query_func(sql: str, Database: McpMeshAgent = None) -> str:
            if Database:
                result = f"{Database.name}: {sql}"
                call_log.append(result)
                return result
            call_log.append("No DB")
            return "No database available"

        wrapped = injector.create_injection_wrapper(query_func, ["Database"])

        # Primary database
        primary_db = Mock()
        primary_db.name = "Primary"
        await injector.register_dependency("Database", primary_db)

        wrapped(sql="SELECT 1")
        assert call_log[-1] == "Primary: SELECT 1"

        # Primary fails, secondary takes over
        secondary_db = Mock()
        secondary_db.name = "Secondary"
        await injector.register_dependency("Database", secondary_db)

        wrapped(sql="SELECT 2")
        assert call_log[-1] == "Secondary: SELECT 2"

        # Primary comes back
        await injector.register_dependency("Database", primary_db)

        wrapped(sql="SELECT 3")
        assert call_log[-1] == "Primary: SELECT 3"

    @pytest.mark.asyncio
    async def test_concurrent_updates(self):
        """Test handling concurrent dependency updates."""

        injector = DependencyInjector()
        update_count = 0

        def counter_func(Counter: McpMeshAgent = None) -> int:
            if Counter:
                return Counter.value
            return -1

        wrapped = injector.create_injection_wrapper(counter_func, ["Counter"])

        # Simulate rapid updates
        async def update_counter():
            nonlocal update_count
            for i in range(10):
                counter = Mock(value=i)
                await injector.register_dependency("Counter", counter)
                update_count += 1
                await asyncio.sleep(0.01)

        # Run updates and calls concurrently
        update_task = asyncio.create_task(update_counter())

        results = []
        for _ in range(20):
            results.append(wrapped())
            await asyncio.sleep(0.005)

        await update_task

        # Verify we got different values as counter updated
        unique_values = set(r for r in results if r != -1)
        assert len(unique_values) > 1  # Should see multiple counter values
        assert update_count == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
