#!/usr/bin/env python3
import asyncio
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastMCP server
agent_name = os.environ.get("AGENT_NAME", "sample-agent")
mcp = FastMCP(agent_name)


# Define tools using MCP Mesh decorators for automatic registration
# Each tool needs its own decorator to register properly
@mcp.tool()
@mesh_agent(
    capability="greet",
    agent_name=agent_name,
    version="1.0.0",
    enable_http=True,  # Force HTTP wrapper
    http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
    registry_url=os.environ.get(
        "MCP_MESH_REGISTRY_URL", "http://mcp-mesh-registry:8080"
    ),
    health_interval=30,
    tags=["sample", "greeting"],
)
async def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}! This is {agent_name} speaking."


@mcp.tool()
@mesh_agent(
    capability="echo",
    agent_name=agent_name,
    version="1.0.0",
    enable_http=True,
    http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
    registry_url=os.environ.get(
        "MCP_MESH_REGISTRY_URL", "http://mcp-mesh-registry:8080"
    ),
    health_interval=30,
    tags=["sample", "utility"],
)
async def echo(message: str) -> str:
    """Echo back the input message."""
    return f"Echo: {message}"


@mcp.tool()
@mesh_agent(
    capability="calculate",
    agent_name=agent_name,
    version="1.0.0",
    enable_http=True,
    http_host=os.environ.get("MCP_MESH_HTTP_HOST", "0.0.0.0"),
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8080")),
    registry_url=os.environ.get(
        "MCP_MESH_REGISTRY_URL", "http://mcp-mesh-registry:8080"
    ),
    health_interval=30,
    tags=["sample", "math"],
)
async def calculate(a: float, b: float, operation: str = "add") -> float:
    """Perform a simple calculation."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    else:
        raise ValueError(f"Unknown operation: {operation}")


async def main():
    # The mcp-mesh runtime will automatically handle:
    # 1. HTTP wrapper creation based on decorator parameters
    # 2. Registration with registry
    # 3. Health monitoring

    logger.info(f"Starting {agent_name}")
    logger.info(
        f"Registry URL: {os.environ.get('MCP_MESH_REGISTRY_URL', 'http://mcp-mesh-registry:8080')}"
    )
    logger.info(f"HTTP Host: {os.environ.get('MCP_MESH_HTTP_HOST', '0.0.0.0')}")
    logger.info(f"HTTP Port: {os.environ.get('MCP_MESH_HTTP_PORT', '8080')}")

    # The decorators should handle everything automatically
    # Let's give them some time to process
    await asyncio.sleep(5)

    # Log the decorator registry state
    from mcp_mesh import DecoratorRegistry

    mesh_agents = DecoratorRegistry.get_mesh_agents()
    logger.info(f"Registered mesh agents: {list(mesh_agents.keys())}")

    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
