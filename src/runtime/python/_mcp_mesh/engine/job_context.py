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
]


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
    """

    job_id: str
    deadline_secs_remaining: Optional[float] = None


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
