#!/usr/bin/env python3
"""
media-llm-provider-openai - MCP Mesh OpenAI LLM Provider Agent

Zero-code LLM provider that exposes OpenAI GPT-4o via mesh delegation.
When the LLM's agentic loop calls tools that return resource_links,
the media resolver on this provider automatically converts them to
inline base64 images so the LLM can see and describe the actual media.

Requires OPENAI_API_KEY environment variable.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Media LLM Provider OpenAI")


@mesh.llm_provider(
    model="openai/gpt-4o",
    capability="llm",
    tags=["openai", "gpt4o", "media"],
    version="1.0.0",
)
def openai_provider():
    """Zero-code OpenAI provider for media analysis."""
    pass


@mesh.agent(
    name="media-llm-provider-openai",
    version="1.0.0",
    description="LLM provider that resolves resource_links to inline images for OpenAI GPT-4o",
    http_port=9204,
    enable_http=True,
    auto_run=True,
)
class MediaLlmProviderOpenAI:
    pass
