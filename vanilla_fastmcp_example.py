#!/usr/bin/env python3
"""
Vanilla FastMCP Server - Multiple Decorators Example
"""

import asyncio
import json
from datetime import datetime

from fastmcp import FastMCP

# Create FastMCP server
app = FastMCP("Multi-Feature Server")


# TOOLS - Function calls
@app.tool()
def get_time() -> str:
    """Get current timestamp."""
    return datetime.now().isoformat()


@app.tool()
def add_numbers(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@app.tool()
def get_system_info() -> dict:
    """Get system information."""
    return {
        "server": "Multi-Feature Server",
        "timestamp": datetime.now().isoformat(),
        "status": "running",
    }


# PROMPTS - Text templates
@app.prompt()
def analysis_prompt(topic: str) -> str:
    """Generate analysis prompt."""
    return f"""Please analyze the following topic in detail:

Topic: {topic}

Provide:
1. Overview
2. Key points
3. Conclusions

Current time: {datetime.now().isoformat()}
"""


@app.prompt()
def summary_prompt(data: str) -> str:
    """Generate summary prompt."""
    return f"""Summarize this data concisely:

{data}

Focus on the most important points.
"""


# RESOURCES - Data access
@app.resource("config://server")
async def server_config() -> str:
    """Server configuration data."""
    config = {
        "name": "Multi-Feature Server",
        "version": "1.0.0",
        "features": ["tools", "prompts", "resources"],
        "created": datetime.now().isoformat(),
    }
    return json.dumps(config, indent=2)


@app.resource("data://stats")
async def server_stats() -> str:
    """Server statistics."""
    stats = {
        "uptime": "running",
        "requests": 0,
        "last_activity": datetime.now().isoformat(),
    }
    return json.dumps(stats, indent=2)


# Run server
if __name__ == "__main__":
    asyncio.run(app.run(transport="stdio"))
