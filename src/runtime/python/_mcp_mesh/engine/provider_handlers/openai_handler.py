"""
OpenAI provider handler.

Optimized for OpenAI models (GPT-4, GPT-4 Turbo, GPT-3.5-turbo)
using OpenAI's native structured output capabilities.
"""

import json
import logging
from typing import Any, Optional

import mcp_mesh_core
from pydantic import BaseModel

from .base_provider_handler import (
    BaseProviderHandler,
    has_media_params,
    make_schema_strict,
    normalize_output_mode_override,
    render_dispatch_status_log,
    sanitize_schema_for_structured_output,
)

logger = logging.getLogger(__name__)


# One-time guard so the dispatch-status DEBUG log fires exactly once per
# process. Mirrors ``_logged_fallback_once`` in openai_native. The
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


def _openai_sdk_version() -> str:
    """Probe the installed openai SDK version for the dispatch-status log."""
    try:
        import openai
        return getattr(openai, "__version__", "<unknown>")
    except Exception:
        return "<import-failed>"


def _log_dispatch_status_once() -> None:
    """Log the resolved native-dispatch status once per process at DEBUG level.

    Designed so users running with ``meshctl ... --debug`` can confirm whether
    an OpenAI provider agent is using the native openai SDK or falling back
    to LiteLLM. Fires on first call only; subsequent invocations are no-ops.

    The rendered text is delegated to the shared base helper but the latch +
    logger stay module-local so the DEBUG record is attributed to this module
    and tests can re-arm the once-guard.
    """
    global _DISPATCH_STATUS_LOGGED
    if _DISPATCH_STATUS_LOGGED:
        return
    _DISPATCH_STATUS_LOGGED = True

    from _mcp_mesh.engine.native_clients import openai_native

    render_dispatch_status_log(
        logger,
        vendor_label="OpenAI",
        sdk_display="openai",
        install_extra="openai",
        native_module=openai_native,
        version_probe=_openai_sdk_version,
    )


