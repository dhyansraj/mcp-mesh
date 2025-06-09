#!/usr/bin/env python3
"""
Simple direct test of MCP functions to show the difference between
plain MCP and MCP Mesh with dependency injection.
"""

import asyncio
import json


async def test_mcp_functions():
    """Test MCP functions directly."""

    print("🧪 Direct MCP Function Testing")
    print("=" * 50)

    # Test 1: List tools
    print("\n📋 Test 1: List Available Tools")
    print("-" * 30)

    list_request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    process = await asyncio.create_subprocess_exec(
        "python",
        "examples/hello_world.py",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        # Send initialization
        init_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }
        )

        process.stdin.write((init_request + "\n").encode())
        await process.stdin.drain()

        # Wait for init response
        init_response = await process.stdout.readline()
        print(
            f"✅ Initialized: {json.loads(init_response.decode())['result']['serverInfo']['name']}"
        )

        # Send tools list request
        process.stdin.write((list_request + "\n").encode())
        await process.stdin.drain()

        # Read tools response
        tools_response = await process.stdout.readline()
        tools_data = json.loads(tools_response.decode())

        if "result" in tools_data and "tools" in tools_data["result"]:
            tools = tools_data["result"]["tools"]
            print(f"📋 Found {len(tools)} tools:")
            for tool in tools:
                print(
                    f"  • {tool['name']}: {tool.get('description', 'No description')}"
                )

        # Test 2: Call greet_from_mcp (plain MCP)
        print("\n🔧 Test 2: Call greet_from_mcp (Plain MCP)")
        print("-" * 40)

        greet_mcp_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "greet_from_mcp", "arguments": {}},
            }
        )

        process.stdin.write((greet_mcp_request + "\n").encode())
        await process.stdin.drain()

        greet_response = await process.stdout.readline()
        greet_data = json.loads(greet_response.decode())

        if "result" in greet_data and "content" in greet_data["result"]:
            content = greet_data["result"]["content"]
            if content and len(content) > 0:
                text = content[0].get("text", "No text")
                print(f"✅ Plain MCP Response: {text}")

        # Test 3: Call greet_from_mcp_mesh (MCP Mesh)
        print("\n🌐 Test 3: Call greet_from_mcp_mesh (MCP Mesh)")
        print("-" * 42)

        greet_mesh_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "greet_from_mcp_mesh", "arguments": {}},
            }
        )

        process.stdin.write((greet_mesh_request + "\n").encode())
        await process.stdin.drain()

        mesh_response = await process.stdout.readline()
        mesh_data = json.loads(mesh_response.decode())

        if "result" in mesh_data and "content" in mesh_data["result"]:
            content = mesh_data["result"]["content"]
            if content and len(content) > 0:
                text = content[0].get("text", "No text")
                print(f"✅ MCP Mesh Response: {text}")

                # Analyze the response
                if "its" in text and "here" in text:
                    print("🎉 SUCCESS: SystemAgent was injected and provided the date!")
                    print("    This shows the mesh dependency injection is working!")
                elif text == "Hello from MCP Mesh":
                    print("ℹ️  INFO: SystemAgent was not injected (fallback mode)")
                    print("    This is expected if system_agent.py is not running")

        # Test 4: Test dependency injection status
        print("\n🧩 Test 4: Test Dependency Injection Status")
        print("-" * 40)

        dep_test_request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "test_dependency_injection", "arguments": {}},
            }
        )

        process.stdin.write((dep_test_request + "\n").encode())
        await process.stdin.drain()

        dep_response = await process.stdout.readline()
        dep_data = json.loads(dep_response.decode())

        if "result" in dep_data and "content" in dep_data["result"]:
            content = dep_data["result"]["content"]
            if content and len(content) > 0:
                text = content[0].get("text", "No text")
                try:
                    result_data = json.loads(text)
                    print(
                        f"📊 Dependency Status: {result_data.get('dependency_injection_status', 'unknown')}"
                    )
                    print(
                        f"🤖 SystemAgent Available: {result_data.get('SystemAgent_available', False)}"
                    )
                    if "SystemAgent_response" in result_data:
                        print(
                            f"📅 SystemAgent Response: {result_data['SystemAgent_response']}"
                        )
                    print(f"💬 Message: {result_data.get('message', 'No message')}")
                except json.JSONDecodeError:
                    print(f"📄 Raw response: {text}")

    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback

        traceback.print_exc()
    finally:
        process.terminate()
        await process.wait()

    print("\n" + "=" * 50)
    print("🎯 Key Observations:")
    print("• greet_from_mcp: Always returns 'Hello from MCP'")
    print("• greet_from_mcp_mesh: Returns date if SystemAgent is injected")
    print("• Dependency injection works when both agents are running")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_mcp_functions())
