"""
Pytest configuration for MCP Mesh SDK tests.

Provides shared fixtures and test configuration across all test modules.
"""

# CRITICAL: Set test environment variables BEFORE any imports
# This prevents server startups during unit tests caused by @mesh.agent auto_run
# The issue: mesh/__init__.py now imports helpers.py at module level, changing
# initialization order. By setting ENV vars here (pytest loads conftest.py FIRST),
# we ensure they're in place before any mesh code runs.
import os

os.environ["MCP_MESH_AUTO_RUN"] = "false"
os.environ["MCP_MESH_HTTP_ENABLED"] = "false"
os.environ["PYTEST_RUNNING"] = "true"

import asyncio
import shutil
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from _mcp_mesh.generated.mcp_mesh_registry_client.api_client import ApiClient
from _mcp_mesh.generated.mcp_mesh_registry_client.configuration import Configuration
from _mcp_mesh.shared.support_types import HealthStatus

# Import SDK components for testing
# FileOperations has been removed


# Configure asyncio for all tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Temporary directories
@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
async def async_temp_dir() -> AsyncGenerator[Path, None]:
    """Async version of temp_dir fixture."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


# Mock registry client
@pytest.fixture
def mock_registry_client():
    """Create a mock registry client for testing."""
    mock_client = AsyncMock(spec=RegistryClient)

    # Configure default behavior
    mock_client.register_agent = AsyncMock()
    mock_client.get_dependency = AsyncMock(return_value="mock-service-v1.0.0")
    mock_client.send_heartbeat = AsyncMock()
    mock_client.close = AsyncMock()

    return mock_client


# FileOperations fixtures removed since FileOperations was removed


# Test data fixtures
@pytest.fixture
def sample_text_files(temp_dir) -> dict:
    """Create sample text files for testing."""
    files = {
        "simple.txt": "Simple text content",
        "multiline.txt": """Line 1
Line 2
Line 3""",
        "empty.txt": "",
        "large.txt": "x" * 10000,  # 10KB file
        "config.json": '{"key": "value", "number": 42}',
        "data.csv": "id,name,value\n1,test,100\n2,sample,200",
    }

    created_files = {}
    for filename, content in files.items():
        file_path = temp_dir / filename
        file_path.write_text(content)
        created_files[filename] = file_path

    return created_files


@pytest.fixture
def sample_directory_structure(temp_dir) -> dict:
    """Create sample directory structure for testing."""
    structure = {
        "docs": {"README.md": "# Documentation", "guide.txt": "User guide content"},
        "src": {
            "main.py": "print('Hello, World!')",
            "utils": {"helpers.py": "def helper(): pass"},
        },
        "tests": {"test_main.py": "def test_main(): assert True"},
    }

    created_structure: dict[str, Any] = {}

    def create_structure(base_path: Path, struct: dict, result: dict):
        for name, content in struct.items():
            path = base_path / name
            if isinstance(content, dict):
                path.mkdir()
                result[name] = {"path": path, "children": {}}
                create_structure(path, content, result[name]["children"])
            else:
                path.write_text(content)
                result[name] = {"path": path, "content": content}

    create_structure(temp_dir, structure, created_structure)
    return created_structure


# Test configuration markers
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "performance: mark test as performance test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line(
        "markers", "mcp_protocol: mark test as MCP protocol compliance test"
    )
    config.addinivalue_line(
        "markers", "mesh_integration: mark test as mesh integration test"
    )


# Custom assertions for tests
class TestAssertions:
    """Custom assertions for MCP Mesh SDK tests."""

    @staticmethod
    def assert_valid_health_status(health_status):
        """Assert that health status is valid."""
        assert isinstance(health_status, HealthStatus)
        assert hasattr(health_status, "agent_name")
        assert hasattr(health_status, "status")
        assert hasattr(health_status, "capabilities")
        assert hasattr(health_status, "timestamp")
        assert isinstance(health_status.capabilities, list)

    @staticmethod
    def assert_mesh_metadata(func):
        """Assert that function has mesh agent metadata."""
        assert hasattr(func, "_mesh_agent_metadata")
        metadata = func._mesh_agent_metadata
        assert "capabilities" in metadata
        assert "dependencies" in metadata
        assert "decorator_instance" in metadata

    @staticmethod
    def assert_file_operation_result(result, expected_type=None):
        """Assert file operation result is valid."""
        if expected_type:
            assert isinstance(result, expected_type)
        assert result is not None


@pytest.fixture
def test_assertions():
    """Provide custom test assertions."""
    return TestAssertions
