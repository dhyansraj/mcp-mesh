"""
PT-009: Basic Mesh Delegation - Consumer Agent

This test consumes LLM services via mesh delegation.
Uses @mesh.llm(provider=dict) to delegate LLM calls to mesh-registered providers.

Test:
    Provider: Port 9020 (LLM provider using @mesh.llm_provider)
    Consumer: Port 9021 (this agent - calls provider via mesh delegation)

Usage:
    docker compose -f docker-compose.llm-delegation.yml --profile test-pt-009 up -d

    # Test consumer calling provider via mesh
    curl -X POST http://localhost:9021/mcp \\
      -H "Content-Type: application/json" \\
      -H "Accept: application/json, text/event-stream" \\
      -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
          "name": "ask_question",
          "arguments": {
            "question": "What is 2+2? Answer in exactly 2 words."
          }
        }
      }'
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

# Create FastMCP app
app = FastMCP("PT-009 Consumer")


class Answer(BaseModel):
    """Answer response model."""

    response: str


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["claude"]},  # Mesh delegation!
    max_iterations=5,
)
@mesh.tool(capability="qa", version="1.0.0")
async def ask_question(question: str, llm: mesh.MeshLlmAgent = None) -> Answer:
    """
    Ask a question using mesh-delegated LLM.

    This function delegates LLM calls to a mesh-registered provider
    instead of calling LiteLLM directly.

    Args:
        question: The question to ask
        llm: Mesh LLM agent (injected automatically)

    Returns:
        Answer with response field
    """
    # LLM will be resolved from mesh (capability="llm", tags=["claude"])
    result = await llm(question)
    return result


@mesh.agent(
    name="pt-009-consumer",
    version="1.0.0",
    description="PT-009: Consumer using mesh-delegated LLM",
    http_port=9021,
    enable_http=True,
    auto_run=True,
)
class Pt009ConsumerAgent:
    """Consumer agent that uses mesh delegation for LLM calls."""

    pass
