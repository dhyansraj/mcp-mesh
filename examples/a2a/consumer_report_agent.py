#!/usr/bin/env python3
"""
A2A consumer example for LONG-RUNNING tasks (issue #910 / Phase 3).

Bridges the existing ``report_a2a_agent.py`` ``generate-report`` skill
into the mesh as a regular ``report`` capability that downstream
callers consume via the standard MeshJob interface (``await
proxy.wait()``, ``await proxy.cancel()``, etc.) — they have no idea
the actual work is happening on an external A2A backend.

Architecture (Option 2 — bridge inside a task=True @mesh.tool)
==============================================================

The consumer is a regular ``task=True`` @mesh.tool whose body submits
to A2A non-blocking via ``_a2a.submit(...)``, then mirrors A2A
polling state into the framework-injected ``MeshJob`` (JobController)
via ``a2a_job.bridge(job)``. ``a2a_job.bridge`` returns the final
artifact value; the mesh ``task=True`` wrapper takes that return and
calls ``mesh_job.complete(...)`` itself.

Cancel semantics: when the downstream caller cancels the mesh job,
the framework raises ``asyncio.CancelledError`` inside our function;
``a2a_job.bridge`` catches it, POSTs ``tasks/cancel`` upstream so the
A2A producer stops billing for the work, then re-raises as
``A2AJobCanceled``. The mesh wrapper records the canceled outcome.

Decorator stacking
==================

``@mesh.a2a_consumer`` already wraps the body and chains to
``@mesh.tool`` internally — passing ``task=True`` as a kwarg to
``@mesh.a2a_consumer`` forwards it via ``**kwargs`` to that inner
``@mesh.tool`` call. We do NOT stack a second ``@mesh.tool``: that
would either double-register or fight over capability/task settings.

Decorator order matters
=======================

``@mesh.agent`` MUST be the LAST decorator in the file. Its
``auto_run=True`` path triggers the mcp_startup pipeline INLINE
(uvicorn boot, registry handshake), which blocks the importing thread
before any module-level code below it can run.

Prereqs (in four terminals)
===========================

  # 1) Registry
  meshctl start registry

  # 2) Long-running provider — exposes generate_report (task=True)
  python examples/jobs/long-task-provider/main.py

  # 3) A2A surface — re-publishes generate_report via A2A v1.0
  python examples/a2a/report_a2a_agent.py

  # 4) This consumer — bridges the A2A surface back into the mesh
  #    as a regular ``report`` capability (long-running)
  python examples/a2a/consumer_report_agent.py

Test
====

A downstream mesh tool consumes the bridged capability via the
standard MeshJob interface — exactly the same shape as a native
``task=True`` provider call:

    @mesh.tool(capability="commission_report", dependencies=["report"])
    async def commission_report(user_id, sections, report: MeshJob = None):
        proxy = await report.submit(user_id=user_id, sections=sections)
        return await proxy.wait(timeout_secs=60)
"""

import json
import os

# Set MCP_MESH_HTTP_PORT BEFORE importing mesh so the framework's
# display_config picks up the same port we'll bind to. Avoids the
# producer's port (9091), the long-task-provider's port (9100), and
# the registry's port (8000).
HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9211"))

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Report Consumer Bridge (long-running)")


@app.tool()
@mesh.a2a_consumer(
    capability="report",
    a2a_url="http://localhost:9091/agents/report",
    a2a_skill_id="generate-report",
    tags=["a2a-bridge"],
    # task=True is forwarded via **kwargs to the inner @mesh.tool so
    # this capability registers with the long-running task substrate
    # — downstream callers see a normal MeshJob proxy, no clue the
    # work is actually happening on an external A2A backend.
    task=True,
)
async def report(
    user_id: str,
    sections: list[str],
    _a2a: mesh.A2AClient = None,
    job: MeshJob = None,
) -> dict:
    """Bridge the report_a2a_agent's generate-report skill into mesh.

    Submits the work to the upstream A2A producer non-blocking, then
    hands the returned ``A2AJob`` to ``bridge(job)`` which polls the
    A2A backend, mirrors progress into the mesh JobController, and
    returns the final artifact value (the producer's report dict).
    """
    a2a_job = await _a2a.submit(
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
    return await a2a_job.bridge(job)


# @mesh.agent MUST be last — see module docstring for why.
@mesh.agent(name="report-consumer", http_port=HTTP_PORT)
class ReportConsumer:
    """Mesh agent that bridges report_a2a_agent's generate-report skill
    into the mesh as a long-running ``report`` capability."""

    pass
