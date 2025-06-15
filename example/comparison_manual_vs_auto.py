#!/usr/bin/env python3
"""
Comparison: Manual FastMCP vs Auto-created FastMCP

This shows both approaches side by side.
"""

import logging
import os
import time

logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

# Choose which approach to demonstrate
DEMO_MODE = "auto"  # Change to "manual" or "auto"

if DEMO_MODE == "manual":
    print("📋 MANUAL APPROACH - User creates FastMCP server explicitly")

    import mesh

    @mesh.agent(name="manual-service")
    class ManualAgent:
        pass

    # Manual: User creates FastMCP server
    server = mesh.create_server()  # or FastMCP("manual-service")

    @mesh.tool(capability="manual_greeting")
    @server.tool()  # Manual: User decorates with @server.tool()
    def hello_manual(name: str = "Manual World") -> str:
        return f"Hello from manual FastMCP, {name}!"

    @mesh.tool(capability="manual_math")
    @server.tool()  # Manual: User decorates with @server.tool()
    def add_manual(a: int, b: int) -> int:
        return a + b

    print("✅ Manual setup complete:")
    print("   • User created FastMCP server")
    print("   • User decorated functions with @server.tool()")
    print("   • User needs to manage server lifecycle")

elif DEMO_MODE == "auto":
    print("🪄 AUTO APPROACH - Processor creates FastMCP server automatically")

    import mesh

    @mesh.agent(name="auto-service")
    class AutoAgent:
        pass

    # Auto: NO FastMCP server creation needed
    # Auto: NO @server.tool() decoration needed

    @mesh.tool(capability="auto_greeting")
    def hello_auto(name: str = "Auto World") -> str:
        return f"Hello from auto-created FastMCP, {name}!"

    @mesh.tool(capability="auto_math")
    def add_auto(a: int, b: int) -> int:
        return a + b

    print("✅ Auto setup complete:")
    print("   • Processor will auto-create FastMCP server")
    print("   • Processor will auto-register @mesh.tool functions")
    print("   • Processor manages server lifecycle automatically")

if __name__ == "__main__":
    print(f"\n🚀 Starting {DEMO_MODE.upper()} FastMCP Demo")
    print("⏳ Waiting for processor initialization...")

    # CRITICAL: Keep process alive
    print("💓 Process must stay alive for FastMCP server to work")
    print("   (This is true for BOTH manual and auto approaches)")
    print("\n📡 Server running... (Ctrl+C to stop)")

    try:
        counter = 0
        while True:
            time.sleep(15)
            counter += 1
            print(f"💓 Heartbeat {counter} - {DEMO_MODE} FastMCP server active")
    except KeyboardInterrupt:
        print(f"\n🛑 Stopping {DEMO_MODE} demo...")
