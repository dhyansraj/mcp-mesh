#!/usr/bin/env python3
"""
Executor Agent - Provides basic file and command execution tools

This agent exposes simple "dumb" tools that can be used by LLM agents:
- bash: Execute shell commands
- write_file: Write content to a file
- read_file: Read content from a file
- grep_files: Search for patterns in files

Tags: ["executor", "tools"]
"""

import os
import subprocess
from pathlib import Path

import mesh
from fastmcp import FastMCP

# Initialize MCP server
app = FastMCP("Executor Agent")

# Workspace directory (will be mounted in Docker)
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", "/workspace"))


@app.tool()
@mesh.tool(
    capability="bash_executor",
    description="Execute bash commands in workspace",
    version="1.0.0",
    tags=["executor", "tools", "develop", "bash", "command"],
)
def bash(command: str, timeout: int = 30) -> str:
    """
    Execute a bash command in the workspace directory.

    Args:
        command: The bash command to execute
        timeout: Maximum execution time in seconds (default: 30)

    Returns:
        Command output (stdout + stderr)
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = []
        if result.stdout:
            output.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output.append(f"STDERR:\n{result.stderr}")
        if result.returncode != 0:
            output.append(f"EXIT CODE: {result.returncode}")

        return (
            "\n".join(output)
            if output
            else "Command completed successfully (no output)"
        )

    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"ERROR: {str(e)}"


@app.tool()
@mesh.tool(
    capability="file_writer",
    description="Write content to files in workspace",
    version="1.0.0",
    tags=["executor", "tools", "develop", "file", "write"],
)
def write_file(file_path: str, content: str) -> str:
    """
    Write content to a file in the workspace.

    Args:
        file_path: Relative path to the file (from workspace root)
        content: Content to write to the file

    Returns:
        Success message or error
    """
    try:
        full_path = WORKSPACE_DIR / file_path

        # Create parent directories if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        full_path.write_text(content)

        return f"Successfully wrote {len(content)} characters to {file_path}"

    except Exception as e:
        return f"ERROR: {str(e)}"


@app.tool()
@mesh.tool(
    capability="file_reader",
    description="Read content from files in workspace",
    version="1.0.0",
    tags=["executor", "tools", "develop", "file", "read"],
)
def read_file(file_path: str) -> str:
    """
    Read content from a file in the workspace.

    Args:
        file_path: Relative path to the file (from workspace root)

    Returns:
        File content or error message
    """
    try:
        full_path = WORKSPACE_DIR / file_path

        if not full_path.exists():
            return f"ERROR: File not found: {file_path}"

        content = full_path.read_text()
        return content

    except Exception as e:
        return f"ERROR: {str(e)}"


@app.tool()
@mesh.tool(
    capability="file_searcher",
    description="Search for patterns in files using grep",
    version="1.0.0",
    tags=["executor", "tools", "develop", "file", "search", "grep"],
)
def grep_files(pattern: str, file_pattern: str = "*") -> str:
    """
    Search for a pattern in files using grep.

    Args:
        pattern: The pattern to search for
        file_pattern: File glob pattern (default: "*")

    Returns:
        Grep results or error message
    """
    try:
        cmd = (
            f"grep -r '{pattern}' {file_pattern} 2>/dev/null || echo 'No matches found'"
        )
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )

        return result.stdout if result.stdout else "No matches found"

    except Exception as e:
        return f"ERROR: {str(e)}"


@mesh.agent(
    name="executor-agent",
    version="1.0.0",
    description="Executor Agent - Provides basic file and command execution tools",
    http_port=9100,
    enable_http=True,
    auto_run=True,
)
class ExecutorAgent:
    """Executor agent that exposes dumb tools for file and command execution."""

    pass
