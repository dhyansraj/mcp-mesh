#!/usr/bin/env python3
"""
Typed supersession signal (issue #1278) — Provider: a write authority that
fences stale-executor writes.

This is the provider half of the calling-job fencing pattern. A state
authority (here an in-memory ledger) accepts mutating writes from job
executors. When a job is re-claimed after a crash/reclaim, a NEWER executor
runs under a HIGHER ``claim_epoch``; the OLD executor may still be mid-flight
and try to write. Those stale writes must be rejected so the newer executor
owns the outcome.

Two mesh surfaces make this a few lines:

    # 1. Read WHO called me (issue #1263 — the calling job's identity).
    cj = mesh.calling_job()          # -> CallingJob(job_id, claim_epoch) | None

    # 2. Reject a superseded caller with the TYPED signal (issue #1278).
    raise mesh.SupersededError(detail)

The framework does NOT auto-detect supersession — the APP decides. The mesh
only propagates the calling job's identity and provides the typed error plus
its emit/recognize plumbing. Here the "is superseded" rule is deliberately
simple and deterministic for teaching: the authority remembers the highest
``claim_epoch`` it has seen per calling ``job_id`` and rejects any call whose
epoch is lower — i.e. "an older executor is trying to write after a newer one
already has". A real authority might instead consult the registry, a lease
table, or a monotonic version column.

``mesh.SupersededError`` crosses the wire as the reserved app envelope
``{"error":"claim_superseded"}`` (plus an optional ``"detail"``). The calling
side's injected proxy recognizes that envelope and re-raises
``mesh.SupersededError`` — so the CONSUMER unwinds with ONE
``except mesh.SupersededError`` (see ``../superseded-consumer/main.py``)
instead of string-matching a marker after every call.

Run:
    MCP_MESH_REGISTRY_URL=http://localhost:8000 python3 main.py
"""

import logging
from typing import Any

import mesh
from fastmcp import FastMCP

log = logging.getLogger("superseded-provider")
app = FastMCP("Superseded Write Authority")

# Highest claim_epoch this authority has accepted a write under, per calling
# job_id. This is the APP's supersession state — the framework does not keep
# it. A single-process async server touches this from one event loop, so a
# plain dict is safe here; a multi-replica authority would keep it in a shared
# store (Redis, a DB version column, ...).
_latest_epoch_by_job: dict[str, int] = {}

# The in-memory "ledger" we are protecting from stale writes.
_ledger: list[dict[str, Any]] = []


@app.tool()
@mesh.tool(
    capability="apply_write",
    description=(
        "Apply a mutating write to the ledger, fencing out writes from a "
        "superseded (older-epoch) executor. Demonstrates calling-job fencing "
        "with the typed SupersededError."
    ),
)
async def apply_write(entry: str) -> dict[str, Any]:
    """Append ``entry`` to the ledger — unless the caller is superseded.

    The mutating payload (``entry``) is an ordinary tool argument. The caller's
    IDENTITY is NOT in the payload — it rides the propagated headers the mesh
    seeds on outbound calls made from within a job execution context, and we
    read it back with ``mesh.calling_job()``.
    """
    cj = mesh.calling_job()

    # No calling-job identity → a regular (non-job) tools/call, or a caller on
    # an old SDK that does not propagate identity. Nothing to fence against;
    # apply the write. (Fencing is defense-in-depth, never a hard requirement
    # to make progress — soft-fail-open when identity is absent.)
    if cj is None or cj.claim_epoch is None:
        log.info("apply_write from non-job/unidentified caller — applying")
        _ledger.append({"entry": entry, "by_epoch": None})
        return {"applied": True, "ledger_size": len(_ledger), "fenced": False}

    seen = _latest_epoch_by_job.get(cj.job_id, -1)

    if cj.claim_epoch < seen:
        # APP DECISION: a newer executor (epoch ``seen``) has already written
        # for this job, so this older executor's write is stale. Reject with
        # the typed signal — this serializes to the reserved
        # {"error":"claim_superseded","detail":...} envelope, and the caller's
        # injected proxy re-raises mesh.SupersededError on its side.
        detail = (
            f"job {cj.job_id}: calling epoch {cj.claim_epoch} < "
            f"latest accepted epoch {seen}"
        )
        log.warning("fencing superseded write: %s", detail)
        raise mesh.SupersededError(detail)

    # Caller is current (>= highest seen). Record its epoch and apply.
    _latest_epoch_by_job[cj.job_id] = max(seen, cj.claim_epoch)
    _ledger.append({"entry": entry, "by_epoch": cj.claim_epoch})
    log.info(
        "applied write for job %s at epoch %s (ledger_size=%d)",
        cj.job_id,
        cj.claim_epoch,
        len(_ledger),
    )
    return {
        "applied": True,
        "ledger_size": len(_ledger),
        "accepted_epoch": cj.claim_epoch,
        "fenced": False,
    }


@mesh.agent(
    name="superseded-provider",
    version="1.0.0",
    description=(
        "Issue #1278 provider — write authority that fences superseded "
        "executors via calling-job epoch + typed SupersededError"
    ),
    http_port=9104,
    enable_http=True,
    auto_run=True,
)
class SupersededProvider:
    """Hosts the ``apply_write`` capability."""

    pass
