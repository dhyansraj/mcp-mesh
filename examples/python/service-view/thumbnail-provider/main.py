#!/usr/bin/env python3
"""
thumbnail-provider - MCP Mesh Agent

Publishes ``media.thumbnail`` — a second slice of the shared ``media.*``
namespace, served by a DIFFERENT agent than caption/transcribe. The tool
declares its dotted wire capability explicitly with
``@mesh.tool(capability="media.thumbnail")``.

Cross-runtime note: parameter names (``assetId``, ``width``) match the Java and
TypeScript providers, so any-runtime gateways are interchangeable.
"""

import os

import mesh
from fastmcp import FastMCP

app = FastMCP("Thumbnail Provider Service")


@app.tool()
@mesh.tool(capability="media.thumbnail")
async def thumbnail(assetId: str, width: int) -> dict:
    """Generate a deterministic thumbnail descriptor for a media asset.

    Published under the dotted capability ``media.thumbnail``.
    """
    w = width if width and width > 0 else 128
    h = max(1, w * 9 // 16)
    return {
        "assetId": assetId,
        "uri": f"thumb://{assetId}?w={w}&h={h}",
        "size": f"{w}x{h}",
        "provider": "thumbnail-provider",
    }


@mesh.agent(
    name="thumbnail-provider",
    version="1.0.0",
    description="Publishes media.thumbnail into the shared media.* namespace",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8121")),
    enable_http=True,
    auto_run=True,
)
class ThumbnailProvider:
    pass
