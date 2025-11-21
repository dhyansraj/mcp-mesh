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
    filter={"tags": ["system"]},  # Filter for system tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    context_param="analysis_ctx",  # Explicit context parameter
)
@mesh.tool(capability="analysis", tags=["prompt-template", "test-002"])
def analyze_system(
    query: str, analysis_ctx: AnalysisContext, llm: mesh.MeshLlmAgent = None
) -> AnalysisResult:
    """Analyze system with context-aware prompting."""
    return llm(query)


@mesh.agent(
    name="test-pt-002-context-model",
    version="1.0.0",
    description="Test agent for MeshContextModel with Field descriptions",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class ContextModelTestAgent:
    """Test agent configuration."""

    pass
