#!/usr/bin/env python3
"""
Test direct registry call with the real payload
"""

import asyncio
import json
import logging

import aiohttp

logging.basicConfig(level=logging.INFO)


async def test_registry_call():
    print("🚀 Testing Direct Registry Call")
    print("=" * 50)

    # The exact payload from our test
    payload = {
        "agent_id": "payload-test-c393a698",
        "agent_type": "mcp_agent",
        "name": "payload-test-c393a698",
        "version": "2.0.0",
        "http_host": "127.0.0.1",
        "http_port": 9999,
        "timestamp": "2025-06-16T05:12:52.519952Z",
        "namespace": "test",
        "tools": [
            {
                "function_name": "test_function",
                "capability": "test_capability",
                "version": "1.0.0",
                "tags": ["test"],
                "dependencies": [],
                "description": "Test test_function",
            },
            {
                "function_name": "another_function",
                "capability": "another_capability",
                "version": "1.0.0",
                "tags": ["test"],
                "dependencies": [],
                "description": "Test another_function",
            },
        ],
    }

    registry_url = "http://localhost:8000"
    endpoint = f"{registry_url}/agents/register"

    print(f"📡 Calling: {endpoint}")
    print("📦 Payload:")
    print(json.dumps(payload, indent=2))
    print("")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload) as response:
                print(f"✅ Response Status: {response.status}")
                print(f"📄 Response Headers: {dict(response.headers)}")

                # Get response data
                if response.status in [200, 201]:
                    response_data = await response.json()
                    print("🎯 Response Body:")
                    print(json.dumps(response_data, indent=2))

                    # Save successful response
                    response_file = f"registry_response_{response.status}_{response_data.get('agent_id', 'unknown')}.json"
                    with open(response_file, "w") as f:
                        json.dump(
                            {
                                "status_code": response.status,
                                "headers": dict(response.headers),
                                "body": response_data,
                                "request_payload": payload,
                            },
                            f,
                            indent=2,
                        )
                    print(f"💾 Response saved to: {response_file}")

                else:
                    response_text = await response.text()
                    print("❌ Error Response:")
                    print(response_text)

                    # Save error response too
                    error_file = f"registry_error_{response.status}.json"
                    with open(error_file, "w") as f:
                        json.dump(
                            {
                                "status_code": response.status,
                                "headers": dict(response.headers),
                                "body": response_text,
                                "request_payload": payload,
                            },
                            f,
                            indent=2,
                        )
                    print(f"💾 Error response saved to: {error_file}")

    except aiohttp.ClientConnectorError as e:
        print(f"❌ Connection Error: {e}")
        print("💡 Make sure the Go registry is running on port 8000")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_registry_call())
