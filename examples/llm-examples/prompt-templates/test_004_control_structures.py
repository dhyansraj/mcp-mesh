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
    filter={"tags": ["analysis"]},
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
)
@mesh.tool(capability="orchestration", tags=["prompt-template", "test-004"])
def orchestrate(
    request: str, ctx: OrchestratorContext, llm: mesh.MeshLlmAgent = None
) -> OrchestratorResult:
    """Orchestrate multi-agent tasks."""
    return llm(request)


@mesh.agent(
    name="test-pt-004-control-structures",
    version="1.0.0",
    description="Test agent for Jinja2 control structures in templates",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class ControlStructuresTestAgent:
    """Test agent configuration."""

    pass
