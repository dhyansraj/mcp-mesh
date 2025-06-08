"""
Performance and Load Tests

Comprehensive performance and load testing for File Agent operations,
MCP protocol handling, and mesh integration under various load conditions.
"""

import asyncio
import gc
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import psutil
import pytest
from mcp_mesh_runtime.shared.exceptions import RateLimitError, TransientError
from mcp_mesh_runtime.shared.types import RetryConfig, RetryStrategy
from mcp_mesh_runtime.tools.file_operations import FileOperations


class PerformanceMetrics:
    """Utility class for collecting and analyzing performance metrics."""

    def __init__(self):
        self.operation_times: dict[str, list[float]] = {}
        self.memory_samples: list[float] = []
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.errors: list[dict[str, Any]] = []

    def start_measurement(self) -> None:
        """Start performance measurement."""
        self.start_time = time.time()
        gc.collect()  # Clean up before measurement

    def end_measurement(self) -> None:
        """End performance measurement."""
        self.end_time = time.time()
        gc.collect()  # Clean up after measurement

    def record_operation(self, operation: str, duration: float) -> None:
        """Record operation timing."""
        if operation not in self.operation_times:
            self.operation_times[operation] = []
        self.operation_times[operation].append(duration)

    def record_memory_sample(self) -> None:
        """Record current memory usage."""
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        self.memory_samples.append(memory_mb)

    def record_error(self, operation: str, error: Exception) -> None:
        """Record error occurrence."""
        self.errors.append(
            {
                "operation": operation,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "timestamp": time.time(),
            }
        )

    def get_statistics(self) -> dict[str, Any]:
        """Get comprehensive performance statistics."""
        stats = {
            "total_duration": (
                self.end_time - self.start_time
                if self.start_time and self.end_time
                else 0
            ),
            "operations": {},
            "memory": {},
            "errors": {
                "total_count": len(self.errors),
                "error_types": {},
                "error_rate": 0,
            },
        }

        # Operation statistics
        total_operations = 0
        for operation, times in self.operation_times.items():
            if times:
                stats["operations"][operation] = {
                    "count": len(times),
                    "mean": statistics.mean(times),
                    "median": statistics.median(times),
                    "min": min(times),
                    "max": max(times),
                    "std_dev": statistics.stdev(times) if len(times) > 1 else 0,
                    "p95": self._percentile(times, 95),
                    "p99": self._percentile(times, 99),
                    "ops_per_second": (
                        len(times) / stats["total_duration"]
                        if stats["total_duration"] > 0
                        else 0
                    ),
                }
                total_operations += len(times)

        # Memory statistics
        if self.memory_samples:
            stats["memory"] = {
                "samples": len(self.memory_samples),
                "mean_mb": statistics.mean(self.memory_samples),
                "max_mb": max(self.memory_samples),
                "min_mb": min(self.memory_samples),
                "std_dev_mb": (
                    statistics.stdev(self.memory_samples)
                    if len(self.memory_samples) > 1
                    else 0
                ),
            }

        # Error statistics
        if self.errors:
            error_types = {}
            for error in self.errors:
                error_type = error["error_type"]
                if error_type not in error_types:
                    error_types[error_type] = 0
                error_types[error_type] += 1

            stats["errors"]["error_types"] = error_types
            stats["errors"]["error_rate"] = (
                len(self.errors) / total_operations if total_operations > 0 else 0
            )

        return stats

    def _percentile(self, data: list[float], percentile: int) -> float:
        """Calculate percentile value."""
        if not data:
            return 0
        sorted_data = sorted(data)
        index = int((percentile / 100) * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]


