#!/usr/bin/env python3
"""
health-block-test-agent - Reproducer for health-endpoint blocking bug.

Hypothesis: FastAPI (/health, /ready, /livez) and the mounted FastMCP app
share a single uvicorn event loop in a single thread. A tool that performs
sync blocking work (time.sleep) inside an async coroutine will block the
loop and prevent /livez from responding while the tool is running.
"""

import time

import mesh
from fastmcp import FastMCP

app = FastMCP("Health Block Test Service")


@app.tool()
@mesh.tool(
    capability="busy_tool",
    description="Blocks the event loop with sync time.sleep (NOT asyncio.sleep)",
    tags=["test", "blocking"],
)
async def busy_tool(seconds: int = 35) -> str:
    """Intentionally block the event loop to reproduce health endpoint stalls."""
    time.sleep(seconds)
    return f"slept {seconds}s (blocking)"


@app.tool()
@mesh.tool(
    capability="quick_tool",
    description="Returns immediately — sanity check that MCP endpoint works",
    tags=["test", "quick"],
)
async def quick_tool() -> str:
    return "ok"


@mesh.agent(
    name="health-block-test-agent",
    version="1.0.0",
    description="Reproducer for /livez blocking during long-running tool calls",
    http_port=9099,
    enable_http=True,
    auto_run=True,
)
class HealthBlockTestAgent:
    pass
