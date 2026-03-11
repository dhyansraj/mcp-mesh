#!/usr/bin/env python3
"""
multi-provider-consumer - MCP Mesh Agent that consumes from multiple Claude providers.

Tests that when two Claude providers (Python + Java) are available on the mesh,
the consumer can successfully get structured output from either one. Validates
multi-provider routing and output_schema handling across runtimes.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("MultiProviderConsumer")


class CountryInfo(BaseModel):
    """Structured output for country information."""

    name: str = Field(..., description="The name of the country")
    capital: str = Field(..., description="The capital city of the country")
    fun_fact: str = Field(..., description="An interesting fact about the country")


class CountryContext(BaseModel):
    """Context for country info request."""

    country: str = Field(..., description="The country to get information about")


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="country_info",
    description="Get structured information about a country using an LLM provider",
    version="1.0.0",
    tags=["llm", "structured-output", "multi-provider"],
)
async def get_country_info(
    ctx: CountryContext,
    llm: mesh.MeshLlmAgent = None,
) -> CountryInfo:
    """Get structured country information from whichever Claude provider is available."""
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for get_country_info")

    messages = [
        {
            "role": "user",
            "content": f"Tell me about {ctx.country}. Provide the country name, its capital city, and one interesting fun fact.",
        }
    ]

    response = await llm(messages)
    return response


@mesh.agent(
    name="multi-provider-consumer",
    version="1.0.0",
    description="Consumer agent that routes to any available Claude provider",
    http_port=9046,
    enable_http=True,
    auto_run=True,
)
class MultiProviderConsumerConfig:
    """Agent for testing multi-provider structured output routing."""

    pass
