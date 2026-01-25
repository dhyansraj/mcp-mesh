#!/usr/bin/env python3
"""
llm-agent - MCP Mesh LLM Agent

A MCP Mesh LLM agent generated using meshctl scaffold.
"""


import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# FastMCP server instance
app = FastMCP("LlmAgent Service")

# System prompt is loaded from: prompts/llm-agent.jinja2
# Customize the prompt file to change the LLM behavior.

# ===== CONTEXT MODEL =====


class LlmAgentContext(BaseModel):
    """Context for llm-agent LLM processing."""

    question: str = Field(..., description="User question to answer")


# ===== LLM TOOL =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    max_iterations=5,
    context_param="ctx",
)
@mesh.tool(
    capability="llm_agent",
    description="Answer user questions using LLM",
    version="1.0.0",
    tags=["llm"],
)
def llm_agent(
    ctx: LlmAgentContext,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """
    Answer user questions using LLM.

    Args:
        ctx: Context containing user question
        llm: Injected LLM agent (provided by mesh)

    Returns:
        Answer as text
    """
    return llm(f"Respond to: {ctx.question}")


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="llm-agent",
    version="1.0.0",
    description="MCP Mesh LLM agent for llm-agent",
    http_port=9010,
    enable_http=True,
    auto_run=True,
)
class LlmAgentAgent:
    """
    LLM Agent that uses Claude for processing.

    The mesh processor will:
    1. Discover the 'app' FastMCP instance
    2. Inject the LLM provider based on tags
    3. Start the FastMCP HTTP server on port 9000
    4. Register capabilities with the mesh registry
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - LLM provider injection
# - HTTP server configuration
# - Service registration with mesh registry
