#!/usr/bin/env python3
"""
Downstream caller fixture for uc25 (issue #908) — a regular mesh
agent with three @mesh.tool functions all depending on the
current-date capability that the A2A consumer publishes:

  - get_formatted_date          : untagged dep (any consumer wins)
  - get_formatted_date_primary  : tag-pinned to date-consumer
  - get_formatted_date_alt      : tag-pinned to date-consumer-alt

The untagged variant exercises auto-rewire on consumer death
(tc03 failover); the tag-pinned variants prove the consumer-name
auto-tag substitution actually makes consumers distinguishable
for the resolver.
"""

import os

HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9203"))

import mesh
from fastmcp import FastMCP

app = FastMCP("Date Caller")


@app.tool()
@mesh.tool(
    capability="formatted-date",
    dependencies=[{"capability": "current-date"}],
)
async def get_formatted_date(current_date: mesh.McpMeshTool = None) -> dict:
    """Call any current-date provider — the resolver picks one of the
    healthy consumers. Returns the producer's date payload."""
    if current_date is None:
        return {"error": "current_date dependency not resolved"}
    return await current_date()


@app.tool()
@mesh.tool(
    capability="formatted-date-primary",
    dependencies=[
        {"capability": "current-date", "tags": ["date-consumer"]},
    ],
)
async def get_formatted_date_primary(
    current_date: mesh.McpMeshTool = None,
) -> dict:
    """Pinned to the primary consumer (auto-tag = agent name)."""
    if current_date is None:
        return {"error": "current_date (date-consumer) dependency not resolved"}
    return await current_date()


@app.tool()
@mesh.tool(
    capability="formatted-date-alt",
    dependencies=[
        {"capability": "current-date", "tags": ["date-consumer-alt"]},
    ],
)
async def get_formatted_date_alt(
    current_date: mesh.McpMeshTool = None,
) -> dict:
    """Pinned to the alt consumer (auto-tag = agent name)."""
    if current_date is None:
        return {"error": "current_date (date-consumer-alt) dependency not resolved"}
    return await current_date()


# @mesh.agent MUST be last.
@mesh.agent(name="date-caller", http_port=HTTP_PORT)
class DateCaller:
    """Downstream consumer that depends on the bridged current-date."""

    pass
