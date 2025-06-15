#!/usr/bin/env python3
"""
Comparison: Auto-Run vs Manual Keep-Alive

This shows the difference between the old manual approach and new auto-run.
Change MODE to see different approaches.
"""

import logging
import os
import time

logging.basicConfig(level=logging.INFO)
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

MODE = "auto"  # Change to "manual" or "auto"

if MODE == "manual":
    print("📋 MANUAL APPROACH - Developer writes keep-alive loop")

    import mesh

    @mesh.agent(name="manual-service")
    class ManualAgent:
        pass

    @mesh.tool(capability="manual_greeting")
    def hello_manual():
        return "Hello from manual approach!"

    print("✅ Manual setup complete")
    print("🔄 Developer must write keep-alive loop...")

    # Manual approach: Developer writes this loop
    try:
        counter = 0
        while True:
            time.sleep(10)
            counter += 1
            print(f"💓 Manual heartbeat #{counter}")
    except KeyboardInterrupt:
        print("🛑 Manual shutdown")

elif MODE == "auto":
    print("🪄 AUTO-RUN APPROACH - No manual loop needed!")

    import mesh

    @mesh.agent(name="auto-service", auto_run=True, auto_run_interval=10)
    class AutoAgent:
        pass

    @mesh.tool(capability="auto_greeting")
    def hello_auto():
        return "Hello from auto-run approach!"

    print("✅ Auto setup complete")
    print("🎯 Starting auto-run service...")

    # Auto approach: Just call this function!
    mesh.start_auto_run_service()

else:
    print("❌ Invalid MODE. Set to 'manual' or 'auto'")
