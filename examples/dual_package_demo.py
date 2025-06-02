"""
Dual Package Architecture Demo

Demonstrates how the same code works with both:
1. mcp-mesh-types (basic MCP SDK compatibility)
2. mcp-mesh (full mesh capabilities)
"""

import asyncio
import sys
from pathlib import Path

# Try importing from mcp-mesh-types first, then fallback to full mcp-mesh
try:
    from mcp_mesh_types import FileOperations, mesh_agent

    print("✅ Using mcp-mesh-types (basic compatibility mode)")
    package_type = "types"
except ImportError:
    try:
        from mcp_mesh import FileOperations, mesh_agent

        print("✅ Using mcp-mesh (full mesh capabilities)")
        package_type = "full"
    except ImportError:
        print("❌ Neither mcp-mesh-types nor mcp-mesh is available")
        sys.exit(1)


@mesh_agent(
    name="demo-agent",
    capabilities=["file_operations"],
    dependencies=["auth_service", "audit_logger"],
    health_interval=30,
)
class DemoFileAgent:
    """Demo agent that works with both package types."""

    def __init__(self):
        self.file_ops = FileOperations(base_directory="/tmp/dual_demo")

        # Create demo directory
        Path("/tmp/dual_demo").mkdir(exist_ok=True)

    async def demo_operations(self):
        """Perform demo file operations."""
        print(f"\n🔧 Package type: {package_type}")
        print(f"📂 Agent class: {self.__class__.__name__}")

        # Check if mesh metadata was attached by decorator
        if hasattr(self.__class__, "_mesh_metadata"):
            metadata = self.__class__._mesh_metadata
            print(f"🏷️  Mesh metadata: {metadata}")
        else:
            print("📋 No mesh metadata (basic mode)")

        # Test basic file operations
        print("\n1. Writing test file...")
        await self.file_ops.write_file(
            "/tmp/dual_demo/test.txt", "Hello from dual package demo!"
        )
        print("✅ File written")

        print("\n2. Reading test file...")
        content = await self.file_ops.read_file("/tmp/dual_demo/test.txt")
        print(f"✅ Content: {content}")

        print("\n3. Listing directory...")
        entries = await self.file_ops.list_directory("/tmp/dual_demo")
        print(f"✅ Entries: {entries}")

        print("\n4. Health check...")
        health = await self.file_ops.health_check()
        print(f"✅ Health: {health}")

        # Try error case
        print("\n5. Testing security validation...")
        try:
            await self.file_ops.read_file("../../../etc/passwd")
        except Exception as e:
            print(f"✅ Security working: {type(e).__name__}: {e}")


async def main():
    """Run the dual package demo."""
    print("🚀 Dual Package Architecture Demo")
    print("=" * 40)

    agent = DemoFileAgent()
    await agent.demo_operations()

    print("\n🎯 Key Benefits of Dual Package Architecture:")
    if package_type == "types":
        print("  - ✅ Basic MCP SDK compatibility")
        print("  - ✅ Zero additional dependencies")
        print("  - ✅ Lightweight for simple use cases")
        print("  - 📦 Upgrade to mcp-mesh for advanced features")
    else:
        print("  - ✅ Full mesh integration capabilities")
        print("  - ✅ Health monitoring and heartbeats")
        print("  - ✅ Dependency injection")
        print("  - ✅ Enhanced error handling and retry logic")
        print("  - ✅ Audit logging and security features")

    print("\n✨ Same code works with both packages!")


if __name__ == "__main__":
    asyncio.run(main())
