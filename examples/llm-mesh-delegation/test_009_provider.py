"""
PT-009: Basic Mesh Delegation - Provider Agent

This test provides the LLM provider agent that will be called by the consumer.
Uses @mesh.llm_provider to create a zero-code Claude provider.

Test:
    Provider: Port 9020 (LLM provider using @mesh.llm_provider)
    Consumer: Port 9021 (calls provider via mesh delegation)

Usage:
    docker compose -f docker-compose.llm-delegation.yml --profile test-pt-009 up -d
"""

import mesh
from fastmcp import FastMCP

# Create FastMCP app
app = FastMCP("PT-009 LLM Provider")


@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["claude", "sonnet", "test"],
    version="1.0.0",
)
def claude_provider():
    """
    Zero-code LLM provider for PT-009 testing.

    This provider will be discovered and called by the consumer agent
    via mesh delegation using provider=dict.
    """
    pass  # Implementation is in the decorator


@mesh.agent(
    name="pt-009-provider",
    version="1.0.0",
    description="PT-009: LLM Provider for Basic Mesh Delegation",
    http_port=9020,
    enable_http=True,
    auto_run=True,
)
class Pt009ProviderAgent:
    """Provider agent that exposes Claude LLM via mesh."""

    pass
