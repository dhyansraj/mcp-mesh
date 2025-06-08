"""
Performance unit tests for File Agent tools.

Tests operation performance, memory usage, concurrent operation safety,
and resource cleanup within acceptable limits.
"""

import asyncio
import shutil
import tempfile
import time

import pytest

try:
    import psutil
except ImportError:
    psutil = None
import gc
from pathlib import Path

from mcp_mesh_runtime.shared.exceptions import FileTooLargeError
from mcp_mesh_runtime.tools.file_operations import FileOperations


@pytest.fixture
async def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
async def perf_file_ops(temp_dir):
    """Create FileOperations for performance testing."""
    ops = FileOperations(
        base_directory=str(temp_dir),
        max_file_size=10 * 1024 * 1024,  # 10MB for performance tests
    )
    yield ops
    await ops.cleanup()


class TestOperationPerformance:
    """Test individual operation performance within acceptable limits."""

    async def test_file_read_performance(self, perf_file_ops, temp_dir):
        """Test file reading performance."""
        # Create test file with reasonable size
        test_file = temp_dir / "perf_read.txt"
        content = "x" * (1024 * 100)  # 100KB
        test_file.write_text(content)

        # Measure read performance
        start_time = time.time()
        read_content = await perf_file_ops.read_file(str(test_file))
        end_time = time.time()

        # Verify correctness
        assert read_content == content

        # Performance assertion - should complete within reasonable time
        # Note: First operation may take longer due to mesh initialization
        read_time = end_time - start_time
        assert read_time < 15.0, f"File read took {read_time:.3f}s, expected < 15.0s"

    async def test_file_write_performance(self, perf_file_ops, temp_dir):
        """Test file writing performance."""
        test_file = temp_dir / "perf_write.txt"
        content = "x" * (1024 * 100)  # 100KB

        # Measure write performance
        start_time = time.time()
        result = await perf_file_ops.write_file(str(test_file), content)
        end_time = time.time()

        # Verify correctness
        assert result is True
        assert test_file.read_text() == content

        # Performance assertion
        write_time = end_time - start_time
        assert write_time < 10.0, f"File write took {write_time:.3f}s, expected < 10.0s"

    async def test_directory_listing_performance(self, perf_file_ops, temp_dir):
        """Test directory listing performance with many files."""
        # Create many files
        num_files = 1000
        for i in range(num_files):
            (temp_dir / f"file_{i:04d}.txt").write_text(f"content {i}")

        # Measure listing performance
        start_time = time.time()
        entries = await perf_file_ops.list_directory(str(temp_dir))
        end_time = time.time()

        # Verify correctness
        assert len(entries) == num_files

        # Performance assertion
        list_time = end_time - start_time
        assert (
            list_time < 2.0
        ), f"Directory listing took {list_time:.3f}s, expected < 2.0s"

    async def test_detailed_listing_performance(self, perf_file_ops, temp_dir):
        """Test detailed directory listing performance."""
        # Create moderate number of files for detailed listing
        num_files = 100
        for i in range(num_files):
            (temp_dir / f"detail_{i:03d}.txt").write_text(f"content {i}")

        # Measure detailed listing performance
        start_time = time.time()
        entries = await perf_file_ops.list_directory(
            str(temp_dir), include_details=True
        )
        end_time = time.time()

        # Verify correctness
        assert len(entries) == num_files
        assert all(isinstance(entry, dict) for entry in entries)

        # Performance assertion - detailed listing takes longer but should be reasonable
        list_time = end_time - start_time
        assert (
            list_time < 3.0
        ), f"Detailed listing took {list_time:.3f}s, expected < 3.0s"

    async def test_backup_creation_performance(self, perf_file_ops, temp_dir):
        """Test backup creation performance."""
        # Create file to backup
        original_file = temp_dir / "backup_source.txt"
        content = "x" * (1024 * 50)  # 50KB
        original_file.write_text(content)

        # Measure backup performance
        start_time = time.time()
        backup_path = await perf_file_ops._create_local_backup(original_file)
        end_time = time.time()

        # Verify correctness
        assert backup_path.exists()
        assert backup_path.read_text() == content

        # Performance assertion
        backup_time = end_time - start_time
        assert (
            backup_time < 1.0
        ), f"Backup creation took {backup_time:.3f}s, expected < 1.0s"


