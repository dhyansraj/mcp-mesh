#!/usr/bin/env python3
"""
OpenAI Provider Agent - LLM provider for multi-agent system

This agent provides OpenAI LLM access to other agents in the multi-agent PoC.
Uses @mesh.llm_provider to create a zero-code LLM provider that can be consumed
by specialist agents (Intent, Developer, Debug, QA, etc.) via mesh delegation.

Tags: ["openai", "gpt", "llm", "provider"]
"""

import os

import mesh
from fastmcp import FastMCP

# Create FastMCP app
app = FastMCP("OpenAI Provider")


async def openai_health_check() -> dict:
    """
    Health check for OpenAI LLM provider.

    Validates:
    1. OPENAI_API_KEY environment variable is set
    2. OpenAI API is reachable

    Returns:
        dict: Health status with checks and errors
    """
    checks = {}
    errors = []
    status = "healthy"

    # Check 1: API Key presence
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        checks["openai_api_key_present"] = True
    else:
        checks["openai_api_key_present"] = False
        errors.append("OPENAI_API_KEY not set")
        status = "unhealthy"

    # Check 2: API connectivity (lightweight GET request to models endpoint)
    if api_key:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Use GET /models endpoint which is lightweight
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                    },
                )
                # 200 = API reachable and key valid
                if response.status_code == 200:
                    checks["openai_api_reachable"] = True
                    checks["openai_api_key_valid"] = True
                elif response.status_code == 401:
                    checks["openai_api_reachable"] = True
                    checks["openai_api_key_valid"] = False
                    errors.append("OpenAI API key is invalid")
                    status = "unhealthy"
                else:
                    # The vendor ANSWERED, so it is reachable — it is just not
                    # serving. Unhealthy: this is the outage the mesh has to route
                    # around, and anything else keeps heartbeating and keeps
                    # consumers pointed here.
                    checks["openai_api_reachable"] = True
                    errors.append(
                        f"OpenAI API returned unexpected status: {response.status_code}"
                    )
                    status = "unhealthy"
        except httpx.RequestError as e:
            # The vendor is not answering at all (DNS, connect, timeout, TLS).
            # Transport failures ONLY: anything else raised in here is a defect
            # in this probe, and it propagates rather than being reported as a
            # vendor outage — the runtime records an indeterminate verdict and
            # keeps this agent serving. A broken probe must not be able to
            # withdraw a working provider.
            checks["openai_api_reachable"] = False
            errors.append(f"OpenAI API unreachable: {str(e)}")
            status = "unhealthy"

    return {
        "status": status,
        "checks": checks,
        "errors": errors,
    }


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
    health_check=openai_health_check,
    health_check_ttl=30,  # Cache for 30 seconds
)
class OpenAIProviderAgent:
    """OpenAI provider agent that exposes OpenAI LLM via mesh."""

    pass
