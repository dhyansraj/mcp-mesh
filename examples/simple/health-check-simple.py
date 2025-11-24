#!/usr/bin/env python3
"""
MCP Mesh Simple Health Check Example

Demonstrates basic health check functionality without external API calls.
Perfect for getting started without requiring API keys or external services.
"""

import os
from datetime import UTC, datetime

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Simple Health Check Example")


async def simple_health_check() -> dict:
    """
    Simple health check that checks environment configuration.

    Can return:
    - bool: True = HEALTHY, False = UNHEALTHY
    - dict: {"status": "healthy/degraded/unhealthy", "checks": {...}, "errors": [...]}

    Returns:
        dict: Health status with checks and errors
    """
    print(f"[{datetime.now(UTC).isoformat()}] Running simple health check...")

    checks = {}
    errors = []
    status = "healthy"  # Can be: "healthy", "degraded", "unhealthy"

    # Check 1: Required environment variables
    required_vars = ["ANTHROPIC_API_KEY"]  # Add your required vars here
    for var in required_vars:
        if os.getenv(var):
            checks[f"env_{var.lower()}"] = True
            print(f"✅ {var} is configured")
        else:
            checks[f"env_{var.lower()}"] = False
            errors.append(f"{var} not set")
            status = "degraded"
            print(f"⚠️ {var} is not configured")

    # Check 2: Disk space (example)
    try:
        import shutil

        stat = shutil.disk_usage("/")
        free_gb = stat.free / (1024**3)
        if free_gb > 1:  # More than 1GB free
            checks["disk_space"] = True
            print(f"✅ Disk space OK ({free_gb:.1f}GB free)")
        else:
            checks["disk_space"] = False
            errors.append(f"Low disk space: {free_gb:.1f}GB")
            status = "degraded"
            print(f"⚠️ Low disk space: {free_gb:.1f}GB")
    except Exception as e:
        checks["disk_space"] = False
        errors.append(f"Disk check failed: {str(e)}")
        print(f"⚠️ Disk check failed: {e}")

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


# Agent configuration with simple health check
@mesh.agent(
    name="simple-agent",
    version="1.0.0",
    description="Simple agent with basic health checks",
    http_port=9092,
    enable_http=True,
    auto_run=True,
    health_check=simple_health_check,
    health_check_ttl=15,  # Cache for 15 seconds
)
class SimpleHealthAgent:
    """
    Agent with simple health checks (no external APIs).

    Health checks:
    - Environment variable validation
    - Disk space checks
    - 15-second TTL caching
    """

    pass


# No main method needed!
# Try accessing:
# - http://localhost:9092/health (health check endpoint)
# - http://localhost:9092/greet?name=Alice (tool endpoint)
