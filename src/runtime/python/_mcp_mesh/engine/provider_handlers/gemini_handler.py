"""
Gemini/Google provider handler.

Optimized for Gemini models (Gemini 3 Flash, Gemini 3 Pro, Gemini 2.0 Flash, etc.)
using Google's best practices for tool calling and structured output.

Features:
- Mixed structured output strategy based on tool presence:
  - STRICT mode (response_format) when NO tools are present
  - HINT mode (prompt-based JSON hints) when tools ARE present
- Native function calling support
- Support for Gemini 2.x and 3.x models
- Large context windows (up to 2M tokens)

Note:
- Gemini 3 + response_format + tools causes non-deterministic infinite tool loops,
  so we avoid response_format when tools are present and use HINT mode instead.
- STRICT mode (response_format) is only used for tool-free requests.

Reference:
- https://docs.litellm.ai/docs/providers/gemini
- https://ai.google.dev/gemini-api/docs
"""

import json
import logging
import os
from typing import Any, Optional

from pydantic import BaseModel

from ._handler_context import (
    clear_pending_output_schema,
    get_pending_output_schema,
    set_pending_output_schema,
)
from .base_provider_handler import (
    BaseProviderHandler,
    has_media_params,
    make_schema_strict,
    normalize_output_mode_override,
    render_dispatch_status_log,
    sanitize_schema_for_structured_output,
)

OUTPUT_MODE_TEXT = "text"
OUTPUT_MODE_STRICT = "strict"
OUTPUT_MODE_HINT = "hint"

logger = logging.getLogger(__name__)


def _gemini_native_structured_tools_enabled() -> bool:
    """Read the ``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS`` kill-switch.

    DEFAULT ON (RFC #1100 follow-up). The Gemini-3 server-enforced
    ``response_json_schema`` + tools path is now the default for qualifying
    requests; this env var is an opt-OUT kill-switch. Returns False only when
    explicitly set to ``0/false/no/off`` (case-insensitive); unset or any
    other value → enabled (True). The resolver still gates on model major
    version (>=3), google-genai >= 1.22, and tool presence, so gemini-2.x,
    an older SDK, or a no-tools request silently keeps the prior behavior
    (PROSE_HINT for tools / RESPONSE_FORMAT_STRICT for no-tools) even with
    the default-on flag. Set ``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0`` to
    revert qualifying requests to the pre-#1102 PROSE_HINT path.
    """
    return os.environ.get(
        "MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS", ""
    ).strip().lower() not in ("0", "false", "no", "off")


# Internal marker stamped on ``model_params`` when the gated
# ``response_json_schema`` path is active. The ``gemini_native`` adapter reads
# it to emit ``config["response_json_schema"]`` (the Gemini-3 strict primitive)
# instead of the ``response_schema`` translation. ``_mesh_``-prefixed so the
# native adapter's unsupported-kwarg WARN filter skips it and it is never
# forwarded to the SDK as a literal kwarg.
RESPONSE_JSON_SCHEMA_MARKER = "_mesh_gemini_response_json_schema"


# One-time guard so the dispatch-status DEBUG log fires exactly once per
# process. Mirrors ``_logged_fallback_once`` in gemini_native. The
# registry caches a singleton handler per vendor
# (``ProviderHandlerRegistry._instances``), so an instance-level flag would
# already dedupe across requests — we keep the state at module level so the
# dedupe survives even if the singleton is ever rebuilt, and to match the
# native-client modules' module-level fallback flag.
_DISPATCH_STATUS_LOGGED = False


def is_dispatch_status_logged() -> bool:
    """Return True once the one-time dispatch-status log has fired.

    Exposed so ``has_native()`` can skip the call frame for
    ``_log_dispatch_status_once`` on every dispatch decision after the
    first — the function dedupes internally, but on the hot path
    avoiding the call entirely is cheaper. Mirrors ``is_fallback_logged``
    on the native-client modules.
    """
    return _DISPATCH_STATUS_LOGGED


def _gemini_sdk_version() -> str:
    """Probe the installed google-genai SDK version for the dispatch-status log."""
    try:
        import google.genai as genai
        return getattr(genai, "__version__", "<unknown>")
    except Exception:
        return "<import-failed>"


