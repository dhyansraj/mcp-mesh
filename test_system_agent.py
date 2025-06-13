#!/usr/bin/env python3
"""
Simple System Agent for testing MCP Mesh integration.
"""

import asyncio
import logging
import os
import platform
import sys
import time
from pathlib import Path

# Add the runtime path
sys.path.insert(0, str(Path(__file__).parent / "src" / "runtime" / "python" / "src"))

from mcp_mesh import mesh_agent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@mesh_agent(
    agent_name="system-monitor",
    capabilities=["cpu_usage", "memory_usage", "system_info"],
    dependencies=["greeting"],  # Depends on hello-world greeting capability
    health_interval=5,
    version="1.0.0",
)
async def system_monitor_main():
    """Main function for system monitor agent."""
    logger.info("System Monitor agent started successfully")

    # Get basic system information
    system_info = {
        "platform": platform.system(),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "uptime": time.time(),
        "agent": "system-monitor",
    }

    logger.info(f"System info: {system_info}")

    # Simulate some work
    await asyncio.sleep(0.1)

    return {
        "message": "System Monitor agent is running",
        "system_info": system_info,
        "capabilities": ["cpu_usage", "memory_usage", "system_info"],
    }


if __name__ == "__main__":
    # Set registry URL from environment or default
    registry_url = os.environ.get("MCP_MESH_REGISTRY_URL", "http://localhost:8000")

    logger.info(f"Starting System Monitor agent with registry: {registry_url}")

    # Run the agent using MCP Mesh processor
    from mcp_mesh.runtime.processor import DecoratorProcessor

    async def main():
        processor = DecoratorProcessor(registry_url=registry_url)

        try:
            # Process decorators (this will register the agent)
            results = await processor.process_all_decorators()
            logger.info(f"Registration results: {results}")

            # Keep the agent running
            logger.info("System Monitor agent is running... Press Ctrl+C to stop")
            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("System Monitor agent shutting down...")
        finally:
            await processor.cleanup()

    asyncio.run(main())
