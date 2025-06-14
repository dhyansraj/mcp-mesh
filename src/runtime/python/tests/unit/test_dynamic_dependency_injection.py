"""
Unit tests for dynamic dependency injection in MCP Mesh.

Tests both static injection and runtime topology changes.
"""

import asyncio
from unittest.mock import Mock, patch

import pytest

from mcp_mesh import mesh_agent
from mcp_mesh.runtime.dependency_injector import DependencyInjector


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

    def test_static_injection(self, injector, mock_services):
        """Test basic dependency injection."""

        # Register dependencies
        for name, service in mock_services.items():
            injector._dependencies[name] = service

        def test_func(data: str = "test", Database=None, Cache=None) -> dict:
            return {
                "data": data,
                "db_result": Database.query(data) if Database else None,
                "cache_result": Cache.get(data) if Cache else None,
            }

        # Create wrapper
        wrapped = injector.create_injection_wrapper(test_func, ["Database", "Cache"])

        # Call without providing dependencies
        result = wrapped(data="hello")

        # Verify injection worked
        assert result["db_result"] == "DB query result"
        assert result["cache_result"] == "Cached value"
        mock_services["Database"].query.assert_called_with("hello")
        mock_services["Cache"].get.assert_called_with("hello")

    def test_partial_injection(self, injector, mock_services):
        """Test injection when some dependencies are unavailable."""

        # Only register Database
        injector._dependencies["Database"] = mock_services["Database"]

        def test_func(Database=None, Cache=None, Logger=None) -> dict:
            return {
                "has_db": Database is not None,
                "has_cache": Cache is not None,
                "has_logger": Logger is not None,
            }

        wrapped = injector.create_injection_wrapper(
            test_func, ["Database", "Cache", "Logger"]
        )

        result = wrapped()

        # Only Database should be injected
        assert result["has_db"] is True
        assert result["has_cache"] is False
        assert result["has_logger"] is False

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

    @pytest.mark.asyncio
    async def test_async_function_injection(self, injector, mock_services):
        """Test injection with async functions."""

        injector._dependencies["Database"] = mock_services["Database"]

        async def async_func(query: str = "SELECT *", Database=None) -> str:
            if Database:
                return f"Async result: {Database.query(query)}"
            return "No database"

        wrapped = injector.create_injection_wrapper(async_func, ["Database"])

        # Verify wrapper is async
        assert asyncio.iscoroutinefunction(wrapped)

        # Test injection
        result = await wrapped(query="SELECT id FROM users")
        assert result == "Async result: DB query result"
        mock_services["Database"].query.assert_called_with("SELECT id FROM users")

    @pytest.mark.asyncio
    async def test_dynamic_updates(self, injector):
        """Test updating dependencies at runtime."""

        call_results = []

        def test_func(Database=None) -> str:
            if Database:
                result = f"DB version: {Database.version}"
            else:
                result = "No database"
            call_results.append(result)
            return result

        wrapped = injector.create_injection_wrapper(test_func, ["Database"])

        # Initial call - no database
        wrapped()
        assert call_results[-1] == "No database"

        # Register database v1
        db_v1 = Mock(version="1.0")
        await injector.register_dependency("Database", db_v1)

        wrapped()
        assert call_results[-1] == "DB version: 1.0"

        # Update to database v2
        db_v2 = Mock(version="2.0")
        await injector.register_dependency("Database", db_v2)

        wrapped()
        assert call_results[-1] == "DB version: 2.0"

        # Unregister database
        await injector.unregister_dependency("Database")

        wrapped()
        assert call_results[-1] == "No database"

    @pytest.mark.asyncio
    async def test_mesh_agent_integration(self):
        """Test mesh_agent decorator with dependency injection."""

        # Mock the global injector at the right location
        with patch(
            "mcp_mesh.runtime.dependency_injector.get_global_injector"
        ) as mock_get_injector:
            mock_injector = DependencyInjector()
            mock_get_injector.return_value = mock_injector

            # Register a test dependency
            test_service = Mock(process=Mock(return_value="Processed!"))
            await mock_injector.register_dependency("TestService", test_service)

            # Create function with mesh_agent
            @mesh_agent(capability="processor", dependencies=["TestService"])
            def process_data(data: str = "test", TestService=None) -> str:
                if TestService:
                    return TestService.process(data)
                return f"No service for {data}"

            # Verify wrapper was created
            assert hasattr(process_data, "_update_dependency")
            assert process_data._dependencies == ["TestService"]

            # Test injection
            result = process_data(data="hello")
            assert result == "Processed!"
            test_service.process.assert_called_with("hello")

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

        def query_func(sql: str, Database=None) -> str:
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

        def counter_func(Counter=None) -> int:
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
