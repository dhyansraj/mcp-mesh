#!/usr/bin/env python3
"""
py-llm-consumer - MCP Mesh LLM Consumer Agent

An LLM agent that uses mesh delegation to consume LLM services
and has a tool dependency on the "add" capability.
Used for UC06 observability tracing tests.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Py LLM Consumer Service")


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude"]},
    filter=[{"capability": "add"}],
    max_iterations=5,
    system_prompt="You are a helpful math assistant. When asked math questions, ALWAYS use the available add tool to compute the answer. Return the numeric result clearly.",
)
@mesh.tool(capability="qa", version="1.0.0")
async def analyze(question: str, llm: mesh.MeshLlmAgent = None) -> str:
    """
    Analyze a question using mesh-delegated LLM with tool access.

    Args:
        question: The question to analyze
        llm: Mesh LLM agent (injected automatically)

    Returns:
        Analysis result
    """
    result = await llm(question)
    return result


@mesh.agent(
    name="py-llm-consumer",
    version="1.0.0",
    description="Python LLM Consumer for observability testing",
    http_port=9031,
    enable_http=True,
    auto_run=True,
)
class PyLlmConsumer:
    pass
