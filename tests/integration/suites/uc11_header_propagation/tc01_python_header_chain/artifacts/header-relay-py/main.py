import mesh
from fastmcp import FastMCP
from mesh.types import McpMeshTool

app = FastMCP("Header Relay Agent")


@app.tool()
@mesh.tool(
    capability="relay_headers",
    description="Call echo_headers and return result",
    dependencies=["echo_headers"],
)
async def relay_headers(echo_svc: McpMeshTool = None) -> str:
    if echo_svc is None:
        return '{"error": "echo_headers dependency not available"}'
    # If x-audit-id not already propagated, inject it via per-call headers
    from _mcp_mesh.tracing.context import TraceContext

    propagated = TraceContext.get_propagated_headers()
    if "x-audit-id" not in propagated:
        result = await echo_svc(headers={"x-audit-id": "injected-by-relay-py"})
    else:
        result = await echo_svc()
    return str(result)


@mesh.agent(
    name="header-relay",
    version="1.0.0",
    description="Relay agent for header propagation testing",
    http_port=0,
    enable_http=True,
    auto_run=True,
)
class HeaderRelayAgent:
    pass
