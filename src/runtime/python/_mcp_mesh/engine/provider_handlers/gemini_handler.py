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
    sanitize_schema_for_structured_output,
)

OUTPUT_MODE_TEXT = "text"
OUTPUT_MODE_STRICT = "strict"
OUTPUT_MODE_HINT = "hint"

logger = logging.getLogger(__name__)


# One-time guard so the dispatch-status DEBUG log fires exactly once per
# process. Mirrors ``_logged_fallback_once`` in gemini_native — we
# deliberately keep the state at module level (not on the handler instance)
# because mesh constructs a fresh handler per request in some paths.
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


def _log_dispatch_status_once() -> None:
    """Log the resolved native-dispatch status once per process at DEBUG level.

    Designed so users running with ``meshctl ... --debug`` can confirm whether
    a Gemini provider agent is using the native google-genai SDK or falling
    back to LiteLLM. Fires on first call only; subsequent invocations are
    no-ops.
    """
    global _DISPATCH_STATUS_LOGGED
    if _DISPATCH_STATUS_LOGGED:
        return
    _DISPATCH_STATUS_LOGGED = True

    env_value = os.getenv("MCP_MESH_NATIVE_LLM", "").strip().lower()

    if env_value in ("0", "false", "no", "off"):
        logger.debug(
            "Gemini native dispatch: disabled "
            "(MCP_MESH_NATIVE_LLM=%s explicitly set; using LiteLLM)",
            env_value,
        )
        return

    from _mcp_mesh.engine.native_clients import gemini_native

    if gemini_native.is_available():
        try:
            import google.genai as genai
            version = getattr(genai, "__version__", "<unknown>")
        except Exception:
            version = "<import-failed>"
        logger.debug(
            "Gemini native dispatch: enabled (google-genai SDK %s)",
            version,
        )
    else:
        logger.debug(
            "Gemini native dispatch: disabled "
            "(google-genai SDK not installed; install mcp-mesh[gemini] to enable)"
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
    - gemini/gemini-2.0-flash (fast, efficient)
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

            # Only use response_format when NO tools present
            # Gemini 3 + response_format + tools causes non-deterministic infinite tool loops
            if not tools:
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
    ) -> dict[str, Any]:
        """
        Apply Gemini-specific structured output for mesh delegation.

        Uses HINT mode (prompt injection) because mesh delegation always involves
        tools, and Gemini 3 + response_format + tools causes infinite tool loops.
        """
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)

        # Store for format_system_prompt (per-async-context to avoid races
        # across concurrent requests sharing this singleton handler).
        set_pending_output_schema(sanitized_schema, output_type_name)

        # Inject HINT instructions into system messages
        # (mesh delegation always has tools, so we can't use response_format)
        messages = model_params.get("messages", [])
        for msg in messages:
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                # Build hint instructions
                hint_text = "\n\nOUTPUT FORMAT:\n"
                hint_text += "Your FINAL response must be ONLY valid JSON (no markdown, no code blocks) with this exact structure:\n"
                properties = sanitized_schema.get("properties", {})
                hint_text += self.build_json_example(properties) + "\n\n"
                hint_text += "Return ONLY the JSON object with actual values. Do not include the schema definition, markdown formatting, or code blocks."

                msg["content"] = base_content + hint_text
                break

        logger.info(
            "Gemini hint mode for '%s' (mesh delegation, schema in prompt)",
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

    def has_native(self) -> bool:
        """Native dispatch is enabled by default when the google-genai SDK is
        importable. Set ``MCP_MESH_NATIVE_LLM=0`` (or ``false``/``no``/``off``)
        to disable and force the LiteLLM fallback path. Setting the flag to
        ``1``/``true``/``yes``/``on`` is accepted as an explicit-enable
        (same behavior as the default).
        """
        # Emit the one-time dispatch-status DEBUG log. Lazy here (vs. at
        # module/handler init) so it fires when the first dispatch decision
        # is actually made — the most useful signal for ``--debug`` runs.
        # Skip the call entirely once the log has fired — the function
        # dedupes internally, but avoiding the call frame on the hot path
        # is cheaper still.
        if not is_dispatch_status_logged():
            _log_dispatch_status_once()

        flag = os.environ.get("MCP_MESH_NATIVE_LLM", "").strip().lower()
        # Explicit opt-out wins over SDK availability.
        if flag in ("0", "false", "no", "off"):
            return False

        # Lazy import inside the function so module import does not fail
        # when the SDK is absent; this mirrors what the call sites do.
        from _mcp_mesh.engine.native_clients import gemini_native

        if not gemini_native.is_available():
            # Skip the log call entirely once it has already fired — the
            # function dedupes internally, but on the no-native hot path
            # avoiding the call frame altogether is cheaper still.
            if not gemini_native.is_fallback_logged():
                gemini_native.log_fallback_once()
            return False

        return True

    async def complete(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ) -> Any:
        """Dispatch a buffered completion to the native Gemini SDK adapter."""
        from _mcp_mesh.engine.native_clients import gemini_native

        return await gemini_native.complete(
            request_params,
            model=model,
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )

    async def complete_stream(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ):
        """Streaming completion via the native Gemini SDK.

        Note: this method is ``async def`` but ``return``s (without
        awaiting) the async generator from
        ``gemini_native.complete_stream``. Callers ``await`` the handler
        call (which resolves the coroutine to the AG), then
        ``async for chunk in stream_iter:`` to consume. Mirrors the
        dispatch contract used in mesh/helpers.py and matches the
        ClaudeHandler / OpenAIHandler patterns.
        """
        from _mcp_mesh.engine.native_clients import gemini_native

        return gemini_native.complete_stream(
            request_params,
            model=model,
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )
