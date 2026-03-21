#!/usr/bin/env python3
"""
media-llm-provider - MCP Mesh Media LLM Provider Agent

Zero-code LLM provider that exposes Claude via mesh delegation.
When the LLM's agentic loop calls tools that return resource_links,
the media resolver on this provider automatically converts them to
inline base64 images so the LLM can see and describe the actual media.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Media LLM Provider")


@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["claude", "sonnet", "media"],
    version="1.0.0",
)
def claude_provider():
    """Zero-code Claude provider for media analysis."""
    pass


@mesh.agent(
    name="media-llm-provider",
    version="1.0.0",
    description="LLM provider that resolves resource_links to inline images for Claude",
    http_port=9202,
    enable_http=True,
    auto_run=True,
)
class MediaLlmProvider:
    pass
