#!/usr/bin/env python3
"""MeshJob test-suite producer (uc21).

Hosts a small zoo of ``task=True`` capabilities, one per scenario the
suite needs to exercise. Each capability is intentionally minimal — we
avoid stuffing branching logic into a single tool because branching
across scenarios via payload args makes failures harder to triage when
the substrate misbehaves.

Capabilities:

- ``generate_report`` — happy path. Emits progress per section (~2s
  each) then explicitly calls ``job.complete(...)``. Mirrors the
  upstream example.
- ``report_with_explicit_complete`` — same shape but with a fixed
  marker payload so tc03 can assert the exact terminal value.
- ``report_with_implicit_complete`` — returns a value WITHOUT calling
  ``job.complete()``. Validates the runtime's auto-complete-on-return.
- ``report_with_explicit_fail`` — calls ``job.fail("...")`` and is
  expected to NOT trigger any retry attempts even when the submitter
  asked for ``max_retries > 0``.
- ``report_that_crashes`` — raises an unhandled exception. Used to
  drive crash-recovery / retry-exhaustion tests when paired with
  ``MCP_MESH_SWEEP_INTERVAL=10s``.
- ``report_with_downstream_call`` — invokes a regular tool (downstream
  ``slow_downstream``) so cancel propagation through ``X-Mesh-Timeout``
  + cancel-token can be observed end-to-end.
- ``runs_overlong`` — slow task whose only purpose is being long-lived
  enough to allow a mid-flight cancel / kill.
"""

import asyncio
import os
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob, McpMeshAgent

app = FastMCP("Long Task Provider (uc21)")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="generate_report",
    task=True,
    description="Long-running multi-section report generator with progress.",
)
async def generate_report(
    user_id: str,
    sections: list[str],
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is not None:
        await job.update_progress(0.0, "starting")

    results = []
    total = max(len(sections), 1)
    for i, section in enumerate(sections):
        await asyncio.sleep(2)
        results.append({"section": section, "content": f"Generated content for {section}"})
        if job is not None:
            await job.update_progress((i + 1) / total, f"finished section {i + 1}/{total}")

    payload = {"user_id": user_id, "report": results}
    if job is not None:
        await job.complete(payload)
    return payload


# ---------------------------------------------------------------------------
# Explicit complete with fixed marker payload
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="report_with_explicit_complete",
    task=True,
    description="Calls job.complete({...}) with a fixed marker payload.",
)
async def report_with_explicit_complete(
    user_id: str,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is not None:
        await job.update_progress(0.5, "midpoint")
        await asyncio.sleep(0.5)
        # Explicit terminal payload — tc03 asserts these exact fields.
        await job.complete({"explicit": True, "marker": "X", "user_id": user_id})
    # Fast-path return so synchronous tools/call still works.
    return {"explicit": True, "marker": "X", "user_id": user_id}


# ---------------------------------------------------------------------------
# Implicit complete (auto-complete on return)
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="report_with_implicit_complete",
    task=True,
    description="Returns a value WITHOUT calling job.complete() — relies on auto-complete.",
)
async def report_with_implicit_complete(
    user_id: str,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is not None:
        # Update progress to confirm controller binding worked. We
        # intentionally do NOT call job.complete() — the runtime's
        # auto-complete path should fire on return.
        await job.update_progress(0.5, "halfway")
        await asyncio.sleep(0.5)
        await job.update_progress(0.9, "almost done")
    return {"implicit": True, "user_id": user_id}


# ---------------------------------------------------------------------------
# Explicit fail — no retry
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="report_with_explicit_fail",
    task=True,
    description="Calls job.fail('reason') — must NOT trigger retry even with max_retries > 0.",
)
async def report_with_explicit_fail(
    user_id: str,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is not None:
        await job.update_progress(0.1, "about to fail")
        await asyncio.sleep(0.3)
        await job.fail("explicit: not retryable")
    # If invoked synchronously (no job context), surface the same intent.
    return {"failed": True, "reason": "explicit: not retryable"}


# ---------------------------------------------------------------------------
# Crash-on-attempt
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="report_that_crashes",
    task=True,
    description="Always raises mid-attempt — drives crash-recovery / retry-exhaustion tests.",
)
async def report_that_crashes(
    user_id: str,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is not None:
        await job.update_progress(0.1, "about to crash")
        await asyncio.sleep(0.3)
    # Unhandled exception — propagates up through the wrapper, the
    # producer-side runtime marks the attempt failed, and the registry
    # sweep is the safety net for orphan re-claim or exhaustion.
    raise RuntimeError("simulated crash for crash-recovery test")


# ---------------------------------------------------------------------------
# Long-running task — useful for mid-flight cancel / external kill
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="runs_overlong",
    task=True,
    description="Sleeps for many small intervals so cancel / kill can land mid-flight.",
)
async def runs_overlong(
    user_id: str,
    seconds: int = 30,
    job: MeshJob = None,
) -> dict[str, Any]:
    # Loop in small chunks so the cancel token can interrupt promptly.
    elapsed = 0.0
    step = 0.5
    total = max(float(seconds), step)
    while elapsed < total:
        await asyncio.sleep(step)
        elapsed += step
        if job is not None:
            await job.update_progress(min(elapsed / total, 0.99), f"alive at {elapsed:.1f}s")
    payload = {"user_id": user_id, "elapsed": elapsed}
    if job is not None:
        await job.complete(payload)
    return payload


# ---------------------------------------------------------------------------
# Job that calls a downstream regular tool — exercises cancel propagation
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="report_with_downstream_call",
    task=True,
    dependencies=["slow_downstream"],
    description="Calls a downstream regular tool that sleeps; cancel must abort the in-flight HTTP.",
)
async def report_with_downstream_call(
    user_id: str,
    slow_downstream: McpMeshAgent = None,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is not None:
        await job.update_progress(0.1, "calling downstream")
    if slow_downstream is None:
        # Returning a dict here would trip the runtime's auto-complete
        # path (W8 fix from PR #878) and mark the job COMPLETED with the
        # error dict as its result. The intent is the opposite — surface
        # the missing-dep state as a terminal failure. job.fail() sets
        # the terminal state explicitly; auto-complete is a no-op once a
        # terminal state has been recorded.
        if job is not None:
            await job.fail({"error": "slow_downstream dependency not injected"})
        return None
    # The downstream tool sleeps 30s. With cancel propagation working,
    # the cancel token aborts the in-flight HTTP request well before
    # the 30s timer elapses.
    result = await slow_downstream(user_id=user_id, seconds=30)
    if job is not None:
        await job.complete(result)
    return result


@mesh.agent(
    name="long-task-provider",
    version="1.0.0",
    description="MeshJob test producer (uc21) — multi-capability fixture for the integration suite.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9100")),
    enable_http=True,
    auto_run=True,
)
class LongTaskProvider:
    pass
