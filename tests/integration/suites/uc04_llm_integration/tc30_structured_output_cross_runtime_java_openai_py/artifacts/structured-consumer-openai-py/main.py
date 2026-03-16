#!/usr/bin/env python3
"""
structured-consumer-openai-py - Cross-Runtime Structured Output Consumer (OpenAI)

Tests that a Python consumer with Pydantic structured output receives
proper structured JSON from a Java OpenAI/GPT provider.
"""


import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("StructuredConsumerOpenAI")


class CountryInfo(BaseModel):
    """Structured output for country information."""

    name: str = Field(..., description="Name of the country")
    capital: str = Field(..., description="Capital city")
    population: str = Field(..., description="Approximate population")
    continent: str = Field(..., description="Continent the country is in")


class CountryContext(BaseModel):
    """Context for structured output request."""

    country: str = Field(..., description="Country to get info about")


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+openai"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="get_country_info",
    description="Get structured country information using LLM",
    version="1.0.0",
    tags=["structured", "openai", "cross-runtime"],
)
def get_country_info(
    ctx: CountryContext,
    llm: mesh.MeshLlmAgent = None,
) -> CountryInfo:
    """Get structured country information via OpenAI provider."""
    return llm(f"Provide information about {ctx.country}")


@mesh.agent(
    name="structured-consumer-openai",
    version="1.0.0",
    description="Python consumer testing cross-runtime structured output with OpenAI",
    http_port=9047,
    enable_http=True,
    auto_run=True,
)
class StructuredConsumerOpenAIAgent:
    """Agent for testing cross-runtime structured output with OpenAI."""

    pass
