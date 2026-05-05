"""
OpenAI provider handler.

Optimized for OpenAI models (GPT-4, GPT-4 Turbo, GPT-3.5-turbo)
using OpenAI's native structured output capabilities.
"""

import json
import logging
import os
from typing import Any, Optional

import mcp_mesh_core
from pydantic import BaseModel

from .base_provider_handler import (
    BaseProviderHandler,
    has_media_params,
)

logger = logging.getLogger(__name__)


# One-time guard so the dispatch-status DEBUG log fires exactly once per
# process. Mirrors ``_logged_fallback_once`` in openai_native — we
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
    an OpenAI provider agent is using the native openai SDK or falling back
    to LiteLLM. Fires on first call only; subsequent invocations are no-ops.
    """
    global _DISPATCH_STATUS_LOGGED
    if _DISPATCH_STATUS_LOGGED:
        return
    _DISPATCH_STATUS_LOGGED = True

    env_value = os.getenv("MCP_MESH_NATIVE_LLM", "").strip().lower()

    if env_value in ("0", "false", "no", "off"):
        logger.debug(
            "OpenAI native dispatch: disabled "
            "(MCP_MESH_NATIVE_LLM=%s explicitly set; using LiteLLM)",
            env_value,
        )
        return

    from _mcp_mesh.engine.native_clients import openai_native

    if openai_native.is_available():
        try:
            import openai
            version = getattr(openai, "__version__", "<unknown>")
        except Exception:
            version = "<import-failed>"
        logger.debug(
            "OpenAI native dispatch: enabled (openai SDK %s)",
            version,
        )
    else:
        logger.debug(
            "OpenAI native dispatch: disabled "
            "(openai SDK not installed; install mcp-mesh[openai] to enable)"
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

        # Skip structured output for str return type (text mode)
        if output_type is str:
            return request_params

        # Only add response_format for Pydantic models
        if not (isinstance(output_type, type) and issubclass(output_type, BaseModel)):
            return request_params

        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
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

    def has_native(self) -> bool:
        """Native dispatch is enabled by default when the openai SDK is
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
        from _mcp_mesh.engine.native_clients import openai_native

        if not openai_native.is_available():
            # Skip the log call entirely once it has already fired — the
            # function dedupes internally, but on the no-native hot path
            # avoiding the call frame altogether is cheaper still.
            if not openai_native.is_fallback_logged():
                openai_native.log_fallback_once()
            return False

        return True

    async def complete(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ) -> Any:
        """Dispatch a buffered completion to the native OpenAI SDK adapter."""
        from _mcp_mesh.engine.native_clients import openai_native

        return await openai_native.complete(
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
        """Streaming completion via the native OpenAI SDK.

        Note: this method is ``async def`` but ``return``s (without
        awaiting) the async generator from
        ``openai_native.complete_stream``. Callers ``await`` the handler
        call (which resolves the coroutine to the AG), then
        ``async for chunk in stream_iter:`` to consume. Mirrors the
        dispatch contract used in mesh/helpers.py and matches the
        ClaudeHandler pattern.
        """
        from _mcp_mesh.engine.native_clients import openai_native

        return openai_native.complete_stream(
            request_params,
            model=model,
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )
