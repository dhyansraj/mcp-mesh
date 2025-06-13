#!/usr/bin/env python3
"""
Simple Hello World Agent for testing MCP Mesh integration.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the runtime path
sys.path.insert(0, str(Path(__file__).parent / "src" / "runtime" / "python" / "src"))

from mcp_mesh import mesh_agent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@mesh_agent(
    agent_name="hello-world",
    capabilities=["greeting", "hello_endpoint"],
    dependencies=[],  # No dependencies
    health_interval=5,
    version="1.0.0",
)
async def hello_world_main():
    """Main function for hello world agent."""
    logger.info("Hello World agent started successfully")

    # Simulate some work
    await asyncio.sleep(0.1)

    return {"message": "Hello World agent is running", "agent": "hello-world"}


if __name__ == "__main__":
    # Set registry URL from environment or default
    registry_url = os.environ.get("MCP_MESH_REGISTRY_URL", "http://localhost:8000")

    logger.info(f"Starting Hello World agent with registry: {registry_url}")

    # Run the agent using MCP Mesh processor
    from mcp_mesh.runtime.processor import DecoratorProcessor

    async def main():
        processor = DecoratorProcessor(registry_url=registry_url)

        try:
            # Process decorators (this will register the agent)
            results = await processor.process_all_decorators()
            logger.info(f"Registration results: {results}")

            # Keep the agent running
            logger.info("Hello World agent is running... Press Ctrl+C to stop")
            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Hello World agent shutting down...")
        finally:
            await processor.cleanup()

    asyncio.run(main())
