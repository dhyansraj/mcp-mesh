#!/usr/bin/env python3
"""
chat-tools-agent - MCP Mesh consumer for the RFC #1100 loop-stress TC (tc37).

This is the multi-tool / multi-turn agentic-LOOP-STRESS consumer for the
Gemini-3 server-enforced response_json_schema + tools path, which is now
DEFAULT-ON (RFC #1100; kill-switch MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0).

Risk vector: the documented response_format + tools non-deterministic infinite-
tool-loop bug. tc36 only covers a single tool / ~2 iterations. This consumer:
  (a) declares a Pydantic structured return type (CalcAnalysis), AND
  (b) has TWO distinct mesh tools available (calc_add, calc_multiply),
  (c) and is driven by a prompt with a hard data dependency that forces
      MULTIPLE sequential tool-call rounds in the provider-side agentic loop:
      "first add X and Y, then multiply that result by Z".

The provider targeted is the Gemini-3 provider (gemini/gemini-3-flash-preview)
started WITHOUT any structured-tools env flag, so it uses the new DEFAULT
response_json_schema + tools path.

max_iterations is set modestly (8) so a runaway loop hits the cap fast rather
than running forever; the test step also has a bounded timeout so a loop fails
fast instead of hanging the run.

Modeled on uc04 tc18_structured_multi_turn_tools_py (multi-turn-tools, Claude)
and tc36 (Gemini-3 single tool) — but Gemini-3 + two tools + forced sequential
rounds.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("ChatToolsAgent")


# ===== STRUCTURED OUTPUT MODEL =====


class CalcAnalysis(BaseModel):
    """Structured output for the multi-step calculation analysis."""

    answer: str = Field(..., description="The final numeric answer to the question")
    reasoning: str = Field(
        ..., description="Brief explanation of the step-by-step calculation"
    )
    steps: int = Field(..., description="Number of calculation steps performed")
    used_tools: bool = Field(..., description="Whether the calculator tools were used")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")


class AnalysisContext(BaseModel):
    """Context for the analysis request."""

    question: str = Field(
        ..., description="A multi-step arithmetic question requiring sequential tools"
    )


# ===== LLM FUNCTION WITH TWO TOOLS + STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+gemini", "+provider"]},
    filter={"capability": "calculator"},
    max_iterations=8,
    context_param="ctx",
)
@mesh.tool(
    capability="analyze",
    description="Analyze a multi-step math question using the LLM with calculator tools",
    version="1.0.0",
    tags=["llm", "analysis", "structured", "tools"],
)
async def analyze(
    ctx: AnalysisContext,
    llm: mesh.MeshLlmAgent = None,
) -> CalcAnalysis:
    """
    Multi-step calc with two tools + structured output via the Gemini provider.

    The prompt deliberately requires SEQUENTIAL tool calls with a data
    dependency (add, then multiply the sum), so the agentic loop must run
    through several iterations WITH tools + server-enforced structured output.
    A loop-safe path completes in a small number of iterations and returns a
    valid structured object; a looping path keeps calling tools until
    max_iterations (8) and fails fast.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for analyze")

    response = await llm(ctx.question)
    return response


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="chat-tools-agent",
    version="1.0.0",
    description="Loop-stress consumer for Gemini-3 response_json_schema + tools",
    http_port=9034,
    enable_http=True,
    auto_run=True,
)
class ChatToolsAgentConfig:
    """Consumer agent for the RFC #1100 loop-stress TC."""

    pass
