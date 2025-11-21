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
    model="anthropic/claude-sonnet-4-5",
    context_param="ctx",  # Explicit context parameter name
)
@mesh.tool(capability="basic_chat", tags=["prompt-template", "test-001"])
def chat(message: str, ctx: dict, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
    """Chat with template-based system prompt."""
    return llm(message)


@mesh.agent(
    name="test-pt-001-basic-template",
    version="1.0.0",
    description="Test agent for basic template with dict context",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class BasicTemplateTestAgent:
    """Test agent configuration."""

    pass
