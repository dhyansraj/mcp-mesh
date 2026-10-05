"""Provider whose tools return the empty/null boundary values from issue #1250.

Contract under test: a tool handler's return value must round-trip through
the injected mesh proxy unchanged - [] -> [], {} -> {}, "" -> "",
None -> null. Emptiness and absence are different values.

get_value deliberately has NO return type annotation: the untyped return
path is where FastMCP collapsed [] into an empty content array, making it
indistinguishable from None on the wire.

get_text_blocks (issue #1630) returns several explicit MCP text content
blocks; consumers must receive every block, in order, not just the first.
"""

import mesh
from fastmcp import FastMCP
from mcp.types import TextContent

app = FastMCP("py-empty-provider")

VALUES = {
    "empty_list": [],
    "empty_dict": {},
    "empty_string": "",
    "null_value": None,
    "nonempty_list": [1, 2, 3],
}


@app.tool()
@mesh.tool(
    capability="empty_value_source",
    description="Return the boundary value for the given kind (untyped return)",
    tags=["empty", "roundtrip"],
)
def get_value(kind: str):
    """Return [], {}, '', None or [1, 2, 3] depending on kind."""
    if kind not in VALUES:
        raise ValueError(f"unknown kind: {kind}")
    return VALUES[kind]


@app.tool()
@mesh.tool(
    capability="empty_list_typed",
    description="Return an empty list through a typed (list[int]) return",
    tags=["empty", "roundtrip", "typed"],
)
def get_empty_list() -> list[int]:
    """Typed empty-list return - exercises the structuredContent seam."""
    return []


@app.tool()
@mesh.tool(
    capability="multi_text_source",
    description="Return three explicit MCP text content blocks (issue #1630)",
    tags=["multi-text", "roundtrip"],
)
def get_text_blocks():
    """Return alpha, beta, gamma as three separate text content blocks.

    Deliberately unannotated: FastMCP passes MCP content blocks through
    verbatim and emits NO structuredContent, so the wire result is
    content=[{text: alpha}, {text: beta}, {text: gamma}]. (A list[str]
    return would instead serialize to ONE JSON text block.)
    """
    return [
        TextContent(type="text", text="alpha"),
        TextContent(type="text", text="beta"),
        TextContent(type="text", text="gamma"),
    ]


@mesh.agent(
    name="py-empty-provider",
    version="1.0.0",
    description="Provider of empty/null boundary return values (issue #1250)",
    http_port=9040,
    auto_run=True,
)
class PyEmptyProvider:
    pass
