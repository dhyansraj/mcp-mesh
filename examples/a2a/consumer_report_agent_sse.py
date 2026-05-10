#!/usr/bin/env python3
"""
A2A consumer example for LONG-RUNNING tasks via SSE (issue #910 / Phase 3).

Same end-to-end behaviour as ``consumer_report_agent.py`` but uses the
A2A ``tasks/sendSubscribe`` SSE stream instead of poll-based
``tasks/send`` + ``tasks/get``. Validates the ``A2AStream`` async
iterator + ``A2AStream.bridge(mesh_job)`` helper end-to-end.

Differences from ``consumer_report_agent.py``
=============================================

- Uses ``_a2a.subscribe(...)`` which opens an SSE connection.
- ``stream.bridge(job)`` mirrors each parsed ``A2AEvent`` (status +
  artifact) into the mesh ``MeshJob`` and returns the final artifact
  value when the stream's terminal frame arrives.
- Cancel propagation is one-way per A2A v1.0: closing the SSE
  connection does NOT POST ``tasks/cancel`` upstream — disconnect is
  a transient signal and the producer keeps running unless explicitly
  canceled. A mesh-side cancel during ``stream.bridge`` re-raises as
  ``A2AJobCanceled`` so the wrapper records the canceled outcome.

Same stacking + decorator-order constraints as the polling variant —
``@mesh.a2a_consumer(..., task=True)`` forwards ``task=True`` to the
inner ``@mesh.tool``, and ``@mesh.agent`` MUST be last.

Prereqs (in four terminals)
===========================

  # 1) Registry
  meshctl start registry

  # 2) Long-running provider — exposes generate_report (task=True)
  python examples/jobs/long-task-provider/main.py

  # 3) A2A surface — re-publishes generate_report via A2A v1.0
  #    (must support tasks/sendSubscribe — report_a2a_agent does)
  python examples/a2a/report_a2a_agent.py

  # 4) This consumer — bridges the SSE stream into the mesh as a
  #    long-running ``report-sse`` capability
  python examples/a2a/consumer_report_agent_sse.py
"""

import json
import os

HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9212"))

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Report Consumer Bridge (SSE)")


@app.tool()
@mesh.a2a_consumer(
    capability="report_sse",
    a2a_url="http://localhost:9091/agents/report",
    a2a_skill_id="generate-report",
    tags=["a2a-bridge", "sse"],
    task=True,
)
async def report_sse(
    user_id: str,
    sections: list[str],
    _a2a: mesh.A2AClient = None,
    job: MeshJob = None,
) -> dict:
    """Bridge generate-report via SSE: open the subscribe stream, mirror
    each event into the mesh JobController, return the final artifact
    when the terminal frame arrives.
    """
    stream = await _a2a.subscribe(
        message={
            "role": "user",
            "parts": [
                {
                    "type": "text",
                    "text": json.dumps({"user_id": user_id, "sections": sections}),
                }
            ],
        }
    )
    return await stream.bridge(job)


# @mesh.agent MUST be last.
@mesh.agent(name="report-consumer-sse", http_port=HTTP_PORT)
class ReportConsumerSSE:
    """Mesh agent that bridges generate-report via the A2A SSE stream."""

    pass
