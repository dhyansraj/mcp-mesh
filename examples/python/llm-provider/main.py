#!/usr/bin/env python3
"""
py-llm-provider - MCP Mesh LLM Provider Agent

A zero-code LLM provider that exposes Claude via mesh delegation.
Used for UC06 observability tracing tests.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Py LLM Provider Service")


@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["claude", "sonnet"],
    version="1.0.0",
)
def claude_provider():
    """Zero-code LLM provider - implementation is in the decorator."""
    pass


@mesh.agent(
    name="py-llm-provider",
    version="1.0.0",
    description="Python LLM Provider for observability testing",
    http_port=9030,
    enable_http=True,
    auto_run=True,
)
class PyLlmProvider:
    pass
