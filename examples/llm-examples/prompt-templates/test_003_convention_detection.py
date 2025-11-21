#!/usr/bin/env python3
"""
Test 3: Convention-Based Context Detection

Validates automatic context parameter detection.
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Convention Detection Test")


class ChatContext(MeshContextModel):
    """Chat context model."""

    user_name: str = Field(description="User's name")
    domain: str = Field(description="Conversation domain")
    tone: str = Field(default="friendly", description="Response tone")
    style: str = Field(default="conversational", description="Response style")


class ChatResponse(BaseModel):
    answer: str


# Test 3a: Type hint detection
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/chat.jinja2",
    # No context_param - should detect via type hint!
    filter=None,
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
)
@mesh.tool(capability="chat_type_hint", tags=["prompt-template", "test-003a"])
def chat_type_hint(
    message: str, ctx: ChatContext, llm: mesh.MeshLlmAgent = None
) -> ChatResponse:
    """Chat with type hint context detection."""
    return llm(message)


# Test 3b: Convention name detection
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/chat.jinja2",
    # No context_param - should detect "prompt_context" by name!
    filter=None,
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
)
@mesh.tool(capability="chat_convention", tags=["prompt-template", "test-003b"])
def chat_convention(
    message: str, prompt_context: dict, llm: mesh.MeshLlmAgent = None
) -> ChatResponse:
    """Chat with convention-based context detection."""
    return llm(message)


@mesh.agent(
    name="test-pt-003-convention",
    version="1.0.0",
    description="Test agent for convention-based context detection",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class ConventionDetectionTestAgent:
    """Test agent configuration."""

    pass
