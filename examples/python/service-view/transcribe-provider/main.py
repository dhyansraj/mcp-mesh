#!/usr/bin/env python3
"""
transcribe-provider - MCP Mesh Agent

Publishes ``media.transcribe`` — the third slice of the shared ``media.*``
namespace, served by its own agent. The tool declares its dotted wire capability
explicitly with ``@mesh.tool(capability="media.transcribe")``.

Cross-runtime note: parameter names (``assetId``, ``text``) match the Java and
TypeScript providers, so any-runtime gateways are interchangeable.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Transcribe Provider Service")


@app.tool()
@mesh.tool(capability="media.transcribe")
async def transcribe(assetId: str, text: str) -> dict:
    """Generate a deterministic transcript for a media asset.

    Published under the dotted capability ``media.transcribe``.
    """
    stripped = text.strip()
    word_count = len(stripped.split()) if stripped else 0
    return {
        "assetId": assetId,
        "transcript": f"[{assetId}] {stripped.upper()}",
        "wordCount": word_count,
        "provider": "transcribe-provider",
    }


@mesh.agent(
    name="transcribe-provider",
    version="1.0.0",
    description="Publishes media.transcribe into the shared media.* namespace",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8122")),
    enable_http=True,
    auto_run=True,
)
class TranscribeProvider:
    pass