def _log_dispatch_status_once() -> None:
    """Log the resolved native-dispatch status once per process at DEBUG level.

    Designed so users running with ``meshctl ... --debug`` can confirm whether
    a Gemini provider agent is using the native google-genai SDK or falling
    back to LiteLLM. Fires on first call only; subsequent invocations are
    no-ops.

    The rendered text is delegated to the shared base helper but the latch +
    logger stay module-local so the DEBUG record is attributed to this module
    and tests can re-arm the once-guard.
    """
    global _DISPATCH_STATUS_LOGGED
    if _DISPATCH_STATUS_LOGGED:
        return
    _DISPATCH_STATUS_LOGGED = True

    from _mcp_mesh.engine.native_clients import gemini_native

    render_dispatch_status_log(
        logger,
        vendor_label="Gemini",
        sdk_display="google-genai",
        install_extra="gemini",
        native_module=gemini_native,
        version_probe=_gemini_sdk_version,
    )


class GeminiHandler(BaseProviderHandler):
    """
    Provider handler for Google Gemini models.

    Gemini Characteristics:
    - Mixed structured output strategy:
      - STRICT mode (response_format) when NO tools are present
      - HINT mode (prompt-based JSON hints) when tools ARE present
    - Gemini 3 + response_format + tools causes non-deterministic infinite tool loops,
      so we avoid combining them.
    - Native function calling support
    - Large context windows (1M-2M tokens)
    - Multimodal support (text, images, video, audio)
    - Works well with concise, focused prompts

    Supported Models (via LiteLLM):
    - gemini/gemini-3-flash-preview (reasoning support)
    - gemini/gemini-3-pro-preview (advanced reasoning)
    - gemini/gemini-2.5-flash (fast, efficient)
    - gemini/gemini-2.0-flash-lite (fastest, most efficient)
    - gemini/gemini-1.5-pro (high capability)
    - gemini/gemini-1.5-flash (balanced)

    Reference:
    https://docs.litellm.ai/docs/providers/gemini
    """

    def __init__(self):
        """Initialize Gemini handler.

        Pending output-schema state lives in ``_handler_context`` ContextVars
        rather than instance fields, because handlers are cached as
        singletons in ``ProviderHandlerRegistry`` and instance state would
        race across concurrent async requests.
        """
        super().__init__(vendor="gemini")

    def determine_output_mode(self, output_type, override_mode=None):
        """Determine output mode for Gemini.

        Gemini 3 supports native response_format with tools.
        Uses STRICT mode (response_format) for all schema types.
        TEXT mode for string return types.
        """
        if override_mode:
            return override_mode
        if output_type is str:
            return OUTPUT_MODE_TEXT
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            return OUTPUT_MODE_STRICT
        return OUTPUT_MODE_STRICT

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        output_type: type,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare request parameters for Gemini API via LiteLLM.

        Gemini Strategy:
        - Use native response_format with strict schema (Gemini 3+)
        - Store schema for HINT fallback in format_system_prompt
        - Skip structured output for str return types (text mode)

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Return type (str or Pydantic model)
            **kwargs: Additional model parameters

        Returns:
            Dictionary of parameters for litellm.completion()
        """
        # Gemini doesn't support parallel_tool_calls API param
        kwargs.pop("parallel_tool_calls", None)

        # Configured model id is passed by the agent for resolver symmetry with
        # the other handlers. Popped here so it does not flow into
        # request_params (model is stamped separately downstream). Captured for
        # the resolver's Gemini-major gate (gated response_json_schema path).
        configured_model = kwargs.pop("model", None)

        # Build base request
        request_params = {
            "messages": messages,
            **kwargs,  # Pass through temperature, max_tokens, etc.
        }

        # Add tools if provided
        # LiteLLM will convert OpenAI tool format to Gemini's function_declarations
        if tools:
            request_params["tools"] = tools

        # Skip structured output for str return type (text mode)
        if output_type is str:
            clear_pending_output_schema()
            return request_params

        # Only store schema for Pydantic models
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema = output_type.model_json_schema()
            schema = sanitize_schema_for_structured_output(schema)

            # Store for HINT mode in format_system_prompt (always needed as fallback)
            set_pending_output_schema(schema, output_type.__name__)

            # Centralized mode selection (RFC #1100 Phase 1). The resolver
            # decides: BaseModel + no tools → RESPONSE_FORMAT_STRICT
            # (response_schema); BaseModel + tools → PROSE_HINT (response_format
            # skipped because Gemini 3 + response_format + tools causes
            # non-deterministic infinite tool loops).
            from .capabilities import StructuredOutputMode, resolve_capabilities

            caps = resolve_capabilities(
                self.vendor,
                configured_model,
                output_is_basemodel=True,
                has_tools=bool(tools),
                gemini_native_structured_tools=(
                    _gemini_native_structured_tools_enabled()
                ),
            )

            if caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT:
                strict_schema = make_schema_strict(schema, add_all_required=True)
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_type.__name__,
                        "schema": strict_schema,
                        "strict": True,
                    },
                }
                logger.debug(
                    "Gemini: Using response_format with strict schema for '%s' (no tools)",
                    output_type.__name__,
                )
            elif caps.structured_output == StructuredOutputMode.RESPONSE_JSON_SCHEMA:
                # DEFAULT ON for Gemini-3+ with tools (RFC #1100 follow-up):
                # server-enforced structured output WITH tools via
                # ``response_json_schema``. Stamp the marker + carry the strict
                # schema in ``response_format`` (the adapter reads it but emits
                # ``response_json_schema``, NOT the legacy ``response_schema``
                # translation). Tools stay intact. Set the kill-switch
                # MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0 to revert to HINT.
                strict_schema = make_schema_strict(schema, add_all_required=True)
                request_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_type.__name__,
                        "schema": strict_schema,
                        "strict": True,
                    },
                }
                request_params[RESPONSE_JSON_SCHEMA_MARKER] = True
                logger.info(
                    "Gemini: response_json_schema + tools for '%s' "
                    "(default-on for Gemini-3+; kill-switch: "
                    "MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0 to disable)",
                    output_type.__name__,
                )
            else:
                logger.debug(
                    "Gemini: Using HINT mode for '%s' (tools present, response_format skipped)",
                    output_type.__name__,
                )
        else:
            clear_pending_output_schema()

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: list[dict[str, Any]] | None,
        output_type: type,
    ) -> str:
        """
        Format system prompt for Gemini with structured output support.

        Delegates to Rust core for prompt construction.

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt optimized for Gemini
        """
        import mcp_mesh_core

        # Use pending schema if set (from apply_structured_output or prepare_request).
        # State lives in a per-async-context ContextVar to avoid races under
        # singleton handler caching.
        output_schema, output_type_name = get_pending_output_schema()

        if output_schema is None:
            if output_type is str:
                # No schema and str return type — text mode
                is_string = True
                schema_json = None
                schema_name = None
            elif isinstance(output_type, type) and issubclass(output_type, BaseModel):
                is_string = False
                output_schema = sanitize_schema_for_structured_output(
                    output_type.model_json_schema()
                )
                output_type_name = output_type.__name__
                schema_json = json.dumps(output_schema)
                schema_name = output_type_name
            else:
                is_string = False
                schema_json = None
                schema_name = None
        else:
            is_string = False
            schema_json = json.dumps(output_schema)
            schema_name = output_type_name

        # Determine mode: strict when no tools, hint when tools present
        determined_mode = self.determine_output_mode(output_type)
        if determined_mode == "strict" and tool_schemas:
            determined_mode = "hint"

        return mcp_mesh_core.format_system_prompt_py(
            "gemini",
            base_prompt,
            bool(tool_schemas),
            has_media_params(tool_schemas),
            schema_json,
            schema_name,
            determined_mode if not (is_string and output_schema is None) else "text",
        )

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return Gemini-specific capabilities.

        Returns:
            Capability flags for Gemini
        """
        return {
            "native_tool_calling": True,
            "structured_output": True,  # Via native response_format (Gemini 3+)
            "streaming": True,
            "vision": True,
            "json_mode": True,  # Native JSON mode via response_format
            "large_context": True,
        }

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: str | None,
        model_params: dict[str, Any],
        *,
        streaming: bool = False,
        model: str | None = None,
        output_mode: str | None = None,
    ) -> dict[str, Any]:
        """
        Apply Gemini-specific structured output for mesh delegation.

        Uses HINT mode (prompt injection) — mesh delegation always involves
        tools, and Gemini 3 + response_format + tools causes infinite tool
        loops, so we cannot use server-side schema enforcement. The agentic
        loop in mesh.helpers validates the final response against the schema
        on every iteration; if it fails to parse, the loop falls back to a
        bounded-timeout response_format retry (with tools stripped — the
        fallback path is safe vs. the infinite-loop constraint).

        The ``streaming`` kwarg is accepted for API symmetry with the other
        vendor handlers; Gemini is HINT-only here regardless, so the flag is
        a no-op.

        DEFAULT-ON EXCEPTION (RFC #1100 follow-up): when the resolver confirms
        Gemini-3+ with google-genai >= 1.22 (and the
        ``MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0`` kill-switch is NOT set),
        this stamps a ``response_json_schema`` marker + the strict schema (as a
        ``response_format`` carrier) and KEEPS tools — letting the native
        adapter emit Gemini's stricter server-side primitive instead of HINT.
        With the kill-switch set, the resolver returns PROSE_HINT and the path
        below is byte-identical to the pre-#1102 default (HINT injected,
        response_format popped).

        OUTPUT_MODE OVERRIDE (finding #6): a valid consumer ``output_mode`` fully
        replaces the resolver-based auto-selection:

        - ``"strict"`` → server-enforced ``response_json_schema`` when the model
          / SDK qualify (Gemini-3+, google-genai >= 1.22); otherwise Gemini
          cannot enforce a schema alongside tools without tripping the
          ``response_schema`` + tools infinite-loop bug, so it falls back to its
          safe default (HINT) with a warning.
        - ``"hint"``   → prose HINT (the resolver's default for tools).
        - ``"text"``   → no schema enforcement (no response_format, no HINT).

        Invalid override → ignored (warning) + auto-selection.
        """
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)
        normalized = normalize_output_mode_override(
            output_mode, vendor_label="Gemini", handler_logger=logger
        )

        if normalized == "text":
            # No schema enforcement: emit plain text. Clear any pending schema
            # state and drop response_format so neither the HINT path nor the
            # native primitive is engaged.
            clear_pending_output_schema()
            model_params.pop("response_format", None)
            model_params.pop(RESPONSE_JSON_SCHEMA_MARKER, None)
            logger.info(
                "Gemini TEXT mode for '%s' (output_mode='text' override; "
                "no schema enforcement)",
                output_type_name or "Response",
            )
            return model_params

        # Mode selection (RFC #1100 follow-up). DEFAULT ON: when the model /
        # SDK qualify (Gemini-3+, google-genai >= 1.22), the resolver returns
        # RESPONSE_JSON_SCHEMA and we take the server-enforced branch. The
        # kill-switch MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0 forces
        # PROSE_HINT, so the HINT block below runs exactly as the pre-#1102
        # default. Non-qualifying requests (gemini-2.x, older SDK) also stay
        # on PROSE_HINT regardless of the flag.
        from .capabilities import StructuredOutputMode, resolve_capabilities

        caps = resolve_capabilities(
            self.vendor,
            model,
            output_is_basemodel=True,
            has_tools=True,  # mesh delegation always attaches tools
            gemini_native_structured_tools=(
                _gemini_native_structured_tools_enabled()
            ),
        )

        # Override resolution. "strict" demands the native server-enforced
        # primitive; "hint" demands prose HINT. When no override is set the
        # resolver's auto decision stands (no regression).
        if normalized == "strict":
            if caps.structured_output != StructuredOutputMode.RESPONSE_JSON_SCHEMA:
                # Gemini cannot safely enforce a schema alongside tools unless
                # the Gemini-3 ``response_json_schema`` primitive is available;
                # the legacy ``response_schema`` + tools combo infinite-loops.
                # Fall back to the safe default (HINT) with a warning rather
                # than hard-failing the request.
                logger.warning(
                    "Gemini: output_mode='strict' requested for '%s' but the "
                    "model/SDK do not support server-enforced response_json_schema "
                    "with tools (requires Gemini-3+ and google-genai >= 1.22); "
                    "falling back to HINT mode.",
                    output_type_name or "Response",
                )
                effective_mode = StructuredOutputMode.PROSE_HINT
            else:
                effective_mode = StructuredOutputMode.RESPONSE_JSON_SCHEMA
        elif normalized == "hint":
            effective_mode = StructuredOutputMode.PROSE_HINT
        else:
            effective_mode = caps.structured_output

        if effective_mode == StructuredOutputMode.RESPONSE_JSON_SCHEMA:
            # Server-enforced structured output WITH tools. Do NOT set
            # _mesh_hint_mode, do NOT pop response_format. Stamp the marker and
            # carry the strict schema in response_format (the adapter reads it
            # but emits ``response_json_schema``, NOT the legacy
            # ``response_schema`` translation documented to infinite-loop with
            # tools). Tools are left untouched in model_params.
            strict_schema = make_schema_strict(
                sanitized_schema, add_all_required=True
            )
            model_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_type_name or "Response",
                    "schema": strict_schema,
                    "strict": True,
                },
            }
            model_params[RESPONSE_JSON_SCHEMA_MARKER] = True
            logger.info(
                "Gemini response_json_schema + tools for '%s' "
                "(mesh delegation; default-on for Gemini-3+ server-enforced, "
                "tools intact; kill-switch: "
                "MCP_MESH_GEMINI_NATIVE_STRUCTURED_TOOLS=0 to disable)",
                output_type_name or "Response",
            )
            return model_params

        # Store for format_system_prompt (per-async-context to avoid races
        # across concurrent requests sharing this singleton handler). This
        # Gemini-only side effect feeds the ``format_system_prompt`` ContextVar
        # path and MUST stay at the call site (not in the shared base helper).
        set_pending_output_schema(sanitized_schema, output_type_name)

        # Inject HINT instructions into the first system message; synthesize
        # one if none exists. Without this, the _mesh_hint_* flags would be set
        # but the model would never see the schema, every response would fail
        # validation, and the fallback timeout would fire on every request.
        # ``support_content_blocks=False`` keeps Gemini's string-only concat
        # (no post-prompt-cache content-block list shape, unlike Claude).
        # The shared base helper also stamps the _mesh_hint_* sentinels and
        # pops response_format (defense-in-depth — never set it on the HINT
        # path; would re-trigger the Gemini 3 + response_format + tools
        # infinite tool-loop bug).
        self.apply_prose_hint(
            model_params,
            sanitized_schema,
            output_type_name,
            support_content_blocks=False,
            logger=logger,
        )

        logger.info(
            "Gemini HINT mode for '%s' (mesh delegation, schema in prompt; "
            "loop will fall back to response_format if parse fails)",
            output_type_name or "Response",
        )
        return model_params

    # ------------------------------------------------------------------
    # Native Gemini SDK dispatch (issue #834, PR 3)
    # ------------------------------------------------------------------
    # Default ON when the google-genai SDK is importable. Set
    # ``MCP_MESH_NATIVE_LLM=0`` (or false/no/off) to force the LiteLLM
    # fallback path. In normal installs the google-genai SDK is a base dep,
    # so the missing-SDK branch should never trigger — kept for symmetry
    # with the Anthropic / OpenAI handlers and to guard against custom
    # installs that strip the SDK.
    #
    # HINT-mode preservation: ``prepare_request`` already decides
    # response_format vs HINT (the existing Gemini API infinite-tool-loop
    # workaround for ``response_format + tools``). The native adapter
    # forwards whatever the handler hands it — no behavioral change.
    #
    # ``has_native()`` / ``complete()`` / ``complete_stream()`` are inherited
    # from BaseProviderHandler, driven by the one-line ``_native_module()`` hook
    # below (plus label/version for the dispatch-status log).

    def _native_module(self):
        # Lazy import inside the method so module import does not fail when the
        # SDK is absent; this mirrors what the call sites do.
        from _mcp_mesh.engine.native_clients import gemini_native

        return gemini_native

    def _native_label(self) -> str:
        return "Gemini"

    def _log_dispatch_status(self) -> None:
        # Skip the call entirely once the log has fired — the function dedupes
        # internally, but avoiding the call frame on the hot path is cheaper.
        if not is_dispatch_status_logged():
            _log_dispatch_status_once()
