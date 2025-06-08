"""
Simple test runner for unit tests to verify basic functionality.
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, "src")

from mcp_mesh_runtime.decorators.mesh_agent import mesh_agent
from mcp_mesh_runtime.shared.exceptions import (
    FileNotFoundError,
    FileTooLargeError,
    FileTypeNotAllowedError,
    PathTraversalError,
)
from mcp_mesh_runtime.shared.types import OperationType
from mcp_mesh_runtime.tools.file_operations import FileOperations


async def test_basic_file_operations():
    """Test basic file operations functionality."""
    print("Testing basic file operations...")

    # Create temporary directory
    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Create file operations instance
        file_ops = FileOperations(base_directory=str(temp_dir), max_file_size=1024)

        # Test file writing (use absolute path within base directory)
        test_file = str(temp_dir / "test.txt")
        test_content = "Hello, MCP-Mesh!"
        result = await file_ops.write_file(test_file, test_content)
        assert result is True
        print("✓ File writing works")

        # Test file reading
        content = await file_ops.read_file(test_file)
        assert content == test_content
        print("✓ File reading works")

        # Test directory listing
        entries = await file_ops.list_directory(str(temp_dir))
        assert "test.txt" in entries
        print("✓ Directory listing works")

        # Cleanup
        await file_ops.cleanup()
        print("✓ Basic file operations test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_security_validation():
    """Test security validation features."""
    print("Testing security validation...")

    temp_dir = Path(tempfile.mkdtemp())

    try:
        file_ops = FileOperations(base_directory=str(temp_dir), max_file_size=100)

        # Test path traversal protection
        try:
            await file_ops._validate_path("../../../etc/passwd", OperationType.READ)
            raise AssertionError("Should have raised PathTraversalError")
        except PathTraversalError:
            print("✓ Path traversal protection works")

        # Test file extension validation (create path within base directory)
        try:
            malware_path = str(temp_dir / "malware.exe")
            await file_ops._validate_path(malware_path, OperationType.WRITE)
            raise AssertionError("Should have raised FileTypeNotAllowedError")
        except FileTypeNotAllowedError:
            print("✓ File extension validation works")

        # Test file size validation
        try:
            large_content = "x" * 200  # Larger than max_file_size (100)
            await file_ops.write_file(str(temp_dir / "large.txt"), large_content)
            raise AssertionError("Should have raised FileTooLargeError")
        except FileTooLargeError:
            print("✓ File size validation works")

        # Test file not found
        try:
            await file_ops.read_file(str(temp_dir / "nonexistent.txt"))
            raise AssertionError("Should have raised FileNotFoundError")
        except FileNotFoundError:
            print("✓ File not found handling works")

        await file_ops.cleanup()
        print("✓ Security validation test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_mesh_agent_decorator():
    """Test mesh agent decorator functionality."""
    print("Testing mesh agent decorator...")

    # Test basic decoration
    @mesh_agent(capabilities=["test"])
    async def test_function(value: str) -> str:
        return f"processed: {value}"

    # Verify metadata is attached
    assert hasattr(test_function, "_mesh_agent_metadata")
    metadata = test_function._mesh_agent_metadata
    assert metadata["capabilities"] == ["test"]
    assert "decorator_instance" in metadata
    print("✓ Decorator metadata attachment works")

    # Test function execution
    result = await test_function("hello")
    assert result == "processed: hello"
    print("✓ Decorated function execution works")

    # Test with dependencies
    @mesh_agent(capabilities=["file_read"], dependencies=["auth_service"])
    async def secure_function(path: str, auth_service: str = None) -> str:
        auth_status = "authenticated" if auth_service else "unauthenticated"
        return f"Reading {path} ({auth_status})"

    result = await secure_function("/test/path")
    assert "Reading /test/path" in result
    print("✓ Dependency injection handling works")

    print("✓ Mesh agent decorator test passed")


async def test_error_handling():
    """Test error handling and MCP compliance."""
    print("Testing error handling...")

    temp_dir = Path(tempfile.mkdtemp())

    try:
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Test error structure
        try:
            await file_ops.read_file(str(temp_dir / "nonexistent.txt"))
        except FileNotFoundError as e:
            error_dict = e.to_dict()
            assert "code" in error_dict
            assert "message" in error_dict
            assert "data" in error_dict
            print("✓ MCP error structure compliance works")

        # Test error conversion
        generic_error = ValueError("Test error")
        mcp_error = file_ops._convert_exception_to_mcp_error(generic_error)
        # The method returns a JSON-RPC 2.0 error response format
        assert isinstance(mcp_error, dict)
        assert "error" in mcp_error
        assert "code" in mcp_error["error"]
        assert "message" in mcp_error["error"]
        print("✓ Error conversion works")

        await file_ops.cleanup()
        print("✓ Error handling test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def test_concurrent_operations():
    """Test concurrent operations."""
    print("Testing concurrent operations...")

    temp_dir = Path(tempfile.mkdtemp())

    try:
        file_ops = FileOperations(base_directory=str(temp_dir))

        # Create test files
        for i in range(3):
            (temp_dir / f"test_{i}.txt").write_text(f"content {i}")

        # Test concurrent reads
        tasks = []
        for i in range(3):
            tasks.append(file_ops.read_file(str(temp_dir / f"test_{i}.txt")))

        results = await asyncio.gather(*tasks)
        assert len(results) == 3
        for i, content in enumerate(results):
            assert content == f"content {i}"
        print("✓ Concurrent reads work")

        # Test concurrent writes
        write_tasks = []
        for i in range(3):
            write_tasks.append(
                file_ops.write_file(str(temp_dir / f"new_{i}.txt"), f"new content {i}")
            )

        write_results = await asyncio.gather(*write_tasks)
        assert all(write_results)
        print("✓ Concurrent writes work")

        await file_ops.cleanup()
        print("✓ Concurrent operations test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def main():
    """Run all tests."""
    print("Running comprehensive unit tests for File Agent tools...\n")

    try:
        await test_basic_file_operations()
        print()

        await test_security_validation()
        print()

        await test_mesh_agent_decorator()
        print()

        await test_error_handling()
        print()

        await test_concurrent_operations()
        print()

        print("🎉 All tests passed successfully!")
        print("\nTest Coverage Summary:")
        print("✓ Basic file operations (read_file, write_file, list_directory)")
        print("✓ Parameter validation and error conditions")
        print("✓ Security validation features")
        print("✓ @mesh_agent decorator functionality")
        print("✓ Error handling and MCP compliance")
        print("✓ Concurrent operations")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
