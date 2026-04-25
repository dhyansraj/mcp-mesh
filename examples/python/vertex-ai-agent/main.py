#!/usr/bin/env python3
"""
vertex-ai-agent - Minimal Gemini-via-Vertex-AI agent

Demonstrates calling Google Gemini through Vertex AI (IAM auth) instead of
AI Studio. The only differences from a Gemini AI Studio agent are:
  - model prefix:   "vertex_ai/<model>"   (vs "gemini/<model>")
  - auth env var:   GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
                    (vs GOOGLE_API_KEY)

Mesh-side prompt shaping (HINT-mode for tool calls, STRICT-mode for tool-free
structured output) is identical for both backends.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Vertex AI Agent")


class CapitalInfo(BaseModel):
    """Structured response describing a country and its capital."""

    name: str
    capital: str


@mesh.llm_provider(
    model="vertex_ai/gemini-2.0-flash",
    capability="llm",
    tags=["gemini", "vertex"],
    version="1.0.0",
)
def vertex_gemini_provider():
    """Zero-code Vertex AI Gemini provider — config is in the decorator."""
    pass


@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["vertex"]},
    system_prompt=(
        "You answer geography questions concisely. "
        "Return the country name and its capital as structured JSON."
    ),
)
@mesh.tool(capability="capital_lookup", version="1.0.0")
async def capital_of(country: str, llm: mesh.MeshLlmAgent = None) -> CapitalInfo:
    """Return the capital of a country as a structured CapitalInfo object."""
    return await llm(f"What is the capital of {country}?")


@mesh.agent(
    name="vertex-ai-agent",
    version="1.0.0",
    description="Gemini via Vertex AI (IAM auth) demo agent",
    http_port=9040,
    enable_http=True,
    auto_run=True,
)
class VertexAiAgent:
    pass
