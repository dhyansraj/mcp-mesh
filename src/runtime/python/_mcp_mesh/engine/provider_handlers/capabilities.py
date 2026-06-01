"""Version-aware capability registry for structured-output mode selection.

Phase 1 of RFC #1100 — a PURE REFACTOR. This module centralizes the
*structured-output mode SELECTION* logic that was previously scattered across
the Claude / OpenAI / Gemini / generic provider handlers and the Anthropic
native client. It does NOT change any wire format, sentinel, schema
sanitization, or the agentic loop / fallback machinery.

``resolve_capabilities`` reproduces the EXACT mode decision each handler made
inline. The handlers now consult the resolver and switch on
``ModelCapabilities.structured_output`` to dispatch to the SAME existing
mode-implementation code. Net effect on ``model_params`` / ``request_params``
for every input is byte-identical to before this refactor.

Several ``ModelCapabilities`` fields (``server_enforced``, ``recovery``,
``schema_with_tools``, ``streaming_structured``, ``token_param``,
``min_sdk_version``) are DESCRIPTIVE only this phase: they record today's
behavior but nothing reads them to change control flow yet. Later RFC phases
will consume them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as _pkg_version

# SDK floors for the strong server-side structured-output primitives.
# These mirror the dependency floors in ``pyproject.toml``; the resolver
# degrades gracefully to the next-best native mode when an installed SDK is
# below its floor (e.g. a constrained install that pins an older SDK).
_ANTHROPIC_OUTPUT_CONFIG_FLOOR = (0, 77)  # anthropic >= 0.77 → output_config
_GEMINI_RESPONSE_JSON_SCHEMA_FLOOR = (1, 22)  # google-genai >= 1.22 → response_json_schema


# Matches a leading ``gemini-<major>`` token in a LiteLLM-style model id, after
# any backend prefix (``gemini/``, ``vertex_ai/``). Examples:
# ``gemini/gemini-3-pro-preview`` → 3; ``vertex_ai/gemini-2.5-flash`` → 2;
# ``gemini/gemini-1.5-pro`` → 1. Returns None when no gemini-major token is
# present (unknown / unparseable model id → conservative degrade).
_GEMINI_MAJOR_RE = re.compile(r"gemini-(\d+)")


def _gemini_major(model: str | None) -> int | None:
    """Return the Gemini major version from a model id, or ``None``.

    Conservative on uncertainty: an absent / unparseable model id returns
    ``None`` so the resolver does not select a Gemini-3-only primitive for a
    model whose generation cannot be confirmed.
    """
    if not model:
        return None
    m = _GEMINI_MAJOR_RE.search(model)
    return int(m.group(1)) if m else None


@lru_cache(maxsize=None)
def _sdk_version(dist: str) -> str | None:
    """Return the installed version string for ``dist`` or ``None``.

    Cached — distribution metadata does not change within a process. Returns
    ``None`` when the distribution is not installed so callers can degrade
    gracefully rather than raise.
    """
    try:
        return _pkg_version(dist)
    except PackageNotFoundError:
        return None


def _parse_version(raw: str | None) -> tuple[int, ...] | None:
    """Parse ``major.minor[.patch]`` from ``raw`` into a numeric tuple.

    Tolerant of pre-release / build suffixes (``1.22.0rc1``, ``0.77.0.dev3``,
    ``1.22+local``): only leading numeric dotted components are read, stopping
    at the first non-numeric component. Returns ``None`` for unparseable input.
    No new dependency — a tiny local parse rather than ``packaging``.
    """
    if not raw:
        return None
    parts: list[int] = []
    for chunk in raw.strip().split("."):
        m = re.match(r"(\d+)", chunk)
        if not m:
            break
        parts.append(int(m.group(1)))
    return tuple(parts) if parts else None


def _sdk_at_least(dist: str, floor: tuple[int, ...]) -> bool:
    """True when the installed ``dist`` version is >= ``floor``.

    Conservative on uncertainty: an uninstalled or unparseable version returns
    ``False`` so the resolver falls back to the next-best mode rather than
    selecting a primitive the SDK may not support.
    """
    parsed = _parse_version(_sdk_version(dist))
    if parsed is None:
        return False
    return parsed >= floor


class StructuredOutputMode:
    """String constants for the resolved structured-output mode.

    These map cleanly onto the existing handler/adapter behavior:

    - ``OUTPUT_CONFIG`` — Anthropic native ``output_config.format`` primitive
      (Sonnet 4.5+ / Opus 4.1+, buffered, native SDK). Handler stamps
      ``_mesh_output_config_*`` sentinels.
    - ``SYNTHETIC_TOOL`` — Anthropic synthetic ``__mesh_format_response`` tool
      (issue #834; older Claude models or any model when output_config is
      unavailable, native SDK, buffered). Handler stamps
      ``_mesh_synthetic_format_*`` sentinels.
    - ``RESPONSE_FORMAT_STRICT`` — OpenAI / Gemini (no tools, Gemini 2.x or
      older SDK) native ``response_format`` with ``strict: true``. For Gemini
      this flows to the adapter's ``response_schema`` field.
    - ``RESPONSE_JSON_SCHEMA`` — Gemini 3+ WITH tools, google-genai
      ``response_json_schema`` field (stricter server-side enforcement than
      ``response_schema``, and avoids the ``response_schema`` + tools
      infinite-loop bug). DEFAULT for qualifying requests (Gemini-3+ AND
      google-genai >= 1.22 AND tools). The
      ``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0`` kill-switch reverts these
      to ``PROSE_HINT``. gemini-2.x, an older SDK, or no-tools requests never
      reach this mode and keep their prior behavior.
    - ``RESPONSE_SCHEMA`` — reserved for future vendor variants of
      server-side schema enforcement. Unused.
    - ``PROSE_HINT`` — schema-in-prompt HINT mode (Claude LiteLLM path,
      Gemini-with-tools, generic). Handler stamps ``_mesh_hint_*`` sentinels
      (generic injects nothing — prose only).
    - ``TEXT`` — plain text output (``str`` return type).
    """

    OUTPUT_CONFIG = "output_config"
    SYNTHETIC_TOOL = "synthetic_tool"
    RESPONSE_FORMAT_STRICT = "response_format_strict"
    RESPONSE_JSON_SCHEMA = "response_json_schema"
    RESPONSE_SCHEMA = "response_schema"
    PROSE_HINT = "prose_hint"
    TEXT = "text"


# Recovery strategies (descriptive only in Phase 1).
RECOVERY_NONE = "none"
RECOVERY_RESPONSE_FORMAT_RETRY = "response_format_retry"
RECOVERY_PROSE_RETRY = "prose_retry"


@dataclass(frozen=True)
class ModelCapabilities:
    """Describes how a (vendor, model, request-shape) tuple handles structured
    output.

    ``structured_output`` is the only field consulted to drive control flow in
    Phase 1 (handlers switch on it). All other fields are descriptive — they
    record today's behavior for later RFC phases but are not read to change any
    dispatch decision yet.
    """

    structured_output: str
    server_enforced: bool
    schema_with_tools: bool
    streaming_structured: bool
    token_param: str = "max_tokens"
    min_sdk_version: str | None = None
    recovery: str = RECOVERY_NONE


def _resolve_anthropic(
    model: str | None,
    *,
    output_is_basemodel: bool,
    has_native: bool,
    streaming: bool,
) -> ModelCapabilities:
    """Reproduce ``ClaudeHandler.apply_structured_output`` selection.

    - ``str`` output → TEXT.
    - BaseModel + ``has_native`` + not ``streaming``:
        - ``_supports_native_output_format(model)`` → OUTPUT_CONFIG
        - else → SYNTHETIC_TOOL
    - BaseModel otherwise (no native, or streaming) → PROSE_HINT.
    """
    # Reuse the single source of truth for the output_config model gate.
    from _mcp_mesh.engine.native_clients.anthropic_native import (
        _supports_native_output_format,
    )

    if not output_is_basemodel:
        return ModelCapabilities(
            structured_output=StructuredOutputMode.TEXT,
            server_enforced=False,
            schema_with_tools=False,
            streaming_structured=False,
            recovery=RECOVERY_NONE,
        )

    if has_native and not streaming:
        # OUTPUT_CONFIG requires anthropic >= 0.77 (stable ``output_config``).
        # With the dependency floor now 0.77 this gate never trips in
        # conforming installs; it makes the resolver correct for constrained
        # installs that pin an older SDK by degrading to the next-best native
        # mode (SYNTHETIC_TOOL, issue #834) rather than emitting a primitive
        # the SDK cannot serialize.
        if _supports_native_output_format(model) and _sdk_at_least(
            "anthropic", _ANTHROPIC_OUTPUT_CONFIG_FLOOR
        ):
            return ModelCapabilities(
                structured_output=StructuredOutputMode.OUTPUT_CONFIG,
                server_enforced=True,
                schema_with_tools=True,
                streaming_structured=False,
                min_sdk_version="0.77",
                recovery=RECOVERY_NONE,
            )
        return ModelCapabilities(
            structured_output=StructuredOutputMode.SYNTHETIC_TOOL,
            server_enforced=True,
            schema_with_tools=True,
            streaming_structured=False,
            recovery=RECOVERY_NONE,
        )

    # LiteLLM path (no native) or streaming → HINT, with response_format retry.
    return ModelCapabilities(
        structured_output=StructuredOutputMode.PROSE_HINT,
        server_enforced=False,
        schema_with_tools=True,
        streaming_structured=streaming,
        recovery=RECOVERY_RESPONSE_FORMAT_RETRY,
    )


def _resolve_openai(*, output_is_basemodel: bool) -> ModelCapabilities:
    """Reproduce ``OpenAIHandler.prepare_request`` selection.

    - ``str`` output → TEXT.
    - BaseModel → RESPONSE_FORMAT_STRICT. Universal, no version gating.
    """
    if not output_is_basemodel:
        return ModelCapabilities(
            structured_output=StructuredOutputMode.TEXT,
            server_enforced=False,
            schema_with_tools=False,
            streaming_structured=False,
            recovery=RECOVERY_NONE,
        )
    return ModelCapabilities(
        structured_output=StructuredOutputMode.RESPONSE_FORMAT_STRICT,
        server_enforced=True,
        schema_with_tools=True,
        streaming_structured=True,
        recovery=RECOVERY_NONE,
    )


def _resolve_gemini(
    model: str | None,
    *,
    output_is_basemodel: bool,
    has_tools: bool,
    gemini_native_structured_tools: bool = False,
) -> ModelCapabilities:
    """Reproduce ``GeminiHandler.prepare_request`` selection.

    - ``str`` output → TEXT.
    - BaseModel + no tools → RESPONSE_FORMAT_STRICT (flows to the adapter's
      ``response_schema`` field).
    - BaseModel + tools → PROSE_HINT (response_format stripped; the
      response_format + tools combo triggers Gemini's infinite-tool-loop bug).
      The tools path never selects a server-side schema primitive.

    DEFAULT-ON EXCEPTION (RFC #1100 follow-up): when
    ``gemini_native_structured_tools`` is True (its default — the
    ``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0`` kill-switch is NOT set) AND
    tools are present AND the model is Gemini-3+ AND google-genai >= 1.22,
    select RESPONSE_JSON_SCHEMA — the stricter Gemini-3 server-side primitive,
    now validated loop-safe (the documented infinite-loop bug is specific to
    the OLDER ``response_schema`` primitive, which this path deliberately
    avoids). The kill-switch (``gemini_native_structured_tools=False``) reverts
    the tools path to PROSE_HINT exactly as the pre-#1102 default. gemini-2.x,
    an older SDK, or no-tools requests never reach this branch.
    """
    if not output_is_basemodel:
        return ModelCapabilities(
            structured_output=StructuredOutputMode.TEXT,
            server_enforced=False,
            schema_with_tools=False,
            streaming_structured=False,
            recovery=RECOVERY_NONE,
        )
    if not has_tools:
        return ModelCapabilities(
            structured_output=StructuredOutputMode.RESPONSE_FORMAT_STRICT,
            server_enforced=True,
            schema_with_tools=False,
            streaming_structured=True,
            recovery=RECOVERY_NONE,
        )
    if (
        gemini_native_structured_tools
        and (major := _gemini_major(model)) is not None
        and major >= 3
        and _sdk_at_least("google-genai", _GEMINI_RESPONSE_JSON_SCHEMA_FLOOR)
    ):
        return ModelCapabilities(
            structured_output=StructuredOutputMode.RESPONSE_JSON_SCHEMA,
            server_enforced=True,
            schema_with_tools=True,
            streaming_structured=False,
            min_sdk_version="1.22",
            recovery=RECOVERY_NONE,
        )
    return ModelCapabilities(
        structured_output=StructuredOutputMode.PROSE_HINT,
        server_enforced=False,
        schema_with_tools=True,
        streaming_structured=False,
        recovery=RECOVERY_RESPONSE_FORMAT_RETRY,
    )


def _resolve_generic(*, output_is_basemodel: bool) -> ModelCapabilities:
    """Reproduce ``GenericHandler`` behavior: prose HINT only (no
    response_format, no sentinels). ``str`` output is plain text either way —
    the generic handler never enforces a schema.
    """
    if not output_is_basemodel:
        return ModelCapabilities(
            structured_output=StructuredOutputMode.TEXT,
            server_enforced=False,
            schema_with_tools=False,
            streaming_structured=False,
            recovery=RECOVERY_NONE,
        )
    return ModelCapabilities(
        structured_output=StructuredOutputMode.PROSE_HINT,
        server_enforced=False,
        schema_with_tools=True,
        streaming_structured=False,
        recovery=RECOVERY_PROSE_RETRY,
    )


def resolve_capabilities(
    vendor: str,
    model: str | None,
    *,
    output_is_basemodel: bool,
    has_native: bool = False,
    streaming: bool = False,
    has_tools: bool = False,
    gemini_native_structured_tools: bool = False,
) -> ModelCapabilities:
    """Resolve the structured-output capabilities for a request.

    Per-vendor logic reproduces the exact mode decisions previously inlined in
    each handler. ``vendor`` is matched case-insensitively against the known
    vendors; anything else routes to the generic (prose-hint) behavior.

    Args:
        vendor: Provider vendor string (e.g. ``"anthropic"``, ``"openai"``,
            ``"gemini"``). Unknown vendors fall through to generic.
        model: Effective LiteLLM-style model id (e.g.
            ``anthropic/claude-sonnet-4-6``). Used for Anthropic's
            output_config gate and Gemini's major-version gate.
        output_is_basemodel: True when the output type is a Pydantic
            ``BaseModel`` subclass (False for ``str`` / text).
        has_native: True when the vendor's native SDK dispatch is active
            (Anthropic only consults this).
        streaming: True on the streaming dispatch path (Anthropic only).
        has_tools: True when real user tools are present (Gemini only).
        gemini_native_structured_tools: DEFAULT ON. When True (the default —
            the ``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0`` kill-switch is NOT
            set), qualifying Gemini-3+ requests with tools use the
            ``response_json_schema`` server-side primitive (Gemini only). When
            False (kill-switch set), the tools path reverts to PROSE_HINT.
    """
    v = (vendor or "").strip().lower()

    if v == "anthropic":
        return _resolve_anthropic(
            model,
            output_is_basemodel=output_is_basemodel,
            has_native=has_native,
            streaming=streaming,
        )
    if v == "openai":
        return _resolve_openai(output_is_basemodel=output_is_basemodel)
    if v == "gemini":
        return _resolve_gemini(
            model,
            output_is_basemodel=output_is_basemodel,
            has_tools=has_tools,
            gemini_native_structured_tools=gemini_native_structured_tools,
        )
    return _resolve_generic(output_is_basemodel=output_is_basemodel)
