"""
Base provider handler interface for vendor-specific LLM behavior.

This module defines the abstract base class for provider-specific handlers
that customize how different LLM vendors (Claude, OpenAI, Gemini, etc.) are called.
"""

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import mcp_mesh_core
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ============================================================================
# Shared HINT-fallback timeout resolution
# ============================================================================
#
# All HINT-mode handlers (Claude, Gemini, future vendors) read the same
# operator-tunable knob for the bounded response_format-retry timeout. The
# canonical env var is ``MCP_MESH_HINT_FALLBACK_TIMEOUT`` (vendor-agnostic).
# ``MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT`` is preserved as a back-compat
# alias with a one-time runtime deprecation warning, so existing operator
# configs keep working but new docs only teach the canonical form.
#
# Precedence: canonical wins over alias if both set. Alias-only fires the
# deprecation warning once per process.

_DEFAULT_HINT_FALLBACK_TIMEOUT = 90

_NEW_HINT_TIMEOUT_ENV = "MCP_MESH_HINT_FALLBACK_TIMEOUT"
_LEGACY_HINT_TIMEOUT_ENV = "MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT"

_legacy_hint_timeout_deprecation_logged = False
_legacy_hint_timeout_lock = threading.Lock()


def _warn_legacy_hint_timeout_once() -> None:
    """Emit the legacy-env-var deprecation warning exactly once per process."""
    global _legacy_hint_timeout_deprecation_logged
    with _legacy_hint_timeout_lock:
        if _legacy_hint_timeout_deprecation_logged:
            return
        _legacy_hint_timeout_deprecation_logged = True
    logger.warning(
        "%s is deprecated; use %s instead "
        "(vendor-agnostic — applies to all HINT-mode handlers).",
        _LEGACY_HINT_TIMEOUT_ENV,
        _NEW_HINT_TIMEOUT_ENV,
    )


def resolve_hint_fallback_timeout(default: int = _DEFAULT_HINT_FALLBACK_TIMEOUT) -> int:
    """Resolve the HINT-mode → response_format bounded-retry timeout (seconds).

    Reads ``MCP_MESH_HINT_FALLBACK_TIMEOUT`` first; falls back to the legacy
    ``MCP_MESH_CLAUDE_HINT_FALLBACK_TIMEOUT`` (with a one-time deprecation
    warning) if the canonical var is unset; falls back to ``default`` if
    neither is set. Fails open on malformed values (logs WARN, returns default).
    """
    raw = os.environ.get(_NEW_HINT_TIMEOUT_ENV)
    legacy_raw = os.environ.get(_LEGACY_HINT_TIMEOUT_ENV)
    if raw is None and legacy_raw is not None:
        _warn_legacy_hint_timeout_once()
        raw = legacy_raw
        source = _LEGACY_HINT_TIMEOUT_ENV
    else:
        if legacy_raw is not None:
            # Both set — canonical wins; still warn about the legacy var so
            # operators know it's now ignored on this host.
            _warn_legacy_hint_timeout_once()
        source = _NEW_HINT_TIMEOUT_ENV

    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "%s=%r is not an integer; using default %ss",
            source, raw, default,
        )
        return default
    if value <= 0:
        logger.warning(
            "%s=%r must be positive; using default %ss",
            source, raw, default,
        )
        return default
    return value


def _reset_legacy_hint_timeout_dedupe() -> None:
    """For tests — drop the once-per-process deprecation-warning latch."""
    global _legacy_hint_timeout_deprecation_logged
    with _legacy_hint_timeout_lock:
        _legacy_hint_timeout_deprecation_logged = False


# ============================================================================
# Shared native-dispatch status logging (issue #834)
# ============================================================================
#
# Each handler module owns a module-level ``_DISPATCH_STATUS_LOGGED`` latch and
# a thin ``_log_dispatch_status_once()`` wrapper that delegates here, passing
# its own logger + vendor labels. The state and the logger stay per-module so:
#   - tests can flip ``<module>._DISPATCH_STATUS_LOGGED`` to re-observe the log,
#   - the DEBUG record is emitted under the handler module's logger name
#     (``...claude_handler`` / ``...openai_handler`` / ``...gemini_handler``),
#   - the latch dedupes independently per vendor (Claude logging once does not
#     suppress OpenAI's log).
# The rendered message text is byte-identical to the original per-vendor logs.


