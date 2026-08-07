#!/usr/bin/env python3
"""
media-llm-provider-kimi - MCP Mesh Kimi (Moonshot) LLM Provider Agent

Zero-code LLM provider that exposes Kimi via mesh delegation.
When the LLM's agentic loop calls tools that return resource_links,
the media resolver on this provider automatically converts them to
inline base64 images so the LLM can see and describe the actual media.

Unlike the OpenAI and Gemini providers, this one points at an
OpenAI-compatible third-party endpoint: the `base_url` and `api_key`
overrides on @mesh.llm_provider are all it takes to route the openai/*
model family somewhere other than OpenAI itself.

Note: kimi-k2.6 and kimi-k3 are both reasoning models. With a small max_tokens
the budget goes to reasoning and `content` comes back empty with no error
(finish_reason=length) — which looks exactly like broken vision. A one-word
answer cost 69 reasoning tokens on k2.6 and 18 on k3; this example sets no
max_tokens, and if you add one leave headroom well past those figures.

Model env-switchable: KIMI_MODEL=openai/kimi-k2.6 (default) or openai/kimi-k3.
Requires MOONSHOT_API_KEY environment variable.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Media LLM Provider Kimi")

KIMI_MODEL = os.getenv("KIMI_MODEL", "openai/kimi-k2.6")


@mesh.llm_provider(
    model=KIMI_MODEL,
    capability="llm",
    tags=["kimi", "media"],
    version="1.0.0",
    api_key=os.getenv("MOONSHOT_API_KEY"),
    base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1"),
)
def kimi_media_provider():
    """Zero-code Kimi provider for media analysis."""
    pass


@mesh.agent(
    name="media-llm-provider-kimi",
    version="1.0.0",
    description=f"LLM provider that resolves resource_links to inline images for Kimi ({KIMI_MODEL})",
    http_port=9207,
    enable_http=True,
    auto_run=True,
)
class MediaLlmProviderKimi:
    pass
