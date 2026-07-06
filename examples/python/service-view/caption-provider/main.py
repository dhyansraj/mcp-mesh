#!/usr/bin/env python3
"""
caption-provider - MCP Mesh Agent

Publishes ONE slice of the shared ``media.*`` namespace via producer sugar
(RFC #1280). A class decorated ``@mesh.service("media")`` publishes each public
async method as a mesh tool under the capability ``media.<method>`` — so the
``caption`` method below becomes the dotted capability ``media.caption``.

Cross-runtime note: the parameter names (``assetId``, ``text``) match the Java
and TypeScript providers exactly, so a gateway in ANY runtime can consume this
provider — the capability + wire schema are identical across runtimes.
"""

import os

import mesh
from fastmcp import FastMCP

# FastMCP server instance (hosts the agent's /mcp HTTP endpoint).
app = FastMCP("Caption Provider Service")


@mesh.service("media")
class MediaCaptionService:
    """Producer sugar: publishes ``media.caption`` (prefix + method name).

    The ``"media"`` prefix is entirely user-chosen — nothing about it is
    hard-coded in the mesh.
    """

    async def caption(self, assetId: str, text: str) -> dict:
        """Generate a deterministic caption for a media asset."""
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
    ``@mesh.service`` producer, then serves + registers ``media.caption``."""

    pass
