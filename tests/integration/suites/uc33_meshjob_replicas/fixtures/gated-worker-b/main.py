#!/usr/bin/env python3
"""Gated MeshJob worker — replica B (uc33, issue #1252 Phase 4).

Replica pair: ``gated-worker-a`` / ``gated-worker-b`` are byte-identical
except for the declared agent name, the ``REPLICA`` stamp and the default
port. They are distinct fixture files because meshctl's "is this agent
already running" check keys off the ``@mesh.agent(name=...)`` decorator
literal (same pattern as uc21's bystander-x / bystander-y). The tests start
BOTH with ``--env MCP_MESH_AGENT_NAME=gated-worker`` so both INSTANCE IDS
share the ``gated-worker-`` prefix (the env var only seeds the instance-id
prefix — the registered ``/agents`` ``.name`` stays this decorator literal).
What mirrors production replicas (``replicas: 2``) is the part #1252 cares
about: two claim workers providing the SAME task capability on ONE shared
job queue — while meshctl manages them as two distinct local processes.

Both capabilities are ``task=True`` and claimed via the shared job queue:
whichever replica's claim worker wins executes the attempt. Every app-level
"transition" event the handlers post is stamped with
``{marker, phase/attempt, epoch: job.claim_epoch, replica: REPLICA}`` so the
test can detect duplicated execution and attribute every side effect to a
specific (replica, claim-epoch) pair.

Capabilities:

- ``gated_phases`` — the #1252 field shape: sequential ``recv_event`` gates.
  Each gate polls in SHORT rounds (``GATE_ROUND_SECS`` ≤ 5s), so every round
  is one executor read = one poll-liveness lease extension, keeping the
  extension cadence well inside even a small lease window. A handler blocked
  on a legitimately quiet gate is therefore provably alive — the registry
  must NOT reclaim it (tc01).

- ``sleepy_phases`` — the wedged-owner shape: attempt 1 blocks in a PURE
  ``asyncio.sleep`` (no recv_event polls → no liveness credit, no progress
  deltas → no lease renewal) past the lease window, so the registry
  legitimately reclaims and the next claim (epoch 2) supersedes attempt 1.
  When attempt 1 wakes, its first fenced write (a progress delta carrying
  the stale epoch) must be rejected as ``claim_superseded`` and fire this
  attempt's cancel token — aborting it BEFORE the duplicate side effects
  further down the handler body can land (tc02).
"""

import asyncio
import os
from typing import Any

import mesh
from fastmcp import FastMCP
from mesh import MeshJob

REPLICA = "b"

app = FastMCP(f"Gated Worker {REPLICA.upper()} (uc33)")

# Short recv_event rounds: one executor read (= one poll-liveness lease
# extension) every <= GATE_ROUND_SECS. Sized for gated_phases (tc01,
# max_duration=15): 4s rounds land several renewals per 15s lease window.
GATE_ROUND_SECS = 4.0
# Per-phase gate budget: GATE_ROUNDS * GATE_ROUND_SECS = 120s. Deliberately
# LONGER than any lease window in the tests — the whole point is that a
# quiet gate outlasting the lease must survive on poll-liveness alone.
GATE_ROUNDS = 30

# sleepy_phases (tc02) submits with max_duration=6 — a 6s lease. A 4s poll
# round would leave only ~2s of renewal margin per round against that lease
# (and with max_retries already spent on the deliberate reclaim, a >2s CI
# hiccup coinciding with the 10s sweep tick would terminally fail the job).
# The finish gate on the re-claimed attempt therefore polls in 2s rounds:
# >=2 liveness renewals per 6s lease window. Same 120s total budget.
SLEEPY_GATE_ROUND_SECS = 2.0
SLEEPY_GATE_ROUNDS = 60


async def _gate(
    job: MeshJob,
    types: list[str],
    round_secs: float = GATE_ROUND_SECS,
    rounds: int = GATE_ROUNDS,
):
    """Block on the next event of ``types``, polling in short rounds.

    Each ``recv_event`` round is an identity-bearing executor read, so the
    registry extends the lease per round (issue #1252 Phase 2). Returns the
    event, or ``None`` when the whole gate budget elapses.
    """
    for _ in range(rounds):
        event = await job.recv_event(types=types, timeout_secs=round_secs)
        if event is not None:
            return event
    return None


async def _post_transition(job: MeshJob, **payload: Any) -> None:
    """Stamp an app-level transition event with (replica, epoch)."""
    await mesh.jobs.post_event(
        job_id=job.job_id,
        event_type="transition",
        payload={"replica": REPLICA, "epoch": job.claim_epoch, **payload},
    )


# ---------------------------------------------------------------------------
# tc01 — quiet gate must survive on poll-liveness (single owner, epoch 1)
# ---------------------------------------------------------------------------


