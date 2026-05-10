#!/usr/bin/env python3
"""
Downstream caller fixture for uc25 Phase 3 tests (issue #910) — a
regular mesh agent that depends on the bridged ``report`` /
``report-sse`` capabilities and consumes them via the standard
MeshJob interface.

Mirrors the canonical task=True consumption pattern from
``tests/integration/suites/uc21_meshjob/fixtures/long-task-consumer``:
``await proxy = dep.submit(...)`` then ``await proxy.wait(...)`` for
happy-path tests, OR ``return {job_id}`` immediately for cancel /
JobLost tests that need to drive the lifecycle from the outside.

The caller has no idea the work is happening on an external A2A
backend — that is precisely the point of the consumer bridge.

Capabilities:

  - ``commission_report``        — submit + wait against ``report``
                                   (poll-based bridge).
  - ``commission_report_sse``    — submit + wait against ``report-sse``
                                   (SSE-based bridge).
  - ``commission_report_async``  — submit + return job_id immediately
                                   against ``report``. Tests poll +
                                   cancel via the helper tools.
"""

from typing import Optional

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Report Caller (uc25 Phase 3)")


@app.tool()
@mesh.tool(
    capability="commission_report",
    dependencies=["report"],
    description="Submit + wait against the report capability (poll-based bridge).",
)
async def commission_report(
    user_id: str,
    sections: list[str],
    wait_timeout_secs: int = 60,
    report: MeshJob = None,
) -> dict:
    """Submit a long-running report job and wait for the result.

    Returns a structured envelope: ``{job_id, status, result}`` on
    success, ``{job_id, status: wait_raised, error}`` if the underlying
    proxy.wait raised (timeout / failed / canceled). Mirrors uc21's
    ``commission_with_options`` envelope shape so tests can assert on
    structured fields rather than exception text.
    """
    if report is None:
        return {"error": "report submitter not injected"}
    proxy = await report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=120,
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:  # pragma: no cover - structured envelope for tests
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


@app.tool()
@mesh.tool(
    capability="commission_report_sse",
    dependencies=["report_sse"],
    description="Submit + wait against the report_sse capability (SSE-based bridge).",
)
async def commission_report_sse(
    user_id: str,
    sections: list[str],
    wait_timeout_secs: int = 60,
    report_sse: MeshJob = None,
) -> dict:
    """Same as commission_report but against the SSE bridge."""
    if report_sse is None:
        return {"error": "report_sse submitter not injected"}
    proxy = await report_sse.submit(
        user_id=user_id,
        sections=sections,
        max_duration=120,
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:  # pragma: no cover - structured envelope for tests
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


@app.tool()
@mesh.tool(
    capability="commission_report_async",
    dependencies=["report"],
    description="Submit a report job and return the job_id without waiting.",
)
async def commission_report_async(
    user_id: str,
    sections: list[str],
    max_duration: int = 120,
    report: MeshJob = None,
) -> dict:
    """Submit + return immediately. Tests then drive the job lifecycle
    via __mesh_job_status / __mesh_job_cancel / __mesh_job_result
    helper tools (they're auto-registered on every mesh agent).
    """
    if report is None:
        return {"error": "report submitter not injected"}
    proxy = await report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=max_duration,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


@app.tool()
@mesh.tool(
    capability="commission_report_sse_async",
    dependencies=["report_sse"],
    description="Submit a report_sse job and return the job_id without waiting.",
)
async def commission_report_sse_async(
    user_id: str,
    sections: list[str],
    max_duration: int = 120,
    report_sse: MeshJob = None,
) -> dict:
    """Same as commission_report_async but against the SSE bridge.

    Used by tc06 to avoid the registry-proxy upstream-timeout pitfall
    that bites synchronous submit+wait callers when the nested
    bridge chain runs for >30s.
    """
    if report_sse is None:
        return {"error": "report_sse submitter not injected"}
    proxy = await report_sse.submit(
        user_id=user_id,
        sections=sections,
        max_duration=max_duration,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# @mesh.agent MUST be last.
@mesh.agent(name="report-caller", http_port=9213)
class ReportCaller:
    """Downstream consumer that exercises the bridged report capabilities
    via the standard MeshJob interface (uc21 pattern)."""

    pass
