#!/usr/bin/env python3
"""
llm-tools-agent - MCP Mesh LLM Agent with Tool Filter

Tests that provider proxy survives tools resolution when they happen
in different heartbeats (race condition fix).

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/448

This agent has BOTH:
1. Provider injection (for LLM)
2. Tool filter (for calculator tools)

The race condition occurred when:
- Provider resolution happens in heartbeat N
- Tools resolution happens in heartbeat N+1
- _process_function_tools() would wipe provider_proxy set by _process_function_provider()
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# FastMCP server instance
app = FastMCP("LlmToolsAgent")


# ===== CONTEXT MODEL =====


class MathQuestionContext(BaseModel):
    """Context for math question."""

    question: str = Field(..., description="Math question to answer")


# ===== LLM TOOL WITH PROVIDER AND TOOLS =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    filter={"capability": "calculator"},  # <-- This triggers tools resolution
    max_iterations=5,
    context_param="ctx",
)
@mesh.tool(
    capability="math_assistant",
    description="Answer math questions using LLM with calculator tools",
    version="1.0.0",
    tags=["llm", "math"],
)
def math_assistant(
    ctx: MathQuestionContext,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """
    Answer math questions using LLM with calculator tools.

    This function has BOTH provider injection AND tool filter,
    which tests the race condition fix. If the fix is not present,
    llm will be None with error "Mesh provider not resolved".

    Args:
        ctx: Context containing math question
        llm: Injected LLM agent (provided by mesh)

    Returns:
        Answer from LLM (may use calculator tools)
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved - race condition bug!")
    return llm(f"Answer this math question: {ctx.question}")


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="llm-tools-agent",
    version="1.0.0",
    description="LLM agent with both provider and tool filter (race condition test)",
    http_port=9031,
    enable_http=True,
    auto_run=True,
)
class LlmToolsAgentAgent:
    """Agent for testing provider-tools race condition fix."""

    pass