@app.tool()
@mesh.tool(
    capability="gated_phases",
    task=True,
    description="Sequential recv_event('go') gates; posts a stamped transition per phase.",
)
async def gated_phases(
    phases: int = 3,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is None:
        return {"status": "no_job_ctx"}
    epoch = job.claim_epoch
    for phase in range(1, phases + 1):
        event = await _gate(job, ["go"])
        if event is None:
            # Loud terminal failure — a silent return would let the test
            # misread a swallowed event as a pass.
            await job.fail(f"gate timeout at phase {phase} (replica={REPLICA})")
            return {"status": "gate_timeout", "phase": phase, "replica": REPLICA}
        await _post_transition(job, marker="phase_done", phase=phase)
        await job.update_progress(
            phase / phases, f"phase {phase}/{phases} (replica={REPLICA}, epoch={epoch})"
        )
    payload = {"status": "done", "phases": phases, "epoch": epoch, "replica": REPLICA}
    await job.complete(payload)
    return payload


# ---------------------------------------------------------------------------
# tc02 — wedged attempt 1 is superseded; its post-wake writes are fenced
# ---------------------------------------------------------------------------
#
# Attempt counter shared across replicas via a job-id-keyed file (both
# replicas run in the same test container). Same pattern as uc21's
# report_with_transient_failures counter — the reclaim dispatches the retry
# on whichever replica's claim worker wins, so process-local state can't
# distinguish attempts.


def _bump_attempt(job_id: str) -> int:
    path = f"/tmp/uc33-sleepy-attempt-{job_id}"
    try:
        with open(path) as f:
            n = int((f.read() or "0").strip())
    except FileNotFoundError:
        n = 0
    n += 1
    with open(path, "w") as f:
        f.write(str(n))
    return n


@app.tool()
@mesh.tool(
    capability="sleepy_phases",
    task=True,
    description="Attempt 1 wedges in a pure sleep past the lease; re-claimed attempt gates on 'finish'.",
)
async def sleepy_phases(
    sleep_secs: int = 35,
    job: MeshJob = None,
) -> dict[str, Any]:
    if job is None:
        return {"status": "no_job_ctx"}
    epoch = job.claim_epoch
    attempt = _bump_attempt(job.job_id)
    await _post_transition(job, marker="claimed", attempt=attempt)

    if attempt == 1:
        # WEDGED-OWNER SIMULATION: pure sleep — no recv_event polls (no
        # poll-liveness credit) and no progress deltas (no lease renewal).
        # The lease (sized by max_duration) lapses mid-sleep; the registry
        # reclaims and a peer (or this same instance) claims epoch 2.
        await asyncio.sleep(float(sleep_secs))

        # Post-wake: this attempt has been superseded. The progress delta
        # below carries the STALE epoch — the registry must reject it as
        # claim_superseded, which fires this attempt's cancel token. The
        # chunked grace loop below gives the async cancel a window to land
        # (batch flush + token propagation) BEFORE the would-be duplicate
        # side effects further down.
        await job.update_progress(
            0.9, f"post-sleep write from superseded attempt (replica={REPLICA})"
        )
        for _ in range(20):
            await asyncio.sleep(0.5)

        # DUPLICATE side effects — with working supersession fencing the
        # CancelledError above means execution NEVER reaches this point.
        # If it does, the post_sleep transition lands in the event log and
        # the test fails on it.
        await _post_transition(job, marker="post_sleep", attempt=attempt)
        payload = {"status": "done", "attempt": attempt, "epoch": epoch, "replica": REPLICA}
        await job.complete(payload)
        return payload

    # attempt >= 2: the healthy re-claimed run. Gate on 'finish' with SHORT
    # 2s polling rounds (see SLEEPY_GATE_ROUND_SECS — the 6s lease leaves no
    # margin for 4s rounds) — poll-liveness keeps THIS attempt's lease alive
    # while the test window proves the stale attempt was fenced on a LIVE row.
    event = await _gate(
        job,
        ["finish"],
        round_secs=SLEEPY_GATE_ROUND_SECS,
        rounds=SLEEPY_GATE_ROUNDS,
    )
    if event is None:
        await job.fail(f"finish gate timeout on re-claimed attempt (replica={REPLICA})")
        return {"status": "gate_timeout", "attempt": attempt, "replica": REPLICA}
    await _post_transition(job, marker="finish_seen", attempt=attempt)
    payload = {"status": "done", "attempt": attempt, "epoch": epoch, "replica": REPLICA}
    await job.complete(payload)
    return payload


@mesh.agent(
    name="gated-worker-b",
    version="1.0.0",
    description="Gated MeshJob worker replica B (uc33) — multi-replica execution integrity fixture.",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9112")),
    enable_http=True,
    auto_run=True,
)
class GatedWorkerB:
    pass
