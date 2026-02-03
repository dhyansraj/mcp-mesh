#!/usr/bin/env python3
"""
analyst-py - MCP Mesh LLM Agent

A MCP Mesh LLM agent generated using meshctl scaffold.
"""

from typing import Any, Dict, List, Optional

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# FastMCP server instance
app = FastMCP("AnalystPy Service")

# System prompt is loaded from: prompts/analyst-py.jinja2
# Customize the prompt file to change the LLM behavior.

# ===== CONTEXT MODEL =====


class AnalysisContext(BaseModel):
    """Context for analysis LLM processing."""

    query: str = Field(..., description="The analysis query")
    data_source: Optional[str] = Field(
        default=None, description="Optional data source hint"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional parameters"
    )


# ===== RESPONSE MODEL =====


class AnalysisResult(BaseModel):
    """Structured response from analysis."""

    summary: str = Field(..., description="Analysis summary")
    insights: List[str] = Field(..., description="List of insights")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0 to 1.0)"
    )
    source: str = Field(..., description="Data source used")


# ===== LLM TOOL =====


@app.tool()
@mesh.llm(
    filter=[{"tags": ["weather", "data"]}],
    filter_mode="all",
    provider={"capability": "llm"},
    max_iterations=5,
    system_prompt="file://prompts/analyst-py.jinja2",
    context_param="ctx",
)
@mesh.tool(
    capability="analyze",
    description="AI-powered data analysis with agentic tool use",
    version="1.0.0",
    tags=["analysis", "llm", "python"],
)
def analyze(
    ctx: AnalysisContext,
    llm: mesh.MeshLlmAgent = None,
) -> AnalysisResult:
    """
    AI-powered data analysis with agentic tool use.

    Args:
        ctx: Context containing analysis query and parameters
        llm: Injected LLM agent (provided by mesh)

    Returns:
        Structured response with analysis results
    """
    return llm(ctx.query)


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="analyst-py",
    version="1.0.0",
    description="MCP Mesh LLM agent for analyst-py",
    http_port=9000,
    enable_http=True,
    auto_run=True,
)
class AnalystPyAgent:
    """
    LLM Agent that uses Claude for processing.

    The mesh processor will:
    1. Discover the 'app' FastMCP instance
    2. Inject the LLM provider based on tags
    3. Start the FastMCP HTTP server on port 9000
    4. Register capabilities with the mesh registry
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - LLM provider injection
# - HTTP server configuration
# - Service registration with mesh registry
