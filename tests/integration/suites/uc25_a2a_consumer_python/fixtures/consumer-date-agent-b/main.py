#!/usr/bin/env python3
"""
Second A2A consumer fixture for uc25 tc03 (issue #908) — registers
the SAME current-date capability with the SAME a2a-bridge tag, but
under a different agent name (date-consumer-alt). The auto-injected
consumer-name tag (date-consumer-alt) is what makes this consumer
distinguishable from date-consumer for capability+tag failover.

Bridges the same upstream date_a2a_agent get-date skill via
localhost:9090 (single-container test environment).
"""

import json
import os

HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9202"))

import mesh
from fastmcp import FastMCP

app = FastMCP("Date Consumer Bridge (alt)")


@app.tool()
@mesh.a2a_consumer(
    capability="current-date",
    a2a_url="http://localhost:9090/agents/date",
    a2a_skill_id="get-date",
    tags=["a2a-bridge"],
)
async def current_date(_a2a: mesh.A2AClient = None) -> dict:
    """Return today's date by calling the upstream A2A get-date skill."""
    response = await _a2a.send(
        message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
    )
    return json.loads(response.artifact_text)


# @mesh.agent MUST be last.
@mesh.agent(name="date-consumer-alt", http_port=HTTP_PORT)
class DateConsumerAlt:
    """Second mesh agent bridging the same get-date skill under a
    different consumer-name tag for failover/pinning tests."""

    pass
