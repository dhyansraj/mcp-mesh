"""Observable startup outcome for embedded mode (issue #1589).

In auto-run mode mesh owns the process, so a startup failure can be answered by
``abort_agent_process()`` — exit non-zero and let the orchestrator restart the
pod (issue #1556). Embedded mode (``auto_run=False``) has neither option:

* Exiting is wrong. The caller owns the process; mesh killing it would take
  down a server mesh does not manage.
* Raising is useless. ``_execute_processing`` runs on a ``threading.Timer``
  thread, so an exception there reaches ``threading.excepthook``, prints a
  traceback and kills that thread. The caller's server keeps serving, nothing
  registered, exit status still 0 — the exact #1556 shape.

So embedded mode records its outcome here and the caller polls it:

    import mesh

    status = mesh.startup_status()
    if status["state"] == "failed":
        raise SystemExit(f"mesh failed to start: {status['error']}")

A single reader with no callback registry keeps this free of ordering
questions: the record is written once, on the timer thread, before the log
line that announces it, and any thread can read it afterwards.
"""

import threading
from typing import Any

# No startup has been attempted yet (or the last one is still running).
PENDING = "pending"
# The pipeline succeeded. Check ``registered``/``heartbeat`` for what that got
# you — a "ready" agent with ``heartbeat: False`` is registered at most once
# and will fall out of the mesh.
READY = "ready"
# The pipeline failed. ``error`` says why. Nothing is registered.
FAILED = "failed"

_lock = threading.Lock()
_status: dict[str, Any] = {
    "state": PENDING,
    "pipeline_type": None,
    "error": None,
    "heartbeat": False,
    "warnings": [],
}


def get_status() -> dict[str, Any]:
    """Return a snapshot of the last embedded-mode startup outcome."""
    with _lock:
        snapshot = dict(_status)
    snapshot["warnings"] = list(snapshot["warnings"])
    return snapshot


def set_ready(
    pipeline_type: str, *, heartbeat: bool, warnings: list[str] | None = None
) -> None:
    """Record a successful pipeline run.

    ``heartbeat`` is whether a heartbeat thread actually started — it is False
    in standalone mode and when ``_setup_heartbeat_background`` swallowed an
    exception, and in both cases the agent will not stay registered.
    """
    with _lock:
        _status.update(
            state=READY,
            pipeline_type=pipeline_type,
            error=None,
            heartbeat=heartbeat,
            warnings=list(warnings or []),
        )


def set_failed(pipeline_type: str | None, error: str) -> None:
    """Record a failed pipeline run. Nothing is registered."""
    with _lock:
        _status.update(
            state=FAILED,
            pipeline_type=pipeline_type,
            error=error,
            heartbeat=False,
            warnings=[],
        )


def reset() -> None:
    """Reset to PENDING. For tests."""
    with _lock:
        _status.update(
            state=PENDING,
            pipeline_type=None,
            error=None,
            heartbeat=False,
            warnings=[],
        )
