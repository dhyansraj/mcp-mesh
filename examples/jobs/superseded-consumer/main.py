#!/usr/bin/env python3
"""
Typed supersession signal (issue #1278) — Consumer: a job executor whose
mutating writes unwind with ONE ``except mesh.SupersededError``.

This is the consumer half of the fencing pattern. ``run_writer`` is a
``task=True`` handler — it executes AS a job, so it runs under a
``claim_epoch``. Every outbound mesh call it makes (here to the provider's
``apply_write``) automatically carries this job's identity on the propagated
headers, so the provider can fence it via ``mesh.calling_job()`` without the
executor threading ``job_id`` / ``claim_epoch`` through each payload.

The point of #1278 is the UNWIND. A job executor makes many mutating downstream
calls; if this executor has been superseded (a newer claim of the same job is
now authoritative) it must stop and bail — cleanly, from wherever it is in the
batch. Because a superseded write re-raises the TYPED ``mesh.SupersededError``,
the whole batch is wrapped in ONE ``except``:

    try:
        for entry in entries:
            await apply_write(entry=entry)   # any of these may be fenced
    except mesh.SupersededError as e:
        return {"status": "superseded", "detail": e.detail}   # one unwind

Contrast the OLD pattern this REPLACES — inspecting every call's result and
string-matching the marker after each one::

    for entry in entries:
        result = await apply_write(entry=entry)
        # brittle: re-check the shape/marker on EVERY call site
        if isinstance(result, dict) and result.get("error") == "claim_superseded":
            return {"status": "superseded"}   # repeated at every call site

Note this is DISTINCT from ``dependency_unavailable`` (issue #1273): that says
"the capability isn't reachable"; supersession says "you personally are stale,
a newer you is authoritative". Both are typed so the CONTRACT (the reserved
envelope), not the error string, drives classification.

Run after the provider is up:
    MCP_MESH_REGISTRY_URL=http://localhost:8000 python3 main.py
"""

import logging

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

log = logging.getLogger("superseded-consumer")
app = FastMCP("Superseded Writer Job")


@app.tool()
@mesh.tool(
    capability="run_writer",
    # task=True: this handler is dispatched AS a job (claimed from the
    # registry), so it runs under a claim_epoch that the mesh stamps onto the
    # calling-job headers of the apply_write call below.
    task=True,
    # Regular McpMeshTool dependency on the provider's mutating capability.
    # (A dependency, NOT a MeshJob submitter — apply_write is a plain tool.)
    dependencies=["apply_write"],
    description=(
        "Run a batch of ledger writes as a job. If this executor is "
        "superseded mid-batch, unwind cleanly with one except SupersededError."
    ),
)
async def run_writer(
    count: int = 3,
    # Injected by name-match: the apply_write McpMeshTool proxy.
    apply_write: mesh.McpMeshTool = None,
    # Injected by type: the controller for THIS job (its own identity /
    # claim_epoch live here; the provider sees it via calling_job()).
    job: MeshJob = None,
) -> dict:
    """Write ``count`` ledger entries, bailing cleanly if superseded."""
    if apply_write is None:
        return {
            "error": "apply_write not injected — check that the "
            "superseded-provider is registered"
        }

    written: list[str] = []
    try:
        for i in range(count):
            entry = f"line-{i}"
            # Any of these calls may be fenced by the provider. If this
            # executor has been superseded, the provider raises
            # SupersededError; the injected proxy recognizes the reserved
            # envelope and re-raises mesh.SupersededError here — so we do NOT
            # inspect each result for a marker.
            await apply_write(entry=entry)
            written.append(entry)
            if job is not None:
                await job.update_progress(
                    (i + 1) / max(count, 1), f"wrote {i + 1}/{count}"
                )
    except mesh.SupersededError as e:
        # ONE unwind for the whole batch. A newer claim of this job is
        # authoritative — stop writing and hand back what we managed before
        # being fenced. No rollback needed: the provider already rejected the
        # stale write, so the ledger reflects only the authoritative executor.
        log.warning("superseded mid-batch after %d writes: %s", len(written), e.detail)
        return {
            "status": "superseded",
            "written_before_fence": written,
            "detail": e.detail,
        }

    return {"status": "completed", "written": written}


@mesh.agent(
    name="superseded-consumer",
    version="1.0.0",
    description=(
        "Issue #1278 consumer — a task=True writer job that unwinds mutating "
        "writes with one except mesh.SupersededError"
    ),
    http_port=9105,
    enable_http=True,
    auto_run=True,
)
class SupersededConsumer:
    """Hosts the ``run_writer`` capability."""

    pass
