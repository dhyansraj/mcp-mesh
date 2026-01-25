#!/usr/bin/env python3
"""
openai-provider - MCP Mesh LLM Provider

A MCP Mesh LLM provider generated using meshctl scaffold.

This agent provides LLM access to other agents via the @mesh.llm_provider decorator.
"""

import os

import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("OpenaiProvider")


# ===== HEALTH CHECK =====


async def health_check() -> dict:
    """
    Health check for openai-provider.

    Validates:
    1. OPENAI_API_KEY environment variable is set
    2. OpenAI API is reachable

    Returns:
        dict: Health status with checks and errors
    """
    checks = {}
    errors = []
    status = "healthy"

    # Check API Key presence
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        checks["openai_api_key_present"] = True
    else:
        checks["openai_api_key_present"] = False
        errors.append("OPENAI_API_KEY not set")
        status = "unhealthy"

    # Check API connectivity
    if api_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if response.status_code == 200:
                    checks["openai_api_reachable"] = True
                    checks["openai_api_key_valid"] = True
                elif response.status_code == 401:
                    checks["openai_api_reachable"] = True
                    checks["openai_api_key_valid"] = False
                    errors.append("OpenAI API key is invalid")
                    status = "unhealthy"
                else:
                    checks["openai_api_reachable"] = False
                    errors.append(f"OpenAI API returned status: {response.status_code}")
                    status = "degraded"
        except Exception as e:
            checks["openai_api_reachable"] = False
            errors.append(f"OpenAI API unreachable: {str(e)}")
            status = "degraded"

    return {
        "status": status,
        "checks": checks,
        "errors": errors,
    }


# ===== LLM PROVIDER =====


@mesh.llm_provider(
    model="openai/gpt-4o",
    capability="llm",
    tags=["llm", "openai", "gpt", "provider"],
    version="1.0.0",
)
def openai_provider():
    """
    Zero-code LLM provider for openai-provider.

    This provider will be discovered and called by other agents
    via mesh delegation using the @mesh.llm decorator.

    The decorator automatically:
    - Creates process_chat(request: MeshLlmRequest) -> str function
    - Wraps LiteLLM with error handling
    - Registers with mesh network for dependency injection
    """
    pass  # Implementation is in the decorator


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="openai-provider",
    version="1.0.0",
    description="LLM Provider for openai/gpt-4o",
    http_port=9000,
    enable_http=True,
    auto_run=True,
    health_check=health_check,
    health_check_ttl=30,
)
class OpenaiProviderAgent:
    """
    LLM Provider agent that exposes openai/gpt-4o via mesh.

    Other agents can use this provider by specifying matching tags
    in their @mesh.llm decorator.
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - LiteLLM provider setup
# - HTTP server configuration
# - Service registration with mesh registry