class OpenAIHandler(BaseProviderHandler):
    """
    Provider handler for OpenAI models.

    OpenAI Characteristics:
    - Native structured output via response_format parameter
    - Strict JSON schema enforcement
    - Built-in function calling
    - Works best with concise, focused prompts
    - response_format ensures valid JSON matching schema

    Key Difference from Claude:
    - Uses response_format instead of prompt-based JSON instructions
    - OpenAI API guarantees JSON schema compliance
    - More strict parsing, less tolerance for malformed JSON
    - Shorter system prompts work better

    Supported Models:
    - gpt-4-turbo-preview and later
    - gpt-4-0125-preview and later
    - gpt-3.5-turbo-0125 and later
    - All gpt-4o models

    Reference:
    https://platform.openai.com/docs/guides/structured-outputs
    """

    def __init__(self):
        """Initialize OpenAI handler."""
        super().__init__(vendor="openai")

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        output_type: type,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare request parameters for OpenAI API with structured output.

        OpenAI Strategy:
        - Use response_format parameter for guaranteed JSON schema compliance
        - This is the KEY difference from Claude handler
        - response_format.json_schema ensures the response matches output_type
        - Skip structured output for str return types (text mode)

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Return type (str or Pydantic model)
            **kwargs: Additional model parameters

        Returns:
            Dictionary of parameters for litellm.completion() with response_format
        """
        # Build base request
        request_params = {
            "messages": messages,
            **kwargs,  # Pass through temperature, max_tokens, etc.
        }

        # Add tools if provided
        if tools:
            request_params["tools"] = tools

        # Centralized mode selection (RFC #1100). For OpenAI the resolver
        # reproduces the universal decision: str → TEXT (no response_format),
        # BaseModel → RESPONSE_FORMAT_STRICT. The response_format-building body
        # below is unchanged.
        from .capabilities import StructuredOutputMode, resolve_capabilities

        is_basemodel = isinstance(output_type, type) and issubclass(
            output_type, BaseModel
        )
        caps = resolve_capabilities(
            self.vendor, None, output_is_basemodel=is_basemodel
        )

        if caps.structured_output == StructuredOutputMode.RESPONSE_FORMAT_STRICT:
            # CRITICAL: Add response_format for structured output
            # This is what makes OpenAI construct responses according to schema
            # rather than relying on prompt instructions alone
            schema = self.prepare_strict_schema(output_type)

            # OpenAI structured output format
            # See: https://platform.openai.com/docs/guides/structured-outputs
            request_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_type.__name__,
                    "schema": schema,
                    "strict": True,  # Enforce schema compliance
                },
            }

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[list[dict[str, Any]]],
        output_type: type,
    ) -> str:
        """
        Format system prompt for OpenAI (concise approach).

        Delegates to Rust core for prompt construction.

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt optimized for OpenAI
        """
        # OpenAI uses strict mode (response_format handles output) for schemas, text for str
        is_string = output_type is str
        output_mode = "text" if is_string else "strict"

        schema_json = None
        schema_name = None
        if (
            not is_string
            and isinstance(output_type, type)
            and issubclass(output_type, BaseModel)
        ):
            schema_json = json.dumps(output_type.model_json_schema())
            schema_name = output_type.__name__

        return mcp_mesh_core.format_system_prompt_py(
            "openai",
            base_prompt,
            bool(tool_schemas),
            has_media_params(tool_schemas),
            schema_json,
            schema_name,
            output_mode,
        )

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: Optional[str],
        model_params: dict[str, Any],
        *,
        streaming: bool = False,
        model: Optional[str] = None,
        output_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Apply OpenAI structured output for mesh delegation.

        AUTO (output_mode unset/None): RESPONSE_FORMAT_STRICT — native
        ``response_format`` with ``strict: true`` (identical to the base
        behavior used before finding #6). This is the no-regression default.

        OVERRIDE (finding #6): when the consumer supplies a valid ``output_mode``
        it fully replaces auto-selection, mapping onto the same per-mode
        behaviors already used elsewhere:

        - ``"strict"`` → native ``response_format`` (same as AUTO).
        - ``"hint"``   → embed the schema in the system prompt (prose HINT) and
          drop ``response_format`` — the shared ``apply_prose_hint`` stamps the
          ``_mesh_hint_*`` sentinels the agentic loop already understands.
        - ``"text"``   → no schema enforcement (no ``response_format``, no HINT).

        Invalid override → ignored (warning logged) + AUTO.
        """
        normalized = normalize_output_mode_override(
            output_mode, vendor_label="OpenAI", handler_logger=logger
        )

        if normalized == "hint":
            sanitized_schema = sanitize_schema_for_structured_output(output_schema)
            self.apply_prose_hint(
                model_params,
                sanitized_schema,
                output_type_name,
                support_content_blocks=False,
                logger=logger,
            )
            logger.info(
                "OpenAI HINT mode for '%s' (output_mode='hint' override; "
                "schema in prompt, response_format dropped)",
                output_type_name or "Response",
            )
            return model_params

        if normalized == "text":
            # No schema enforcement: strip any response_format that a prior code
            # path may have set; emit plain text.
            model_params.pop("response_format", None)
            logger.info(
                "OpenAI TEXT mode for '%s' (output_mode='text' override; "
                "no schema enforcement)",
                output_type_name or "Response",
            )
            return model_params

        # normalized in ("strict", None) → native response_format (AUTO default).
        sanitized_schema = sanitize_schema_for_structured_output(output_schema)
        strict_schema = make_schema_strict(sanitized_schema, add_all_required=True)
        model_params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_type_name or "Response",
                "schema": strict_schema,
                "strict": True,
            },
        }
        if normalized == "strict":
            logger.info(
                "OpenAI STRICT mode for '%s' (output_mode='strict' override; "
                "native response_format)",
                output_type_name or "Response",
            )
        return model_params

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return OpenAI-specific capabilities.

        Returns:
            Capability flags for OpenAI
        """
        return {
            "native_tool_calling": True,  # OpenAI has native function calling
            "structured_output": True,  # ✅ Native response_format support!
            "streaming": True,  # Supports streaming
            "vision": True,  # GPT-4V and later support vision
            "json_mode": True,  # Has dedicated JSON mode via response_format
        }

    # ------------------------------------------------------------------
    # Native OpenAI SDK dispatch (issue #834, PR 2)
    # ------------------------------------------------------------------
    # Default ON when the openai SDK is importable. Set
    # ``MCP_MESH_NATIVE_LLM=0`` (or false/no/off) to force the LiteLLM
    # fallback path. In normal installs the openai SDK is a base dep, so
    # the missing-SDK branch should never trigger — kept for symmetry with
    # the Anthropic handler and to guard against custom installs that
    # strip the SDK.
    #
    # ``has_native()`` / ``complete()`` / ``complete_stream()`` are inherited
    # from BaseProviderHandler, driven by the one-line ``_native_module()`` hook
    # below (plus label/version for the dispatch-status log).

    def _native_module(self):
        # Lazy import inside the method so module import does not fail when the
        # SDK is absent; this mirrors what the call sites do.
        from _mcp_mesh.engine.native_clients import openai_native

        return openai_native

    def _native_label(self) -> str:
        return "OpenAI"

    def _log_dispatch_status(self) -> None:
        # Skip the call entirely once the log has fired — the function dedupes
        # internally, but avoiding the call frame on the hot path is cheaper.
        if not is_dispatch_status_logged():
            _log_dispatch_status_once()
