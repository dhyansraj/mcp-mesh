"""
Test 1: Basic LLM Agent with No Tools (LLM-001)

This test verifies basic LLM integration without tool dependencies.
The LLM agent provides a simple chat capability that responds to questions
without calling any external tools.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Basic LLM Test Agent")


class ChatResponse(BaseModel):
    """Type-safe response from basic chat."""

    answer: str
    confidence: float
    reasoning: str = ""


@app.tool()
@mesh.llm(
    filter=None,  # No tools - empty filter
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=5,
    system_prompt="You are a helpful assistant. Answer questions concisely.",
)
@mesh.tool(capability="basic_chat", tags=["llm", "chat", "test"])
def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
    """
    Basic chat without tools.

    This function tests:
    1. MeshLlmAgent injection
    2. LiteLLM provider configuration
    3. Pydantic output type parsing
    4. Basic agentic loop (no tools)
    """
    return llm(message)


@mesh.agent(
    name="basic-llm-test",
    version="1.0.0",
    description="Test agent for basic LLM integration",
    http_port=9001,
    enable_http=True,
    auto_run=True,
)
class BasicLLMTestAgent:
    """Test agent configuration."""

    pass
