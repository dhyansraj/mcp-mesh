"""Fixture for tc12 — verifies orchestrator rejects mixed @mesh.tool + @mesh.a2a.

The mcp-mesh startup orchestrator's debounce coordinator collects all
decorators registered during import-time, then chooses a single
pipeline (mcp / route / a2a) to run. If decorators from MORE THAN ONE
family register in the same process the orchestrator MUST raise
RuntimeError("Mixed mode not supported: ...") rather than silently
running one and ignoring the rest.

This fixture intentionally combines:
  - a FastMCP @app.tool() + @mesh.tool (mcp family)
  - a mesh.a2a.mount(...) (a2a family)

so that startup_orchestrator._determine_pipeline_type() returns
"mixed" and the orchestrator raises.

The fixture's __main__ block calls uvicorn.run(...) but the orchestrator
fires its mixed-mode check on the debounce timer (~1s after the last
decorator runs at import) BEFORE uvicorn ever serves a request — so
the script exits with the RuntimeError traceback well within tc12's
8-second timeout cap. The test captures stdout+stderr and asserts the
rejection message is present.
"""

import os

# Set MCP_MESH_HTTP_PORT BEFORE importing mesh — same pattern as the
# other A2A fixtures. Port 9095 avoids collision with the rest of the
# suite's port plan (9090/9091/9100/9102).
os.environ.setdefault("MCP_MESH_HTTP_PORT", "9095")

import mesh
from fastapi import FastAPI
from fastmcp import FastMCP
from mesh.types import McpMeshTool

# ---- mcp-tool family decorator -------------------------------------------
# @app.tool() + @mesh.tool puts a decorator into the "mcp" family in
# DecoratorRegistry — sufficient to flip _determine_pipeline_type()
# into "mixed" once the a2a.mount() below also registers.
app_mcp = FastMCP("Mixed Mode Test")


@app_mcp.tool()
@mesh.tool(capability="hello", description="says hi")
async def hello() -> str:
    return "hi"


# ---- a2a-surface family decorator ----------------------------------------
# Same process: registering an a2a.mount(...) at import-time forces the
# orchestrator into "mixed" mode and triggers the RuntimeError.
app = FastAPI(title="Mixed Mode A2A")


@mesh.a2a.mount(
    app,
    path="/agents/mixed",
    dependencies=["hello"],
    description="should never be reachable",
)
async def mixed_a2a(payload: dict, hello: McpMeshTool = None):
    return {"says": await hello()}


if __name__ == "__main__":
    # uvicorn.run never actually serves: the orchestrator's debounce
    # timer (~1s) raises RuntimeError before this becomes reachable.
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9095, log_level="info")