class TestMemoryUsage:
    """Test memory usage for large file operations."""

    @pytest.mark.skipif(not psutil, reason="psutil not available")
    async def test_large_file_read_memory(self, perf_file_ops, temp_dir):
        """Test memory usage when reading large files."""
        # Create large file (1MB)
        large_file = temp_dir / "large_read.txt"
        content = "x" * (1024 * 1024)  # 1MB
        large_file.write_text(content)

        # Measure memory before operation
        process = psutil.Process()
        gc.collect()  # Force garbage collection
        memory_before = process.memory_info().rss

        # Read large file
        read_content = await perf_file_ops.read_file(str(large_file))

        # Measure memory after operation
        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Verify correctness
        assert read_content == content

        # Memory increase should be reasonable (allow for overhead)
        # Should not exceed 3x file size
        max_expected_increase = len(content) * 3
        assert (
            memory_increase < max_expected_increase
        ), f"Memory increase {memory_increase} bytes exceeds expected {max_expected_increase}"

    @pytest.mark.skipif(not psutil, reason="psutil not available")
    async def test_large_file_write_memory(self, perf_file_ops, temp_dir):
        """Test memory usage when writing large files."""
        test_file = temp_dir / "large_write.txt"
        content = "x" * (1024 * 1024)  # 1MB

        # Measure memory before operation
        process = psutil.Process()
        gc.collect()
        memory_before = process.memory_info().rss

        # Write large file
        result = await perf_file_ops.write_file(str(test_file), content)

        # Measure memory after operation
        memory_after = process.memory_info().rss
        memory_increase = memory_after - memory_before

        # Verify correctness
        assert result is True
        assert test_file.read_text() == content

        # Memory increase should be reasonable
        max_expected_increase = len(content) * 3
        assert (
            memory_increase < max_expected_increase
        ), f"Memory increase {memory_increase} bytes exceeds expected {max_expected_increase}"

    async def test_memory_cleanup_after_operations(self, perf_file_ops, temp_dir):
        """Test that memory is properly cleaned up after operations."""
        # This test verifies that no significant memory leaks occur
        initial_objects = len(gc.get_objects())

        # Perform multiple operations
        for i in range(10):
            test_file = temp_dir / f"cleanup_{i}.txt"
            content = f"content {i}" * 1000  # Moderate size

            await perf_file_ops.write_file(str(test_file), content)
            read_content = await perf_file_ops.read_file(str(test_file))
            assert read_content == content

        # Force garbage collection
        gc.collect()

        # Check that object count hasn't grown significantly
        final_objects = len(gc.get_objects())
        object_increase = final_objects - initial_objects

        # Allow for some object creation but not excessive
        assert (
            object_increase < 1000
        ), f"Object count increased by {object_increase}, potential memory leak"


