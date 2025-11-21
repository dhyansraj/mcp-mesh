#!/usr/bin/env python3
"""
Test 1: Basic Template with Dict Context

Validates file:// template loading and dict context rendering.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Basic Template Test")


class ChatResponse(BaseModel):
    """Simple chat response."""

    answer: str
    confidence: float


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/basic_chat.jinja2",
    filter=None,
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # LiteLLM requires vendor prefix
    context_param="ctx",  # Explicit context parameter name
)
@mesh.tool(capability="chat")
def chat(
    message: str, ctx: dict, llm: mesh.MeshLlmAgent = None  # Dict context
) -> ChatResponse:
    """Chat with template-based system prompt."""
    return llm(message)


# Agent configuration for HTTP transport
@mesh.agent(
    name="basic-template-test",
    version="1.0.0",
    description="Basic Template Test Agent",
    http_port=9092,  # Use port 9092 (9091 is system_agent)
    enable_http=True,
    auto_run=True,
)
class BasicTemplateTestAgent:
    """Agent class for template testing."""

    pass


if __name__ == "__main__":
    app.run()
