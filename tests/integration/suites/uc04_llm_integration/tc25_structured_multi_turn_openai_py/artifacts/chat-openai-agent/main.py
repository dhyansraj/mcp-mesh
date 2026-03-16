#!/usr/bin/env python3
"""
chat-openai-agent - Python consumer with structured output via OpenAI provider

Tests that native response_format structured output remains reliable across 5 conversation
turns with the OpenAI provider. Fills the gap left by tc08 which is single-turn only.
"""

from fastmcp import FastMCP
from pydantic import BaseModel, Field

import mesh

app = FastMCP("ChatOpenAIAgent")


# ===== IN-MEMORY CHAT HISTORY =====

chat_history: list[dict] = []


# ===== STRUCTURED OUTPUT MODEL =====


class ConversationalResponse(BaseModel):
    """Structured output for multi-turn chat."""

    reply: str = Field(..., description="The actual answer to the user's question")
    topic: str = Field(..., description="Main topic of the conversation")
    sentiment: str = Field(
        ..., description="Sentiment of the response: positive, neutral, or negative"
    )


class ChatContext(BaseModel):
    """Context for chat request."""

    message: str = Field(..., description="User message to chat about")


# ===== LLM FUNCTION WITH STRUCTURED OUTPUT =====


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+gpt"]},
    max_iterations=1,
    context_param="ctx",
)
@mesh.tool(
    capability="chat",
    description="Chat with structured responses via OpenAI provider",
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
    see the full conversation. This tests whether native response_format
    structured output works with OpenAI across multiple turns.
    """
    if llm is None:
        raise RuntimeError("Mesh provider not resolved for chat")

    chat_history.append({"role": "user", "content": ctx.message})

    response = await llm(list(chat_history))

    chat_history.append({"role": "assistant", "content": response.model_dump_json()})

    return response


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="chat-openai-agent",
    version="1.0.0",
    description="Agent testing OpenAI structured output durability across multi-turn conversations",
    http_port=9045,
    enable_http=True,
    auto_run=True,
)
class ChatOpenAIAgentConfig:
    """Agent for testing OpenAI structured output multi-turn durability."""

    pass
