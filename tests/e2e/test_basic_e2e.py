"""
Basic End-to-End Test

Simple test to verify basic file operations work end-to-end.
"""

import tempfile
from pathlib import Path

import pytest
from mcp_mesh_runtime.tools.file_operations import FileOperations


@pytest.mark.asyncio
async def test_basic_file_operations_e2e():
    """Test basic file operations work end-to-end."""
    with tempfile.TemporaryDirectory() as temp_dir:
        file_ops = FileOperations(base_directory=temp_dir)

        # Test file creation
        test_file = str(Path(temp_dir) / "test.txt")
        content = "Hello, World!"

        result = await file_ops.write_file(test_file, content)
        assert result is True

        # Test file reading
        read_content = await file_ops.read_file(test_file)
        assert read_content == content

        # Test directory listing
        entries = await file_ops.list_directory(temp_dir)
        assert "test.txt" in entries

        await file_ops.cleanup()


@pytest.mark.asyncio
async def test_basic_workflow_e2e():
    """Test basic workflow with multiple operations."""
    with tempfile.TemporaryDirectory() as temp_dir:
        file_ops = FileOperations(base_directory=temp_dir, max_file_size=1024 * 1024)

        # Create project structure
        docs_dir = str(Path(temp_dir) / "docs")
        readme_path = str(Path(docs_dir) / "README.md")

        readme_content = """# Test Project

## Overview
This is a test project for E2E testing.

## Features
- File operations
- Directory management
- Basic workflows
"""

        # Write file (creates directory if needed)
        result = await file_ops.write_file(readme_path, readme_content)
        assert result is True

        # Verify file exists and content is correct
        content = await file_ops.read_file(readme_path)
        assert content == readme_content
        assert "Test Project" in content

        # List directory with details
        entries = await file_ops.list_directory(docs_dir, include_details=True)
        assert len(entries) == 1

        readme_entry = entries[0]
        assert readme_entry["name"] == "README.md"
        assert readme_entry["type"] == "file"
        assert readme_entry["size"] > 0

        await file_ops.cleanup()
