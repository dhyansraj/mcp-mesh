#!/usr/bin/env python3
"""
Test Client with MCP Mesh-like Architecture

This transforms the simple client into a decorator-driven MCP server
that mimics MCP Mesh's architecture where:
- No main function
- Server starts during decorator processing
- FastMCP client calls happen within MCP tool context
"""

import os
import asyncio
import logging
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create FastMCP instance (like MCP Mesh users do)
app = FastMCP("Test Client Mesh")

# Import our test mesh processor (this will trigger server startup)
from test_mesh_processor import test_mesh

@app.tool()
@test_mesh.tool()  # This decorator will trigger server startup
async def call_remote_server(task_type: str = "ping") -> dict:
    """Tool that calls test-server with parameterized task type to test async behavior.

    Args:
        task_type: Type of task to call on remote server: 'slow', 'fast', 'ping', or 'echo'
    """
    from fastmcp import Client

    target_host = os.getenv("TARGET_HOST", "localhost:8080")  # Use env var for Docker service names
    endpoint = f"http://{target_host}/mcp"

    logger.info(f"🎯 Calling remote server at: {endpoint} with task_type: {task_type}")

    try:
        async with Client(endpoint) as client:
            logger.info("✅ FastMCP client connected successfully")

            if task_type == "slow":
                logger.info("🐌 Starting slow task (30 seconds) - this should NOT block other calls")
                result = await client.call_tool("slow_task")
                logger.info(f"📥 Slow task result: {result}")
                return {
                    "status": "success",
                    "task_type": task_type,
                    "target_host": target_host,
                    "endpoint": endpoint,
                    "result": result,
                    "message": "Successfully completed slow task - concurrent calls should work"
                }
            elif task_type == "fast":
                logger.info("⚡ Starting fast task (immediate)")
                result = await client.call_tool("fast_task")
                logger.info(f"📥 Fast task result: {result}")
                return {
                    "status": "success",
                    "task_type": task_type,
                    "target_host": target_host,
                    "endpoint": endpoint,
                    "result": result,
                    "message": "Successfully completed fast task - should return immediately even during slow task"
                }
            elif task_type == "echo":
                result = await client.call_tool("echo", {"message": "Hello from client mesh!"})
                logger.info(f"📥 Echo result: {result}")
                return {
                    "status": "success",
                    "task_type": task_type,
                    "result": result,
                    "message": "Successfully called echo"
                }
            else:  # Default to ping
                result = await client.call_tool("ping")
                logger.info(f"📥 Ping result: {result}")
                return {
                    "status": "success",
                    "task_type": task_type,
                    "result": result,
                    "message": "Successfully called ping"
                }

    except Exception as e:
        logger.error(f"❌ Failed to call remote server with task_type {task_type}: {e}")
        return {
            "status": "error",
            "task_type": task_type,
            "target_host": target_host,
            "endpoint": endpoint,
            "error": str(e),
            "message": f"Failed to call remote server with task_type {task_type}"
        }


@app.tool()
@test_mesh.tool()
def get_client_info() -> dict:
    """Get information about this client mesh instance."""
    import socket
    hostname = socket.gethostname()

    return {
        "service_name": "test-client-mesh",
        "hostname": hostname,
        "target_host": os.getenv("TARGET_HOST", "localhost:8080"),
        "status": "running",
        "message": "Hello from test client mesh!"
    }

# NO main function - server will start during decorator processing
# This is the key difference from vanilla FastMCP and mimics MCP Mesh architecture

logger.info("🚀 Test client mesh script loaded - server should start via decorators")