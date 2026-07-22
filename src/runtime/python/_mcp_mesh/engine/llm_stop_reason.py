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
  structured object cannot ride it directly. Instead the provider emits a
  single reserved terminal control frame as the final chunk — a JSON string
  whose top-level key is ``_mesh_stream_end``. The consumer's stream wrapper
  recognizes it by a cheap prefix check, never forwards it, and raises the
  typed error at end-of-iteration.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Shared vocabulary token (kept identical to the string the deleted core
# ``agentic_loop`` module used, so a future consolidation reuses it).
STOP_REASON_MAX_ITERATIONS = "max_iterations"

# Reserved sibling key on the buffered reply envelope.
STOP_REASON_KEY = "_mesh_stop_reason"

# Reserved top-level key of the terminal stream control frame.
STREAM_END_KEY = "_mesh_stream_end"

# Cheap prefix used to detect the terminal frame without JSON-parsing every
# text chunk. Genuine LLM token deltas never begin with this exact sequence,
# and the provider yields the whole frame in a single ``yield``.
_STREAM_END_PREFIX = '{"' + STREAM_END_KEY + '"'


def encode_stream_end(stop_reason: str) -> str:
    """Serialize the terminal control frame as a single stream chunk string."""
    return json.dumps({STREAM_END_KEY: {"stop_reason": stop_reason}})


def parse_stream_end(chunk: object) -> str | None:
    """Return the frame's ``stop_reason`` if ``chunk`` is a terminal control
    frame, else ``None`` (i.e. an ordinary text chunk the wrapper forwards)."""
    if not isinstance(chunk, str) or not chunk.startswith(_STREAM_END_PREFIX):
        return None
    try:
        obj = json.loads(chunk)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    frame = obj.get(STREAM_END_KEY)
    if isinstance(frame, dict):
        stop_reason = frame.get("stop_reason")
        if stop_reason != STOP_REASON_MAX_ITERATIONS:
            # Well-formed terminal frame with a stop_reason we don't yet
            # recognize. The caller drops it (no typed error) — leave a trace
            # so a future stop_reason value isn't silently swallowed.
            logger.debug(
                "parse_stream_end: terminal control frame carried an "
                f"unrecognized stop_reason {stop_reason!r}; dropping it."
            )
        return stop_reason
    return None
