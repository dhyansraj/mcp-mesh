#!/usr/bin/env python3
"""
chat-history-agent - MCP Mesh Agent with persistent chat history

Tests that structured output (HINT mode) remains reliable across 10+ conversation turns.
The agent maintains in-memory chat history, passing it to the LLM on each call.

Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/598
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("ChatHistoryAgent")


# ===== IN-MEMORY CHAT HISTORY =====

chat_history: list[dict] = []


# ===== STRUCTURED OUTPUT MODEL (6+ fields to stress HINT mode) =====


class ConversationalResponse(BaseModel):
    """Complex structured output to test HINT mode durability."""

    reply: str = Field(..., description="The actual answer to the user's question")
    sentiment: str = Field(
        ..., description="Sentiment of the response: positive, neutral, or negative"
    )
    topic: str = Field(..., description="Main topic of the conversation")
    turn_number: int = Field(..., description="Current conversation turn number")
    keywords: list[str] = Field(
        ..., description="Key terms extracted from the response"
    )
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")


class ChatContext(BaseModel):
    """Context for chat request."""

    message: str = Field(..., description="User message to chat about")


# ===== LLM FUNCTION WITH STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude", "+provider"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="chat",
    description="Chat with structured responses, maintaining conversation history",
    version="1.0.0",
    tags=["llm", "chat", "structured"],
)
async def chat(
    ctx: ChatContext,
    llm: mesh.MeshLlmAgent = None,
) -> ConversationalResponse:
    """
    Chat function that maintains history and returns structured output.

    Each call appends to the global chat_history, so subsequent calls
    see the full conversation. This tests whether HINT-mode structured
    output degrades as conversation history grows.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for chat")

    # Add user message to persistent history
    chat_history.append({"role": "user", "content": ctx.message})

    # Call LLM with full conversation history
    # MeshLlmAgent will inject system prompt at messages[0]
    response = await llm(list(chat_history))

    # Store assistant response as JSON in history for next turn
    chat_history.append({"role": "assistant", "content": response.model_dump_json()})

    return response


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="chat-history-agent",
    version="1.0.0",
    description="Agent testing structured output durability across multi-turn conversations",
    http_port=9033,
    enable_http=True,
    auto_run=True,
)
class ChatHistoryAgentConfig:
    """Agent for testing structured output multi-turn durability."""

    pass
