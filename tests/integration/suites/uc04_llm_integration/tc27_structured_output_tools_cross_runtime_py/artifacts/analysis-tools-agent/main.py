#!/usr/bin/env python3
"""
analysis-tools-agent - MCP Mesh Agent with structured output and tool calling.

Tests the most complex scenario: cross-runtime structured output with tools.
Python consumer with BOTH structured output AND tool calling routing through
a Java Claude provider. This is the production avatar pattern.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("AnalysisToolsAgent")


class AnalysisResponse(BaseModel):
    """Structured output for analysis responses."""

    answer: str = Field(..., description="The direct answer to the question")
    reasoning: str = Field(
        ..., description="Brief explanation of how the answer was derived"
    )
    used_tools: bool = Field(..., description="Whether calculator tools were used")


class AnalysisContext(BaseModel):
    """Context for analysis request."""

    question: str = Field(
        ..., description="Question to analyze, may require calculations"
    )


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    filter={"capability": "calculator"},
    max_iterations=5,
    context_param="ctx",
)
@mesh.tool(
    capability="analysis",
    description="Analyze questions using LLM with calculator tools and structured output",
    version="1.0.0",
    tags=["llm", "analysis", "structured", "tools"],
)
async def analyze(
    ctx: AnalysisContext,
    llm: mesh.MeshLlmAgent = None,
) -> AnalysisResponse:
    """
    Analyze questions with tools and structured output.

    Some questions require calculator tools (testing agentic loop with cross-runtime
    provider), others are knowledge questions (testing direct structured output).
    All must return AnalysisResponse.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for analyze")

    messages = [
        {
            "role": "user",
            "content": ctx.question,
        }
    ]

    response = await llm(messages)
    return response


@mesh.agent(
    name="analysis-tools-agent",
    version="1.0.0",
    description="Agent testing cross-runtime structured output with tool calling",
    http_port=9047,
    enable_http=True,
    auto_run=True,
)
class AnalysisToolsAgentConfig:
    """Agent for testing cross-runtime structured output with tools."""

    pass
