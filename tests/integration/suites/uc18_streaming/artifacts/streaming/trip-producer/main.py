#!/usr/bin/env python3
"""Minimal Python streaming producer for cross-runtime tests (issue #854).

Provides a deterministic ``mesh.Stream[str]`` capability so that
non-Python gateway tests (TS in tc04, Java in tc05) can verify they
forward chunks through to an SSE HTTP client without needing an LLM
provider or any external secrets.
"""

import asyncio

import mesh
from fastmcp import FastMCP

app = FastMCP("Trip Producer")


@app.tool()
@mesh.tool(
    capability="trip_planning",
    description="Stream tiny test plan",
    version="1.0.0",
    tags=["streaming"],
)
async def plan_trip(destination: str = "Tokyo") -> mesh.Stream[str]:
    """Yields 5 chunks deterministically — no LLM required."""
    chunks = [
        "Planning ",
        f"trip to {destination}",
        ".\nDay 1: Arrival.\n",
        "Day 2: Sightseeing.\n",
        "Day 3: Departure.",
    ]
    for chunk in chunks:
        await asyncio.sleep(0.05)  # short delay — keeps test fast
        yield chunk


@mesh.agent(
    name="trip-producer",
    version="1.0.0",
    description="Minimal stream producer for cross-runtime tests",
    http_port=9201,
    enable_http=True,
    auto_run=True,
)
class TripProducer:
    pass
