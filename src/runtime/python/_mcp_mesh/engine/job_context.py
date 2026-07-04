"""Python-side mirror of the Rust core ``JobContext`` (Phase 1 — MeshJob).

The Rust core (``mcp_mesh_core::job_context``) holds the source of truth
for the active job context — set via ``with_job`` / ``run_as_job`` from
the inbound HTTP tool wrapper or the claim worker. The outbound HTTP
proxy reads it (via ``inject_job_headers``) to attach
``X-Mesh-Job-Id`` / ``X-Mesh-Timeout`` on downstream calls.

Python user code can also need to read the active job context (e.g. to
log the current job id, branch on whether a tool is running under a
job). Crossing the FFI boundary on every read is wasteful, so this
module exposes a ``contextvars.ContextVar`` mirror that the inbound
binding (next dispatch) sets alongside the Rust call.

For the current dispatch only the Python surface is defined; the
inbound wrapper that populates it lands in the next dispatch. Until
then ``current_job()`` returns ``None`` (no active job) — which is the
correct answer for any tool invoked via a regular ``tools/call`` rather
than a job-dispatch path.

See ``MESHJOB_DESIGN.org`` → "Timeout & Cancellation" → "Async-local
primitives" for the cross-runtime parity (Python ``contextvars`` ≡
TypeScript ``AsyncLocalStorage`` ≡ Java ``ThreadLocal``).
"""

import contextvars
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "JobContextSnapshot",
    "CURRENT_JOB",
    "current_job",
    "remaining_seconds",
    "CallingJob",
    "calling_job",
]

# Propagated-header names carrying the CALLING job's identity (issue #1263).
# A dedicated pair — distinct from the push-mode dispatch protocol's
# x-mesh-job-id / x-mesh-claim-epoch (x-mesh-job-id doubles as the dispatch
# discriminator, so it cannot also carry calling identity). Seeded on outbound
# mesh→mesh calls made from within a job execution context (see
# ``unified_mcp_proxy``'s calling-identity overlay) and read back here on the
# provider side.
_HDR_CALLING_JOB_ID = "x-mesh-calling-job-id"
_HDR_CALLING_CLAIM_EPOCH = "x-mesh-calling-claim-epoch"


@dataclass(frozen=True)
class JobContextSnapshot:
    """Read-only snapshot of the active job context for the current task.

    Mirrors the fields of the Rust core's ``JobContext`` that Python user
    code can usefully observe. The cancel token itself stays in the Rust
    core — Python observes its effects (via ``CancelledError`` raised by
    the runtime, or via tool-runtime fast-fail on outbound calls) rather
    than polling it directly.

    Attributes:
        job_id: Server-assigned job UUID this task is executing for.
        deadline_secs_remaining: Seconds left until the per-attempt
            deadline expires, or ``None`` if no deadline is set
            (unlimited per design-doc default).
        claim_epoch: Claim generation this attempt executes under (from
            the registry's ``POST /jobs/claim`` response), or ``None`` for
            a push-mode inbound job / an old registry (issue #1252).
            Additive, read-only — handlers can stamp it on side effects so
            a superseded re-execution's writes are distinguishable downstream.
    """

    job_id: str
    deadline_secs_remaining: Optional[float] = None
    claim_epoch: Optional[int] = None


CURRENT_JOB: contextvars.ContextVar[Optional[JobContextSnapshot]] = (
    contextvars.ContextVar("mesh_current_job", default=None)
)
"""Active ``JobContextSnapshot`` on the current task, or ``None``.

The inbound HTTP tool wrapper (next dispatch) sets this alongside the
Rust core's ``with_job`` so Python user code can read either side
without crossing FFI. When neither side is active, the value is
``None``.
"""


def current_job() -> Optional[JobContextSnapshot]:
    """Return the active job snapshot for the current task, or ``None``.

    Safe to call from any context — never raises. Returns ``None`` outside
    of any active job (e.g. for tools invoked via a regular ``tools/call``
    or in unit tests with no job-dispatch path).

    Note: The source of truth is the Rust core. This function reads the
    Python-side mirror for fast in-process access; for cross-FFI parity
    use ``mcp_mesh_core.current_job()`` (returns the same view as a dict).
    """
    return CURRENT_JOB.get()


@dataclass(frozen=True)
class CallingJob:
    """Identity of the job whose handler made the CURRENT inbound call
    (issue #1263).

    This is the provider-side dual of :class:`JobContextSnapshot`:
    ``current_job()`` answers "what job am I executing as", while
    ``calling_job()`` answers "what job invoked me". A provider (e.g. a
    state-authority agent) reads it to fence stale-executor writes without
    the caller threading identity through every tool-call payload.

    Attributes:
        job_id: Server-assigned job UUID of the calling job (from the
            incoming ``x-mesh-calling-job-id`` propagated header).
        claim_epoch: Claim generation the caller executes under (from the
            incoming ``x-mesh-calling-claim-epoch`` propagated header), or
            ``None`` for a push-mode inbound job / an old SDK that did not
            seed it.
    """

    job_id: str
    claim_epoch: Optional[int] = None


def calling_job() -> Optional[CallingJob]:
    """Return the identity of the job that made the current inbound call,
    or ``None`` when the call did not originate from a job handler
    (issue #1263).

    Reads the ``x-mesh-calling-job-id`` / ``x-mesh-calling-claim-epoch``
    propagated headers the mesh seeds on outbound calls made from within a job
    execution context. This is the "the job that CALLED me" view — it is
    ``None`` inside a directly-claimed job handler (that handler's OWN identity
    lives on :func:`current_job`). Safe to call from any tool body — never
    raises; returns ``None`` for regular (non-job) ``tools/call`` invocations
    and for calls from an old SDK that did not propagate the identity.

    Purely additive: reading it has no effect on the call.
    """
    try:
        from ..tracing.context import TraceContext

        headers = TraceContext.get_propagated_headers() or {}
    except Exception:
        return None
    job_id = headers.get(_HDR_CALLING_JOB_ID)
    if not job_id:
        return None
    claim_epoch: Optional[int] = None
    raw_epoch = headers.get(_HDR_CALLING_CLAIM_EPOCH)
    if raw_epoch is not None:
        try:
            parsed = int(raw_epoch)
            if parsed >= 0:
                claim_epoch = parsed
        except (TypeError, ValueError):
            claim_epoch = None
    return CallingJob(job_id=job_id, claim_epoch=claim_epoch)


def remaining_seconds() -> Optional[float]:
    """Seconds remaining on the active job's deadline, or ``None``.

    Returns ``None`` if no job is active, or if the active job has no
    deadline set (unlimited). Returns ``0.0`` once the deadline has passed
    — caller should treat that as "no time left" and abort outbound work.
    """
    snap = CURRENT_JOB.get()
    if snap is None:
        return None
    return snap.deadline_secs_remaining
