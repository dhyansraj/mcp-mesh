#!/usr/bin/env python3
"""
media-llm-provider-gemini - MCP Mesh Gemini LLM Provider Agent

Zero-code LLM provider that exposes Google Gemini 2.0 Flash via mesh delegation.
When the LLM's agentic loop calls tools that return resource_links,
the media resolver on this provider automatically converts them to
inline base64 images so the LLM can see and describe the actual media.

Requires GEMINI_API_KEY environment variable.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Media LLM Provider Gemini")


@mesh.llm_provider(
    model="gemini/gemini-2.0-flash",
    capability="llm",
    tags=["gemini", "flash", "media"],
    version="1.0.0",
)
def gemini_provider():
    """Zero-code Gemini provider for media analysis."""
    pass


@mesh.agent(
    name="media-llm-provider-gemini",
    version="1.0.0",
    description="LLM provider that resolves resource_links to inline images for Gemini 2.0 Flash",
    http_port=9205,
    enable_http=True,
    auto_run=True,
)
class MediaLlmProviderGemini:
    pass