class TestConcurrentOperationSafety:
    """Test safety and performance of concurrent operations."""

    async def test_concurrent_read_performance(self, perf_file_ops, temp_dir):
        """Test performance of concurrent read operations."""
        # Create multiple test files
        num_files = 50
        files = []
        for i in range(num_files):
            file_path = temp_dir / f"concurrent_read_{i}.txt"
            content = f"content {i}" * 100  # Moderate size
            file_path.write_text(content)
            files.append(str(file_path))

        # Measure concurrent read performance
        start_time = time.time()
        tasks = [perf_file_ops.read_file(f) for f in files]
        results = await asyncio.gather(*tasks)
        end_time = time.time()

        # Verify correctness
        assert len(results) == num_files
        for i, content in enumerate(results):
            expected = f"content {i}" * 100
            assert content == expected

        # Performance assertion - concurrent should be faster than sequential
        concurrent_time = end_time - start_time
        assert (
            concurrent_time < 5.0
        ), f"Concurrent reads took {concurrent_time:.3f}s, expected < 5.0s"

    async def test_concurrent_write_performance(self, perf_file_ops, temp_dir):
        """Test performance of concurrent write operations."""
        num_files = 50

        # Prepare write tasks
        write_tasks = []
        for i in range(num_files):
            file_path = temp_dir / f"concurrent_write_{i}.txt"
            content = f"concurrent content {i}" * 100
            write_tasks.append(perf_file_ops.write_file(str(file_path), content))

        # Measure concurrent write performance
        start_time = time.time()
        results = await asyncio.gather(*write_tasks)
        end_time = time.time()

        # Verify correctness
        assert all(results)
        for i in range(num_files):
            file_path = temp_dir / f"concurrent_write_{i}.txt"
            expected = f"concurrent content {i}" * 100
            assert file_path.read_text() == expected

        # Performance assertion
        concurrent_time = end_time - start_time
        assert (
            concurrent_time < 5.0
        ), f"Concurrent writes took {concurrent_time:.3f}s, expected < 5.0s"

    async def test_mixed_concurrent_operations_performance(
        self, perf_file_ops, temp_dir
    ):
        """Test performance of mixed concurrent operations."""
        # Setup initial files
        for i in range(10):
            file_path = temp_dir / f"initial_{i}.txt"
            file_path.write_text(f"initial {i}")

        # Create mixed operation tasks
        tasks = []

        # Read tasks
        for i in range(10):
            tasks.append(perf_file_ops.read_file(str(temp_dir / f"initial_{i}.txt")))

        # Write tasks
        for i in range(10):
            file_path = temp_dir / f"new_{i}.txt"
            content = f"new content {i}"
            tasks.append(perf_file_ops.write_file(str(file_path), content))

        # List tasks
        for _ in range(5):
            tasks.append(perf_file_ops.list_directory(str(temp_dir)))

        # Measure mixed operation performance
        start_time = time.time()
        results = await asyncio.gather(*tasks)
        end_time = time.time()

        # Verify correctness
        assert len(results) == 25  # 10 reads + 10 writes + 5 lists

        # Performance assertion
        mixed_time = end_time - start_time
        assert (
            mixed_time < 5.0
        ), f"Mixed operations took {mixed_time:.3f}s, expected < 5.0s"

    async def test_concurrent_operations_with_rate_limiting(
        self, perf_file_ops, temp_dir
    ):
        """Test concurrent operations performance with rate limiting."""
        # Create test file
        test_file = temp_dir / "rate_test.txt"
        test_file.write_text("test content")

        # Set reasonable rate limit
        perf_file_ops._max_operations_per_minute = 20

        # Create tasks that should fit within rate limit
        num_tasks = 15
        tasks = [perf_file_ops.read_file(str(test_file)) for _ in range(num_tasks)]

        # Measure performance with rate limiting
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()

        # Most should succeed
        successes = [r for r in results if isinstance(r, str)]
        assert len(successes) >= 10  # Most should succeed within rate limit

        # Performance should still be reasonable
        rate_limited_time = end_time - start_time
        assert (
            rate_limited_time < 3.0
        ), f"Rate limited operations took {rate_limited_time:.3f}s"


class TestResourceCleanup:
    """Test resource cleanup performance and effectiveness."""

    async def test_cleanup_performance(self, temp_dir):
        """Test that cleanup operations complete quickly."""
        # Create file operations instance
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Perform some operations to create state
        for i in range(10):
            file_path = temp_dir / f"cleanup_{i}.txt"
            await file_ops.write_file(str(file_path), f"content {i}")
            await file_ops.read_file(str(file_path))

        # Measure cleanup performance
        start_time = time.time()
        await file_ops.cleanup()
        end_time = time.time()

        # Cleanup should be fast
        cleanup_time = end_time - start_time
        assert cleanup_time < 1.0, f"Cleanup took {cleanup_time:.3f}s, expected < 1.0s"

    async def test_multiple_cleanup_calls(self, temp_dir):
        """Test that multiple cleanup calls are safe and fast."""
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Perform some operations
        test_file = temp_dir / "test.txt"
        await file_ops.write_file(str(test_file), "test content")

        # Multiple cleanup calls should be safe
        for _ in range(3):
            start_time = time.time()
            await file_ops.cleanup()
            end_time = time.time()

            cleanup_time = end_time - start_time
            assert cleanup_time < 0.5, f"Repeated cleanup took {cleanup_time:.3f}s"

    async def test_resource_cleanup_under_load(self, temp_dir):
        """Test resource cleanup under concurrent load."""
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Start background operations
        async def background_operations():
            for i in range(50):
                file_path = temp_dir / f"bg_{i}.txt"
                try:
                    await file_ops.write_file(str(file_path), f"background {i}")
                    await file_ops.read_file(str(file_path))
                except Exception:
                    # Some operations may fail during cleanup
                    pass

        # Start background task
        bg_task = asyncio.create_task(background_operations())

        # Wait a bit for operations to start
        await asyncio.sleep(0.1)

        # Cleanup while operations are running
        start_time = time.time()
        await file_ops.cleanup()
        end_time = time.time()

        # Cancel background operations
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass

        # Cleanup should still complete reasonably quickly
        cleanup_time = end_time - start_time
        assert cleanup_time < 2.0, f"Cleanup under load took {cleanup_time:.3f}s"


