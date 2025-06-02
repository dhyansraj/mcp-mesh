#!/usr/bin/env python3
"""
MCP Test Client

A test client to verify MCP protocol compliance and test server functionality.
Demonstrates client-server communication using the official MCP SDK.
"""

import asyncio
import sys
from pathlib import Path
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class MCPTestClient:
    """Test client for MCP protocol compliance verification."""

    def __init__(self, server_script: str):
        """
        Initialize the test client.

        Args:
            server_script: Path to the MCP server script to test
        """
        self.server_script = server_script
        self.session: ClientSession | None = None

    async def connect(self) -> bool:
        """
        Connect to the MCP server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            print(f"🔌 Connecting to server: {self.server_script}")

            # Create server parameters
            server_params = StdioServerParameters(
                command=sys.executable, args=[self.server_script]
            )

            # Create stdio client connection
            stdio_streams = stdio_client(server_params)
            read_stream, write_stream = await stdio_streams.__aenter__()

            # Create and initialize client session
            self.session = ClientSession(read_stream, write_stream)

            # Initialize the session
            init_result = await self.session.initialize()
            print(f"✅ Connected! Server capabilities: {init_result.capabilities}")

            return True

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    async def test_list_tools(self) -> list[dict[str, Any]]:
        """
        Test listing available tools.

        Returns:
            List of available tools
        """
        print("\n🔧 Testing: List Tools")
        try:
            if not self.session:
                raise RuntimeError("Not connected to server")

            tools = await self.session.list_tools()
            print(f"📋 Found {len(tools)} tools:")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            return tools

        except Exception as e:
            print(f"❌ List tools failed: {e}")
            return []

    async def test_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Test calling a specific tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool

        Returns:
            Tool execution result
        """
        print(f"\n🛠️ Testing: Call Tool '{tool_name}' with {arguments}")
        try:
            if not self.session:
                raise RuntimeError("Not connected to server")

            result = await self.session.call_tool(tool_name, arguments)
            print(f"✅ Tool result: {result}")
            return result

        except Exception as e:
            print(f"❌ Tool call failed: {e}")
            return None

    async def test_list_resources(self) -> list[dict[str, Any]]:
        """
        Test listing available resources.

        Returns:
            List of available resources
        """
        print("\n📄 Testing: List Resources")
        try:
            if not self.session:
                raise RuntimeError("Not connected to server")

            resources = await self.session.list_resources()
            print(f"📋 Found {len(resources)} resources:")
            for resource in resources:
                print(f"  - {resource.uri}: {resource.name}")
            return resources

        except Exception as e:
            print(f"❌ List resources failed: {e}")
            return []

    async def test_read_resource(self, uri: str) -> Any:
        """
        Test reading a specific resource.

        Args:
            uri: URI of the resource to read

        Returns:
            Resource content
        """
        print(f"\n📖 Testing: Read Resource '{uri}'")
        try:
            if not self.session:
                raise RuntimeError("Not connected to server")

            result = await self.session.read_resource(uri)
            print(f"✅ Resource content: {result.contents[0].text[:100]}...")
            return result

        except Exception as e:
            print(f"❌ Read resource failed: {e}")
            return None

    async def test_list_prompts(self) -> list[dict[str, Any]]:
        """
        Test listing available prompts.

        Returns:
            List of available prompts
        """
        print("\n💬 Testing: List Prompts")
        try:
            if not self.session:
                raise RuntimeError("Not connected to server")

            prompts = await self.session.list_prompts()
            print(f"📋 Found {len(prompts)} prompts:")
            for prompt in prompts:
                print(f"  - {prompt.name}: {prompt.description}")
            return prompts

        except Exception as e:
            print(f"❌ List prompts failed: {e}")
            return []

    async def test_get_prompt(self, name: str, arguments: dict[str, Any] = None) -> Any:
        """
        Test getting a specific prompt.

        Args:
            name: Name of the prompt to get
            arguments: Arguments to pass to the prompt

        Returns:
            Prompt result
        """
        print(f"\n📝 Testing: Get Prompt '{name}' with {arguments or {}}")
        try:
            if not self.session:
                raise RuntimeError("Not connected to server")

            result = await self.session.get_prompt(name, arguments or {})
            print(f"✅ Prompt result: {len(result.messages)} messages")
            for i, msg in enumerate(result.messages):
                print(f"  Message {i+1}: {msg.content.text[:100]}...")
            return result

        except Exception as e:
            print(f"❌ Get prompt failed: {e}")
            return None

    async def run_comprehensive_test(self) -> dict[str, bool]:
        """
        Run comprehensive MCP protocol compliance tests.

        Returns:
            Dictionary of test results
        """
        print("🧪 Starting Comprehensive MCP Protocol Tests")
        print("=" * 50)

        results = {}

        # Test 1: Connection
        results["connection"] = await self.connect()
        if not results["connection"]:
            print("💥 Connection failed - stopping tests")
            return results

        # Test 2: List Tools
        tools = await self.test_list_tools()
        results["list_tools"] = len(tools) > 0

        # Test 3: Call Tools
        if tools:
            # Test say_hello tool
            hello_result = await self.test_call_tool(
                "say_hello", {"name": "MCP Test Client"}
            )
            results["call_tool_hello"] = hello_result is not None

            # Test echo tool
            echo_result = await self.test_call_tool(
                "echo", {"message": "Protocol compliance test"}
            )
            results["call_tool_echo"] = echo_result is not None

            # Test add tool (for simple_hello.py)
            math_result = await self.test_call_tool("add", {"a": 10, "b": 5})
            results["call_tool_math"] = math_result is not None

        # Test 4: List Resources
        resources = await self.test_list_resources()
        results["list_resources"] = len(resources) > 0

        # Test 5: Read Resources
        if resources:
            for resource in resources[:2]:  # Test first 2 resources
                resource_result = await self.test_read_resource(str(resource.uri))
                results[f"read_resource_{resource.uri}"] = resource_result is not None

        # Test 6: List Prompts
        prompts = await self.test_list_prompts()
        results["list_prompts"] = len(prompts) > 0

        # Test 7: Get Prompts
        if prompts:
            # Test greeting prompt (for simple_hello.py)
            greeting_result = await self.test_get_prompt(
                "greeting", {"name": "Test User"}
            )
            results["get_prompt_greeting"] = greeting_result is not None

        return results

    def print_test_summary(self, results: dict[str, bool]):
        """
        Print a summary of test results.

        Args:
            results: Dictionary of test results
        """
        print("\n" + "=" * 50)
        print("📊 MCP Protocol Compliance Test Summary")
        print("=" * 50)

        passed = sum(1 for result in results.values() if result)
        total = len(results)

        print(f"✅ Passed: {passed}/{total} tests ({passed/total*100:.1f}%)")
        print()

        for test_name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} - {test_name}")

        print("\n" + "=" * 50)
        if passed == total:
            print("🎉 ALL TESTS PASSED! MCP Protocol compliance verified.")
        else:
            print(f"⚠️ {total - passed} tests failed. Check server implementation.")


async def main():
    """Run the MCP client tests."""
    # Get the server script path - try simple_hello_server.py first
    server_script = Path(__file__).parent / "simple_hello_server.py"

    if not server_script.exists():
        print(f"❌ Server script not found: {server_script}")
        return

    # Create and run test client
    client = MCPTestClient(str(server_script))

    try:
        # Run comprehensive tests
        results = await client.run_comprehensive_test()

        # Print summary
        client.print_test_summary(results)

    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted by user")
    except Exception as e:
        print(f"❌ Test execution failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
