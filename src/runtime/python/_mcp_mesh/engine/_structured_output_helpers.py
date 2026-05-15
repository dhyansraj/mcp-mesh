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
#: refusal rate on conversational/borderline content (v2.0.0 synthetic-tool
#: decline regression). The softened advisory wording reads more reliably
#: across models.
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
    The current caller (``anthropic_native._build_create_kwargs``)
    inspects ``raw_tools`` BEFORE ``_convert_tools`` runs, so the
    handler-injected tool is still in OpenAI shape; the Anthropic-shape
    branch is forward-looking for callers that inspect post-translation.
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


# JSON-Schema fields native ``output_config`` rejects but the synthetic-tool
# path accepts silently. LiteLLM strips these in
# ``filter_anthropic_output_schema`` (transformation.py:204-263) per Anthropic
# issue #19444. Without stripping, schemas that work on Haiku 400 on Sonnet.
#
# Defined here (not in ``anthropic_native``) so both the handler and the
# adapter can apply the same filter without crossing the handler→adapter
# import boundary. The handler stamps the post-filter schema as
# ``_mesh_output_config_schema`` so the loop's defense-in-depth parse check
# sees the exact shape that went on the wire.
_ANTHROPIC_OUTPUT_SCHEMA_REJECTED_KEYS = frozenset({"maxItems", "minItems"})


def filter_anthropic_output_schema(schema: Any) -> Any:
    """Recursively strip JSON-Schema fields Anthropic's native
    ``output_config.format`` rejects (``maxItems`` / ``minItems``).

    Walks ``properties``, ``items``, ``$defs`` / ``definitions``, and the
    ``anyOf`` / ``allOf`` / ``oneOf`` combinators. Preserves all other keys
    verbatim. Non-dict / non-list input is returned unchanged (defensive).

    Conservative — only the two keys LiteLLM hit in production are removed.
    If future Anthropic releases reject more fields, extend
    ``_ANTHROPIC_OUTPUT_SCHEMA_REJECTED_KEYS``.

    Idempotent: running on an already-filtered schema is a no-op.
    """
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key in _ANTHROPIC_OUTPUT_SCHEMA_REJECTED_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                # Property names are arbitrary identifiers — keep them
                # verbatim, recurse on each property's sub-schema.
                out[key] = {
                    prop_name: filter_anthropic_output_schema(prop_schema)
                    for prop_name, prop_schema in value.items()
                }
                continue
            if key in ("$defs", "definitions") and isinstance(value, dict):
                out[key] = {
                    def_name: filter_anthropic_output_schema(def_schema)
                    for def_name, def_schema in value.items()
                }
                continue
            out[key] = filter_anthropic_output_schema(value)
        return out
    if isinstance(schema, list):
        return [filter_anthropic_output_schema(item) for item in schema]
    return schema
