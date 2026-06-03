#!/usr/bin/env python3
"""
hint-override-agent - Consumer that FORCES output_mode="hint" against an OpenAI provider.

Issue #1112 finding #6: a @mesh.llm consumer can set ``output_mode`` to override
the provider's auto-selected structured-output mode. OpenAI auto-selects ``strict``
(native ``response_format``); this consumer forces ``hint`` so the provider must
embed the schema in the prompt and DROP ``response_format`` while still producing
valid structured output.

Mirrors tc08's structured-agent (same simple CountryInfo model). The
``get_country_info_hint`` tool is ADDITIVE — the default ``get_country_info`` is
kept so the no-override behavior is also exercisable.
"""

from typing import Optional

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("HintOverrideAgent")


# ===== STRUCTURED OUTPUT MODEL (reused, simple) =====


class CountryInfo(BaseModel):
    """Structured output for country information."""

    country: str = Field(..., description="Name of the country")
    capital: str = Field(..., description="Capital city")
    population: Optional[str] = Field(None, description="Approximate population")


class StructuredContext(BaseModel):
    """Context for structured output request."""

    country_name: str = Field(..., description="Country to get info about")


# ===== DEFAULT (auto / unset output_mode) — kept for parity with tc08 =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+openai", "+provider"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="get_country_info",
    description="Get structured country information using LLM (auto mode)",
    version="1.0.0",
    tags=["structured", "openai"],
)
def get_country_info(
    ctx: StructuredContext,
    llm: mesh.MeshLlmAgent = None,
) -> CountryInfo:
    """Default path: provider auto-selects strict (native response_format)."""
    return llm(f"Provide information about {ctx.country_name}")


# ===== OVERRIDE: output_mode="hint" (Issue #1112 finding #6) =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+openai", "+provider"]},
    max_iterations=1,
    context_param="ctx",
    # Force HINT: overrides OpenAI's auto-selected STRICT. The provider must
    # embed the schema in the prompt and drop response_format.
    output_mode="hint",
)
@mesh.tool(
    capability="get_country_info_hint",
    description="Get structured country information using LLM with forced HINT mode",
    version="1.0.0",
    tags=["structured", "openai", "hint-override"],
)
def get_country_info_hint(
    ctx: StructuredContext,
    llm: mesh.MeshLlmAgent = None,
) -> CountryInfo:
    """
    Forced-HINT path: the consumer sets output_mode="hint", overriding the
    OpenAI provider's default strict mode while still producing a CountryInfo.
    """
    return llm(f"Provide information about {ctx.country_name}")


@mesh.agent(
    name="hint-override-agent",
    version="1.0.0",
    description="LLM consumer forcing output_mode=hint against an OpenAI provider",
    http_port=9042,
    enable_http=True,
    auto_run=True,
)
class HintOverrideAgent:
    """Agent for testing the output_mode='hint' consumer override (finding #6)."""

    pass
