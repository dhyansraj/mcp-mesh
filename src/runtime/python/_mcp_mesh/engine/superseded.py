"""Typed supersession signal (issue #1278).

A provider tool that detects it is being called by a SUPERSEDED executor —
the app compares the calling job's epoch via :func:`mesh.calling_job`
(issue #1263) against its own live epoch — rejects the call by raising
:class:`SupersededError`. That crosses the wire as the reserved app envelope
``{"error":"claim_superseded"}`` (plus an optional ``"detail"`` string), and
the CALLING side's injected ``McpMeshTool`` proxy recognizes the envelope and
re-raises :class:`SupersededError`. A superseded caller then unwinds with one
``except mesh.SupersededError`` instead of string-matching ``claim_superseded``
after every mutating call.

The framework does NOT auto-detect supersession — the app decides (full
control); the framework provides the typed class plus the emit/recognize
plumbing. This is the structural parallel of the ``dependency_unavailable``
refusal (issue #1273): both raise a ``ToolError`` whose message is a reserved
JSON envelope, so the contract (not the carrier) drives classification.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastmcp.exceptions import ToolError

# Reserved marker string for the supersession envelope. This is the SAME
# canonical marker the job path already uses on the wire (Rust
# ``task_backend.rs`` ``CLAIM_SUPERSEDED_REASON`` / Go
# ``ent_service_jobs.go``), reused verbatim so a superseded signal is one
# string end-to-end.
CLAIM_SUPERSEDED_MARKER = "claim_superseded"


class SupersededError(ToolError):
    """Raised by a provider tool to reject a call from a superseded executor.

    Subclasses fastmcp's :class:`~fastmcp.exceptions.ToolError` — the same
    error primitive the ``dependency_unavailable`` refusal uses — so raising it
    from a ``@mesh.tool`` handler auto-emits an ``isError`` tool result whose
    text is the reserved envelope, through the EXISTING fastmcp ToolError path
    (no provider wrapper change needed).

    The serialized message (``str(err)``) is
    ``{"error":"claim_superseded","detail":<detail>}`` — the ``detail`` key is
    omitted entirely when no detail is supplied.

    Provider usage::

        cj = mesh.calling_job()
        if cj and cj.claim_epoch is not None and cj.claim_epoch < my_live_epoch:
            raise mesh.SupersededError(f"stale epoch {cj.claim_epoch}")

    ``except mesh.SupersededError`` is the specific catch this enables; because
    it IS a ToolError, ``except ToolError`` still catches it too.
    """

    def __init__(self, detail: Optional[str] = None):
        self.detail = detail
        envelope: dict[str, Any] = {"error": CLAIM_SUPERSEDED_MARKER}
        if detail is not None:
            envelope["detail"] = detail
        # Compact separators → byte-identical to the TS/Java emit and the
        # compact job-path marker (no whitespace after ',' / ':').
        super().__init__(json.dumps(envelope, separators=(",", ":")))


def parse_superseded_envelope(error_text: str) -> Optional[SupersededError]:
    """Return a :class:`SupersededError` if ``error_text`` is the reserved
    supersession envelope, else ``None``.

    Defensive parse for the consumer recognize path: a non-JSON body, a JSON
    body that is not an object, or one whose ``error`` field is not exactly the
    reserved marker all return ``None`` so the caller falls through to its
    existing generic error handling. Only the exact reserved marker is
    classified — a ``dependency_unavailable`` (or any other) envelope is left
    alone.
    """
    try:
        payload = json.loads(error_text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("error") != CLAIM_SUPERSEDED_MARKER:
        return None
    detail = payload.get("detail")
    return SupersededError(detail if isinstance(detail, str) else None)
