#!/usr/bin/env python3
"""MeshJob test-suite consumer (uc21).

Hosts several variants of the submit-and-await pattern so individual
test cases can exercise behavioural knobs without forking new agents:

- ``commission_report`` — submit + wait; raises on terminal error.
  Mirrors the upstream example.
- ``commission_with_options`` — submit + wait with caller-supplied
  ``max_retries`` and an optional ``total_deadline_secs`` (relative,
  converted to a UTC datetime under the hood). Returns a structured
  envelope on terminal failure instead of raising — lets tests assert
  status / error fields directly.
- ``commission_submit_only`` — submit and return ``{job_id}``
  immediately. Tests poll status / result / cancel themselves via
  the helper tools, which is the right shape for cancellation /
  recovery scenarios where blocking on ``wait()`` would hide signal.
- ``commission_explicit_fail`` — submits ``report_with_explicit_fail``
  with caller-supplied ``max_retries``. Always returns the structured
  envelope so tc05 can assert ``status=failed`` + attempt_count.
- ``commission_crash`` — submits ``report_that_crashes`` with caller-
  supplied ``max_retries`` and (optional) ``total_deadline_secs``.
- ``commission_overlong`` — submits ``runs_overlong``. Used by
  cancel-token tests.
- ``commission_downstream`` — submits ``report_with_downstream_call``.
  Used by tc09 to verify cancel aborts the downstream HTTP.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Long Task Consumer (uc21)")


def _utc_deadline_from_relative(secs: Optional[int]) -> Optional[datetime]:
    if secs is None:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=secs)


# ---------------------------------------------------------------------------
# Submit + wait (raises on terminal error) — happy-path baseline
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_report",
    dependencies=["generate_report"],
    description="Submit a generate_report job and wait up to 60s for the result.",
)
async def commission_report(
    user_id: str,
    sections: list[str],
    generate_report: MeshJob = None,
) -> dict:
    if generate_report is None:
        return {"error": "generate_report submitter not injected"}
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=60,
    )
    return await proxy.wait(timeout_secs=60)


# ---------------------------------------------------------------------------
# Submit + wait with caller-controlled retry / deadline knobs
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_with_options",
    dependencies=["generate_report"],
    description="Submit generate_report with caller-supplied max_retries / total_deadline_secs.",
)
async def commission_with_options(
    user_id: str,
    sections: list[str],
    max_retries: int = 1,
    total_deadline_secs: Optional[int] = None,
    wait_timeout_secs: int = 60,
    generate_report: MeshJob = None,
) -> dict:
    if generate_report is None:
        return {"error": "generate_report submitter not injected"}
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=60,
        max_retries=max_retries,
        total_deadline=_utc_deadline_from_relative(total_deadline_secs),
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:  # pragma: no cover - structured envelope for tests
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


# ---------------------------------------------------------------------------
# Submit-only — return job_id immediately
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_submit_only",
    dependencies=["generate_report"],
    description="Submit generate_report and return the job_id without waiting.",
)
async def commission_submit_only(
    user_id: str,
    sections: list[str],
    max_retries: int = 1,
    max_duration: int = 60,
    generate_report: MeshJob = None,
) -> dict:
    if generate_report is None:
        return {"error": "generate_report submitter not injected"}
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=max_duration,
        max_retries=max_retries,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Explicit-fail submitter — submits report_with_explicit_fail
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_explicit_fail",
    dependencies=["report_with_explicit_fail"],
    description="Submit report_with_explicit_fail with caller-supplied max_retries.",
)
async def commission_explicit_fail(
    user_id: str,
    max_retries: int = 3,
    wait_timeout_secs: int = 30,
    report_with_explicit_fail: MeshJob = None,
) -> dict:
    if report_with_explicit_fail is None:
        return {"error": "report_with_explicit_fail submitter not injected"}
    proxy = await report_with_explicit_fail.submit(
        user_id=user_id,
        max_duration=30,
        max_retries=max_retries,
    )
    job_id = getattr(proxy, "job_id", None)
    try:
        result = await proxy.wait(timeout_secs=wait_timeout_secs)
        return {"job_id": job_id, "status": "completed", "result": result}
    except Exception as e:
        return {"job_id": job_id, "status": "wait_raised", "error": str(e)}


# ---------------------------------------------------------------------------
# Crash submitter — submits report_that_crashes
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_crash",
    dependencies=["report_that_crashes"],
    description="Submit report_that_crashes (always raises) with caller-supplied retry / deadline.",
)
async def commission_crash(
    user_id: str,
    max_retries: int = 0,
    total_deadline_secs: Optional[int] = None,
    report_that_crashes: MeshJob = None,
) -> dict:
    if report_that_crashes is None:
        return {"error": "report_that_crashes submitter not injected"}
    proxy = await report_that_crashes.submit(
        user_id=user_id,
        max_duration=30,
        max_retries=max_retries,
        total_deadline=_utc_deadline_from_relative(total_deadline_secs),
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Overlong submitter — submits runs_overlong (cancel-token tests)
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_overlong",
    dependencies=["runs_overlong"],
    description="Submit runs_overlong and return the job_id (no wait).",
)
async def commission_overlong(
    user_id: str,
    seconds: int = 30,
    runs_overlong: MeshJob = None,
) -> dict:
    if runs_overlong is None:
        return {"error": "runs_overlong submitter not injected"}
    proxy = await runs_overlong.submit(
        user_id=user_id,
        seconds=seconds,
        max_duration=120,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


# ---------------------------------------------------------------------------
# Downstream-call submitter — submits report_with_downstream_call
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="commission_downstream",
    dependencies=["report_with_downstream_call"],
    description="Submit report_with_downstream_call (provider calls slow_downstream) and return job_id.",
)
async def commission_downstream(
    user_id: str,
    report_with_downstream_call: MeshJob = None,
) -> dict:
    if report_with_downstream_call is None:
        return {"error": "report_with_downstream_call submitter not injected"}
    proxy = await report_with_downstream_call.submit(
        user_id=user_id,
        max_duration=120,
    )
    return {"job_id": getattr(proxy, "job_id", None)}


import os  # noqa: E402  (kept here for clarity that env-port is the only env hook)


@mesh.agent(
    name="long-task-consumer",
    version="1.0.0",
    description="MeshJob test consumer (uc21) — multi-capability fixture for the integration suite.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9101")),
    enable_http=True,
    auto_run=True,
)
class LongTaskConsumer:
    pass
