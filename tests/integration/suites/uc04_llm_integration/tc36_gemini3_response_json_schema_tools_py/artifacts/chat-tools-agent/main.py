#!/usr/bin/env python3
"""
chat-tools-agent - MCP Mesh consumer for the RFC #1100 live experiment.

LIVE EXPERIMENT (RFC #1100 follow-up): does Gemini-3 + response_json_schema +
tools trigger the documented infinite-tool-loop bug, or is it loop-safe?

This consumer:
  (a) declares a Pydantic structured return type (AnalysisResponse), AND
  (b) has a mesh tool available to the LLM (calculator capability),
so the provider-side agentic loop runs WITH tools + structured output.

The provider it targets is the Gemini-3 provider, started with
MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=1 so the gated response_json_schema
path is exercised instead of the default PROSE_HINT.

max_iterations is set modestly (6) so a runaway loop hits the cap fast rather
than running forever; the test step itself also has a bounded timeout so a loop
fails fast.

Modeled on uc04 tc18_structured_multi_turn_tools_py / tc27, but pointed at the
Gemini provider via the +gemini provider tag.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("ChatToolsAgent")


# ===== STRUCTURED OUTPUT MODEL =====


class AnalysisResponse(BaseModel):
    """Structured output for the analysis response."""

    answer: str = Field(..., description="The direct answer to the question")
    reasoning: str = Field(
        ..., description="Brief explanation of how the answer was derived"
    )
    used_tools: bool = Field(..., description="Whether the calculator tool was used")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")


class AnalysisContext(BaseModel):
    """Context for the analysis request."""

    question: str = Field(
        ..., description="Question to analyze, may require a calculation"
    )


# ===== LLM FUNCTION WITH TOOLS AND STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+gemini", "+provider"]},
    filter={"capability": "calculator"},
    max_iterations=6,
    context_param="ctx",
)
@mesh.tool(
    capability="analyze",
    description="Analyze a question using the LLM with the calculator tool",
    version="1.0.0",
    tags=["llm", "analysis", "structured", "tools"],
)
async def analyze(
    ctx: AnalysisContext,
    llm: mesh.MeshLlmAgent = None,
) -> AnalysisResponse:
    """
    Analyze a question with tools + structured output via the Gemini provider.

    The prompt deliberately requires a single tool call (the calculator) and
    then a structured return, so the agentic loop runs WITH tools + structured
    output. A loop-safe path completes in a small number of iterations; a
    looping path will keep calling the tool until max_iterations.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for analyze")

    response = await llm(ctx.question)
    return response


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="chat-tools-agent",
    version="1.0.0",
    description="Consumer for the Gemini-3 response_json_schema + tools experiment",
    http_port=9034,
    enable_http=True,
    auto_run=True,
)
class ChatToolsAgentConfig:
    """Consumer agent for the RFC #1100 live experiment."""

    pass
