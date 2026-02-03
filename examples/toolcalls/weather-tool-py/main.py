#!/usr/bin/env python3
"""
weather-tool-py - MCP Mesh Agent

A MCP Mesh agent that provides mock weather information.
"""

import random
from typing import Any

import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("WeatherToolPy Service")


# ===== TOOLS =====


@app.tool()
@mesh.tool(
    capability="get_weather",
    description="Get current weather for a city",
    tags=["weather", "data", "python"],
)
async def get_weather(city: str) -> dict[str, Any]:
    """
    Get current weather for a city.

    Args:
        city: The city name (e.g., "San Francisco", "New York", "London")

    Returns:
        Weather information including city, temperature, description, humidity.
    """
    descriptions = [
        "Partly cloudy with a chance of code reviews",
        "Sunny with scattered debugging sessions",
        "Clear skies, perfect for deploying",
        "Overcast with occasional stack traces",
        "Breezy with light refactoring showers",
        "Foggy with limited visibility into legacy code",
        "Warm and pleasant, ideal for pair programming",
        "Stormy with intermittent merge conflicts",
    ]

    temp_f = random.randint(5, 80)
    temp_c = round((temp_f - 32) * 5 / 9)
    humidity = random.randint(30, 90)
    description = random.choice(descriptions)

    return {
        "city": city,
        "temperature": f"{temp_f}F ({temp_c}C)",
        "description": description,
        "humidity": f"{humidity}%",
    }


# ===== AGENT CONFIGURATION =====


@mesh.agent(
    name="weather-tool-py",
    version="1.0.0",
    description="MCP Mesh agent for weather-tool-py",
    http_port=9000,
    enable_http=True,
    auto_run=True,
)
class WeatherToolPyAgent:
    """
    Agent class that configures how mesh should run the FastMCP server.

    The mesh processor will:
    1. Discover the 'app' FastMCP instance
    2. Apply dependency injection to decorated functions
    3. Start the FastMCP HTTP server on the configured port
    4. Register all capabilities with the mesh registry
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - Dependency injection between functions
# - HTTP server configuration
# - Service registration with mesh registry
