"""
Comprehensive Integration Tests for Phase 3: Fallback Chain Implementation

Tests the CRITICAL feature that enables interface-optional dependency injection:
- Seamless degradation from remote to local services
- <200ms performance target for fallback transitions
- Zero Protocol definitions needed
- Same code works in mesh and standalone environments
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from mcp_mesh_runtime.decorators.mesh_agent import mesh_agent
from mcp_mesh_runtime.fallback import (
    FallbackConfiguration,
    FallbackMode,
)
from mcp_mesh_runtime.shared.fallback_chain import MeshFallbackChain
from mcp_mesh_runtime.shared.registry_client import RegistryClient
from mcp_mesh_runtime.shared.service_discovery import ServiceDiscoveryService


# Test service classes for dependency injection
class OAuth2AuthService:
    """Example auth service for testing fallback chain."""

    def __init__(
        self, api_key: str = "test-key", endpoint: str = "https://auth.example.com"
    ):
        self.api_key = api_key
        self.endpoint = endpoint
        self.authenticated = False

    async def authenticate(self, token: str) -> dict:
        """Authenticate a user token."""
        self.authenticated = True
        return {
            "user_id": "user123",
            "scopes": ["read", "write"],
            "token": token,
            "service_type": "local" if hasattr(self, "_is_local") else "remote",
        }

    def get_user_info(self, user_id: str) -> dict:
        """Get user information."""
        return {"user_id": user_id, "name": "Test User", "email": "test@example.com"}


class DataProcessingService:
    """Example data processing service for testing."""

    def __init__(self, workers: int = 4, cache_size: int = 1000):
        self.workers = workers
        self.cache_size = cache_size

    async def process_batch(self, data: list) -> dict:
        """Process a batch of data."""
        await asyncio.sleep(0.01)  # Simulate processing
        return {
            "processed_count": len(data),
            "workers_used": self.workers,
            "service_type": "local" if hasattr(self, "_is_local") else "remote",
        }


class TestFallbackChainCore:
    """Test core fallback chain functionality."""

    @pytest.fixture
    async def registry_client(self):
        """Create a mock registry client."""
        client = AsyncMock(spec=RegistryClient)
        client.get_dependency = AsyncMock(return_value=None)
        return client

    @pytest.fixture
    async def service_discovery(self, registry_client):
        """Create a mock service discovery service."""
        discovery = AsyncMock(spec=ServiceDiscoveryService)
        discovery.find_agents_by_capability = AsyncMock(return_value=[])
        return discovery

    @pytest.fixture
    async def fallback_chain(self, registry_client, service_discovery):
        """Create a fallback chain for testing."""
        config = FallbackConfiguration(
            mode=FallbackMode.REMOTE_FIRST,
            remote_timeout_ms=100.0,
            local_timeout_ms=50.0,
            total_timeout_ms=200.0,
        )

        chain = MeshFallbackChain(
            registry_client=registry_client,
            service_discovery=service_discovery,
            config=config,
        )

        return chain

    async def test_remote_first_fallback_to_local(self, fallback_chain):
        """Test remote-first fallback to local instantiation."""
        start_time = time.perf_counter()

        # Remote should fail, local should succeed
        result = await fallback_chain.resolve_dependency(OAuth2AuthService)

        end_time = time.perf_counter()
        resolution_time_ms = (end_time - start_time) * 1000

        # Verify result
        assert result is not None
        assert isinstance(result, OAuth2AuthService)
        assert hasattr(result, "authenticate")

        # Verify performance target
        assert (
            resolution_time_ms < 200.0
        ), f"Resolution took {resolution_time_ms:.2f}ms, target is <200ms"

        # Verify metrics
        metrics = fallback_chain.get_metrics()
        assert metrics.total_attempts > 0
        assert metrics.local_successes > 0

    async def test_local_only_mode(self):
        """Test local-only resolution mode."""
        config = FallbackConfiguration(
            mode=FallbackMode.LOCAL_ONLY, local_timeout_ms=100.0, total_timeout_ms=150.0
        )

        chain = MeshFallbackChain(config=config)

        start_time = time.perf_counter()
        result = await chain.resolve_dependency(DataProcessingService)
        end_time = time.perf_counter()

        resolution_time_ms = (end_time - start_time) * 1000

        assert result is not None
        assert isinstance(result, DataProcessingService)
        assert resolution_time_ms < 150.0

        # Should only try local resolver
        metrics = chain.get_metrics()
        assert metrics.remote_attempts == 0
        assert metrics.local_attempts > 0

    async def test_performance_under_load(self, fallback_chain):
        """Test fallback chain performance under concurrent load."""
        # Simulate multiple concurrent dependency resolutions
        tasks = []
        for _ in range(20):
            task = asyncio.create_task(
                fallback_chain.resolve_dependency(OAuth2AuthService)
            )
            tasks.append(task)

        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.perf_counter()

        total_time_ms = (end_time - start_time) * 1000
        avg_time_per_resolution = total_time_ms / len(tasks)

        # Verify all resolutions succeeded
        successful_results = [r for r in results if isinstance(r, OAuth2AuthService)]
        assert len(successful_results) == len(tasks)

        # Verify average performance is reasonable
        assert (
            avg_time_per_resolution < 300.0
        ), f"Average resolution time {avg_time_per_resolution:.2f}ms too high"

        # Verify metrics
        metrics = fallback_chain.get_metrics()
        assert metrics.total_attempts == len(tasks)

    async def test_circuit_breaker_functionality(self, fallback_chain):
        """Test circuit breaker prevents repeated failures."""
        # Configure with low failure threshold
        fallback_chain.config.circuit_breaker_failure_threshold = 2
        fallback_chain.config.circuit_breaker_enabled = True

        # Force remote resolver to fail
        with patch.object(
            fallback_chain._service_discovery,
            "find_agents_by_capability",
            side_effect=Exception("Service discovery failed"),
        ):

            # First few attempts should try remote and fail
            for i in range(3):
                result = await fallback_chain.resolve_dependency(OAuth2AuthService)
                assert result is not None  # Should fall back to local

            # Check that circuit breaker is now open for remote resolver
            assert fallback_chain._is_circuit_breaker_open("remote_proxy")

    async def test_caching_behavior(self, fallback_chain):
        """Test caching of successful resolutions."""
        fallback_chain.config.cache_successful_resolutions = True
        fallback_chain.config.cache_ttl_seconds = 1.0

        # First resolution
        start_time = time.perf_counter()
        result1 = await fallback_chain.resolve_dependency(OAuth2AuthService)
        first_resolution_time = (time.perf_counter() - start_time) * 1000

        # Second resolution (should use cache)
        start_time = time.perf_counter()
        result2 = await fallback_chain.resolve_dependency(OAuth2AuthService)
        cached_resolution_time = (time.perf_counter() - start_time) * 1000

        assert result1 is not None
        assert result2 is not None
        assert result1 is result2  # Same cached instance
        assert (
            cached_resolution_time < first_resolution_time / 2
        )  # Should be much faster


class TestInterfaceOptionalDependencyInjection:
    """Test the CRITICAL interface-optional dependency injection feature."""

    async def test_mesh_agent_with_fallback_dependencies(self):
        """Test @mesh_agent decorator with fallback dependencies."""

        @mesh_agent(
            capabilities=["secure_operation"],
            dependencies=["OAuth2AuthService"],
            fallback_mode=True,
        )
        async def secure_operation(auth: OAuth2AuthService) -> dict:
            """A function that needs auth service - works with remote OR local!"""
            return await auth.authenticate("test-token-123")

        # Test the decorated function
        start_time = time.perf_counter()
        result = await secure_operation()
        end_time = time.perf_counter()

        resolution_time_ms = (end_time - start_time) * 1000

        # Verify the function worked
        assert result is not None
        assert result["user_id"] == "user123"
        assert result["token"] == "test-token-123"

        # Verify performance target
        assert (
            resolution_time_ms < 300.0
        ), f"Total execution took {resolution_time_ms:.2f}ms"

    async def test_class_decoration_with_dependencies(self):
        """Test class decoration with dependency injection."""

        @mesh_agent(
            capabilities=["data_processing"],
            dependencies=["DataProcessingService"],
            fallback_mode=True,
        )
        class DataProcessor:
            async def process_user_data(
                self, processor: DataProcessingService, user_data: list
            ) -> dict:
                """Process user data using injected service."""
                return await processor.process_batch(user_data)

            def get_stats(self, processor: DataProcessingService) -> dict:
                """Get processing stats."""
                return {
                    "workers": processor.workers,
                    "cache_size": processor.cache_size,
                }

        # Create instance and test
        dp = DataProcessor()

        # Test async method
        result = await dp.process_user_data([1, 2, 3, 4, 5])
        assert result["processed_count"] == 5
        assert "service_type" in result

        # Test sync method
        stats = dp.get_stats()
        assert "workers" in stats
        assert "cache_size" in stats

    async def test_mixed_remote_and_local_dependencies(self):
        """Test handling multiple dependencies with different resolution paths."""

        @mesh_agent(
            capabilities=["advanced_processing"],
            dependencies=["OAuth2AuthService", "DataProcessingService"],
            fallback_mode=True,
        )
        async def advanced_secure_processing(
            auth: OAuth2AuthService, processor: DataProcessingService, data: list
        ) -> dict:
            """Function with multiple injected dependencies."""
            # Authenticate first
            auth_result = await auth.authenticate("admin-token")

            # Process data
            process_result = await processor.process_batch(data)

            return {
                "auth": auth_result,
                "processing": process_result,
                "total_items": len(data),
            }

        # Test with multiple dependencies
        test_data = list(range(10))
        result = await advanced_secure_processing(data=test_data)

        assert result["auth"]["user_id"] == "user123"
        assert result["processing"]["processed_count"] == 10
        assert result["total_items"] == 10

    async def test_graceful_degradation_with_partial_failures(self):
        """Test graceful degradation when some dependencies fail."""

        @mesh_agent(
            capabilities=["resilient_operation"],
            dependencies=["OAuth2AuthService"],
            fallback_mode=True,
        )
        async def resilient_operation(auth: OAuth2AuthService | None = None) -> dict:
            """Function that gracefully handles missing dependencies."""
            if auth:
                auth_result = await auth.authenticate("fallback-token")
                return {"authenticated": True, "user": auth_result["user_id"]}
            else:
                return {"authenticated": False, "user": "anonymous"}

        # Should work even if dependency injection fails
        result = await resilient_operation()

        # In our test case, it should succeed with local fallback
        assert result["authenticated"] is True
        assert result["user"] == "user123"


class TestPerformanceOptimization:
    """Test performance optimizations for <200ms target."""

    async def test_parallel_dependency_resolution(self):
        """Test parallel resolution of multiple dependencies."""

        @mesh_agent(
            capabilities=["parallel_processing"],
            dependencies=["OAuth2AuthService", "DataProcessingService"],
            fallback_mode=True,
        )
        async def parallel_operation(
            auth: OAuth2AuthService, processor: DataProcessingService
        ) -> dict:
            """Function with multiple dependencies resolved in parallel."""
            # Dependencies should be resolved in parallel during injection
            auth_task = auth.authenticate("parallel-token")
            process_task = processor.process_batch([1, 2, 3])

            auth_result, process_result = await asyncio.gather(auth_task, process_task)

            return {"auth": auth_result, "processing": process_result}

        start_time = time.perf_counter()
        result = await parallel_operation()
        end_time = time.perf_counter()

        execution_time_ms = (end_time - start_time) * 1000

        assert result["auth"]["user_id"] == "user123"
        assert result["processing"]["processed_count"] == 3

        # Should complete well under performance target
        assert (
            execution_time_ms < 150.0
        ), f"Parallel operation took {execution_time_ms:.2f}ms"

    async def test_timeout_and_performance_monitoring(self):
        """Test timeout handling and performance monitoring."""
        config = FallbackConfiguration(
            mode=FallbackMode.REMOTE_FIRST,
            remote_timeout_ms=50.0,  # Very aggressive timeout
            local_timeout_ms=25.0,
            total_timeout_ms=100.0,
            enable_detailed_metrics=True,
            enable_performance_logging=True,
        )

        chain = MeshFallbackChain(config=config)

        # Test multiple resolutions to gather metrics
        resolution_times = []
        for _ in range(10):
            start_time = time.perf_counter()
            result = await chain.resolve_dependency(OAuth2AuthService)
            end_time = time.perf_counter()

            resolution_time_ms = (end_time - start_time) * 1000
            resolution_times.append(resolution_time_ms)

            assert result is not None
            assert resolution_time_ms < 100.0

        # Verify performance consistency
        avg_time = sum(resolution_times) / len(resolution_times)
        max_time = max(resolution_times)

        assert avg_time < 75.0, f"Average resolution time {avg_time:.2f}ms too high"
        assert max_time < 100.0, f"Max resolution time {max_time:.2f}ms exceeded limit"

        # Check metrics
        metrics = chain.get_metrics()
        assert metrics.average_resolution_time_ms < 75.0
        assert metrics.total_attempts == 10


class TestRealWorldScenarios:
    """Test real-world scenarios for fallback chain."""

    async def test_microservice_environment_simulation(self):
        """Simulate a microservice environment with varying availability."""

        # Create services with different availability patterns
        @mesh_agent(
            capabilities=["user_service"],
            dependencies=["OAuth2AuthService"],
            fallback_mode=True,
        )
        async def user_service(auth: OAuth2AuthService, user_id: str) -> dict:
            """User service that depends on auth."""
            auth_result = await auth.authenticate(f"token-{user_id}")
            user_info = auth.get_user_info(user_id)

            return {"user": user_info, "auth": auth_result, "service": "user_service"}

        @mesh_agent(
            capabilities=["order_service"],
            dependencies=["DataProcessingService"],
            fallback_mode=True,
        )
        async def order_service(processor: DataProcessingService, orders: list) -> dict:
            """Order service that depends on data processing."""
            result = await processor.process_batch(orders)

            return {
                "orders_processed": result["processed_count"],
                "service": "order_service",
            }

        # Simulate concurrent requests to both services
        tasks = []

        # User service requests
        for i in range(5):
            task = asyncio.create_task(user_service(user_id=f"user{i}"))
            tasks.append(task)

        # Order service requests
        for i in range(5):
            orders = [f"order{j}" for j in range(i + 1, i + 4)]
            task = asyncio.create_task(order_service(orders=orders))
            tasks.append(task)

        # Execute all requests concurrently
        start_time = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.perf_counter()

        total_time_ms = (end_time - start_time) * 1000

        # Verify all requests succeeded
        successful_results = [r for r in results if isinstance(r, dict)]
        assert len(successful_results) == 10

        # Verify reasonable performance
        avg_time_per_request = total_time_ms / len(tasks)
        assert (
            avg_time_per_request < 200.0
        ), f"Average request time {avg_time_per_request:.2f}ms too high"

        # Verify service differentiation
        user_results = [
            r for r in successful_results if r.get("service") == "user_service"
        ]
        order_results = [
            r for r in successful_results if r.get("service") == "order_service"
        ]

        assert len(user_results) == 5
        assert len(order_results) == 5

    async def test_network_partition_simulation(self):
        """Simulate network partition and recovery."""

        @mesh_agent(
            capabilities=["critical_service"],
            dependencies=["OAuth2AuthService"],
            fallback_mode=True,
        )
        async def critical_service(auth: OAuth2AuthService) -> dict:
            """Critical service that must work even during network issues."""
            result = await auth.authenticate("critical-token")
            return {"critical_operation": "completed", "auth": result}

        # Test during "network partition" (all remote services fail)
        # In our test setup, this will always fall back to local
        results = []

        for i in range(5):
            start_time = time.perf_counter()
            result = await critical_service()
            end_time = time.perf_counter()

            resolution_time = (end_time - start_time) * 1000

            results.append({"result": result, "time_ms": resolution_time})

        # Verify all operations succeeded despite "network issues"
        for r in results:
            assert r["result"]["critical_operation"] == "completed"
            assert r["result"]["auth"]["user_id"] == "user123"
            assert r["time_ms"] < 200.0  # Should still meet performance target

        # Verify consistent performance during degraded conditions
        times = [r["time_ms"] for r in results]
        avg_time = sum(times) / len(times)
        assert (
            avg_time < 150.0
        ), f"Performance degraded too much: {avg_time:.2f}ms average"


# Performance benchmark test
@pytest.mark.performance
class TestPerformanceBenchmarks:
    """Benchmark tests for fallback chain performance."""

    async def test_fallback_transition_benchmark(self):
        """Benchmark the critical remote→local fallback transition."""
        config = FallbackConfiguration(
            mode=FallbackMode.REMOTE_FIRST,
            remote_timeout_ms=50.0,  # Force quick timeout
            local_timeout_ms=50.0,
            total_timeout_ms=150.0,
        )

        chain = MeshFallbackChain(config=config)

        # Benchmark 100 fallback transitions
        transition_times = []

        for _ in range(100):
            start_time = time.perf_counter()
            result = await chain.resolve_dependency(OAuth2AuthService)
            end_time = time.perf_counter()

            transition_time_ms = (end_time - start_time) * 1000
            transition_times.append(transition_time_ms)

            assert result is not None

        # Calculate statistics
        avg_time = sum(transition_times) / len(transition_times)
        min_time = min(transition_times)
        max_time = max(transition_times)
        p95_time = sorted(transition_times)[int(0.95 * len(transition_times))]

        print("\nFallback Transition Performance Benchmark:")
        print(f"  Average: {avg_time:.2f}ms")
        print(f"  Min: {min_time:.2f}ms")
        print(f"  Max: {max_time:.2f}ms")
        print(f"  P95: {p95_time:.2f}ms")

        # Verify performance targets
        assert (
            avg_time < 100.0
        ), f"Average fallback time {avg_time:.2f}ms exceeds 100ms target"
        assert (
            p95_time < 150.0
        ), f"P95 fallback time {p95_time:.2f}ms exceeds 150ms target"
        assert (
            max_time < 200.0
        ), f"Max fallback time {max_time:.2f}ms exceeds 200ms limit"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])
