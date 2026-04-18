import json

import mesh
from _mcp_mesh.tracing.context import TraceContext
from fastmcp import FastMCP

app = FastMCP("Header Echo Agent")


@app.tool()
@mesh.tool(capability="echo_headers", description="Return propagated headers")
async def echo_headers() -> str:
    headers = TraceContext.get_propagated_headers()
    return json.dumps(headers)


@mesh.agent(
    name="header-echo",
    version="1.0.0",
    description="Echo agent for header propagation testing",
    http_port=0,
    enable_http=True,
    auto_run=True,
)
class HeaderEchoAgent:
    pass
