"""
Dual-Decorator Pattern Example

Demonstrates how tools work with both MCP protocol and mesh integration,
ensuring compatibility with vanilla MCP SDK even when mesh is unavailable.
"""

import asyncio
import os

try:
    from mcp.server.fastmcp import FastMCP

    FASTMCP_AVAILABLE = True
except ImportError:
    # Fallback for development/testing
    FASTMCP_AVAILABLE = False

    class MockFastMCP:
        def __init__(self, name: str):
            self.name = name
            self.tools = []

        def tool(self, name: str | None = None, description: str | None = None):
            def decorator(func):
                func._tool_name = name or func.__name__
                func._tool_description = description or func.__doc__
                self.tools.append(func)
                return func

            return decorator

    FastMCP = MockFastMCP

from mcp_mesh_types import mesh_agent

# Create FastMCP app instance
app = (
    FastMCP(name="dual-decorator-demo")
    if FASTMCP_AVAILABLE
    else MockFastMCP("dual-decorator-demo")
)


# Example 1: Simple file read with dual decorators
@app.tool(
    name="read_text_file", description="Read a text file - works with vanilla MCP SDK"
)
@mesh_agent(
    capabilities=["file_read"],
    dependencies=["audit_logger"],
    fallback_mode=True,  # Graceful degradation when mesh unavailable
)
async def read_text_file(
    path: str, audit_logger: str | None = None  # Injected by mesh, optional for MCP
) -> str:
    """
    Read file contents.

    This function works in two modes:
    1. Pure MCP mode: Works with vanilla MCP SDK, no mesh features
    2. Mesh mode: Enhanced with audit logging and dependency injection
    """
    # Mesh feature: audit logging (only if available)
    if audit_logger:
        print(f"📝 Audit logger active: {audit_logger}")

    # Core MCP functionality (always works)
    try:
        with open(path) as f:
            content = f.read()
        print(f"✅ Read {len(content)} characters from {path}")
        return content
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        raise


# Example 2: System info with mesh monitoring
@app.tool(
    name="get_system_status",
    description="Get system status - enhanced with mesh monitoring",
)
@mesh_agent(
    capabilities=["system_info"],
    dependencies=["monitoring_service"],
    health_interval=60,
    fallback_mode=True,
)
async def get_system_status(
    monitoring_service: str | None = None,  # Injected by mesh
) -> dict:
    """
    Get system status information.

    Provides basic system info via MCP protocol,
    enhanced monitoring data when mesh is available.
    """
    # Core system info (always available)
    status = {"platform": os.name, "cwd": os.getcwd(), "pid": os.getpid()}

    # Enhanced monitoring (only if mesh available)
    if monitoring_service:
        print(f"📊 Enhanced monitoring via: {monitoring_service}")
        status["mesh_monitoring"] = True
        status["monitoring_service"] = monitoring_service
    else:
        status["mesh_monitoring"] = False

    return status


# Example 3: File write with backup capability
@app.tool(name="write_text_file", description="Write text file with optional backup")
@mesh_agent(
    capabilities=["file_write"],
    dependencies=["backup_service", "audit_logger"],
    fallback_mode=True,
)
async def write_text_file(
    path: str,
    content: str,
    create_backup: bool = True,
    backup_service: str | None = None,  # Injected by mesh
    audit_logger: str | None = None,  # Injected by mesh
) -> bool:
    """
    Write content to file.

    Basic functionality via MCP, enhanced backup via mesh.
    """
    # Enhanced backup (mesh feature)
    if create_backup and backup_service and os.path.exists(path):
        print(f"💾 Creating backup via: {backup_service}")
        # In real implementation, would use backup service
        backup_path = f"{path}.backup"
        with open(path) as src, open(backup_path, "w") as dst:
            dst.write(src.read())
        print(f"✅ Backup created: {backup_path}")

    # Core write functionality (always works)
    try:
        with open(path, "w") as f:
            f.write(content)

        # Enhanced audit logging (mesh feature)
        if audit_logger:
            print(f"📝 Audit log via: {audit_logger}")
            print(f"📝 Logged write: {path} ({len(content)} chars)")

        print(f"✅ Successfully wrote {len(content)} characters to {path}")
        return True

    except Exception as e:
        print(f"❌ Error writing file: {e}")
        raise


async def demo_vanilla_mcp_mode():
    """Demonstrate tools working in pure MCP mode (no mesh)."""
    print("🔧 Testing VANILLA MCP MODE (no mesh integration)")
    print("=" * 60)

    # Create test file
    test_file = "/tmp/mcp_test.txt"

    # Test write (no mesh dependencies injected)
    print("\n1. Writing file (pure MCP mode)...")
    result = await write_text_file(test_file, "Hello from MCP SDK!")
    print(f"Write result: {result}")

    # Test read (no mesh dependencies injected)
    print("\n2. Reading file (pure MCP mode)...")
    content = await read_text_file(test_file)
    print(f"Read content: {content}")

    # Test system status (no mesh dependencies injected)
    print("\n3. Getting system status (pure MCP mode)...")
    status = await get_system_status()
    print(f"System status: {status}")

    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)


async def demo_mesh_enhanced_mode():
    """Simulate tools working with mesh integration."""
    print("\n🌐 Testing MESH-ENHANCED MODE (simulated)")
    print("=" * 60)

    # Create test file
    test_file = "/tmp/mesh_test.txt"

    # Test write with simulated mesh dependencies
    print("\n1. Writing file (mesh mode)...")
    result = await write_text_file(
        test_file,
        "Hello from MCP-Mesh SDK!",
        backup_service="mesh-backup-service",
        audit_logger="mesh-audit-logger",
    )
    print(f"Write result: {result}")

    # Test read with simulated mesh dependencies
    print("\n2. Reading file (mesh mode)...")
    content = await read_text_file(test_file, audit_logger="mesh-audit-logger")
    print(f"Read content: {content}")

    # Test system status with simulated mesh dependencies
    print("\n3. Getting system status (mesh mode)...")
    status = await get_system_status(monitoring_service="mesh-monitoring-service")
    print(f"System status: {status}")

    # Cleanup
    for path in [test_file, f"{test_file}.backup"]:
        if os.path.exists(path):
            os.remove(path)


async def main():
    """Run the dual-decorator pattern demonstration."""
    print("🚀 DUAL-DECORATOR PATTERN DEMONSTRATION")
    print("=" * 60)
    print("Showing how tools work with both MCP protocol and mesh integration")
    print()

    # Test 1: Vanilla MCP mode (tools work without mesh)
    await demo_vanilla_mcp_mode()

    # Test 2: Mesh-enhanced mode (tools work with mesh features)
    await demo_mesh_enhanced_mode()

    print("\n✅ DEMONSTRATION COMPLETE")
    print("=" * 60)
    print("Key Points:")
    print("• Tools work with vanilla MCP SDK (no mesh required)")
    print("• Mesh features are optional enhancements")
    print("• @app.tool ensures MCP protocol compliance")
    print("• @mesh_agent adds enhanced capabilities")
    print("• Graceful degradation when mesh unavailable")


if __name__ == "__main__":
    asyncio.run(main())
