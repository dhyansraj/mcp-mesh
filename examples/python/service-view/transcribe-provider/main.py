#!/usr/bin/env python3
"""
transcribe-provider - MCP Mesh Agent

Publishes ``media.transcribe`` via producer sugar (RFC #1280): a class decorated
``@mesh.service("media")`` publishes its public ``transcribe`` method as the
dotted capability ``media.transcribe`` — the third slice of the shared
``media.*`` namespace, served by its own agent.

Cross-runtime note: parameter names (``assetId``, ``text``) match the Java and
TypeScript providers, so any-runtime gateways are interchangeable.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Transcribe Provider Service")


@mesh.service("media")
class MediaTranscribeService:
    """Producer sugar: publishes ``media.transcribe``."""

    async def transcribe(self, assetId: str, text: str) -> dict:
        """Generate a deterministic transcript for a media asset."""
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
