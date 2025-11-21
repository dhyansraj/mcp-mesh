#!/usr/bin/env python3
"""
Test 4: Template with Control Structures

Validates Jinja2 control structures in templates.
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Control Structures Test")


class OrchestratorContext(MeshContextModel):
    """Orchestration context."""

    task_type: str = Field(description="Type of task to orchestrate")
    priority: str = Field(
        default="normal", description="Priority: low, normal, medium, high"
    )
    capabilities: list[str] = Field(
        default_factory=list, description="Available capabilities"
    )
    constraints: list[str] = Field(default_factory=list, description="Task constraints")


class OrchestratorResult(BaseModel):
    plan: str
    steps: list[str]


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/orchestrator.jinja2",
    filter=None,  # Simplified for testing
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # LiteLLM requires vendor prefix
)
@mesh.tool(capability="orchestration")
def orchestrate(
    request: str, ctx: OrchestratorContext, llm: mesh.MeshLlmAgent = None
) -> OrchestratorResult:
    """Orchestrate multi-agent tasks."""
    return llm(request)


# Agent configuration for HTTP transport
@mesh.agent(
    name="control-structures-test",
    version="1.0.0",
    description="Control Structures Test Agent",
    http_port=9095,  # Use port 9095
    enable_http=True,
    auto_run=True,
)
class ControlStructuresTestAgent:
    """Agent class for control structures testing."""

    pass


if __name__ == "__main__":
    app.run()
