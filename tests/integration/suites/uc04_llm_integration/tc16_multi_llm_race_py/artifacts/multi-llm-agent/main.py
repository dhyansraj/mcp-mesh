#!/usr/bin/env python3
"""
multi-llm-agent - MCP Mesh Agent with MULTIPLE @mesh.llm functions

Tests that per-function tool update events don't delete sibling LLM functions' state.

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/598

BUG SCENARIO:
1. Agent has two @mesh.llm functions: math_assistant and science_assistant
2. Both have provider=... and filter=...
3. Rust core sends per-function tool updates (one function at a time)
4. rust_heartbeat.py wraps single function in dict, calls update_llm_tools()
5. update_llm_tools() has deletion logic that treats per-function event as full snapshot
6. When math_assistant's tools update arrives, science_assistant's provider_proxy is deleted
7. Calling science_assistant now fails with "Mesh provider not resolved"

The bug only manifests with MULTIPLE @mesh.llm functions in the same agent.
Single @mesh.llm function (like tc11) works fine because there's no sibling to delete.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("MultiLlmAgent")


# ===== CONTEXT MODELS =====


class MathQuestionContext(BaseModel):
    """Context for math questions."""

    question: str = Field(..., description="Math question to answer")


class ScienceQuestionContext(BaseModel):
    """Context for science questions."""

    question: str = Field(..., description="Science question to answer")


# ===== LLM FUNCTION 1: MATH ASSISTANT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    filter={"capability": "calculator"},
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
    """Answer math questions using LLM with calculator tools."""
    if llm is None:
        raise RuntimeError(
            "Mesh provider not resolved for math_assistant - multi-function race bug!"
        )
    return llm(f"Answer this math question: {ctx.question}")


# ===== LLM FUNCTION 2: SCIENCE ASSISTANT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    filter={"capability": "calculator"},
    max_iterations=5,
    context_param="ctx",
)
@mesh.tool(
    capability="science_assistant",
    description="Answer science questions using LLM with calculator tools",
    version="1.0.0",
    tags=["llm", "science"],
)
def science_assistant(
    ctx: ScienceQuestionContext,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Answer science questions using LLM with calculator tools."""
    if llm is None:
        raise RuntimeError(
            "Mesh provider not resolved for science_assistant - multi-function race bug!"
        )
    return llm(f"Answer this science question: {ctx.question}")


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="multi-llm-agent",
    version="1.0.0",
    description="Agent with multiple @mesh.llm functions (multi-function race test)",
    http_port=9032,
    enable_http=True,
    auto_run=True,
)
class MultiLlmAgentConfig:
    """Agent for testing multi-function provider_proxy race condition."""

    pass
