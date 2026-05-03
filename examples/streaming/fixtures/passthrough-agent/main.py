#!/usr/bin/env python3
"""
passthrough-agent - MCP Mesh streaming intermediary (issue #645)

Re-emits chunks from an upstream ``chat`` capability without buffering.
Proves multi-hop streaming works (consumer -> passthrough -> chatbot, all
``Stream[str]`` end-to-end).
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Passthrough Agent")


@app.tool()
@mesh.tool(
    capability="chat_passthrough",
    description="Forward a chat stream from an upstream chat capability (issue #645)",
    version="1.0.0",
    tags=["streaming"],
    dependencies=["chat"],
)
async def chat_passthrough(
    prompt: str,
    chat: mesh.McpMeshTool = None,
) -> mesh.Stream[str]:
    """Forward chunks from the upstream ``chat`` capability."""
    if chat is None:
        raise RuntimeError("chat_passthrough: 'chat' dependency not injected")

    async for chunk in chat.stream(prompt=prompt):
        yield chunk


@mesh.agent(
    name="passthrough-agent",
    version="1.0.0",
    description="Streaming passthrough agent (issue #645)",
    http_port=9171,
    enable_http=True,
    auto_run=True,
)
class PassthroughAgent:
    pass
