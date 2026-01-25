#!/usr/bin/env python3
"""
structured-agent - MCP Mesh LLM Agent with Structured Output (Gemini)

Tests that Gemini provider correctly returns structured data (Pydantic model)
instead of JSON schema metadata.

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/459
"""

from typing import Optional

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# FastMCP server instance
app = FastMCP("StructuredAgentGemini")


# ===== STRUCTURED OUTPUT MODEL =====


class CountryInfo(BaseModel):
    """Structured output for country information."""

    country: str = Field(..., description="Name of the country")
    capital: str = Field(..., description="Capital city")
    population: Optional[str] = Field(None, description="Approximate population")


class StructuredContext(BaseModel):
    """Context for structured output request."""

    country_name: str = Field(..., description="Country to get info about")


# ===== LLM TOOL WITH STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+gemini", "+provider"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="get_country_info",
    description="Get structured country information using Gemini LLM",
    version="1.0.0",
    tags=["structured", "gemini"],
)
def get_country_info(
    ctx: StructuredContext,
    llm: mesh.MeshLlmAgent = None,
) -> CountryInfo:
    """
    Get structured country information.

    The return type annotation (CountryInfo) tells mesh to use
    structured output mode with Gemini.

    Args:
        ctx: Context containing country name
        llm: Injected LLM agent (provided by mesh)

    Returns:
        CountryInfo: Structured country data
    """
    return llm(f"Provide information about {ctx.country_name}")


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="structured-agent-gemini",
    version="1.0.0",
    description="LLM agent testing structured output with Gemini",
    http_port=9021,
    enable_http=True,
    auto_run=True,
)
class StructuredAgentGeminiAgent:
    """Agent for testing structured output with Gemini."""

    pass
