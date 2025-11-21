#!/usr/bin/env python3
"""
Test 3: LLM Agent with Multiple Tools

This test verifies LLM can work with multiple tools and make intelligent
decisions about which tools to use based on the user's question.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Multi-Tool Chat Agent")


class ChatResponse(BaseModel):
    """Response with detailed tool usage information."""

    answer: str
    confidence: float
    tools_used: list[str] = []
    reasoning: str = ""


@app.tool()
@mesh.llm(
    filter=[
        {"capability": "date_service"},  # Time/date tools
        {"capability": "info", "tags": ["system", "general"]},  # System info
        {"capability": "uptime_info"},  # Uptime information
    ],
    filter_mode="all",  # Get ALL matching tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # Same as test_002
    max_iterations=15,
    system_prompt="""You are a system administration assistant.
    You have access to multiple system tools:
    - Time and date information
    - System information and status
    - Uptime information

    Use the appropriate tools to answer questions accurately.
    If a question requires multiple pieces of information, use multiple tools.
    Explain your reasoning in the 'reasoning' field.""",
)
@mesh.tool(capability="multi_tool_chat", tags=["llm", "chat", "admin"])
def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
    """
    Chat with multiple tool access.

    This tests:
    1. Multiple capability filters
    2. Tag-based filtering
    3. Filter mode "all"
    4. LLM tool selection logic
    5. Multiple tool calls in single conversation
    """
    return llm(message)


# Test 7: Filter Mode "best_match"
@app.tool()
@mesh.llm(
    filter=[
        {"capability": "date_service"},  # Time/date tools
        {"capability": "info", "tags": ["system", "general"]},  # System info
        {"capability": "uptime_info"},  # Uptime information
    ],
    filter_mode="best_match",  # Best match per capability
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=15,
    system_prompt="""You are a system administration assistant.
    You have access to multiple system tools selected by best match criteria.

    Use the appropriate tools to answer questions accurately.
    If a question requires multiple pieces of information, use multiple tools.
    Explain your reasoning in the 'reasoning' field.""",
)
@mesh.tool(
    capability="multi_tool_chat_best_match", tags=["llm", "chat", "admin", "best_match"]
)
def chat_best_match(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
    """
    Chat with best_match filter mode.

    This tests:
    1. Filter mode "best_match"
    2. One tool per capability (best match)
    3. Tag-based selection for best match
    """
    return llm(message)


# Test 8: Wildcard Filter Mode (*)
@app.tool()
@mesh.llm(
    filter=None,  # No specific filter
    filter_mode="*",  # Wildcard - all available tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=15,
    system_prompt="""You are a system administration assistant with access to ALL available system tools.

    You have complete access to:
    - Time and date information
    - System information (both general and detailed disk/OS info)
    - Uptime information
    - Health diagnostics

    Use the appropriate tools to answer questions accurately.
    You can use any tool that helps answer the user's question.
    Explain your reasoning in the 'reasoning' field.""",
)
@mesh.tool(
    capability="multi_tool_chat_wildcard", tags=["llm", "chat", "admin", "wildcard"]
)
def chat_wildcard(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
    """
    Chat with wildcard filter mode (*).

    This tests:
    1. Filter mode "*" (wildcard)
    2. Access to ALL available tools
    3. Should receive all 5 tools from system agent
    """
    return llm(message)


@mesh.agent(
    name="multi-tool-chat-test",
    version="1.0.0",
    description="Test agent for multi-tool LLM integration",
    http_port=9003,
    enable_http=True,
    auto_run=True,
)
class MultiToolChatTestAgent:
    """Test agent configuration."""

    pass
