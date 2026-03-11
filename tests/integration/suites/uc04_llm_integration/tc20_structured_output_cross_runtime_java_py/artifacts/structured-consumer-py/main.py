#!/usr/bin/env python3
"""
structured-consumer-py - Cross-Runtime Structured Output Consumer

Tests that a Python consumer with Pydantic structured output receives
proper structured JSON from a Claude provider (Java or TypeScript).

Validates the apply_structured_output fix uses native response_format
instead of HINT mode.
"""

from typing import Optional

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# FastMCP server instance
app = FastMCP("StructuredConsumer")


# ===== STRUCTURED OUTPUT MODEL =====


class CountryInfo(BaseModel):
    """Structured output for country information."""

    name: str = Field(..., description="Name of the country")
    capital: str = Field(..., description="Capital city")
    population: str = Field(..., description="Approximate population")
    continent: str = Field(..., description="Continent the country is in")
    language: str = Field(..., description="Primary official language")


class CountryContext(BaseModel):
    """Context for structured output request."""

    country: str = Field(..., description="Country to get info about")


# ===== LLM TOOL WITH STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="get_country_info",
    description="Get structured country information using LLM",
    version="1.0.0",
    tags=["structured", "claude", "cross-runtime"],
)
def get_country_info(
    ctx: CountryContext,
    llm: mesh.MeshLlmAgent = None,
) -> CountryInfo:
    """
    Get structured country information.

    The return type annotation (CountryInfo) tells mesh to use
    structured output mode with the Claude provider.

    Args:
        ctx: Context containing country name
        llm: Injected LLM agent (provided by mesh)

    Returns:
        CountryInfo: Structured country data
    """
    return llm(f"Provide information about {ctx.country}")


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="structured-consumer",
    version="1.0.0",
    description="Python consumer testing cross-runtime structured output",
    http_port=9040,
    enable_http=True,
    auto_run=True,
)
class StructuredConsumerAgent:
    """Agent for testing cross-runtime structured output with Claude."""

    pass
