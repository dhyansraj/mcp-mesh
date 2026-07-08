#!/usr/bin/env python3
"""
caption-provider - MCP Mesh Agent

Publishes ONE slice of the shared ``media.*`` namespace. The tool declares its
dotted wire capability explicitly with ``@mesh.tool(capability="media.caption")``
— the capability is chosen deliberately, never derived from the Python method
name.

Cross-runtime note: the parameter names (``assetId``, ``text``) match the Java
and TypeScript providers exactly, so a gateway in ANY runtime can consume this
provider — the capability + wire schema are identical across runtimes.
"""

import os

import mesh
from fastmcp import FastMCP

# FastMCP server instance (hosts the agent's /mcp HTTP endpoint).
app = FastMCP("Caption Provider Service")


@app.tool()
@mesh.tool(capability="media.caption")
async def caption(assetId: str, text: str) -> dict:
    """Generate a deterministic caption for a media asset.

    Published under the dotted capability ``media.caption`` — one slice of the
    shared ``media.*`` namespace. The ``media`` segment carries no special
    meaning; it is simply the namespace this provider populates.
    """
    return {
        "assetId": assetId,
        "caption": f"A scene showing {text.strip().lower()}.",
        "provider": "caption-provider",
    }


@mesh.agent(
    name="caption-provider",
    version="1.0.0",
    description="Publishes media.caption into the shared media.* namespace",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8120")),
    enable_http=True,
    auto_run=True,
)
class CaptionProvider:
    """Agent bootstrap — the mesh processor discovers ``app`` and the
    ``@mesh.tool`` producer, then serves + registers ``media.caption``."""

    pass