class TestRetryPerformance:
    """Test performance of retry mechanisms."""

    async def test_retry_delay_calculation_performance(self, perf_file_ops):
        """Test that retry delay calculation is fast."""
        from mcp_mesh_runtime.shared.types import RetryConfig, RetryStrategy

        retry_config = RetryConfig(
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=10,
            initial_delay_ms=100,
            backoff_multiplier=2.0,
        )

        # Measure delay calculation performance
        start_time = time.time()
        for attempt in range(100):  # Calculate many delays
            await perf_file_ops._calculate_retry_delay(attempt % 10, retry_config)
        end_time = time.time()

        # Should be very fast
        calc_time = end_time - start_time
        assert (
            calc_time < 0.1
        ), f"Retry delay calculation took {calc_time:.3f}s for 100 calculations"

    async def test_rate_limit_check_performance(self, perf_file_ops):
        """Test performance of rate limit checking."""
        # Perform many rate limit checks
        start_time = time.time()
        for _ in range(1000):
            await perf_file_ops._check_rate_limit("test_operation")
        end_time = time.time()

        # Should be very fast
        check_time = end_time - start_time
        assert (
            check_time < 0.5
        ), f"Rate limit checks took {check_time:.3f}s for 1000 checks"


class TestScalabilityLimits:
    """Test behavior at scalability limits."""

    async def test_maximum_file_size_handling(self, temp_dir):
        """Test handling of maximum allowed file size."""
        # Create FileOperations with specific size limit
        max_size = 1024 * 1024  # 1MB limit
        file_ops = FileOperations(base_directory=str(temp_dir), max_file_size=max_size)

        try:
            # Test file just under limit
            under_limit_content = "x" * (max_size - 100)
            test_file = temp_dir / "under_limit.txt"

            start_time = time.time()
            result = await file_ops.write_file(str(test_file), under_limit_content)
            end_time = time.time()

            assert result is True
            write_time = end_time - start_time
            assert write_time < 2.0, f"Large file write took {write_time:.3f}s"

            # Test file over limit
            over_limit_content = "x" * (max_size + 100)
            with pytest.raises(FileTooLargeError):
                await file_ops.write_file(str(test_file), over_limit_content)

        finally:
            await file_ops.cleanup()

    async def test_many_small_files_performance(self, perf_file_ops, temp_dir):
        """Test performance with many small files."""
        num_files = 2000

        # Create many small files
        start_time = time.time()
        tasks = []
        for i in range(num_files):
            file_path = temp_dir / f"small_{i:04d}.txt"
            content = f"small content {i}"
            tasks.append(perf_file_ops.write_file(str(file_path), content))

        await asyncio.gather(*tasks)
        end_time = time.time()

        # Should handle many small files efficiently
        total_time = end_time - start_time
        time_per_file = total_time / num_files
        assert (
            time_per_file < 0.01
        ), f"Average time per file {time_per_file:.4f}s too high"

        # Test listing many files
        start_time = time.time()
        entries = await perf_file_ops.list_directory(str(temp_dir))
        end_time = time.time()

        assert len(entries) == num_files
        list_time = end_time - start_time
        assert list_time < 3.0, f"Listing {num_files} files took {list_time:.3f}s"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
