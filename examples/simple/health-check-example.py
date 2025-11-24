#!/usr/bin/env python3
"""
MCP Mesh Health Check Example

Demonstrates custom health check with TTL caching:
1. Define a custom health check function
2. Configure it with @mesh.agent decorator
3. Test LLM API connectivity as part of health checks
4. FastMCP integration with dual decorators
"""

import os
from datetime import UTC, datetime

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Health Check Example")


async def my_health_check() -> dict:
    """
    Custom health check that validates LLM API connectivity.

    This function is called before each heartbeat (with TTL caching)
    and when the /health endpoint is accessed.

    Can return:
    - bool: True = HEALTHY, False = UNHEALTHY
    - dict: {"status": "healthy/degraded/unhealthy", "checks": {...}, "errors": [...]}

    Returns:
        dict: Health status with checks and errors
    """
    print(f"[{datetime.now(UTC).isoformat()}] Running health check...")

    checks = {}
    errors = []
    status = "healthy"  # Can be: "healthy", "degraded", "unhealthy"

    # Check 1: LLM API Key presence
    api_key = os.getenv("ANTHROPIC_API_KEYS")
    if api_key:
        checks["llm_api_key_present"] = True
        print("✅ LLM API key is configured")
    else:
        checks["llm_api_key_present"] = False
        errors.append("ANTHROPIC_API_KEY not set")
        status = "unhealthy"
        print("❌ LLM API key is missing")

    # Check 2: Test LLM API connectivity with a lightweight HTTP request
    if api_key:
        try:
            # Simple HTTP HEAD request to check API reachability
            # This is fast and doesn't consume credits
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Simple HEAD request to check if endpoint exists
                # This is the fastest way to test connectivity without consuming credits
                response = await client.head(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "anthropic-version": "2023-06-01",
                        "x-api-key": api_key,
                    },
                )
                # We expect 405 (Method Not Allowed) or 401 (Unauthorized)
                # 405 = API reachable, endpoint exists, key not checked (HEAD not supported)
                # 401 = API reachable, key invalid
                # 400 = API reachable, key valid (some APIs)
                # 5xx = API unreachable or error
                if response.status_code in [400, 405]:
                    # 405 means endpoint exists but HEAD not allowed - that's fine
                    # 400 means endpoint exists and we got a response
                    checks["llm_api_reachable"] = True
                    checks["llm_api_key_valid"] = (
                        True  # Can't validate key with HEAD, assume OK
                    )
                    print("✅ LLM API is reachable")
                elif response.status_code == 401:
                    checks["llm_api_reachable"] = True
                    checks["llm_api_key_valid"] = False
                    errors.append("LLM API key is invalid")
                    status = "unhealthy"
                    print("❌ LLM API key is invalid (401)")
                else:
                    checks["llm_api_reachable"] = False
                    errors.append(
                        f"LLM API returned unexpected status: {response.status_code}"
                    )
                    status = "degraded"
                    print(
                        f"⚠️ LLM API returned unexpected status: {response.status_code}"
                    )
        except Exception as e:
            checks["llm_api_reachable"] = False
            errors.append(f"LLM API unreachable: {str(e)}")
            status = "degraded"
            print(f"⚠️ LLM API unreachable: {e}")

    # Check 3: Any other custom checks
    # For example: database connectivity, external service availability, etc.

    # Return simple dict - framework handles the rest
    return {
        "status": status,
        "checks": checks,
        "errors": errors,
    }


# Dual decorators: FastMCP + Mesh
@app.tool()
@mesh.tool(capability="greeting", description="Simple greeting function")
def greet(name: str = "World") -> str:
    """Greet someone by name."""
    return f"Hello, {name}! 👋"


# Agent configuration with health check
@mesh.agent(
    name="health-example",
    version="1.0.0",
    description="Example agent with custom health checks",
    http_port=9091,
    enable_http=True,
    auto_run=True,
    health_check=my_health_check,
    health_check_ttl=15,  # Cache for 15 seconds
)
class HealthCheckAgent:
    """
    Agent class that configures health checking.

    The mesh processor will:
    1. Discover the 'app' FastMCP instance
    2. Call health check function before heartbeats (cached for 15s)
    3. Expose /health endpoint with same cached results
    4. Start the FastMCP HTTP server on port 9091
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - Health check execution with TTL caching
# - HTTP server configuration on port 9091
# - Service registration with mesh registry
#
# Try accessing:
# - http://localhost:9091/health (health check endpoint)
# - http://localhost:9091/greet?name=Alice (tool endpoint)
#
# Health check behavior:
# - Runs before heartbeats (every 5s) with 15s cache
# - Runs on /health endpoint with same 15s cache
# - Cache shared between heartbeat and endpoint
