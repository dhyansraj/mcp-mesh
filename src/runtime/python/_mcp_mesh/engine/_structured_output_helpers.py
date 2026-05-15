"""Shared helpers for the synthetic-tool structured-output pattern (issue #834).

Two injection paths use the same wire-shape: (1) handler-injected via
``ClaudeHandler._apply_native_synthetic_format``, (2) adapter-injected from
``response_format`` inside ``anthropic_native._build_create_kwargs``. This
module is the single source of truth for that shape — pure builders, no
side effects.

Schema sanitization (``make_schema_strict``,
``sanitize_schema_for_structured_output``) is the CALLER's responsibility —
these helpers assume the schema is clean.

Kept vendor-agnostic. OpenAI/Gemini have native ``response_format`` and
don't currently need synthetic-tool injection, but Phase B/C may reuse
these helpers for vendors whose strict mode emits refusals.
"""

from __future__ import annotations

from typing import Any

#: Tool name the agentic loop recognizes as "model's final structured answer".
#: Double-underscore prefix marks it as internal — agents must not register
#: a tool with this name.
SYNTHETIC_FORMAT_TOOL_NAME = "__mesh_format_response"

SYNTHETIC_FORMAT_TOOL_DESCRIPTION = (
    "Use this tool to return your final structured answer matching the "
    "schema. Call this tool only after gathering all needed data via other "
    "available tools."
)

#: Advisory addendum. The earlier "MUST / Do NOT" framing raised Haiku's
#: refusal rate on conversational/borderline content (Maya regression
#: v2.0.0). The softened advisory wording reads more reliably across models.
SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION = (
    "\n\nWhen you are ready to respond, call the `__mesh_format_response` "
    "tool with your final answer in the required structured format."
)


def schema_to_synthetic_tool(
    schema: dict[str, Any],
    *,
    tool_name: str = SYNTHETIC_FORMAT_TOOL_NAME,
    description: str = SYNTHETIC_FORMAT_TOOL_DESCRIPTION,
) -> dict[str, Any]:
    """Build an OpenAI-shape function-tool dict with ``schema`` placed verbatim
    under ``function.parameters``.

    Returns::

        {"type": "function",
         "function": {"name": tool_name,
                      "description": description,
                      "parameters": schema}}

    Vendor adapters translate the resulting dict to native shape via their
    existing ``_convert_tools`` translators — no special-casing needed.
    """
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": schema,
        },
    }


def build_synthetic_tool_choice(
    *,
    real_tools_present: bool,
    tool_name: str = SYNTHETIC_FORMAT_TOOL_NAME,
) -> str | dict[str, Any]:
    """Return ``tool_choice`` for synthetic injection.

    * ``real_tools_present=False`` → force the synthetic tool (single
      deterministic round-trip):
      ``{"type": "function", "function": {"name": tool_name}}``
    * ``real_tools_present=True``  → ``"auto"`` (the model picks between
      real tools and the synthetic — matches the TS Vercel-AI-SDK /
      Java Spring-AI pattern).
    """
    if real_tools_present:
        return "auto"
    return {"type": "function", "function": {"name": tool_name}}


def append_synthetic_system_instruction(system: str | None) -> str:
    """Append :data:`SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION` to a system-message
    string.

    Tolerates ``None`` / empty (returns the instruction with leading
    whitespace stripped). NOT suitable for content-block-list system
    messages (prompt-cache decorated shape) — the handler keeps its own
    list-aware path; the adapter-side path only encounters bare strings
    (after ``_split_system_messages`` merge).
    """
    if not system:
        return SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION.lstrip("\n")
    return system + SYNTHETIC_FORMAT_SYSTEM_INSTRUCTION


def is_synthetic_tool_in_list(
    tools: list[dict[str, Any]] | None,
    *,
    tool_name: str = SYNTHETIC_FORMAT_TOOL_NAME,
) -> bool:
    """True if ``tools`` contains the synthetic tool.

    Used for adapter-side coordination: when the handler has already
    injected the synthetic tool the adapter must NOT re-inject.

    Recognizes BOTH the OpenAI shape (``function.name``) AND the
    pre-translated Anthropic shape (``name`` + ``input_schema``).
    Tolerates ``None`` / empty; skips non-dict entries.
    """
    if not tools:
        return False
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") or {}
        if isinstance(fn, dict) and fn.get("name") == tool_name:
            return True
        if t.get("name") == tool_name and "input_schema" in t:
            return True
    return False
