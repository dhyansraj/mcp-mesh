#!/usr/bin/env python3
"""
Claude Provider Agent - LLM provider for multi-agent system

This agent provides Claude LLM access to other agents in the multi-agent PoC.
Uses @mesh.llm_provider to create a zero-code LLM provider that can be consumed
by specialist agents (Intent, Developer, Debug, QA, etc.) via mesh delegation.

Tags: ["claude", "anthropic", "llm", "provider"]
"""

import mesh
from fastmcp import FastMCP

# Create FastMCP app
app = FastMCP("Claude Provider")


@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["llm", "claude", "anthropic", "sonnet", "provider"],
    version="1.0.0",
)
def claude_provider():
    """
    Zero-code Claude LLM provider for multi-agent system.

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
    name="claude-provider",
    version="1.0.0",
    description="Claude Provider - LLM provider for multi-agent system",
    http_port=9101,
    enable_http=True,
    auto_run=True,
)
class ClaudeProviderAgent:
    """Claude provider agent that exposes Claude LLM via mesh."""

    pass
