#!/usr/bin/env python3
"""
MeshJob Phase 1 — Producer Example: long-running report generator.

Demonstrates the producer-side dispatch surface:

    @mesh.tool(capability="generate_report", task=True)
    async def generate_report(..., job: MeshJob = None):
        await job.update_progress(...)
        await job.complete({...})

When invoked via the consumer's `MeshJobSubmitter.submit(...)` (see
``../long-task-consumer/main.py``), the inbound tool wrapper sees the
`X-Mesh-Job-Id` header attached by the registry's claim flow, builds a
:class:`mcp_mesh_core.JobController` bound to that job id, and injects
it into the ``job`` parameter. Progress updates and the terminal
``complete()`` flush directly to the registry — the consumer's
``await proxy.wait(...)`` polls the registry until terminal.

If you call ``generate_report`` synchronously (regular ``tools/call``,
no ``X-Mesh-Job-Id`` header), the runtime passes ``None`` for ``job``
per ``MESHJOB_DDDI_CONTRACT.md`` — the function then runs the fast
path and just returns its result.

Run:
    MCP_MESH_REGISTRY_URL=http://localhost:8000 python3 main.py
"""

import asyncio
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

# Single FastMCP server instance — discovered automatically by the mesh
# startup pipeline and mounted under the agent's HTTP transport.
app = FastMCP("Long Task Provider")


@app.tool()
@mesh.tool(
    capability="generate_report",
    task=True,
    description=(
        "Long-running report generator. Demonstrates progress updates "
        "and structured terminal results."
    ),
)
async def generate_report(
    user_id: str,
    sections: list[str],
    job: MeshJob = None,
) -> dict[str, Any]:
    """Generate a multi-section report.

    Each section takes ~2 seconds to "compute" (sleep). Progress updates
    fire after each section so a consumer polling status sees the report
    advance through ``working → completed`` smoothly.

    The function returns the same dict it passes to ``job.complete()``
    so a regular synchronous ``tools/call`` (where ``job is None``) still
    yields a useful result.
    """
    if job is not None:
        await job.update_progress(0.0, "starting")

    results = []
    total = max(len(sections), 1)
    for i, section in enumerate(sections):
        # Simulate substantive work. In a real producer this might be
        # an LLM call, a long DB query, or video transcoding.
        await asyncio.sleep(2)
        results.append({"section": section, "content": f"Generated content for {section}"})
        if job is not None:
            await job.update_progress(
                (i + 1) / total, f"finished section {i + 1}/{total}"
            )

    payload = {"user_id": user_id, "report": results}

    if job is not None:
        # Explicit terminal call — flushes immediately past the
        # batching tick so the consumer sees ``status=completed``
        # without waiting on the next batch interval.
        await job.complete(payload)

    return payload


@mesh.agent(
    name="long-task-provider",
    version="1.0.0",
    description="MeshJob Phase 1 producer — generates reports as long-running jobs",
    http_port=9100,
    enable_http=True,
    auto_run=True,
)
class LongTaskProvider:
    """Hosts the ``generate_report`` capability as a task=True tool."""

    pass
