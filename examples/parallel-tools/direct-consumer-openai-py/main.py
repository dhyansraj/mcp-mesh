#!/usr/bin/env python3
"""
direct-consumer-openai-py - MCP Mesh Direct LLM Agent (OpenAI)

A MCP Mesh LLM agent that tests parallel tool execution using
direct mode with OpenAI GPT-4o.
"""

from typing import List, Optional

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("DirectConsumerOpenAIPy Service")


class AnalysisContext(BaseModel):
    """Context for stock analysis."""

    query: str = Field(..., description="The analysis query")
    ticker: Optional[str] = Field(
        default=None, description="Optional ticker symbol hint"
    )


class StockAnalysis(BaseModel):
    """Structured response from stock analysis."""

    summary: str = Field(..., description="Analysis summary")
    insights: List[str] = Field(..., description="List of insights")
    ticker: str = Field(..., description="Ticker symbol analyzed")
    data_sources: List[str] = Field(..., description="Data sources used")


@app.tool()
@mesh.llm(
    filter=[{"tags": ["financial", "slow-tool"]}],
    provider="openai/gpt-4o",
    max_iterations=5,
    parallel_tool_calls=True,
    system_prompt="file://prompts/system.jinja2",
    context_param="ctx",
)
@mesh.tool(
    capability="parallel_analyze",
    description="AI-powered stock analysis with parallel tool execution",
    version="1.0.0",
    tags=["analysis", "llm", "parallel-test"],
)
def parallel_analyze(
    ctx: AnalysisContext,
    llm: mesh.MeshLlmAgent = None,
) -> StockAnalysis:
    """
    AI-powered stock analysis using parallel tool execution.

    Args:
        ctx: Context containing analysis query and optional ticker
        llm: Injected LLM agent (provided by mesh)

    Returns:
        Structured stock analysis result
    """
    return llm(ctx.query)


@mesh.agent(
    name="direct-consumer-openai-py",
    version="1.0.0",
    description="Direct LLM agent (OpenAI) testing parallel tool execution",
    http_port=9000,
    enable_http=True,
    auto_run=True,
)
class DirectConsumerOpenAIPyAgent:
    pass
