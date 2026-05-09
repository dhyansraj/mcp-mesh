#!/usr/bin/env python3
"""
MeshJob Phase 1 — Consumer Example: commission a remote long-running job.

Demonstrates the consumer-side dispatch surface:

    @mesh.tool(capability="commission_report", dependencies=["generate_report"])
    async def commission_report(..., generate_report: MeshJob = None):
        proxy = await generate_report.submit(...)
        return await proxy.wait(timeout_secs=60)

The DI layer sees the ``MeshJob``-typed parameter whose name matches
the declared dependency capability and injects a
:class:`_mcp_mesh.engine.mesh_job_submitter.MeshJobSubmitter` for that
capability. ``submit(...)`` posts to ``/jobs`` and returns a
:class:`mcp_mesh_core.JobProxy` bound to the new job id; ``wait(...)``
polls the registry's ``GET /jobs/{id}`` until the status is terminal.

Run after the provider is up:
    MCP_MESH_REGISTRY_URL=http://localhost:8000 python3 main.py
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Long Task Consumer")


@app.tool()
@mesh.tool(
    capability="commission_report",
    # The dependency name MUST match the MeshJob param name below so
    # the runtime can wire a MeshJobSubmitter into the slot. (Same
    # name-matching convention used for McpMeshTool dependencies.)
    dependencies=["generate_report"],
    description=(
        "Commission a report from the long-task provider and await its "
        "result. Demonstrates the submit-and-wait pattern."
    ),
)
async def commission_report(
    user_id: str,
    sections: list[str],
    # MeshJob-typed param: at runtime the framework injects a
    # MeshJobSubmitter bound to the ``generate_report`` capability.
    # The annotation is what makes the slot a job submitter (vs a
    # regular McpMeshTool proxy).
    generate_report: MeshJob = None,
) -> dict:
    """Submit a report job and wait up to 60 seconds for it to finish."""
    if generate_report is None:
        # Defensive: in unit tests or if injection fails, fall back so
        # callers see a clear error message rather than ``NoneType has
        # no attribute 'submit'``.
        return {
            "error": "generate_report submitter not injected — check that "
            "the long-task-provider is registered with task=True"
        }

    # ``submit`` posts to /jobs and returns a JobProxy bound to the new
    # job id. ``max_duration`` is the per-attempt soft timeout the
    # provider runtime enforces (and the registry's deadline-exceeded
    # cron sweeps if the producer crashes).
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=60,
    )

    # Poll the registry until terminal. Returns the producer's
    # ``complete()`` payload on success; raises on failure / cancel
    # / timeout.
    return await proxy.wait(timeout_secs=60)


@mesh.agent(
    name="long-task-consumer",
    version="1.0.0",
    description="MeshJob Phase 1 consumer — commissions and awaits remote reports",
    http_port=9101,
    enable_http=True,
    auto_run=True,
)
class LongTaskConsumer:
    """Hosts the ``commission_report`` capability."""

    pass
