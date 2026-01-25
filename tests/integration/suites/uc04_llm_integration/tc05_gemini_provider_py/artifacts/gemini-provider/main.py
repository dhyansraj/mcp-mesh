#!/usr/bin/env python3
"""
gemini-provider - MCP Mesh LLM Provider

A MCP Mesh LLM provider generated using meshctl scaffold.

This agent provides LLM access to other agents via the @mesh.llm_provider decorator.
"""

import os

import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("GeminiProvider")


# ===== HEALTH CHECK =====


async def health_check() -> dict:
    """
    Health check for gemini-provider.

    Validates:
    1. GOOGLE_API_KEY environment variable is set
    2. Google Gemini API is reachable

    Returns:
        dict: Health status with checks and errors
    """
    checks = {}
    errors = []
    status = "healthy"

    # Check API Key presence
    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        checks["google_api_key_present"] = True
    else:
        checks["google_api_key_present"] = False
        errors.append("GOOGLE_API_KEY not set")
        status = "unhealthy"

    # Check API connectivity (uses /v1beta/models - metadata only, no tokens consumed)
    if api_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                )
                if response.status_code == 200:
                    checks["gemini_api_reachable"] = True
                    checks["google_api_key_valid"] = True
                elif response.status_code == 400 or response.status_code == 403:
                    checks["gemini_api_reachable"] = True
                    checks["google_api_key_valid"] = False
                    errors.append("Google API key is invalid")
                    status = "unhealthy"
                else:
                    checks["gemini_api_reachable"] = False
                    errors.append(f"Gemini API returned status: {response.status_code}")
                    status = "degraded"
        except Exception as e:
            checks["gemini_api_reachable"] = False
            errors.append(f"Gemini API unreachable: {str(e)}")
            status = "degraded"

    return {
        "status": status,
        "checks": checks,
        "errors": errors,
    }


# ===== LLM PROVIDER =====


@mesh.llm_provider(
    model="gemini/gemini-2.0-flash",
    capability="llm",
    tags=["llm", "gemini", "google", "provider"],
    version="1.0.0",
)
def gemini_provider():
    """
    Zero-code LLM provider for gemini-provider.

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
    name="gemini-provider",
    version="1.0.0",
    description="LLM Provider for gemini/gemini-2.0-flash",
    http_port=9000,
    enable_http=True,
    auto_run=True,
    health_check=health_check,
    health_check_ttl=30,
)
class GeminiProviderAgent:
    """
    LLM Provider agent that exposes gemini/gemini-2.0-flash via mesh.

    Other agents can use this provider by specifying matching tags
    in their @mesh.llm decorator.
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - LiteLLM provider setup
# - HTTP server configuration
# - Service registration with mesh registry