def render_dispatch_status_log(
    module_logger: logging.Logger,
    *,
    vendor_label: str,
    sdk_display: str,
    install_extra: str,
    native_module: Any,
    version_probe: Callable[[], str],
) -> None:
    """Emit the once-per-process native-dispatch status DEBUG log.

    ``module_logger`` is the calling handler module's logger so the record is
    attributed to that module. ``vendor_label`` is the display name ("Claude"/
    "OpenAI"/"Gemini"); ``sdk_display`` is the SDK name as it appears in the log
    ("anthropic"/"openai"/"google-genai"); ``install_extra`` is the pip extra
    ("anthropic"/"openai"/"gemini"); ``native_module`` exposes ``is_available()``;
    ``version_probe`` is a zero-arg callable returning the SDK version string.

    The caller is responsible for the once-per-process latch — this function
    always renders.
    """
    env_value = os.getenv("MCP_MESH_NATIVE_LLM", "").strip().lower()

    if env_value in ("0", "false", "no", "off"):
        module_logger.debug(
            "%s native dispatch: disabled "
            "(MCP_MESH_NATIVE_LLM=%s explicitly set; using LiteLLM)",
            vendor_label,
            env_value,
        )
        return

    if native_module.is_available():
        version = version_probe()
        module_logger.debug(
            "%s native dispatch: enabled (%s SDK %s)",
            vendor_label,
            sdk_display,
            version,
        )
    else:
        module_logger.debug(
            "%s native dispatch: disabled "
            "(%s SDK not installed; install mcp-mesh[%s] to enable)",
            vendor_label,
            sdk_display,
            install_extra,
        )


# ============================================================================
# Shared Media Detection
# ============================================================================


def has_media_params(tool_schemas: Optional[list[dict[str, Any]]]) -> bool:
    """
    Check if any tool schema contains x-media-type properties.

    Args:
        tool_schemas: List of OpenAI-format tool schemas

    Returns:
        True if at least one tool has a parameter with x-media-type
    """
    if not tool_schemas:
        return False
    for tool_schema in tool_schemas:
        if mcp_mesh_core.detect_media_params_py(json.dumps(tool_schema)):
            return True
    return False


# ============================================================================
# Shared structured-output override validation (finding #6)
# ============================================================================

_VALID_OUTPUT_MODES = ("strict", "hint", "text")


def normalize_output_mode_override(
    output_mode: Optional[str],
    *,
    vendor_label: str,
    handler_logger: logging.Logger,
) -> Optional[str]:
    """Validate a consumer-supplied ``output_mode`` override.

    Returns the override lower-cased when it is one of ``strict`` / ``hint`` /
    ``text``. Returns ``None`` when the override is unset (auto-selection) OR
    when it is an invalid value — in the invalid case a one-line WARNING is
    emitted (per finding #6: invalid → ignore + auto + log a warning) so the
    caller transparently falls back to its per-vendor auto path.
    """
    if output_mode is None:
        return None
    normalized = str(output_mode).strip().lower()
    if normalized in _VALID_OUTPUT_MODES:
        return normalized
    handler_logger.warning(
        "%s: ignoring invalid output_mode override %r "
        "(expected one of %s); falling back to auto-selection.",
        vendor_label,
        output_mode,
        ", ".join(_VALID_OUTPUT_MODES),
    )
    return None


# ============================================================================
# Shared Schema Utilities
# ============================================================================


def make_schema_strict(
    schema: dict[str, Any],
    add_all_required: bool = True,
) -> dict[str, Any]:
    """
    Make a JSON schema strict for structured output.

    Delegates to Rust core. Adds additionalProperties: false to all object
    types and optionally ensures 'required' includes all property keys.

    Args:
        schema: JSON schema to make strict
        add_all_required: If True, set 'required' to include ALL property keys.
                         OpenAI and Gemini require this; Claude does not.
                         Default: True

    Returns:
        New schema with strict constraints (original not mutated)
    """
    result_json = mcp_mesh_core.make_schema_strict_py(
        json.dumps(schema), add_all_required
    )
    return json.loads(result_json)


