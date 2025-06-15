#!/usr/bin/env python3
"""
Example showing how to fix the FastMCP server naming issue.

This demonstrates the solution to ensure FastMCP server uses @mesh.agent configuration.
"""

import logging
import time

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Import mesh decorators
import mesh


# Solution 1: Use mesh.create_server() to automatically use @mesh.agent name
@mesh.agent(
    name="hello-world-service",
    version="1.0.0",
    description="Fixed Hello World service",
    enable_http=True,
    namespace="demo",
)
class HelloWorldAgent:
    pass


# Create server using mesh.create_server() - this will use "hello-world-service" as the server name
server = mesh.create_server()


@mesh.tool(capability="greeting", description="Say hello to someone")
@server.tool()
def hello_world(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@mesh.tool(capability="status", description="Get service status")
@server.tool()
def get_status() -> dict:
    """Get service status."""
    return {
        "status": "running",
        "service": "hello-world-service",
        "timestamp": time.time(),
    }


@mesh.tool(capability="info", description="Get service information")
@server.tool()
def get_info() -> dict:
    """Get service information."""
    return {
        "name": "hello-world-service",
        "version": "1.0.0",
        "capabilities": ["greeting", "status", "info"],
    }


if __name__ == "__main__":
    print("🚀 Starting Fixed Hello World service...")
    print("🔧 Server name should now match @mesh.agent name: 'hello-world-service'")
    print("📝 Registry should show agent_id: hello-world-service-XXXXXXXX")
    print("🌐 HTTP endpoint should use @mesh.agent configuration")

    # The server will run and the processor will:
    # 1. Use "hello-world-service" as the agent name (from @mesh.agent)
    # 2. Create agent_id: "hello-world-service-XXXXXXXX"
    # 3. Use existing FastMCP server (created with mesh.create_server())
    # 4. Log that server name matches agent_id (no warning)
    # 5. Set up HTTP wrapper using @mesh.agent config (enable_http=True, etc.)

    try:
        while True:
            time.sleep(30)
            print("💓 Service running with properly configured server name...")
    except KeyboardInterrupt:
        print("\n🛑 Stopping service")
