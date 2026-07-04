#!/usr/bin/env python3
"""uc35 flap-worker — task=True consumer with a REQUIRED dep (issue #1268).

``checked_task`` is the capability under test: ``task=True`` (claimed from the
shared job queue) with a ``required=True`` dependency on flap-provider's
``flap_data``. Two claim-path guarantees from #1268 land here:

1. Pre-claim local skip (primary): while the ``flap_data`` proxy slot is
   locally unresolved, this agent's claim worker never POSTs /jobs/claim —
   the job stays queued with no owner and NO attempt increment.
2. Pre-invoke guard (safety net): a claim that slips through the race window
   (registry gate open, local slot still null) releases its lease instead of
   invoking the handler with a null proxy.

The handler calls the required dep DELIBERATELY UNGUARDED: if either guard
regressed and the handler ran with a null injection, ``await flap_data()``
raises ``TypeError: 'NoneType' object is not callable`` — the pre-fix
symptom — which the dispatcher's exception path posts as a terminal fail().
The test asserts both the absence of that log signature and the row-level
observables (attempt_count == 1, exactly one stamped execution).
"""

import os
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Flap Worker (uc35)")


@app.tool()
@mesh.tool(
    capability="checked_task",
    task=True,
    dependencies=[{"capability": "flap_data", "required": True}],
    description="Job handler that calls its required flap_data dep unguarded.",
)
async def checked_task(
    label: str = "unlabeled",
    flap_data: mesh.McpMeshTool = None,
    job: MeshJob = None,
) -> dict[str, Any]:
    # UNGUARDED on purpose (see module docstring): a null required proxy here
    # must be impossible — the claim gate/pre-invoke guard keep the job queued
    # instead. Guarding would silently mask the regression under test.
    dep_result = await flap_data()

    if job is not None:
        # Stamp every actual execution so the test can assert EXACTLY-ONCE
        # from the event log (uc33 pattern), attributed to a claim epoch.
        await mesh.jobs.post_event(
            job_id=job.job_id,
            event_type="transition",
            payload={"marker": "executed", "label": label, "epoch": job.claim_epoch},
        )

    payload = {
        "status": "done",
        "label": label,
        "dep_marker": str(dep_result),
    }
    if job is not None:
        await job.complete(payload)
    return payload


@mesh.agent(
    name="flap-worker",
    version="1.0.0",
    description="uc35 task=true consumer with required dep on flap_data (issue #1268)",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9102")),
    enable_http=True,
    auto_run=True,
)
class FlapWorker:
    pass
