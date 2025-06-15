#!/usr/bin/env python3
"""
Inspect the actual registration payload structure
"""

import asyncio
import json
import logging
import sys
from datetime import datetime

# Add source to path
sys.path.insert(0, "src/runtime/python/src")

logging.basicConfig(level=logging.INFO)


class PayloadInspectorRegistry:
    def __init__(self):
        self.logger = logging.getLogger("PayloadInspector")
        self.payloads = []

    async def register_multi_tool_agent(self, agent_id, metadata):
        """Capture and inspect the registration payload"""
        payload = {
            "agent_id": agent_id,
            "metadata": metadata,
            "timestamp": datetime.now().isoformat(),
        }

        self.payloads.append(payload)

        # Log detailed payload structure
        self.logger.info(f"🔍 FULL REGISTRATION PAYLOAD for {agent_id}:")
        self.logger.info(f"📊 Top-level keys: {list(metadata.keys())}")

        # Check agent-level endpoint info
        agent_endpoint_info = {
            "http_host": metadata.get("http_host"),
            "http_port": metadata.get("http_port"),
            "endpoint": metadata.get("endpoint"),
        }
        self.logger.info(f"🌐 Agent-level endpoint: {agent_endpoint_info}")

        # Check tools array structure
        tools = metadata.get("tools", [])
        self.logger.info(f"🔧 Tools array has {len(tools)} items")

        for i, tool in enumerate(tools):
            self.logger.info(f"📝 Tool {i+1}: {tool.get('function_name', 'unknown')}")
            tool_keys = list(tool.keys()) if isinstance(tool, dict) else "not_dict"
            self.logger.info(f"   Keys: {tool_keys}")

            # Check if tool has endpoint info
            if isinstance(tool, dict):
                tool_endpoint_info = {
                    k: v
                    for k, v in tool.items()
                    if "endpoint" in k.lower()
                    or "url" in k.lower()
                    or "http" in k.lower()
                }
                if tool_endpoint_info:
                    self.logger.info(f"   Endpoint info: {tool_endpoint_info}")
                else:
                    self.logger.info("   No endpoint info found in tool")

        # Save full payload to file
        payload_file = f"registration_payload_{agent_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        # Convert any non-serializable objects to strings
        def serialize_payload(obj):
            if hasattr(obj, "__dict__"):
                return {k: serialize_payload(v) for k, v in obj.__dict__.items()}
            elif isinstance(obj, list):
                return [serialize_payload(item) for item in obj]
            elif isinstance(obj, dict):
                return {k: serialize_payload(v) for k, v in obj.items()}
            else:
                try:
                    json.dumps(obj)
                    return obj
                except:
                    return str(obj)

        serializable_payload = serialize_payload(payload)

        with open(payload_file, "w") as f:
            json.dump(serializable_payload, f, indent=2)

        self.logger.info(f"💾 Full payload saved to: {payload_file}")

        return {"status": "success"}

    # Mock for generated client path
    async def post(self, url, **kwargs):
        data = kwargs.get("json") or kwargs.get("data")

        self.logger.info("🎯 GENERATED CLIENT REGISTRATION:")
        self.logger.info(f"   URL: {url}")

        if data:
            # Save generated client payload too
            payload_file = f"generated_client_payload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            def serialize_payload(obj):
                if hasattr(obj, "__dict__"):
                    return {k: serialize_payload(v) for k, v in obj.__dict__.items()}
                elif isinstance(obj, list):
                    return [serialize_payload(item) for item in obj]
                elif isinstance(obj, dict):
                    return {k: serialize_payload(v) for k, v in obj.items()}
                else:
                    try:
                        json.dumps(obj)
                        return obj
                    except:
                        return str(obj)

            serializable_data = serialize_payload(data)

            with open(payload_file, "w") as f:
                json.dump(serializable_data, f, indent=2)

            self.logger.info(f"💾 Generated client payload saved to: {payload_file}")

            # Also log key structure
            if hasattr(data, "__dict__"):
                self.logger.info(
                    f"📊 Generated payload attributes: {list(data.__dict__.keys())}"
                )

                # Check for endpoint info
                endpoint_attrs = [
                    k
                    for k in data.__dict__.keys()
                    if "endpoint" in k.lower()
                    or "http" in k.lower()
                    or "url" in k.lower()
                ]
                self.logger.info(f"🌐 Endpoint-related attributes: {endpoint_attrs}")

                # Check tools
                if hasattr(data, "tools"):
                    tools = data.tools
                    self.logger.info(f"🔧 Tools count: {len(tools) if tools else 0}")
                    if tools and len(tools) > 0:
                        first_tool = tools[0]
                        if hasattr(first_tool, "__dict__"):
                            self.logger.info(
                                f"📝 First tool attributes: {list(first_tool.__dict__.keys())}"
                            )

        # Mock response
        class MockResponse:
            def __init__(self):
                self.status_code = 200
                self.json_data = {"status": "success"}

            async def json(self):
                return self.json_data

            def is_success(self):
                return True

        return MockResponse()


async def test_payload_inspection():
    print("🔍 PAYLOAD INSPECTION TEST")
    print("=" * 50)

    from mcp_mesh.runtime.processor import MeshToolProcessor

    # Set up payload inspector
    inspector = PayloadInspectorRegistry()
    processor = MeshToolProcessor(inspector)

    # Mock tools and agent config
    class MockDecoratedFunction:
        def __init__(self, name, capability):
            def mock_func():
                return f"Response from {name}"

            mock_func.__name__ = name
            self.function = mock_func
            self.metadata = {
                "capability": capability,
                "description": f"Test {name}",
                "version": "1.0.0",
                "tags": ["test"],
                "dependencies": [],
            }

    tools = {
        "test_function": MockDecoratedFunction("test_function", "test_capability"),
        "another_function": MockDecoratedFunction(
            "another_function", "another_capability"
        ),
    }

    # Agent config with HTTP enabled
    agent_config = {
        "name": "payload-test",
        "http_host": "0.0.0.0",
        "http_port": 0,
        "enable_http": True,
        "version": "2.0.0",
        "namespace": "test",
    }

    processor._get_agent_configuration = lambda: agent_config

    # Mock HTTP wrapper to return fake endpoint
    async def mock_http_setup(agent_id, tools, agent_config):
        fake_endpoint = "http://127.0.0.1:9999"
        print(f"🚀 Mock HTTP wrapper returning: {fake_endpoint}")
        return fake_endpoint

    processor._setup_http_wrapper_for_tools = mock_http_setup

    print("🎯 Processing tools and capturing payload...")
    print("📁 Payload files will be saved to current directory")
    print("")

    await processor.process_tools(tools)

    print("\n✅ Payload inspection complete!")
    print("📄 Check the generated JSON files to see the full payload structure")


if __name__ == "__main__":
    asyncio.run(test_payload_inspection())
