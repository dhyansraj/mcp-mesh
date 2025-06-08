"""
Example FastMCP Integration with Dual-Decorator Pattern

Shows the correct dual-decorator pattern: @app.tool() + @mesh_agent()
Ensures tools work with vanilla MCP SDK and enhanced mesh features.
"""

import asyncio
import os

# Note: This example demonstrates the integration pattern
# In a real implementation, you would import FastMCP:
# from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


class MockFastMCP:
    """Mock FastMCP for demonstration purposes."""

    def __init__(self, name: str):
        self.name = name
        self.tools = []

    def tool(self, name: str | None = None, description: str | None = None):
        """Mock tool decorator that mimics FastMCP's @app.tool() decorator."""

        def decorator(func):
            func._tool_name = name or func.__name__
            func._tool_description = description or func.__doc__
            self.tools.append(func)
            return func

        return decorator


# Create FastMCP app instance
app = MockFastMCP(name="mesh-file-agent")


# Example 1: File operations with DUAL-DECORATOR pattern
@app.tool(name="read_file", description="Read file with mesh security")
@mesh_agent(
    capabilities=["file_read", "secure_access"],
    dependencies=["auth_service", "audit_logger"],
    health_interval=30,
    security_context="file_operations",
)
async def read_file(
    path: str, auth_service: str | None = None, audit_logger: str | None = None
) -> str:
    """Read file with automatic mesh integration."""
    # The @mesh_agent decorator has already:
    # - Registered capabilities with the registry
    # - Injected dependencies as function parameters
    # - Started health monitoring
    # - Set up error handling and retry logic

    print(f"🔒 Auth service: {auth_service or 'fallback mode'}")
    print(f"📝 Audit logger: {audit_logger or 'fallback mode'}")

    try:
        with open(path) as f:
            content = f.read()
        print(f"✅ Successfully read {len(content)} characters from {path}")
        return content
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        raise


# Example 2: System operations with DUAL-DECORATOR pattern
@app.tool(name="get_system_info", description="Get system information")
@mesh_agent(
    capabilities=["system_info"],
    dependencies=["monitoring_service"],
    health_interval=60,  # Less frequent heartbeat
    enable_caching=True,
    fallback_mode=True,
)
async def get_system_info(monitoring_service: str | None = None) -> dict:
    """Get system information with mesh monitoring."""
    print(f"📊 Monitoring service: {monitoring_service or 'fallback mode'}")

    return {
        "platform": os.name,
        "cwd": os.getcwd(),
        "pid": os.getpid(),
        "env_count": len(os.environ),
    }


# Example 3: Network operations with DUAL-DECORATOR pattern
@app.tool(name="network_health", description="Check network health")
@mesh_agent(
    capabilities=["network_check"],
    dependencies=["network_monitor", "alert_service"],
    health_interval=15,  # Frequent heartbeat for critical operations
    timeout=10,  # Short timeout
    retry_attempts=5,  # More retries
    fallback_mode=False,  # Strict mode - fail if mesh unavailable
)
async def check_network_health(
    network_monitor: str | None = None, alert_service: str | None = None
) -> dict:
    """Check network health with strict mesh requirements."""
    print(f"🌐 Network monitor: {network_monitor or 'not available'}")
    print(f"🚨 Alert service: {alert_service or 'not available'}")

    # Simulate network check
    return {"status": "healthy", "latency_ms": 12, "packet_loss": 0.0}


async def main():
    """Demonstrate FastMCP + mesh integration."""
    print("🚀 FastMCP + MCP-Mesh Integration Demo")
    print("=" * 50)

    # Test file operations
    print("\n1. Testing file operations with mesh...")
    try:
        # Create test file
        test_file = "/tmp/fastmcp_test.txt"
        with open(test_file, "w") as f:
            f.write("Hello from FastMCP + MCP-Mesh!")

        content = await read_file(test_file)
        print(f"File content: {content}")

    except Exception as e:
        print(f"Error in file operations: {e}")

    # Test system info
    print("\n2. Testing system info with mesh...")
    try:
        sys_info = await get_system_info()
        print(f"System info: {sys_info}")

    except Exception as e:
        print(f"Error in system info: {e}")

    # Test network health (will work in fallback mode since registry isn't running)
    print("\n3. Testing network health with mesh...")
    try:
        health = await check_network_health()
        print(f"Network health: {health}")

    except Exception as e:
        print(f"Error in network health: {e}")

    print("\n4. Cleaning up mesh resources...")
    # Cleanup all mesh decorators
    for tool_func in app.tools:
        if hasattr(tool_func, "_mesh_agent_metadata"):
            decorator_instance = tool_func._mesh_agent_metadata["decorator_instance"]
            await decorator_instance.cleanup()

    print("✅ Demo completed!")


if __name__ == "__main__":
    asyncio.run(main())
