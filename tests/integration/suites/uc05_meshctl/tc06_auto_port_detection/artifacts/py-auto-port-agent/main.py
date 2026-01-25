"""
Python agent with auto-port assignment (http_port=0).
Used to test that auto-assigned port is correctly reported to registry.
Related Issue: https://github.com/dhyansraj/mcp-mesh/issues/457
"""

from datetime import datetime

import mesh
from fastmcp import FastMCP

app = FastMCP("py-auto-port-agent")


@app.tool()
@mesh.tool(
    capability="echo",
    description="Echo back the input",
    tags=["echo", "test", "python"],
)
def echo(message: str = "test") -> str:
    """Echo back the message."""
    return f"Echo: {message} at {datetime.now().isoformat()}"


@mesh.agent(
    name="py-auto-port-agent",
    version="1.0.0",
    description="Agent with auto-port assignment for testing",
    http_port=9000,  # Default port - will be overridden by MCP_MESH_HTTP_PORT=0
    enable_http=True,  # Enable HTTP mode
    auto_run=True,
)
class PyAutoPortAgent:
    pass
