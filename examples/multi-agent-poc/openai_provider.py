#!/usr/bin/env python3
"""
OpenAI Provider Agent - LLM provider for multi-agent system

This agent provides OpenAI LLM access to other agents in the multi-agent PoC.
Uses @mesh.llm_provider to create a zero-code LLM provider that can be consumed
by specialist agents (Intent, Developer, Debug, QA, etc.) via mesh delegation.

Tags: ["openai", "gpt", "llm", "provider"]
"""

import mesh
from fastmcp import FastMCP

# Create FastMCP app
app = FastMCP("OpenAI Provider")


@mesh.llm_provider(
    model="openai/gpt-4o",
    capability="llm",
    tags=["llm", "openai", "gpt", "provider"],
    version="1.0.0",
)
def openai_provider():
    """
    Zero-code OpenAI LLM provider for multi-agent system.

    This provider will be discovered and called by specialist agents
    (Intent Agent, Developer Agent, Debug Agent, QA Agent, etc.)
    via mesh delegation using llm_provider filter.

    The decorator automatically:
    - Creates process_chat(request: MeshLlmRequest) -> str function
    - Wraps LiteLLM with error handling
    - Registers with mesh network for dependency injection
    """
    pass  # Implementation is in the decorator


@mesh.agent(
    name="openai-provider",
    version="1.0.0",
    description="OpenAI Provider - LLM provider for multi-agent system",
    http_port=9104,
    enable_http=True,
    auto_run=True,
)
class OpenAIProviderAgent:
    """OpenAI provider agent that exposes OpenAI LLM via mesh."""

    pass
