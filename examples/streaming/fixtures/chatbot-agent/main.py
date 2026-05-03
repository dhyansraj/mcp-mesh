#!/usr/bin/env python3
"""
chatbot-agent - MCP Mesh streaming chatbot (issue #645)

Exposes a single ``chat`` capability as ``mesh.Stream[str]``. The framework
detects the streaming return annotation and forwards each yielded chunk to
the consumer via FastMCP ``Context.report_progress(message=chunk)``.

Two modes:
- Real LLM: streams tokens from the injected ``MeshLlmAgent`` via the new
  ``MeshLlmAgent.stream()`` API.
- Dry run (``MESH_LLM_DRY_RUN=1``): emits a deterministic chunk sequence so
  tsuite tests do not depend on Anthropic API access.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Chatbot Agent")


_DRY_RUN_CHUNKS = [
    "Hello",
    " ",
    "world",
    "!",
    " This",
    " is",
    " a",
    " test",
    " response.",
]


def _dry_run_enabled() -> bool:
    return os.environ.get("MESH_LLM_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    max_iterations=1,
)
@mesh.tool(
    capability="chat",
    description="Stream a chat response token-by-token (issue #645)",
    version="1.0.0",
    tags=["llm", "streaming"],
)
async def chat(
    prompt: str,
    llm: mesh.MeshLlmAgent = None,
) -> mesh.Stream[str]:
    """Stream a chat response one token at a time."""
    if _dry_run_enabled():
        for chunk in _DRY_RUN_CHUNKS:
            yield chunk
        return

    if llm is None:
        raise RuntimeError(
            "chat: LLM dependency not injected and MESH_LLM_DRY_RUN is not set"
        )

    async for chunk in llm.stream(prompt):
        yield chunk


@mesh.agent(
    name="chatbot-agent",
    version="1.0.0",
    description="Streaming chatbot agent (issue #645)",
    http_port=9170,
    enable_http=True,
    auto_run=True,
)
class ChatbotAgent:
    pass