def is_simple_schema(schema: dict[str, Any]) -> bool:
    """
    Check if a JSON schema is simple enough for hint mode.

    Delegates to Rust core. Simple schema criteria:
    - Less than 5 fields
    - All fields are basic types (str, int, float, bool, list)
    - No nested Pydantic models ($ref or nested objects with properties)

    Args:
        schema: JSON schema dict

    Returns:
        True if schema is simple, False otherwise
    """
    return mcp_mesh_core.is_simple_schema_py(json.dumps(schema))


def sanitize_schema_for_structured_output(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize a JSON schema by removing validation keywords unsupported by LLM APIs.

    Delegates to Rust core. Removes keywords like minimum, maximum, pattern, etc.
    that are not supported by LLM structured output APIs.

    Args:
        schema: JSON schema dict (will not be mutated)

    Returns:
        New schema with unsupported validation keywords removed
    """
    result_json = mcp_mesh_core.sanitize_schema_py(json.dumps(schema))
    return json.loads(result_json)


# ============================================================================
# Base Provider Handler
# ============================================================================


class BaseProviderHandler(ABC):
    """
    Abstract base class for provider-specific LLM handlers.

    Each vendor (Claude, OpenAI, Gemini, etc.) can have its own handler
    that customizes request preparation, system prompt formatting, and
    response parsing to work optimally with that vendor's API.

    Handler Selection:
        The ProviderHandlerRegistry selects handlers based on the 'vendor'
        field from the LLM provider registration (extracted via LiteLLM).

    Extensibility:
        New handlers can be added by:
        1. Subclassing BaseProviderHandler
        2. Implementing required methods
        3. Registering in ProviderHandlerRegistry
        4. Optionally: Adding as Python entry point for auto-discovery
    """

    def __init__(self, vendor: str):
        """
        Initialize provider handler.

        Args:
            vendor: Vendor name (e.g., "anthropic", "openai", "google")
        """
        self.vendor = vendor

    @classmethod
    def prepare_strict_schema(cls, output_type) -> dict:
        """Prepare a strict JSON schema from a Pydantic output type."""
        schema = output_type.model_json_schema()
        schema = sanitize_schema_for_structured_output(schema)
        schema = make_schema_strict(schema, add_all_required=True)
        return schema

    @abstractmethod
    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        output_type: type[BaseModel],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare vendor-specific request parameters.

        This method allows customization of the request sent to the LLM provider.
        For example:
        - OpenAI: Add response_format parameter for structured output
        - Claude: Use native tool calling format
        - Gemini: Add generation config

        Args:
            messages: List of message dicts (role, content)
            tools: Optional list of tool schemas (OpenAI format)
            output_type: Pydantic model for expected response
            **kwargs: Additional model parameters

        Returns:
            Dictionary of parameters to pass to litellm.completion()
            Must include at minimum: messages, tools (if provided)
            May include vendor-specific params like response_format, temperature, etc.
        """
        pass

    @abstractmethod
    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[list[dict[str, Any]]],
        output_type: type[BaseModel],
    ) -> str:
        """
        Format system prompt for vendor-specific requirements.

        Different vendors have different best practices for system prompts:
        - Claude: Prefers detailed instructions, handles XML well
        - OpenAI: Structured output mode makes JSON instructions optional
        - Gemini: System instructions separate from messages

        Args:
            base_prompt: Base system prompt (from template or config)
            tool_schemas: Optional list of tool schemas (if tools available)
            output_type: Pydantic model for response validation

        Returns:
            Formatted system prompt string optimized for this vendor
        """
        pass

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return vendor-specific capability flags.

        Override this to indicate which features the vendor supports:
        - native_tool_calling: Vendor has native function calling
        - structured_output: Vendor supports structured output (response_format)
        - streaming: Vendor supports streaming responses
        - vision: Vendor supports image inputs
        - json_mode: Vendor has JSON response mode

        Returns:
            Dictionary of capability flags
        """
        return {
            "native_tool_calling": True,
            "structured_output": False,
            "streaming": False,
            "vision": False,
            "json_mode": False,
        }

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
        Apply vendor-specific structured output handling to model params.

        This is used by LLM providers (via mesh) when they receive an output_schema
        from a consumer. Each vendor can customize how structured output is enforced.

        Default behavior: Apply response_format with strict schema.
        Override in subclasses for vendor-specific behavior (e.g., Claude hint mode).

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type (e.g., "AnalysisResult")
            model_params: Current model parameters dict (will be modified)
            streaming: When True, the call site is the streaming dispatch path.
                Vendors that have a synthetic-tool injection mode (e.g. Claude)
                use this to fall back to HINT mode for streaming — a single
                forced tool call doesn't actually stream as text chunks, while
                HINT (schema-in-prompt) flows naturally through the stream.
                Default False preserves the buffered behavior for all existing
                callers.
            model: Effective LiteLLM-style model id (e.g.
                ``anthropic/claude-sonnet-4-6``). Used by handlers that
                model-gate their structured-output strategy (e.g. Claude's
                ``output_config`` branch). Default None preserves backward
                compatibility — handlers that ignore the model are unaffected.
            output_mode: Consumer-supplied structured-output mode override
                ("strict" / "hint" / "text"). When set and valid it replaces the
                handler's per-vendor auto-selection; an invalid value is ignored
                (auto-selection runs) with a warning. Default None preserves the
                auto behavior. The base implementation ignores this argument —
                vendor handlers that honor the override do so in their own
                ``apply_structured_output``.

        Returns:
            Modified model_params with structured output settings applied
        """
        # Sanitize schema first to remove unsupported validation keywords
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
        return model_params

    @staticmethod
    def build_json_example(properties: dict) -> str:
        """Build a human-readable JSON example string from schema properties.

        Generates a JSON-like block with example values based on property types
        and optional description comments. Used by handlers that inject schema
        hints into the system prompt (e.g., Gemini HINT mode).

        Args:
            properties: Schema properties dict (prop_name -> prop_schema)

        Returns:
            Multi-line string resembling a JSON object with example values
        """
        if not properties:
            return "{}"

        parts = []
        prop_items = list(properties.items())
        for i, (prop_name, prop_schema) in enumerate(prop_items):
            prop_type = prop_schema.get("type", "string")
            prop_desc = prop_schema.get("description", "")

            if prop_type == "string":
                example_value = f'"<your {prop_name} here>"'
            elif prop_type in ("number", "integer"):
                example_value = "0"
            elif prop_type == "array":
                example_value = '["item1", "item2"]'
            elif prop_type == "boolean":
                example_value = "true"
            elif prop_type == "object":
                example_value = "{}"
            else:
                example_value = "..."

            comma = "," if i < len(prop_items) - 1 else ""
            if prop_desc:
                parts.append(f'  "{prop_name}": {example_value}{comma}  // {prop_desc}')
            else:
                parts.append(f'  "{prop_name}": {example_value}{comma}')

        return "{\n" + "\n".join(parts) + "\n}"

    def _build_hint_text(self, sanitized_schema: dict[str, Any]) -> str:
        """Build the ``OUTPUT FORMAT:`` HINT block for ``apply_structured_output``.

        Returned text starts with leading blank lines so it can be appended
        directly to existing system message content. Callers that synthesize
        a fresh system message should ``.strip()`` the result.

        Shared verbatim by Claude and Gemini HINT modes — the rendered text is
        byte-identical for both vendors.
        """
        hint_text = "\n\nOUTPUT FORMAT:\n"
        hint_text += (
            "Your FINAL response must be ONLY valid JSON (no markdown, "
            "no code blocks) with this exact structure:\n"
        )
        properties = sanitized_schema.get("properties", {})
        hint_text += self.build_json_example(properties) + "\n\n"
        hint_text += (
            "Return ONLY the JSON object with actual values. Do not "
            "include the schema definition, markdown formatting, or "
            "code blocks."
        )
        return hint_text

    def apply_prose_hint(
        self,
        model_params: dict[str, Any],
        sanitized_schema: dict[str, Any],
        output_type_name: Optional[str],
        *,
        support_content_blocks: bool,
        logger: Optional[logging.Logger] = None,
    ) -> dict[str, Any]:
        """Inject the OUTPUT FORMAT HINT block into the first system message.

        Shared HINT-mode mechanics for the prompt-injection vendors (Claude,
        Gemini): append the hint to the first system message (synthesizing one
        if none exists), stamp the ``_mesh_hint_*`` sentinels read by the
        agentic loop, and pop ``response_format`` (defense-in-depth — the HINT
        path must never set it).

        ``support_content_blocks``:
            True  — tolerate a content-block list on the system message
                    (post-prompt-cache, Claude): a string concatenates; a list
                    gets a NEW text block appended; an unknown shape is coerced
                    to string with a DEBUG log.
            False — string-only concatenation (Gemini): ``content + hint_text``.

        ``logger``:
            Optional per-vendor module logger so the HINT-injection DEBUG
            records are attributed to the calling handler's module
            (``...claude_handler`` / ``...gemini_handler``) rather than this
            base module. Defaults to the base module logger when not supplied.

        Vendor-specific side effects (e.g. Gemini's ``set_pending_output_schema``)
        and the per-vendor INFO log stay at the call site — this method only
        performs the shared inject/synthesize/stamp/pop work.
        """
        log = logger if logger is not None else globals()["logger"]
        messages = model_params.get("messages", [])
        hint_text = self._build_hint_text(sanitized_schema)
        hint_block_inserted = False
        for msg in messages:
            if msg.get("role") == "system":
                base_content = msg.get("content", "")
                if support_content_blocks:
                    # Tolerate string OR content-block list (post-prompt-cache).
                    # A string concatenates; a list gets a NEW text block
                    # appended so the original blocks' cache_control is preserved.
                    if isinstance(base_content, str):
                        msg["content"] = base_content + hint_text
                    elif isinstance(base_content, list):
                        msg["content"] = list(base_content) + [
                            {"type": "text", "text": hint_text}
                        ]
                    else:
                        # Unknown content shape — defensive coerce to string so
                        # the model still sees the schema. Log so the unexpected
                        # shape surfaces in debugging.
                        log.debug(
                            "%s HINT injection: unexpected system content "
                            "type %s; coercing to string",
                            self._native_label(),
                            type(base_content).__name__,
                        )
                        msg["content"] = str(base_content) + hint_text
                else:
                    msg["content"] = base_content + hint_text
                hint_block_inserted = True
                break

        if not hint_block_inserted:
            # No system message found — synthesize one containing just the
            # HINT block. Without this, the _mesh_hint_* flags below would
            # still be set but the model would never see the schema, every
            # response would fail validation, and the fallback timeout would
            # fire on every request.
            messages.insert(0, {"role": "system", "content": hint_text.strip()})
            log.debug(
                "%s HINT mode for '%s': no system message found, "
                "synthesized one with HINT block",
                self._native_label(),
                output_type_name or "Response",
            )
            # Keep model_params["messages"] in sync — messages may be a
            # fresh list reference if the caller passed an empty/missing list.
            model_params["messages"] = messages

        # Internal flags read by the agentic loop. Prefixed with "_mesh_" so
        # the loop strips them before calling LiteLLM (these are NOT API params).
        fallback_timeout = resolve_hint_fallback_timeout()
        model_params["_mesh_hint_mode"] = True
        model_params["_mesh_hint_schema"] = sanitized_schema
        model_params["_mesh_hint_fallback_timeout"] = fallback_timeout
        model_params["_mesh_hint_output_type_name"] = output_type_name or "Response"

        # Defense-in-depth: never set response_format on the HINT path.
        model_params.pop("response_format", None)

        return model_params

    # ------------------------------------------------------------------
    # Native SDK dispatch (issue #834)
    # ------------------------------------------------------------------
    # Native dispatch is driven by ``_native_module()``: a subclass that ships
    # a native vendor SDK adapter overrides it (plus ``_native_label()``) to
    # return the imported native module. The base
    # ``has_native()`` / ``complete()`` / ``complete_stream()`` then operate
    # against that module's uniform surface (``is_available()``,
    # ``is_fallback_logged()``, ``log_fallback_once()``, ``complete()``,
    # ``complete_stream()``). The base default returns ``None`` so the buffered /
    # streaming call sites in mesh.helpers transparently keep using LiteLLM for
    # vendors that have not migrated yet.
    #
    # Native dispatch is enabled by default; the ``MCP_MESH_NATIVE_LLM=0`` env
    # flag (also false/no/off) is the explicit opt-out and wins over SDK
    # availability.

    def _native_module(self):
        """Return the imported native-SDK adapter module, or None.

        Base default: None — ``has_native()`` stays False and the native
        ``complete*`` paths raise NotImplementedError. Subclasses that ship a
        native adapter override this with a one-line lazy import (so the SDK is
        not imported at module load).
        """
        return None

    def _native_label(self) -> str:
        """Display label for the vendor in the dispatch-status DEBUG log.

        Subclasses override (e.g. "Claude" / "OpenAI" / "Gemini").
        """
        return self.vendor

    def _log_dispatch_status(self) -> None:
        """Emit the once-per-process native-dispatch status DEBUG log.

        Subclasses with a native adapter override this to delegate to their
        module-level once-latch (so tests can re-arm it and the record is
        attributed to the handler module's logger). Base default: no-op.
        """
        return

    def has_native(self) -> bool:
        """Return True if this handler can dispatch via a native vendor SDK.

        Driven by ``_native_module()``: returns False when the subclass has not
        migrated (module is None). For migrated handlers, honors
        ``MCP_MESH_NATIVE_LLM`` in {0,false,no,off} as an explicit opt-out that
        wins over SDK availability, and returns False (with a one-time fallback
        log) when the SDK is not importable.
        """
        native = self._native_module()
        if native is None:
            return False

        # Emit the one-time dispatch-status DEBUG log. Lazy here (vs. at
        # module/handler init) so it fires when the first dispatch decision
        # is actually made — the most useful signal for ``--debug`` runs.
        self._log_dispatch_status()

        flag = os.environ.get("MCP_MESH_NATIVE_LLM", "").strip().lower()
        # Explicit opt-out wins over SDK availability.
        if flag in ("0", "false", "no", "off"):
            return False

        if not native.is_available():
            # Skip the log call entirely once it has already fired — the
            # function dedupes internally, but on the no-native hot path
            # avoiding the call frame altogether is cheaper still.
            if not native.is_fallback_logged():
                native.log_fallback_once()
            return False

        return True

    async def complete(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ) -> Any:
        """Run a buffered completion via the vendor's native SDK.

        Dispatches to ``_native_module().complete(...)``. Subclasses with a
        native adapter (``_native_module()`` not None) inherit this directly;
        the base raises NotImplementedError when no native module is wired so
        the default contract is preserved.
        """
        native = self._native_module()
        if native is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not implement native complete()"
            )
        return await native.complete(
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
        """Stream a completion via the vendor's native SDK.

        ``async def`` but ``return``s (without awaiting) the async generator
        from ``_native_module().complete_stream(...)``. Callers ``await`` this
        handler call (which resolves the coroutine to the AG), then
        ``async for chunk in stream_iter:`` to consume. Subclasses with a
        native adapter inherit this directly; the base raises
        NotImplementedError when no native module is wired.
        """
        native = self._native_module()
        if native is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} does not implement native complete_stream()"
            )
        return native.complete_stream(
            request_params,
            model=model,
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )

    def __repr__(self) -> str:
        """String representation of handler."""
        return f"{self.__class__.__name__}(vendor='{self.vendor}')"
