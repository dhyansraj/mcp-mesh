#!/usr/bin/env python3
"""Gated MeshJob worker for the admin-surface tests (uc36, issues #1265/#1267).

One task capability, ``admin_gated``: post a stamped ``claimed`` transition,
then block on a ``recv_event('finish')`` gate polled in SHORT 2s rounds. Every
round is one identity-bearing executor read = one poll-liveness lease
extension (issue #1252 Phase 2), so a gated attempt is provably alive and is
NEVER naturally reclaimed — the only way to evict it is the admin surface
under test (``meshctl job reclaim``). That is exactly the operator story
behind #1265: a healthy handler renews its lease every poll, so a natural
re-claim is nearly impossible to produce on demand.

Observability stamps (uc33/uc35 pattern):

- every app-level ``transition`` event carries ``{marker, attempt, epoch}``
  so tests can attribute every side effect to a specific (attempt,
  claim-epoch) pair and detect duplicated execution;
- the attempt counter is a job-id-keyed file (``/tmp/uc36-admin-attempt-*``)
  — a re-claim dispatches the retry through the same in-process claim worker,
  so process-local state cannot distinguish attempts;
- when a superseded attempt observes cancellation, the handler SYNCHRONOUSLY
  writes ``/tmp/uc36-cancel-observed-<job_id>`` before re-raising.
  Synchronous on purpose: no await inside the except block can itself be
  interrupted by the in-flight cancellation. Cancellation surfaces on TWO
  documented SDK channels, and this fixture must observe both:
    1. the gate's own ``recv_event`` is rejected ``claim_superseded`` by the
       registry — the Rust core fires this execution's cancel token and
       surfaces ``JobError::Cancelled``, which the Python FFI maps to
       ``RuntimeError("job cancelled by enclosing context")`` (jobs_py.rs) —
       the same shape an explicit user cancel takes mid-``recv_event``;
    2. the already-fired per-epoch cancel token aborts the task at any OTHER
       await point, raising ``asyncio.CancelledError`` (the uc33 write-path
       shape).

After the gate opens the handler posts a ``finish_seen`` transition, an
``update_progress`` delta and ``complete()`` — three registry-bound deltas
the drain test (#1267) uses to prove a job RUNNING at drain-entry still gets
its writes accepted and finishes normally.
"""

import asyncio
import os
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Admin Worker (uc36)")

# Short recv_event rounds: one executor read (= one poll-liveness lease
# extension) every <= 2s. The tests submit with max_duration >= 45 (a 45-60s
# lease window), so >= 20 renewals land per window — the gate can NEVER lapse
# naturally; only `meshctl job reclaim` evicts it.
GATE_ROUND_SECS = 2.0
# Total gate budget 180s — longer than any single test phase, shorter than
# the 300s test timeout so a wedged run still fails loudly via job.fail().
GATE_ROUNDS = 90


def _bump_attempt(job_id: str) -> int:
    """Job-id-keyed attempt counter shared across claims (uc33 pattern)."""
    path = f"/tmp/uc36-admin-attempt-{job_id}"
    try:
        with open(path) as f:
            n = int((f.read() or "0").strip())
    except FileNotFoundError:
        n = 0
    n += 1
    with open(path, "w") as f:
        f.write(str(n))
    return n


def _mark_cancel_observed(job_id: str, attempt: int) -> None:
    """SYNCHRONOUS cancel-observation marker — safe inside except CancelledError."""
    with open(f"/tmp/uc36-cancel-observed-{job_id}", "a") as f:
        f.write(f"attempt={attempt}\n")


async def _post_transition(job: MeshJob, **payload: Any) -> None:
    """Stamp an app-level transition event with the claim epoch."""
    await mesh.jobs.post_event(
        job_id=job.job_id,
        event_type="transition",
        payload={"epoch": job.claim_epoch, **payload},
    )


@app.tool()
@mesh.tool(
    capability="admin_gated",
    task=True,
    description="Gate on recv_event('finish') in short liveness-earning rounds; stamp every side effect with (attempt, epoch).",
)
async def admin_gated(job: MeshJob = None) -> dict[str, Any]:
    if job is None:
        return {"status": "no_job_ctx"}
    epoch = job.claim_epoch
    attempt = _bump_attempt(job.job_id)
    await _post_transition(job, marker="claimed", attempt=attempt)

    try:
        event = None
        for _ in range(GATE_ROUNDS):
            event = await job.recv_event(types=["finish"], timeout_secs=GATE_ROUND_SECS)
            if event is not None:
                break
    except asyncio.CancelledError:
        # Channel 2: the per-epoch cancel token (fired by a claim_superseded
        # rejection) aborted this task at an await point. Record the positive
        # observation synchronously, then let the cancellation propagate —
        # NOTHING below this point may run for a superseded attempt.
        _mark_cancel_observed(job.job_id, attempt)
        raise
    except RuntimeError as exc:
        # Channel 1: the gate's own recv_event was rejected claim_superseded
        # (owner cleared by `meshctl job reclaim`, or a newer epoch on the
        # row). The Rust core fires this execution's cancel token and
        # surfaces JobError::Cancelled, mapped by the Python FFI to
        # RuntimeError("job cancelled by enclosing context") — the exact
        # shape a user cancel takes mid-recv_event. Anything else is a real
        # bug and must propagate unrecorded.
        if "cancelled" in str(exc):
            _mark_cancel_observed(job.job_id, attempt)
        raise

    if event is None:
        # Loud terminal failure — a silent return would let a test misread
        # a swallowed event as a pass.
        await job.fail(f"finish gate timeout (attempt={attempt})")
        return {"status": "gate_timeout", "attempt": attempt}

    # DUPLICATE-side-effect tripwires for the reclaim test: with working
    # supersession fencing only the surviving attempt ever reaches here.
    await _post_transition(job, marker="finish_seen", attempt=attempt)
    await job.update_progress(0.9, f"pre-complete delta (attempt={attempt}, epoch={epoch})")
    payload = {"status": "done", "attempt": attempt, "epoch": epoch}
    await job.complete(payload)
    return payload


@mesh.agent(
    name="admin-worker",
    version="1.0.0",
    description="Gated MeshJob worker (uc36) — admin reclaim/drain fixture.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9161")),
    enable_http=True,
    auto_run=True,
)
class AdminWorker:
    pass
