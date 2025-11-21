#!/usr/bin/env python3
"""
Test 2: MeshContextModel with Field Descriptions

Validates type-safe context models and field description extraction.
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Context Model Test")


class AnalysisContext(MeshContextModel):
    """Context for system analysis prompts."""

    domain: str = Field(
        ..., description="Analysis domain (e.g., infrastructure, network)"
    )
    user_level: str = Field(
        default="beginner", description="User expertise: beginner, intermediate, expert"
    )
    max_tools: int = Field(
        default=5, description="Maximum number of tools to use in analysis"
    )
    focus_areas: list[str] = Field(
        default_factory=list, description="Specific areas to analyze"
    )


class AnalysisResult(BaseModel):
    """Analysis result."""

    summary: str
    findings: list[str]
    recommendations: list[str]


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/analyst.jinja2",
    filter=None,  # No tools for now - test context model first
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # LiteLLM requires vendor prefix
    context_param="analysis_ctx",  # Explicit context parameter
)
@mesh.tool(capability="orchestration")
def analyze_system(
    query: str,
    analysis_ctx: AnalysisContext,  # Type-safe context!
    llm: mesh.MeshLlmAgent = None,
) -> AnalysisResult:
    """Analyze system with context-aware prompting."""
    return llm(query)


# Agent configuration for HTTP transport
@mesh.agent(
    name="context-model-test",
    version="1.0.0",
    description="Context Model Test Agent",
    http_port=9093,  # Use port 9093
    enable_http=True,
    auto_run=True,
)
class ContextModelTestAgent:
    """Agent class for context model testing."""

    pass


if __name__ == "__main__":
    app.run()
