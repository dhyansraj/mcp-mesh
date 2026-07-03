"""Consumer that probes empty/null round-trips through injected proxies (issue #1250).

Each probe calls its injected dependency and reports EXACTLY what arrived:
- is_none: whether the value is None
- value_type: the Python type name of the value
- value_json: compact JSON of the value ("[]", "{}", "\"\"", "null", "[1,2,3]")

The test asserts on value_json/is_none so [] collapsing to None (or "" or
an envelope leak) is surfaced, never accommodated.
"""

import json

import mesh
from fastmcp import FastMCP

app = FastMCP("py-empty-consumer")


def _report(kind: str, value) -> dict:
    return {
        "kind": kind,
        "is_none": value is None,
        "value_type": type(value).__name__,
        "value_json": json.dumps(value, separators=(",", ":"), sort_keys=True),
    }


@app.tool()
@mesh.tool(
    capability="empty_probe",
    description="Call empty_value_source(kind) and report exactly what came back",
    tags=["empty", "roundtrip"],
    dependencies=["empty_value_source"],
)
async def probe_roundtrip(kind: str, source: mesh.McpMeshTool = None) -> dict:
    """Round-trip the boundary value for `kind` through the injected proxy."""
    if source is None:
        return {"kind": kind, "error": "dependency empty_value_source not injected"}
    value = await source(kind=kind)
    return _report(kind, value)


@app.tool()
@mesh.tool(
    capability="empty_probe_typed",
    description="Call the typed empty-list capability and report exactly what came back",
    tags=["empty", "roundtrip", "typed"],
    dependencies=["empty_list_typed"],
)
async def probe_typed_empty_list(source: mesh.McpMeshTool = None) -> dict:
    """Round-trip a typed (list[int]) empty-list return through the proxy."""
    if source is None:
        return {
            "kind": "typed_empty_list",
            "error": "dependency empty_list_typed not injected",
        }
    value = await source()
    return _report("typed_empty_list", value)


@mesh.agent(
    name="py-empty-consumer",
    version="1.0.0",
    description="Probes empty/null round-trips via injected dependencies (issue #1250)",
    http_port=9050,
    auto_run=True,
)
class PyEmptyConsumer:
    pass
