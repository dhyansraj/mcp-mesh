#!/usr/bin/env python3
"""
chat-tools-agent - MCP Mesh Agent with chat history, tools, and structured output

Tests that structured output (HINT mode) remains reliable across 10+ conversation turns
when the agentic loop also uses tools. This is the most complex scenario:
- In-memory chat history across calls (cross-call state)
- Agentic loop with tool calling (within-call multi-turn)
- Complex Pydantic return type (structured output via HINT)

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/598
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("ChatToolsAgent")


# ===== IN-MEMORY CHAT HISTORY =====

chat_history: list[dict] = []


# ===== STRUCTURED OUTPUT MODEL (6+ fields) =====


class AnalysisResponse(BaseModel):
    """Complex structured output for analysis responses."""

    answer: str = Field(..., description="The direct answer to the question")
    reasoning: str = Field(
        ..., description="Brief explanation of how the answer was derived"
    )
    used_tools: bool = Field(..., description="Whether calculator tools were used")
    topic: str = Field(..., description="Main topic: math, science, general, or mixed")
    turn_number: int = Field(..., description="Current conversation turn number")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")


class AnalysisContext(BaseModel):
    """Context for analysis request."""

    question: str = Field(
        ..., description="Question to analyze, may require calculations"
    )


# ===== LLM FUNCTION WITH TOOLS AND STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    filter={"capability": "calculator"},
    max_iterations=5,
    context_param="ctx",
)
@mesh.tool(
    capability="analyze",
    description="Analyze questions using LLM with calculator tools and conversation history",
    version="1.0.0",
    tags=["llm", "analysis", "structured", "tools"],
)
async def analyze(
    ctx: AnalysisContext,
    llm: mesh.MeshLlmAgent = None,
) -> AnalysisResponse:
    """
    Analyze questions with tools and structured output.

    Maintains persistent chat history across calls. Some questions require
    calculator tools (testing agentic loop), others are knowledge questions
    (testing direct structured output). All must return AnalysisResponse.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for analyze")

    # Add user message to persistent history
    chat_history.append({"role": "user", "content": ctx.question})

    # Call LLM with full conversation history
    response = await llm(list(chat_history))

    # Store assistant response in history
    chat_history.append({"role": "assistant", "content": response.model_dump_json()})

    return response


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="chat-tools-agent",
    version="1.0.0",
    description="Agent testing structured output durability with tools and conversation history",
    http_port=9034,
    enable_http=True,
    auto_run=True,
)
class ChatToolsAgentConfig:
    """Agent for testing structured output multi-turn durability with tools."""

    pass
