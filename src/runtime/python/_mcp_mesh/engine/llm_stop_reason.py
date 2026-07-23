"""Shared vocabulary for the LLM exhaustion signal (issue #1355).

When a provider-managed agentic loop hits ``max_iterations`` it must make the
exhaustion *structurally* distinguishable so the delegating consumer can raise
a typed error instead of returning a fabricated answer. Per the #1247 envelope
contract, ``content`` is always the answer string — the discriminant never
lives inside it.

Two channels carry the signal:

- **Buffered** reply envelope: a namespaced sibling field
  ``_mesh_stop_reason: "max_iterations"`` (sibling of ``content`` /
  ``_mesh_usage``). Absent on normal completion.
- **Streaming**: the MCP stream channel is strictly stringly-typed
  (``Stream[str]`` → FastMCP progress notifications carry ``str`` chunks), so a
  structured object cannot ride it directly. We adopt the Anthropic Messages
  API streaming discipline: the discriminator is the frame *type*, never the
  text content. EVERY chunk is a typed frame — a JSON *string* keyed by a
  RESERVED ``_mesh_``-namespaced discriminator — so text can never be misread
  as a control signal:

  - text delta            → ``{"_mesh_frame": "chunk", "content": "<delta>"}``
  - terminal, normal      → ``{"_mesh_frame": "end"}``
  - terminal, exhaustion  → ``{"_mesh_frame": "end", "stop_reason": "max_iterations"}``

  The discriminator lives under the reserved ``_mesh_frame`` key, not the
  common ``type`` token, so two collision surfaces close:

  1. A framed text delta whose ``content`` is literally an end-frame JSON string
     still arrives as ``{"_mesh_frame": "chunk", "content": "..."}`` — parsed as
     a ``chunk``, its content yielded verbatim; no control collision.
  2. An UNFRAMED raw model delta from a non-framing provider (an old-version
     Python provider mid-rollout, or a cross-runtime provider) that happens to
     read like ``{"type": "end"}`` or ``{"type": "chunk", "content": "x"}`` does
     NOT carry ``_mesh_frame`` → ``parse_stream_frame`` returns ``None`` and the
     consumer passes it through as raw text (defensive fallback), never
     misreading it as a control/text frame.

  The consumer parses each frame by its reserved discriminator, unwraps
  ``chunk`` content to the caller, and raises the typed error on an ``end``
  frame carrying ``stop_reason == "max_iterations"``.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Shared vocabulary token (kept identical to the string the deleted core
# ``agentic_loop`` module used, so a future consolidation reuses it).
STOP_REASON_MAX_ITERATIONS = "max_iterations"

# Reserved sibling key on the buffered reply envelope.
STOP_REASON_KEY = "_mesh_stop_reason"

# Typed stream-envelope frame vocabulary. The discriminator is a RESERVED
# ``_mesh_``-namespaced key so raw model text can never satisfy the frame check
# (the common ``type`` token would be a far wider collision surface).
FRAME_KEY = "_mesh_frame"
FRAME_CHUNK = "chunk"
FRAME_END = "end"


def encode_chunk(text: str) -> str:
    """Serialize a text delta as a typed ``chunk`` frame string."""
    return json.dumps({FRAME_KEY: FRAME_CHUNK, "content": text})


def encode_end(stop_reason: str | None = None) -> str:
    """Serialize a terminal ``end`` frame string.

    ``stop_reason`` is included only when set (e.g. ``"max_iterations"`` on
    exhaustion); a normal completion emits ``{"_mesh_frame": "end"}``.
    """
    frame: dict[str, str] = {FRAME_KEY: FRAME_END}
    if stop_reason is not None:
        frame["stop_reason"] = stop_reason
    return json.dumps(frame)


def parse_stream_frame(chunk: object) -> dict | None:
    """Parse a stream chunk into a typed frame dict, or ``None``.

    A well-formed frame is a JSON object carrying the reserved ``_mesh_frame``
    discriminator set to a recognized frame type (``"chunk"`` or ``"end"``).
    Anything else — a non-string, invalid JSON, a JSON value that isn't an
    object, an object missing ``_mesh_frame``, or one whose ``_mesh_frame`` is
    unrecognized — returns ``None`` so the consumer can apply a defensive
    passthrough fallback. Because the discriminator is ``_mesh_``-namespaced,
    an UNFRAMED raw model delta that merely looks frame-ish (e.g. a literal
    ``{"type": "end"}`` in the model's own text) does NOT match and is passed
    through verbatim rather than misread as a control/text frame.
    """
    if not isinstance(chunk, str):
        return None
    try:
        obj = json.loads(chunk)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get(FRAME_KEY) not in (FRAME_CHUNK, FRAME_END):
        return None
    return obj
