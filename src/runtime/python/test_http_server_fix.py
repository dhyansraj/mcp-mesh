#!/usr/bin/env python3

"""
Test HTTP server fix to verify curl works
"""

import mesh


@mesh.agent(name="curl-test", http_port=8123, auto_run=True)
class CurlTestAgent:
    pass


@mesh.tool(capability="curl_test")
def test_curl(message: str = "Hello") -> str:
    return f"Response: {message}"


print("🚀 Test agent started on http://127.0.0.1:8123")
print("📋 Test with: curl http://127.0.0.1:8123/health")
print(
    "📋 Test with: curl -X POST http://127.0.0.1:8123/mcp -H 'Content-Type: application/json' -d '{\"method\": \"tools/list\"}'"
)
print("🛑 Press Ctrl+C to stop")
