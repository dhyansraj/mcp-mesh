#!/usr/bin/env python3
"""
Test 5: Hierarchical Context Models

Validates nested MeshContextModel structures.
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Hierarchical Context Test")


class UserContext(MeshContextModel):
    """Nested user context."""

    name: str = Field(description="User's full name")
    role: str = Field(description="User's role: user, admin, superadmin")
    permissions: list[str] = Field(default_factory=list, description="User permissions")


class TaskContext(MeshContextModel):
    """Task context with nested user."""

    user: UserContext = Field(description="User information")  # Nested!
    task_type: str = Field(description="Type of task")
    priority: str = Field(default="normal", description="Task priority")
    deadline: str | None = Field(default=None, description="Task deadline if any")


class TaskResult(BaseModel):
    status: str
    summary: str


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/hierarchical.jinja2",
    filter=None,  # Simplified for testing
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # LiteLLM requires vendor prefix
)
@mesh.tool(capability="task_execution")
def execute_task(
    request: str, task: TaskContext, llm: mesh.MeshLlmAgent = None
) -> TaskResult:
    """Execute task with hierarchical context."""
    return llm(request)


# Agent configuration for HTTP transport
@mesh.agent(
    name="hierarchical-test",
    version="1.0.0",
    description="Hierarchical Context Test Agent",
    http_port=9096,  # Use port 9096
    enable_http=True,
    auto_run=True,
)
class HierarchicalTestAgent:
    """Agent class for hierarchical context testing."""

    pass


if __name__ == "__main__":
    app.run()
