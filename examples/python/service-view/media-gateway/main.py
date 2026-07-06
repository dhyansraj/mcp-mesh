#!/usr/bin/env python3
"""
media-gateway - MCP Mesh Agent

Aggregates three independent capabilities behind ONE typed service view
(RFC #1280) and fans a single request out across them. Because each view method
binds its own capability, the ``servedBy`` fields in the result name THREE
different provider agents answering through one interface.

Consumption style: the view is injected as a ``@mesh.tool`` PARAMETER (the
Python form of RFC #1280). Each view method becomes a dependency edge on the
``process_media`` tool. The ``caption`` method is ``required=True``, so the mesh
runtime returns the structured ``dependency_unavailable`` refusal BEFORE the
handler runs whenever caption has no provider; the optional ``thumbnail`` /
``transcribe`` methods raise ``ToolError`` when unresolved, which the handler
catches for graceful degradation.

Cross-runtime: the ``media.*`` capabilities are identical across the Java,
Python, and TypeScript examples, so this gateway can consume the providers from
ANY runtime (e.g. a Python gateway over the Java providers) and vice versa.
"""

import json
import os

import mesh
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

app = FastMCP("Media Gateway Service")


def _is_dependency_unavailable(err: ToolError) -> bool:
    """True only for the structured ``dependency_unavailable`` refusal.

    An unresolved OPTIONAL view edge raises ``ToolError`` whose message is the
    JSON ``{"error": "dependency_unavailable", "capability": "..."}``. Inspect
    the payload so we degrade ONLY on that shape — any other ToolError (a real
    provider bug, a bad request) must propagate rather than be masked as
    "provider offline".
    """
    try:
        payload = json.loads(str(err))
    except (ValueError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("error") == "dependency_unavailable"


@mesh.service
class MediaService:
    """Consumer service view: three capabilities behind one typed interface.

    Each method is a selector stub (its body never runs); the framework injects
    a facade whose methods delegate to each capability's own resolved proxy.
    """

    @mesh.selector("media.caption", required=True)
    async def caption(self, args: dict) -> dict: ...

    @mesh.selector("media.thumbnail")
    async def thumbnail(self, args: dict) -> dict: ...

    @mesh.selector("media.transcribe")
    async def transcribe(self, args: dict) -> dict: ...


def _entry(value: str, served_by: str) -> dict:
    """One combined-result entry: the value plus the provider agent that served it."""
    return {"value": value, "servedBy": served_by}


async def _combine(media: MediaService, asset_id: str, text: str) -> dict:
    """Run one asset through all three view methods and combine the results."""
    result: dict = {"assetId": asset_id}

    # REQUIRED edge — a missing provider is refused before this handler runs.
    caption = await media.caption({"assetId": asset_id, "text": text})
    result["caption"] = _entry(caption["caption"], caption["provider"])

    # OPTIONAL edge — degrade gracefully ONLY on dependency_unavailable.
    try:
        thumb = await media.thumbnail({"assetId": asset_id, "width": 320})
        result["thumbnail"] = _entry(f"{thumb['uri']} ({thumb['size']})", thumb["provider"])
    except ToolError as e:
        if not _is_dependency_unavailable(e):
            raise
        result["thumbnail"] = _entry("(no thumbnail — provider offline)", "unavailable")

    # OPTIONAL edge — degrade gracefully ONLY on dependency_unavailable.
    try:
        tx = await media.transcribe({"assetId": asset_id, "text": text})
        result["transcript"] = _entry(
            f"{tx['transcript']} [{tx['wordCount']} words]", tx["provider"]
        )
    except ToolError as e:
        if not _is_dependency_unavailable(e):
            raise
        result["transcript"] = _entry("(no transcript — provider offline)", "unavailable")

    return result


@app.tool()
@mesh.tool(
    capability="process_media",
    description="Runs an asset through caption, thumbnail and transcribe via one service view",
    tags=["media", "gateway"],
)
async def process_media(assetId: str, text: str, media: MediaService = None) -> dict:
    """Fan one media asset across the three view methods and combine results.

    ``media`` is the injected service-view facade (hidden from the MCP input
    schema); ``assetId`` and ``text`` are the tool's real inputs.
    """
    return await _combine(media, assetId, text)


@mesh.agent(
    name="media-gateway",
    version="1.0.0",
    description="Aggregates three media capabilities behind one typed service view",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "8123")),
    enable_http=True,
    auto_run=True,
)
class MediaGateway:
    pass
