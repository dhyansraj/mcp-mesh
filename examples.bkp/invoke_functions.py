#!/usr/bin/env python3
"""
MCP Client to invoke functions on the RUNNING hello_world.py server

This shows how to actually call the functions and see the results.
"""

import asyncio
import json
import subprocess

from mcp import ClientSession


async def invoke_via_mcp_cli():
    """Use mcp CLI tool to invoke functions."""
    print("🎯 Method 1: Using mcp CLI tool")
    print("=" * 60)

    # The mcp CLI can connect to stdio servers
    # Format: echo '{}' | mcp call <server> <function> <args>

    functions = [
        "greet_from_mcp",
        "greet_from_mcp_mesh",
        "greet_single_capability",
        "test_dependency_injection",
    ]

    for func in functions:
        print(f"\n📞 Calling {func}():")
        try:
            # Use mcp dev tools to call the function
            cmd = f"echo '{{}}' | npx @modelcontextprotocol/inspector call stdio 'python examples/hello_world.py' {func}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"   → {result.stdout.strip()}")
            else:
                print(f"   → Error: {result.stderr}")
        except Exception as e:
            print(f"   → Failed: {e}")


async def invoke_via_python_client():
    """Direct Python client connection."""
    print("\n\n🎯 Method 2: Direct Python MCP Client")
    print("=" * 60)

    # Since the servers are running via stdio, we need to connect differently
    # The running servers are managed by mcp-mesh-dev, so we can't directly connect
    # Instead, let's show how to test with a fresh instance

    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command="python",
        args=["examples/hello_world.py"],
        env={"MCP_MESH_REGISTRY_URL": "http://localhost:8080"},
    )

    print("Starting a fresh hello_world.py instance to test...\n")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Call each function
            functions = [
                ("greet_from_mcp", "Plain MCP function"),
                ("greet_from_mcp_mesh", "Mesh function with dependency injection"),
                ("greet_single_capability", "Single capability pattern"),
                ("test_dependency_injection", "Check injection status"),
            ]

            for func_name, desc in functions:
                print(f"\n📞 {func_name} - {desc}:")
                try:
                    result = await session.call_tool(func_name, {})
                    content = result.content[0].text

                    # Pretty print JSON results
                    if func_name in ["test_dependency_injection", "get_demo_status"]:
                        try:
                            data = json.loads(content)
                            print(f"   → {json.dumps(data, indent=6)}")
                        except:
                            print(f"   → {content}")
                    else:
                        print(f"   → {content}")

                except Exception as e:
                    print(f"   → Error: {e}")


def show_manual_test_method():
    """Show how to manually test with existing tools."""
    print("\n\n🎯 Method 3: Manual Testing Options")
    print("=" * 60)

    print(
        """
Since your servers are already running with mcp-mesh-dev, here are ways to test:

1. **Using MCP Inspector (Recommended):**
   ```bash
   npx @modelcontextprotocol/inspector
   ```
   Then:
   - Add stdio server: python examples/hello_world.py
   - Browse and invoke functions interactively

2. **Using curl with JSON-RPC (if HTTP endpoint exposed):**
   The mesh may expose HTTP endpoints. Check mcp-mesh-dev logs for URLs.

3. **Using Claude Desktop or other MCP clients:**
   Configure your MCP client to connect to the stdio server.

4. **Quick Test - See the mesh in action:**
   Stop and restart hello_world.py to see how it automatically gets SystemAgent!
   """
    )


if __name__ == "__main__":
    print("🚀 How to Invoke Functions on Running MCP Servers")
    print("=" * 60)
    print("Your servers are running and registered. Here's how to call them:\n")

    # Method 1: Try CLI approach
    # asyncio.run(invoke_via_mcp_cli())

    # Method 2: Python client with fresh instance
    print("Testing with a fresh hello_world.py instance...")
    print("(Your existing servers remain running)")
    asyncio.run(invoke_via_python_client())

    # Method 3: Show manual options
    show_manual_test_method()

    print("\n✨ Key Point: When both servers are running, the mesh functions")
    print("automatically get SystemAgent injected and show the date/time!")
