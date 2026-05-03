#!/usr/bin/env python3
"""chatbot-agent - Streaming weather chatbot backed by Claude (issue #645 spike)."""

import mesh
from fastmcp import FastMCP

app = FastMCP("ChatbotAgent Service")


@app.tool()
@mesh.llm(
    filter=[{"capability": "get_weather"}],
    filter_mode="all",
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=5,
    system_prompt="file://prompts/chatbot-agent.jinja2",
)
@mesh.tool(
    capability="chat",
    description="Stream a chat response token-by-token with weather tool support",
    version="1.0.0",
    tags=["llm", "streaming", "chat"],
)
async def chat(
    prompt: str,
    llm: mesh.MeshLlmAgent = None,
) -> mesh.Stream[str]:
    """Stream the final-iteration response from Claude one chunk at a time."""
    if llm is None:
        raise RuntimeError("chat: LLM dependency not injected")

    async for chunk in llm.stream(prompt):
        yield chunk


@mesh.agent(
    name="chatbot-agent",
    version="1.0.0",
    description="Streaming weather chatbot powered by Claude",
    http_port=9181,
    enable_http=True,
    auto_run=True,
)
class ChatbotAgentAgent:
    pass
