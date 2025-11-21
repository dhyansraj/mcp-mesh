#!/usr/bin/env python3
"""
Test 2: LLM Agent with System Time Tools (LLM-002)

This test verifies LLM agent can discover and use mesh tools.
The LLM will be able to call system time functions when asked about time.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Chat with Time Agent")


class ChatResponse(BaseModel):
    """Type-safe response with tool usage tracking."""

    answer: str
    confidence: float
    tools_used: list[str] = []


@app.tool()
@mesh.llm(
    filter={"capability": "date_service"},  # Request date_service tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=10,
    system_prompt="""You are a helpful assistant with access to system time tools.
    When asked about the current time or date, use the available tools to get accurate information.
    Always mention which tool you used in your response.""",
)
@mesh.tool(capability="chat_with_time", tags=["llm", "chat", "time"])
def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
    """
    Chat with access to system time tools.

    This function tests:
    1. Tool filtering by capability
    2. Tool injection into MeshLlmAgent
    3. Automatic tool discovery from registry
    4. Tool execution via MCP proxies
    5. Agentic loop with tool calls
    """
    return llm(message)


@mesh.agent(
    name="chat-with-time-test",
    version="1.0.0",
    description="Test agent for LLM with tool access",
    http_port=9003,  # Changed from 9002 to avoid conflict
    enable_http=True,
    auto_run=True,
)
class ChatWithTimeTestAgent:
    """Test agent configuration."""

    pass