class LoadTestEnvironment:
    """Environment for load testing."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(tempfile.mkdtemp())
        self.file_ops: FileOperations | None = None
        self.mock_registry = AsyncMock()
        self.metrics = PerformanceMetrics()

        # Setup mock registry
        self.mock_registry.get_dependency.return_value = "mock-service-v1.0.0"
        self.mock_registry.register_agent = AsyncMock()
        self.mock_registry.send_heartbeat = AsyncMock()
        self.mock_registry.close = AsyncMock()

    async def setup(self, max_file_size: int = 100 * 1024 * 1024) -> None:
        """Setup load test environment."""
        with patch(
            "mcp_mesh.decorators.mesh_agent.RegistryClient",
            return_value=self.mock_registry,
        ):
            self.file_ops = FileOperations(
                base_directory=str(self.base_dir), max_file_size=max_file_size
            )

    async def cleanup(self) -> None:
        """Cleanup test environment."""
        if self.file_ops:
            await self.file_ops.cleanup()

        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)

    async def run_timed_operation(self, operation_name: str, operation_func) -> Any:
        """Run operation with timing measurement."""
        start_time = time.time()
        self.metrics.record_memory_sample()

        try:
            result = await operation_func()
            duration = time.time() - start_time
            self.metrics.record_operation(operation_name, duration)
            return result
        except Exception as e:
            duration = time.time() - start_time
            self.metrics.record_operation(operation_name, duration)
            self.metrics.record_error(operation_name, e)
            raise


@pytest.fixture
async def load_env():
    """Create load test environment."""
    env = LoadTestEnvironment()
    await env.setup()
    yield env
    await env.cleanup()


class TestFileOperationPerformance:
    """Test performance of core file operations."""

    async def test_single_file_read_performance(self, load_env):
        """Test read performance for various file sizes."""
        env = load_env
        env.metrics.start_measurement()

        # Test different file sizes
        file_sizes = [
            (1024, "1KB"),
            (10 * 1024, "10KB"),
            (100 * 1024, "100KB"),
            (1024 * 1024, "1MB"),
            (10 * 1024 * 1024, "10MB"),
        ]

        for size_bytes, size_label in file_sizes:
            # Create test file
            content = "x" * size_bytes
            file_path = str(env.base_dir / f"test_{size_label}.txt")
            await env.file_ops.write_file(file_path, content)

            # Measure read performance (multiple iterations)
            iterations = 5
            for _i in range(iterations):
                operation_name = f"read_{size_label}"
                result = await env.run_timed_operation(
                    operation_name, lambda: env.file_ops.read_file(file_path)
                )
                assert len(result) == size_bytes

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Verify performance characteristics
        for size_bytes, size_label in file_sizes:
            operation_name = f"read_{size_label}"
            if operation_name in stats["operations"]:
                op_stats = stats["operations"][operation_name]

                # Basic performance assertions
                assert op_stats["count"] == 5  # 5 iterations
                assert op_stats["mean"] > 0
                assert op_stats["error_rate"] == 0  # No errors expected

                # Performance should scale reasonably with file size
                if size_bytes <= 1024 * 1024:  # Up to 1MB
                    assert op_stats["p95"] < 1.0  # 95th percentile under 1 second

    async def test_write_performance_with_backups(self, load_env):
        """Test write performance with backup creation."""
        env = load_env
        env.metrics.start_measurement()

        # Test write performance with different content sizes
        content_sizes = [(1024, "1KB"), (50 * 1024, "50KB"), (500 * 1024, "500KB")]

        iterations = 3

        for size_bytes, size_label in content_sizes:
            content = "data " * (
                size_bytes // 5
            )  # Create content of approximately target size

            for i in range(iterations):
                file_path = str(env.base_dir / f"write_test_{size_label}_{i}.txt")

                # Test write without backup
                operation_name = f"write_no_backup_{size_label}"
                result = await env.run_timed_operation(
                    operation_name,
                    lambda: env.file_ops.write_file(
                        file_path, content, create_backup=False
                    ),
                )
                assert result is True

                # Test write with backup (file exists now)
                operation_name = f"write_with_backup_{size_label}"
                updated_content = content + " updated"
                result = await env.run_timed_operation(
                    operation_name,
                    lambda: env.file_ops.write_file(
                        file_path, updated_content, create_backup=True
                    ),
                )
                assert result is True

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Analyze backup overhead
        for size_bytes, size_label in content_sizes:
            no_backup_key = f"write_no_backup_{size_label}"
            with_backup_key = f"write_with_backup_{size_label}"

            if (
                no_backup_key in stats["operations"]
                and with_backup_key in stats["operations"]
            ):
                no_backup_mean = stats["operations"][no_backup_key]["mean"]
                with_backup_mean = stats["operations"][with_backup_key]["mean"]

                # Backup overhead should be reasonable (less than 3x slower)
                backup_overhead = with_backup_mean / no_backup_mean
                assert (
                    backup_overhead < 3.0
                ), f"Backup overhead too high: {backup_overhead:.2f}x"

    async def test_directory_listing_performance(self, load_env):
        """Test directory listing performance with many files."""
        env = load_env
        env.metrics.start_measurement()

        # Create directories with different numbers of files
        file_counts = [10, 50, 100, 500]

        for file_count in file_counts:
            # Create test directory
            test_dir = env.base_dir / f"test_dir_{file_count}"
            test_dir.mkdir()

            # Create files
            for i in range(file_count):
                file_path = test_dir / f"file_{i:04d}.txt"
                file_path.write_text(f"Content for file {i}")

            # Test basic listing
            operation_name = f"list_basic_{file_count}"
            result = await env.run_timed_operation(
                operation_name, lambda: env.file_ops.list_directory(str(test_dir))
            )
            assert len(result) == file_count

            # Test detailed listing
            operation_name = f"list_detailed_{file_count}"
            result = await env.run_timed_operation(
                operation_name,
                lambda: env.file_ops.list_directory(
                    str(test_dir), include_details=True
                ),
            )
            assert len(result) == file_count
            assert all("size" in entry for entry in result)

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Verify listing performance scales reasonably
        for file_count in file_counts:
            basic_key = f"list_basic_{file_count}"
            detailed_key = f"list_detailed_{file_count}"

            if basic_key in stats["operations"]:
                basic_stats = stats["operations"][basic_key]
                assert basic_stats["mean"] < 2.0  # Should complete within 2 seconds

            if detailed_key in stats["operations"]:
                detailed_stats = stats["operations"][detailed_key]
                # Detailed listing should be slower but still reasonable
                assert detailed_stats["mean"] < 5.0


class TestConcurrentOperationPerformance:
    """Test performance under concurrent operation loads."""

    async def test_concurrent_read_performance(self, load_env):
        """Test performance of concurrent read operations."""
        env = load_env
        env.metrics.start_measurement()

        # Setup test files
        num_files = 20
        test_files = []

        for i in range(num_files):
            file_path = str(env.base_dir / f"concurrent_read_{i}.txt")
            content = (
                f"Content for concurrent read test file {i} " * 100
            )  # ~4KB per file
            await env.file_ops.write_file(file_path, content)
            test_files.append((file_path, content))

        # Test different levels of concurrency
        concurrency_levels = [1, 5, 10, 20]

        for concurrency in concurrency_levels:
            # Select files for this test
            selected_files = test_files[:concurrency]

            # Concurrent read operations
            async def read_file_timed(file_info):
                file_path, expected_content = file_info
                return await env.run_timed_operation(
                    f"concurrent_read_{concurrency}",
                    lambda: env.file_ops.read_file(file_path),
                )

            # Execute concurrent reads
            start_time = time.time()
            tasks = [read_file_timed(file_info) for file_info in selected_files]
            results = await asyncio.gather(*tasks)
            end_time = time.time()

            # Verify results
            assert len(results) == concurrency
            for i, (result, (_, expected_content)) in enumerate(
                zip(results, selected_files, strict=False)
            ):
                assert result == expected_content

            # Record overall concurrency performance
            total_duration = end_time - start_time
            env.metrics.record_operation(
                f"concurrent_batch_{concurrency}", total_duration
            )

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Analyze concurrency scaling
        batch_times = {}
        for concurrency in concurrency_levels:
            batch_key = f"concurrent_batch_{concurrency}"
            if batch_key in stats["operations"]:
                batch_times[concurrency] = stats["operations"][batch_key]["mean"]

        # Verify reasonable concurrency scaling
        if len(batch_times) >= 2:
            # Higher concurrency shouldn't be dramatically slower for I/O bound operations
            max_time = max(batch_times.values())
            min_time = min(batch_times.values())
            scaling_factor = max_time / min_time

            # Allow for some overhead, but shouldn't be more than 3x slower
            assert (
                scaling_factor < 3.0
            ), f"Poor concurrency scaling: {scaling_factor:.2f}x"

    async def test_mixed_operation_concurrency(self, load_env):
        """Test performance of mixed concurrent operations."""
        env = load_env
        env.metrics.start_measurement()

        # Setup base files
        base_files = {}
        for i in range(10):
            file_path = str(env.base_dir / f"mixed_test_{i}.txt")
            content = f"Initial content {i}"
            await env.file_ops.write_file(file_path, content)
            base_files[i] = (file_path, content)

        # Mixed operation scenarios
        scenarios = [
            ("light_load", 10, 0.1),
            ("medium_load", 25, 0.05),
            ("heavy_load", 50, 0.02),
        ]

        for scenario_name, total_ops, think_time in scenarios:
            operations = []

            # Generate mixed operations
            for op_num in range(total_ops):
                op_type = op_num % 4  # Cycle through operation types
                file_idx = op_num % len(base_files)
                file_path, base_content = base_files[file_idx]

                if op_type == 0:  # Read operation

                    async def read_op():
                        await asyncio.sleep(think_time)  # Simulate user think time
                        return await env.run_timed_operation(
                            f"mixed_read_{scenario_name}",
                            lambda: env.file_ops.read_file(file_path),
                        )

                    operations.append(read_op())

                elif op_type == 1:  # Write operation
                    new_content = f"Updated content {op_num}"

                    async def write_op():
                        await asyncio.sleep(think_time)
                        return await env.run_timed_operation(
                            f"mixed_write_{scenario_name}",
                            lambda: env.file_ops.write_file(file_path, new_content),
                        )

                    operations.append(write_op())

                elif op_type == 2:  # List operation

                    async def list_op():
                        await asyncio.sleep(think_time)
                        return await env.run_timed_operation(
                            f"mixed_list_{scenario_name}",
                            lambda: env.file_ops.list_directory(str(env.base_dir)),
                        )

                    operations.append(list_op())

                else:  # Write with backup
                    backup_content = f"Backup content {op_num}"

                    async def backup_write_op():
                        await asyncio.sleep(think_time)
                        return await env.run_timed_operation(
                            f"mixed_backup_{scenario_name}",
                            lambda: env.file_ops.write_file(
                                file_path, backup_content, create_backup=True
                            ),
                        )

                    operations.append(backup_write_op())

            # Execute mixed operations
            start_time = time.time()
            results = await asyncio.gather(*operations, return_exceptions=True)
            end_time = time.time()

            # Count successful operations
            successful_ops = [r for r in results if not isinstance(r, Exception)]
            [r for r in results if isinstance(r, Exception)]

            success_rate = len(successful_ops) / len(results)
            total_duration = end_time - start_time

            env.metrics.record_operation(
                f"mixed_scenario_{scenario_name}", total_duration
            )

            # Verify reasonable success rate and performance
            assert (
                success_rate >= 0.95
            ), f"Low success rate for {scenario_name}: {success_rate:.2%}"

            # Calculate throughput
            throughput = len(successful_ops) / total_duration
            env.metrics.record_operation(f"throughput_{scenario_name}", throughput)

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Verify throughput scaling
        throughputs = {}
        for scenario_name, _, _ in scenarios:
            throughput_key = f"throughput_{scenario_name}"
            if throughput_key in stats["operations"]:
                throughputs[scenario_name] = stats["operations"][throughput_key]["mean"]

        # System should handle at least 5 ops/second under load
        for scenario, throughput in throughputs.items():
            assert (
                throughput >= 5.0
            ), f"Low throughput for {scenario}: {throughput:.2f} ops/sec"


class TestScalabilityAndLimits:
    """Test system scalability and operational limits."""

    async def test_memory_usage_under_load(self, load_env):
        """Test memory usage patterns under sustained load."""
        env = load_env
        env.metrics.start_measurement()

        # Baseline memory measurement
        env.metrics.record_memory_sample()

        # Create sustained load with varying file sizes
        sustained_duration = 10  # seconds
        end_time = time.time() + sustained_duration

        operation_count = 0
        file_sizes = [1024, 10240, 102400]  # 1KB, 10KB, 100KB

        while time.time() < end_time:
            # Cycle through different file sizes
            size = file_sizes[operation_count % len(file_sizes)]
            content = "x" * size

            file_path = str(env.base_dir / f"memory_test_{operation_count}.txt")

            # Write file
            await env.run_timed_operation(
                "memory_load_write", lambda: env.file_ops.write_file(file_path, content)
            )

            # Read file back
            result = await env.run_timed_operation(
                "memory_load_read", lambda: env.file_ops.read_file(file_path)
            )
            assert len(result) == size

            operation_count += 1

            # Sample memory every 10 operations
            if operation_count % 10 == 0:
                env.metrics.record_memory_sample()

                # Clean up old files to prevent disk space issues
                if operation_count > 50:
                    old_file = env.base_dir / f"memory_test_{operation_count - 50}.txt"
                    if old_file.exists():
                        old_file.unlink()

        # Final memory measurement
        env.metrics.record_memory_sample()
        env.metrics.end_measurement()

        stats = env.metrics.get_statistics()

        # Verify memory stability
        if stats["memory"]["samples"] > 2:
            memory_growth = stats["memory"]["max_mb"] - stats["memory"]["min_mb"]

            # Memory growth should be reasonable (less than 100MB over test duration)
            assert (
                memory_growth < 100
            ), f"Excessive memory growth: {memory_growth:.2f} MB"

            # Memory standard deviation should be reasonable
            assert (
                stats["memory"]["std_dev_mb"] < 50
            ), f"High memory variance: {stats['memory']['std_dev_mb']:.2f} MB"

        # Verify operation count and performance
        assert operation_count >= 20, f"Too few operations completed: {operation_count}"

        # Check operation performance remained stable
        if "memory_load_write" in stats["operations"]:
            write_stats = stats["operations"]["memory_load_write"]
            assert (
                write_stats["p95"] < 1.0
            ), "Write performance degraded under sustained load"

    async def test_rate_limiting_behavior(self, load_env):
        """Test rate limiting behavior under high load."""
        env = load_env

        # Configure aggressive rate limits for testing
        original_max_ops = env.file_ops._max_operations_per_minute
        original_window = env.file_ops._rate_limit_window

        env.file_ops._max_operations_per_minute = 10  # Very low limit
        env.file_ops._rate_limit_window = 5  # 5 second window

        try:
            env.metrics.start_measurement()

            # Attempt rapid operations to trigger rate limiting
            rapid_ops = 20  # More than rate limit

            tasks = []
            for i in range(rapid_ops):
                file_path = str(env.base_dir / f"rate_limit_test_{i}.txt")
                content = f"Rate limit test content {i}"

                task = env.run_timed_operation(
                    "rate_limited_write",
                    lambda: env.file_ops.write_file(file_path, content),
                )
                tasks.append(task)

            # Execute all operations
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Analyze results
            successful_ops = [r for r in results if r is True]
            rate_limit_errors = [r for r in results if isinstance(r, RateLimitError)]
            other_errors = [
                r
                for r in results
                if isinstance(r, Exception) and not isinstance(r, RateLimitError)
            ]

            env.metrics.end_measurement()
            env.metrics.get_statistics()

            # Verify rate limiting worked
            assert (
                len(rate_limit_errors) > 0
            ), "Rate limiting should have been triggered"
            assert (
                len(successful_ops) <= env.file_ops._max_operations_per_minute
            ), "Too many operations succeeded"

            # Should have minimal other errors
            assert (
                len(other_errors) < rapid_ops * 0.1
            ), f"Too many non-rate-limit errors: {len(other_errors)}"

            # Verify rate limit errors contain retry information
            for error in rate_limit_errors:
                assert hasattr(
                    error, "retry_after"
                ), "Rate limit error should include retry_after"
                assert error.retry_after > 0, "retry_after should be positive"

        finally:
            # Restore original rate limits
            env.file_ops._max_operations_per_minute = original_max_ops
            env.file_ops._rate_limit_window = original_window

    async def test_error_recovery_performance(self, load_env):
        """Test performance of error recovery mechanisms."""
        env = load_env
        env.metrics.start_measurement()

        # Configure fast retry for testing
        retry_config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=3,
            initial_delay_ms=10,  # Very fast for testing
            max_delay_ms=100,
            backoff_multiplier=2.0,
            jitter=False,  # Deterministic for testing
        )

        # Test scenarios with different failure rates
        failure_scenarios = [
            ("low_failure", 0.1),  # 10% failure rate
            ("medium_failure", 0.3),  # 30% failure rate
            ("high_failure", 0.5),  # 50% failure rate
        ]

        for scenario_name, failure_rate in failure_scenarios:
            operations_per_scenario = 20
            failure_count = 0

            for i in range(operations_per_scenario):
                file_path = str(env.base_dir / f"recovery_test_{scenario_name}_{i}.txt")
                content = f"Recovery test content {i}"

                # Simulate failures based on failure rate
                should_fail = (i / operations_per_scenario) < failure_rate

                if should_fail:
                    # Create a failing operation
                    async def failing_operation():
                        failure_count += 1
                        if failure_count <= 2:  # Fail first 2 attempts
                            raise TransientError("Simulated failure", retry_delay=0.01)
                        # Succeed on 3rd attempt
                        return await env.file_ops.write_file(file_path, content)

                    # Execute with retry
                    result = await env.run_timed_operation(
                        f"recovery_{scenario_name}",
                        lambda: env.file_ops._execute_with_retry(
                            failing_operation, retry_config
                        ),
                    )
                    assert result is True

                else:
                    # Normal operation
                    result = await env.run_timed_operation(
                        f"normal_{scenario_name}",
                        lambda: env.file_ops.write_file(file_path, content),
                    )
                    assert result is True

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Analyze recovery performance
        for scenario_name, failure_rate in failure_scenarios:
            recovery_key = f"recovery_{scenario_name}"
            normal_key = f"normal_{scenario_name}"

            if (
                recovery_key in stats["operations"]
                and normal_key in stats["operations"]
            ):
                recovery_time = stats["operations"][recovery_key]["mean"]
                normal_time = stats["operations"][normal_key]["mean"]

                # Recovery should be slower but not excessively so
                recovery_overhead = recovery_time / normal_time
                assert (
                    recovery_overhead < 10.0
                ), f"Excessive recovery overhead: {recovery_overhead:.2f}x"


class TestMeshIntegrationPerformance:
    """Test performance of mesh integration features."""

    async def test_dependency_injection_performance(self, load_env):
        """Test performance impact of dependency injection."""
        env = load_env

        # Test with and without dependency injection
        test_scenarios = [
            ("no_dependencies", []),
            ("light_dependencies", ["auth_service"]),
            ("heavy_dependencies", ["auth_service", "audit_logger", "backup_service"]),
        ]

        for scenario_name, dependencies in test_scenarios:
            env.metrics.start_measurement()

            # Configure mock to simulate dependency resolution time
            async def mock_get_dependency_with_delay(dep_name: str):
                await asyncio.sleep(0.01)  # 10ms delay per dependency
                return f"mock-{dep_name}-v1.0.0"

            env.mock_registry.get_dependency = mock_get_dependency_with_delay

            # Run file operations
            operations = 10
            for i in range(operations):
                file_path = str(env.base_dir / f"dep_test_{scenario_name}_{i}.txt")
                content = f"Dependency test content {i}"

                # Write operation (triggers dependency injection)
                result = await env.run_timed_operation(
                    f"write_with_deps_{scenario_name}",
                    lambda: env.file_ops.write_file(file_path, content),
                )
                assert result is True

                # Read operation (also triggers dependency injection)
                result = await env.run_timed_operation(
                    f"read_with_deps_{scenario_name}",
                    lambda: env.file_ops.read_file(file_path),
                )
                assert result == content

            env.metrics.end_measurement()

        stats = env.metrics.get_statistics()

        # Analyze dependency injection overhead
        baseline_scenario = "no_dependencies"
        if f"write_with_deps_{baseline_scenario}" in stats["operations"]:
            baseline_write = stats["operations"][
                f"write_with_deps_{baseline_scenario}"
            ]["mean"]

            for scenario_name, dependencies in test_scenarios[1:]:  # Skip baseline
                write_key = f"write_with_deps_{scenario_name}"
                if write_key in stats["operations"]:
                    dep_write_time = stats["operations"][write_key]["mean"]
                    overhead = dep_write_time / baseline_write

                    # Dependency injection overhead should be reasonable
                    max_expected_overhead = 1 + (
                        len(dependencies) * 0.5
                    )  # 50% per dependency
                    assert (
                        overhead < max_expected_overhead
                    ), f"High dependency overhead: {overhead:.2f}x"

    async def test_health_monitoring_performance(self, load_env):
        """Test performance impact of health monitoring."""
        env = load_env
        env.metrics.start_measurement()

        # Run operations while health monitoring is active
        operations = 30
        health_checks = []

        for i in range(operations):
            file_path = str(env.base_dir / f"health_test_{i}.txt")
            content = f"Health monitoring test content {i}"

            # File operation
            result = await env.run_timed_operation(
                "operation_with_health_monitoring",
                lambda: env.file_ops.write_file(file_path, content),
            )
            assert result is True

            # Periodic health check
            if i % 5 == 0:  # Every 5 operations
                health_status = await env.run_timed_operation(
                    "health_check", lambda: env.file_ops.health_check()
                )
                health_checks.append(health_status)

        env.metrics.end_measurement()
        stats = env.metrics.get_statistics()

        # Verify health checks completed successfully
        assert len(health_checks) == 6  # Every 5 operations + initial

        for health_status in health_checks:
            assert health_status.agent_name == "file-operations-agent"
            assert hasattr(health_status, "status")
            assert hasattr(health_status, "capabilities")

        # Verify health check performance
        if "health_check" in stats["operations"]:
            health_stats = stats["operations"]["health_check"]
            assert health_stats["mean"] < 0.1, "Health checks should be fast"
            assert (
                health_stats["p95"] < 0.2
            ), "Health check 95th percentile should be under 200ms"

        # Verify operation performance wasn't significantly impacted
        if "operation_with_health_monitoring" in stats["operations"]:
            op_stats = stats["operations"]["operation_with_health_monitoring"]
            assert (
                op_stats["mean"] < 0.5
            ), "Operations should remain fast with health monitoring"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
