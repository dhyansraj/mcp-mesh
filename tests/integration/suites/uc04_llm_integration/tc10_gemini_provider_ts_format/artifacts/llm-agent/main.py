#!/usr/bin/env python3
"""
llm-agent - MCP Mesh LLM Agent for Gemini TS Provider

Tests that Gemini TypeScript provider correctly handles message format
without AI_InvalidPromptError.

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/461
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# FastMCP server instance
app = FastMCP("LlmAgentGeminiTs")


# ===== CONTEXT MODEL =====


class LlmAgentContext(BaseModel):
    """Context for llm-agent LLM processing."""

    question: str = Field(..., description="User question to answer")


# ===== LLM TOOL =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+gemini", "+provider"]},
    max_iterations=5,
    context_param="ctx",
)
@mesh.tool(
    capability="llm_agent_gemini_ts",
    description="Answer user questions using Gemini TS provider",
    version="1.0.0",
    tags=["llm", "gemini"],
)
def llm_agent_gemini_ts(
    ctx: LlmAgentContext,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """
    Answer user questions using Gemini TypeScript provider.

    This tests that the TS provider correctly formats messages
    for the Vercel AI SDK without causing AI_InvalidPromptError.

    Args:
        ctx: Context containing user question
        llm: Injected LLM agent (provided by mesh)

    Returns:
        Answer as text
    """
    return llm(f"Respond to: {ctx.question}")


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="llm-agent-gemini-ts",
    version="1.0.0",
    description="LLM agent for testing Gemini TS provider message format",
    http_port=9022,
    enable_http=True,
    auto_run=True,
)
class LlmAgentGeminiTsAgent:
    """Agent for testing Gemini TS provider message format."""

    pass
