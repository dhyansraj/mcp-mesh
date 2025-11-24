#!/usr/bin/env python3
"""
Developer Agent - Expert software development specialist

This agent acts as an expert software developer with access to file and command execution tools.
Uses mesh delegation to connect to Claude LLM provider and executor tools.

Architecture:
- LLM Provider: Claude (via mesh delegation)
- Tool Filter: Tags ["executor", "tools"] for all executor capabilities
- System Prompt: Template-based (prompts/developer.jinja2)
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Developer Agent")


class DevelopmentResponse(BaseModel):
    """Response from development tasks."""

    status: str  # "success", "in_progress", "failed"
    summary: str
    files_modified: list[str] = []
    commands_executed: list[str] = []
    next_steps: str = ""


@app.tool()
@mesh.llm(
    filter={
        "tags": ["executor", "tools"]
    },  # Smart tag-based filter for all executor tools
    filter_mode="all",  # Get all matching tools
    provider={
        "capability": "llm",
        "tags": ["llm", "+claude"],
    },  # Mesh delegation with Claude preference
    model="anthropic/claude-sonnet-4-5",  # Ignored (provider handles)
    max_iterations=20,  # Allow complex multi-step development
    system_prompt="file://prompts/developer.jinja2",  # Template-based system prompt
)
@mesh.tool(
    capability="software_development",
    tags=["developer", "coding", "llm", "specialist"],
    version="1.0.0",
)
def develop(task: str, llm: mesh.MeshLlmAgent = None) -> DevelopmentResponse:
    """
    Execute software development tasks.

    This function provides expert software development capabilities:
    - Code implementation and modification
    - File management and organization
    - Testing and verification
    - Documentation

    The LLM has access to executor tools via mesh filtering:
    - bash: Execute commands for testing and building
    - write_file: Create and modify code files
    - read_file: Read existing files
    - grep_files: Search through codebases

    Args:
        task: Development task description
        llm: Injected MeshLlmAgent (connects to Claude via mesh)

    Returns:
        DevelopmentResponse with task results
    """
    return llm(task)


@mesh.agent(
    name="developer-agent",
    version="1.0.0",
    description="Developer Agent - Expert software development specialist",
    http_port=9102,
    enable_http=True,
    auto_run=True,
)
class DeveloperAgent:
    """Developer agent that provides software development capabilities."""

    pass
