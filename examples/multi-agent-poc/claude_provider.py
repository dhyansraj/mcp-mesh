#!/usr/bin/env python3
"""
Claude Provider Agent - LLM provider for multi-agent system

This agent provides Claude LLM access to other agents in the multi-agent PoC.
Uses @mesh.llm_provider to create a zero-code LLM provider that can be consumed
by specialist agents (Intent, Developer, Debug, QA, etc.) via mesh delegation.

Tags: ["claude", "anthropic", "llm", "provider"]
"""

import os

import mesh
from fastmcp import FastMCP

# Create FastMCP app
app = FastMCP("Claude Provider")


async def claude_health_check() -> dict:
    """
    Health check for Claude LLM provider.

    Validates:
    1. ANTHROPIC_API_KEY environment variable is set
    2. Anthropic API is reachable

    Returns:
        dict: Health status with checks and errors
    """
    checks = {}
    errors = []
    status = "healthy"

    # Check 1: API Key presence
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        checks["anthropic_api_key_present"] = True
    else:
        checks["anthropic_api_key_present"] = False
        errors.append("ANTHROPIC_API_KEY not set")
        status = "unhealthy"

    # Check 2: API connectivity (lightweight HEAD request)
    if api_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.head(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "anthropic-version": "2023-06-01",
                        "x-api-key": api_key,
                    },
                )
                # 405 = API reachable (HEAD not supported), 400 = endpoint exists
                if response.status_code in [400, 405]:
                    checks["anthropic_api_reachable"] = True
                    checks["anthropic_api_key_valid"] = True
                elif response.status_code == 401:
                    checks["anthropic_api_reachable"] = True
                    checks["anthropic_api_key_valid"] = False
                    errors.append("Anthropic API key is invalid")
                    status = "unhealthy"
                else:
                    checks["anthropic_api_reachable"] = False
                    errors.append(
                        f"Anthropic API returned unexpected status: {response.status_code}"
                    )
                    status = "degraded"
        except Exception as e:
            checks["anthropic_api_reachable"] = False
            errors.append(f"Anthropic API unreachable: {str(e)}")
            status = "degraded"

    return {
        "status": status,
        "checks": checks,
        "errors": errors,
    }


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
    health_check=claude_health_check,
    health_check_ttl=30,  # Cache for 30 seconds
)
class ClaudeProviderAgent:
    """Claude provider agent that exposes Claude LLM via mesh."""

    pass
