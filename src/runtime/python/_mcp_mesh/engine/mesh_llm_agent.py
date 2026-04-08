"""
MeshLlmAgent proxy implementation.

Provides automatic agentic loop for LLM-based agents with tool integration.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel

from .llm_config import LLMConfig
from .llm_errors import (
    LLMAPIError,
    MaxIterationsError,
    ResponseParseError,
    ToolExecutionError,
)
from .provider_handlers import ProviderHandlerRegistry
from .response_parser import ResponseParser
from .tool_executor import ToolExecutor
from .tool_schema_builder import ToolSchemaBuilder

# Import Jinja2 for template rendering
try:
    from jinja2 import Environment, FileSystemLoader, Template, TemplateSyntaxError
except ImportError:
    Environment = None
    FileSystemLoader = None
    Template = None
    TemplateSyntaxError = None

# Import litellm at module level for mocking in tests
try:
    from litellm import completion
except ImportError:
    completion = None

logger = logging.getLogger(__name__)

# Sentinel value to distinguish "context not provided" from "explicitly None/empty"
_CONTEXT_NOT_PROVIDED = object()


# ---------------------------------------------------------------------------
# Mock LiteLLM response types for mesh-delegated provider responses
# ---------------------------------------------------------------------------
# These lightweight classes mimic the litellm.completion() response shape so
# that the agentic loop can treat direct-LiteLLM and mesh-delegated responses
# identically.  Extracted to module level for reusability and testability.


class _MockFunction:
    """Function namespace with .name and .arguments attributes."""

    __slots__ = ("name", "arguments")

    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _MockToolCall:
    """Mock tool call object matching LiteLLM structure."""

    __slots__ = ("id", "type", "function")

    def __init__(self, tc_dict: dict):
        self.id = tc_dict["id"]
        self.type = tc_dict["type"]
        self.function = _MockFunction(
            name=tc_dict["function"]["name"],
            arguments=tc_dict["function"]["arguments"],
        )


class _MockMessage:
    """Mock message matching LiteLLM ModelResponse.choices[].message."""

    __slots__ = ("content", "role", "tool_calls")

    def __init__(self, message_dict: dict):
        self.content = message_dict.get("content")
        self.role = message_dict.get("role", "assistant")
        self.tool_calls = None
        if "tool_calls" in message_dict and message_dict["tool_calls"]:
            self.tool_calls = [_MockToolCall(tc) for tc in message_dict["tool_calls"]]

    def model_dump(self) -> dict:
        dump: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            dump["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in self.tool_calls
            ]
        return dump


class _MockChoice:
    """Mock choice object matching LiteLLM ModelResponse.choices[]."""

    __slots__ = ("message", "finish_reason")

    def __init__(self, message: _MockMessage):
        self.message = message
        self.finish_reason = "stop"


class _MockUsage:
    """Mock usage object for token tracking (Issue #311)."""

    __slots__ = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self, usage_dict: dict):
        self.prompt_tokens = usage_dict.get("prompt_tokens", 0)
        self.completion_tokens = usage_dict.get("completion_tokens", 0)
        self.total_tokens = self.prompt_tokens + self.completion_tokens


class _MockResponse:
    """Mock LiteLLM ModelResponse for mesh-delegated provider results."""

    __slots__ = ("choices", "usage", "model")

    def __init__(self, message_dict: dict):
        self.choices = [_MockChoice(_MockMessage(message_dict))]
        mesh_usage = message_dict.get("_mesh_usage")
        self.usage = _MockUsage(mesh_usage) if mesh_usage else None
        self.model = mesh_usage.get("model") if mesh_usage else None


class MeshLlmAgent:
    """
    LLM agent proxy with automatic agentic loop.

    Handles the complete flow:
    1. Format tools for LLM provider (via LiteLLM)
    2. Call LLM API with tools
    3. If tool_use: execute via MCP proxies, loop back to LLM
    4. If final response: parse into output type (Pydantic model)
    5. Return typed response
    """

    def __init__(
        self,
        config: LLMConfig,
        filtered_tools: list[dict[str, Any]],
        output_type: type[BaseModel] | type[str],
        tool_proxies: Optional[dict[str, Any]] = None,
        template_path: Optional[str] = None,
        context_value: Optional[Any] = None,
        provider_proxy: Optional[Any] = None,
        vendor: Optional[str] = None,
        default_model_params: Optional[dict[str, Any]] = None,
        parallel_tool_calls: bool = False,
    ):
        """
        Initialize MeshLlmAgent proxy.

        Args:
            config: LLM configuration (provider, model, api_key, etc.)
            filtered_tools: List of tool metadata from registry (for schema building)
            output_type: Pydantic BaseModel for response validation, or str for plain text
            tool_proxies: Optional map of function_name -> proxy for tool execution
            template_path: Optional path to Jinja2 template file for system prompt
            context_value: Optional context for template rendering (MeshContextModel, dict, or None)
            provider_proxy: Optional pre-resolved provider proxy for mesh delegation
            vendor: Optional vendor name for handler selection (e.g., "anthropic", "openai")
            default_model_params: Optional dict of default LLM parameters from decorator
                                  (e.g., max_tokens, temperature). These are merged with
                                  call-time kwargs, with call-time taking precedence.
        """
        self.config = config
        self.provider = config.provider
        self.model = config.model
        self.api_key = config.api_key
        self.tools_metadata = filtered_tools  # Tool metadata for schema building
        self.tool_proxies = tool_proxies or {}  # Proxies for execution
        self.max_iterations = config.max_iterations
        self.output_type = output_type
        self.system_prompt = config.system_prompt  # Public attribute for tests
        self.output_mode = config.output_mode  # Output mode override (strict/hint/text)
        self._iteration_count = 0
        self._default_model_params = (
            default_model_params or {}
        )  # Decorator-level defaults
        self._parallel_tool_calls = parallel_tool_calls
        if self._parallel_tool_calls:
            logger.info(
                "🔀 parallel tool calls enabled — tools will execute concurrently via asyncio.gather()"
            )

        # Detect if using mesh delegation (provider is dict)
        self._is_mesh_delegated = isinstance(self.provider, dict)
        self._mesh_provider_proxy = provider_proxy  # Pre-resolved by heartbeat

        # Template rendering support (Phase 3)
        self._template_path = template_path
        self._context_value = context_value
        self._template: Optional[Any] = None  # Cached template object

        # Load template if path provided
        if template_path:
            self._template = self._load_template(template_path)

        # Build tool schemas for LLM (OpenAI format used by LiteLLM)
        self._tool_schemas = ToolSchemaBuilder.build_schemas(self.tools_metadata)

        # Phase 2: Get provider-specific handler
        # This enables vendor-optimized behavior (e.g., OpenAI response_format)
        self._provider_handler = ProviderHandlerRegistry.get_handler(vendor)
        logger.debug(
            f"🎯 Using provider handler: {self._provider_handler} for vendor: {vendor}"
        )

        # Note: Tool calling instructions are injected in the system prompt
        # construction (see __call__ method), not cached here.

        # Only generate JSON schema for Pydantic models, not for str return type
        if self.output_type is not str and hasattr(
            self.output_type, "model_json_schema"
        ):
            schema = self.output_type.model_json_schema()
            schema_str = json.dumps(schema, indent=2)
            self._cached_json_instructions = (
                f"\n\nIMPORTANT: You must return your final response as valid JSON matching this schema:\n"
                f"{schema_str}\n\nReturn ONLY the JSON object, no additional text."
            )
        else:
            # str return type - no JSON schema needed
            self._cached_json_instructions = ""

        logger.debug(
            f"🤖 MeshLlmAgent initialized: provider={config.provider}, model={config.model}, "
            f"tools={len(filtered_tools)}, max_iterations={config.max_iterations}, handler={self._provider_handler}"
        )

    def set_system_prompt(self, prompt: str) -> None:
        """Override the system prompt at runtime."""
        self.system_prompt = prompt
        logger.debug(f"🔧 System prompt updated: {prompt[:50]}...")

    def _load_template(self, template_path: str) -> Any:
        """
        Load Jinja2 template from file path.

        Args:
            template_path: Path to template file (relative or absolute)

        Returns:
            Jinja2 Template object

        Raises:
            FileNotFoundError: If template file not found
            TemplateSyntaxError: If template has syntax errors
            ImportError: If jinja2 not installed
        """
        if Environment is None:
            raise ImportError(
                "jinja2 is required for template rendering. Install with: pip install jinja2"
            )

        # Resolve template path
        path = Path(template_path)

        # If relative path, try to resolve it
        if not path.is_absolute():
            # Try relative to current working directory first
            if path.exists():
                template_file = path
            else:
                # If not found, raise error with helpful message
                raise FileNotFoundError(
                    f"Template file not found: {template_path}\n"
                    f"Tried: {path.absolute()}"
                )
        else:
            template_file = path
            if not template_file.exists():
                raise FileNotFoundError(f"Template file not found: {template_path}")

        # Load template using FileSystemLoader for better error messages
        template_dir = template_file.parent
        template_name = template_file.name

        env = Environment(loader=FileSystemLoader(str(template_dir)))

        try:
            template = env.get_template(template_name)
            logger.debug(f"📄 Loaded template: {template_path}")
            return template
        except Exception as e:
            # Re-raise with context
            logger.error(f"❌ Failed to load template {template_path}: {e}")
            raise

    def _prepare_context(self, context_value: Any) -> dict:
        """
        Prepare context for template rendering.

        Converts various context types to dict:
        - MeshContextModel -> model_dump()
        - dict -> use directly
        - None -> empty dict {}
        - Other types -> TypeError

        Args:
            context_value: Context value to prepare

        Returns:
            Dictionary for template rendering

        Raises:
            TypeError: If context is invalid type
        """
        if context_value is None:
            return {}

        # Check if it's a MeshContextModel (has model_dump method)
        if hasattr(context_value, "model_dump") and callable(context_value.model_dump):
            return context_value.model_dump()

        # Check if it's a dict
        if isinstance(context_value, dict):
            return context_value

        # Invalid type
        raise TypeError(
            f"Invalid context type: {type(context_value).__name__}. "
            f"Expected MeshContextModel, dict, or None."
        )

    def _resolve_context(
        self,
        runtime_context: Union[dict, None, object],
        context_mode: Literal["replace", "append", "prepend"],
    ) -> dict:
        """
        Resolve effective context for template rendering.

        Merges auto-populated context (from decorator's context_param) with
        runtime context passed to __call__(), based on the context_mode.

        Args:
            runtime_context: Context passed at call time, or _CONTEXT_NOT_PROVIDED
            context_mode: How to merge contexts - "replace", "append", or "prepend"

        Returns:
            Resolved context dictionary for template rendering

        Behavior:
            - If runtime_context is _CONTEXT_NOT_PROVIDED: use auto-populated context
            - If context_mode is "replace": use runtime_context entirely
            - If context_mode is "append": auto_context | runtime_context (runtime wins)
            - If context_mode is "prepend": runtime_context | auto_context (auto wins)

        Note:
            Empty dict {} with "replace" mode explicitly clears context.
            Empty dict {} with "append"/"prepend" is a no-op (keeps auto context).
        """
        # Get auto-populated context from decorator
        auto_context = self._prepare_context(self._context_value)

        # If no runtime context provided, use auto-populated context unchanged
        if runtime_context is _CONTEXT_NOT_PROVIDED:
            return auto_context

        # Prepare runtime context (handles MeshContextModel, dict, None)
        runtime_dict = self._prepare_context(runtime_context)

        # Apply context_mode
        if context_mode == "replace":
            # Replace entirely with runtime context (even if empty)
            return runtime_dict
        elif context_mode == "prepend":
            # Runtime first, auto overwrites (auto wins on conflicts)
            return {**runtime_dict, **auto_context}
        else:  # "append" (default)
            # Auto first, runtime overwrites (runtime wins on conflicts)
            return {**auto_context, **runtime_dict}

    def _render_system_prompt(self, effective_context: Optional[dict] = None) -> str:
        """
        Render system prompt from template or return literal.

        If template_path was provided in __init__, renders template with context.
        If system_prompt was set via set_system_prompt(), uses that override.
        Otherwise, uses config.system_prompt as literal.

        Args:
            effective_context: Optional pre-resolved context dict for template rendering.
                               If None, uses auto-populated _context_value.

        Returns:
            Rendered system prompt string

        Raises:
            jinja2.UndefinedError: If required template variable missing
        """
        # If runtime override via set_system_prompt(), use that
        if self.system_prompt and self.system_prompt != self.config.system_prompt:
            return self.system_prompt

        # If template provided, render it
        if self._template is not None:
            # Use provided effective_context or fall back to auto-populated context
            context = (
                effective_context
                if effective_context is not None
                else self._prepare_context(self._context_value)
            )
            try:
                rendered = self._template.render(**context)
                logger.debug(
                    f"🎨 Rendered template with context: {list(context.keys())}"
                )
                return rendered
            except Exception as e:
                logger.error(f"❌ Template rendering error: {e}")
                raise

        # Otherwise, use literal system prompt from config
        return self.system_prompt or ""

    def _attach_mesh_meta(
        self,
        result: Any,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> Any:
        """
        Attach _mesh_meta to result object if possible.

        For Pydantic models and regular classes, attaches LlmMeta as _mesh_meta.
        For primitives (str, int, etc.) and frozen models, silently skips.

        Args:
            result: The parsed result object
            model: Model identifier used
            input_tokens: Total input tokens across all iterations
            output_tokens: Total output tokens across all iterations
            latency_ms: Total latency in milliseconds

        Returns:
            The result object (unchanged, but with _mesh_meta attached if possible)
        """
        from mesh.types import LlmMeta

        # Extract provider from model string (e.g., "anthropic/claude-3-5-haiku" -> "anthropic")
        provider = "unknown"
        if isinstance(model, str) and "/" in model:
            provider = model.split("/")[0]

        meta = LlmMeta(
            provider=provider,
            model=model or "unknown",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
        )

        # Try to attach _mesh_meta to result
        try:
            # This works for Pydantic models and most Python objects
            object.__setattr__(result, "_mesh_meta", meta)
            logger.debug(
                f"📊 Attached _mesh_meta: model={model}, "
                f"tokens={input_tokens}+{output_tokens}={input_tokens + output_tokens}, "
                f"latency={latency_ms:.1f}ms"
            )
        except (TypeError, AttributeError):
            # Primitives (str, int, etc.) and frozen objects don't support attribute assignment
            logger.debug(
                f"📊 Could not attach _mesh_meta to {type(result).__name__} "
                f"(tokens={input_tokens}+{output_tokens}, latency={latency_ms:.1f}ms)"
            )

        return result

    def _enrich_tools_with_endpoints(self) -> list[dict]:
        """Add _mesh_endpoint to tool schemas for provider-side execution.

        When mesh delegation is active, enriches each tool schema with the
        MCP endpoint URL of the agent that owns the tool. This allows the
        provider to execute tools directly via MCP proxies instead of
        returning tool_calls back to the consumer.

        Returns:
            List of enriched tool schemas with _mesh_endpoint on each function.
        """
        if not self._tool_schemas:
            return []
        enriched = []
        for tool in self._tool_schemas:
            func = tool.get("function", {})
            func_name = func.get("name", "")
            proxy = self.tool_proxies.get(func_name)
            if proxy and hasattr(proxy, "endpoint"):
                tool_copy = {
                    **tool,
                    "function": {**func, "_mesh_endpoint": proxy.endpoint},
                }
            else:
                tool_copy = {**tool, "function": dict(func)}
            enriched.append(tool_copy)
        return enriched

    async def _get_mesh_provider(self) -> Any:
        """
        Get the mesh provider proxy (already resolved during heartbeat).

        Returns:
            UnifiedMCPProxy for the mesh provider agent

        Raises:
            RuntimeError: If provider proxy not resolved
        """
        if self._mesh_provider_proxy is None:
            raise RuntimeError(
                f"Mesh provider not resolved. Provider filter: {self.provider}. "
                f"The provider should have been resolved during heartbeat. "
                f"Check that a matching provider is registered in the mesh."
            )

        return self._mesh_provider_proxy

    async def _call_mesh_provider(
        self, messages: list, tools: list | None = None, **kwargs
    ) -> Any:
        """
        Call mesh-delegated LLM provider agent.

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            **kwargs: Additional model parameters

        Returns:
            LiteLLM-compatible response object

        Raises:
            RuntimeError: If provider proxy not available or invocation fails
        """
        # Get the pre-resolved provider proxy
        provider_proxy = await self._get_mesh_provider()

        # Import MeshLlmRequest type
        from mesh.types import MeshLlmRequest

        # Build MeshLlmRequest
        request = MeshLlmRequest(
            messages=messages, tools=tools, model_params=kwargs if kwargs else None
        )

        logger.debug(
            f"📤 Delegating to mesh provider: {len(messages)} messages, {len(tools) if tools else 0} tools"
        )

        # Call provider's process_chat tool
        try:
            # provider_proxy is UnifiedMCPProxy, call it with request dict
            # Convert dataclass to dict for MCP call
            request_dict = {
                "messages": request.messages,
                "tools": request.tools,
                "model_params": request.model_params,
                "context": request.context,
                "request_id": request.request_id,
                "caller_agent": request.caller_agent,
            }

            result = await provider_proxy(request=request_dict)

            # Result is a message dict with content, role, and optionally tool_calls
            # Parse it to create LiteLLM-compatible response
            message_dict = result

            # Cross-runtime providers (Java, TypeScript) may return a plain string
            # instead of a message dict. Wrap it in the expected format.
            if isinstance(message_dict, str):
                logger.debug(
                    "Received string result from mesh provider, "
                    "wrapping in message dict format"
                )
                try:
                    parsed = json.loads(message_dict)
                    if isinstance(parsed, dict):
                        message_dict = parsed
                    else:
                        message_dict = {
                            "role": "assistant",
                            "content": message_dict,
                        }
                except (json.JSONDecodeError, TypeError):
                    message_dict = {
                        "role": "assistant",
                        "content": message_dict,
                    }

            logger.debug(
                f"📥 Received response from mesh provider: "
                f"content={(message_dict.get('content') or '')[:200]}..., "
                f"tool_calls={len(message_dict.get('tool_calls') or [])}"
            )

            return _MockResponse(message_dict)

        except Exception as e:
            logger.error(f"❌ Mesh provider call failed: {e}")
            raise RuntimeError(f"Mesh LLM provider invocation failed: {e}") from e

    async def _resolve_media_inputs(self, media: list) -> list[dict]:
        """Resolve media items to provider-native content blocks.

        Each item can be:
        - str: A media URI (file://, s3://, etc.) resolved via MediaStore.fetch()
        - tuple[bytes, str]: Raw (bytes_data, mime_type) pair

        Returns a list of content blocks formatted per media type:
        - Images: OpenAI-compatible image_url (LiteLLM converts for other providers)
        - PDFs: vendor-specific (Claude document block, text fallback for others)
        - Text files: text content block (all providers)

        Items that fail to resolve are logged and skipped.
        """
        import base64

        from _mcp_mesh.media.media_store import get_media_store
        from _mcp_mesh.media.resolver import (
            IMAGE_MIME_TYPES,
            PDF_MIME_TYPES,
            TEXT_MIME_TYPES,
            _format_for_openai,
            _format_pdf_for_claude,
            _format_pdf_for_openai,
            _format_text_content,
        )

        parts: list[dict] = []
        store = get_media_store()
        vendor_name = self._provider_handler.vendor

        for item in media:
            try:
                if isinstance(item, str):
                    data, mime_type = await store.fetch(item)
                elif isinstance(item, tuple) and len(item) == 2:
                    data, mime_type = item
                else:
                    logger.warning(
                        "Skipping unsupported media item type: %s", type(item)
                    )
                    continue

                if mime_type in IMAGE_MIME_TYPES:
                    b64 = base64.b64encode(data).decode("ascii")
                    parts.append(_format_for_openai(b64, mime_type))
                elif mime_type in PDF_MIME_TYPES:
                    b64 = base64.b64encode(data).decode("ascii")
                    if vendor_name in ("anthropic", "claude"):
                        parts.append(_format_pdf_for_claude(b64))
                    else:
                        parts.append(_format_pdf_for_openai(b64, "document.pdf"))
                elif mime_type in TEXT_MIME_TYPES or mime_type.startswith("text/"):
                    parts.append(_format_text_content(data, mime_type, "document"))
                else:
                    try:
                        text = data.decode("utf-8")
                        parts.append(
                            {
                                "type": "text",
                                "text": f"[File content ({mime_type})]\n{text[:50000]}",
                            }
                        )
                    except (UnicodeDecodeError, AttributeError):
                        parts.append(
                            {
                                "type": "text",
                                "text": f"[Unsupported media type: {mime_type}]",
                            }
                        )
            except Exception as exc:
                logger.error(
                    "Failed to resolve media item %s: %s",
                    item if isinstance(item, str) else "(bytes)",
                    exc,
                )

        return parts

    async def __call__(
        self,
        message: Union[str, list[dict[str, Any]]],
        *,
        media: Union[list, None] = None,
        context: Union[dict, None, object] = _CONTEXT_NOT_PROVIDED,
        context_mode: Literal["replace", "append", "prepend"] = "append",
        **kwargs,
    ) -> Any:
        """
        Execute automatic agentic loop and return typed response.

        Args:
            message: Either:
                - str: Single user message (will be wrapped in messages array)
                - List[Dict[str, Any]]: Full conversation history with messages
                  in format [{"role": "user|assistant|system", "content": "..."}]
            media: Optional list of media items to attach to the initial user message.
                Each item can be:
                - str: A media URI (file://, s3://, etc.) resolved via MediaStore
                - tuple[bytes, str]: Raw (bytes_data, mime_type) pair
                When provided, the user message content is converted to a multipart
                array with text + image_url blocks (OpenAI-compatible format).
            context: Optional runtime context for system prompt template rendering.
                     Can be dict, MeshContextModel, or None. If not provided,
                     uses the auto-populated context from decorator's context_param.
            context_mode: How to merge runtime context with auto-populated context:
                - "append" (default): auto_context | runtime_context (runtime wins on conflicts)
                - "prepend": runtime_context | auto_context (auto wins on conflicts)
                - "replace": use runtime_context entirely (ignores auto-populated)
            **kwargs: Additional arguments passed to LLM

        Returns:
            Parsed response matching output_type

        Raises:
            MaxIterationsError: If max iterations exceeded
            ToolExecutionError: If tool execution fails
            ValidationError: If response doesn't match output_type schema

        Examples:
            # Use auto-populated context (default behavior)
            result = await llm("What is the answer?")

            # Attach an image by URI
            result = await llm("Describe this image", media=["file:///tmp/photo.png"])

            # Attach raw bytes
            result = await llm("What is this?", media=[(png_bytes, "image/png")])

            # Multiple media items
            result = await llm("Compare these", media=["file:///a.png", "s3://bucket/b.jpg"])

            # Append extra context (runtime wins on key conflicts)
            result = await llm("What is the answer?", context={"extra": "info"})

            # Replace context entirely
            result = await llm("What is the answer?", context={"only": "this"}, context_mode="replace")
        """
        self._iteration_count = 0

        # Issue #311: Track timing and token usage for _mesh_meta
        start_time = time.perf_counter()
        total_input_tokens = 0
        total_output_tokens = 0
        effective_model = self.model  # Track actual model used

        # Check if litellm is available
        if completion is None:
            raise ImportError(
                "litellm is required for MeshLlmAgent. Install with: pip install litellm"
            )

        # Resolve effective context (merge auto-populated with runtime context)
        effective_context = self._resolve_context(context, context_mode)

        # Render base system prompt (from template or literal) with effective context
        base_system_prompt = self._render_system_prompt(effective_context)

        # Phase 2: Format system prompt
        if self._is_mesh_delegated:
            # Delegate path: Just use base prompt + basic tool instructions
            # Provider will add vendor-specific formatting
            system_content = base_system_prompt
            if self._tool_schemas:
                if self._parallel_tool_calls:
                    system_content += "\n\nYou have access to tools. You CAN and SHOULD call multiple tools simultaneously when the calls are independent."
                else:
                    system_content += "\n\nYou have access to tools. Use them when needed to gather information."
        else:
            # Direct path: Use vendor handler for vendor-specific optimizations
            system_content = self._provider_handler.format_system_prompt(
                base_prompt=base_system_prompt,
                tool_schemas=self._tool_schemas,
                output_type=self.output_type,
            )
            # Append parallel tool calling instruction for direct mode
            if self._parallel_tool_calls and self._tool_schemas:
                system_content += "\n\nYou CAN and SHOULD call multiple tools simultaneously when the calls are independent. Return all independent tool calls in a single response."

        # Debug: Log system prompt (truncated for privacy)
        logger.debug(
            f"📝 System prompt (formatted by {self._provider_handler}): {system_content[:200]}..."
        )

        # Resolve media inputs to image content blocks (if provided)
        media_parts: list[dict] = []
        if media:
            media_parts = await self._resolve_media_inputs(media)
            if media_parts:
                logger.info(f"Resolved {len(media_parts)} media items for user message")

        # Build messages array based on input type
        if isinstance(message, list):
            # Multi-turn conversation - use provided messages array
            messages = message.copy()

            # Only add/update system message if we have non-empty content
            # (Claude API rejects empty system messages - though decorator provides default)
            if system_content:
                if not messages or messages[0].get("role") != "system":
                    messages.insert(0, {"role": "system", "content": system_content})
                else:
                    # Replace existing system message with our constructed one
                    messages[0] = {"role": "system", "content": system_content}

            # If media provided, find the last user message and append media parts
            if media_parts:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        existing_content = messages[i].get("content", "")
                        if isinstance(existing_content, str):
                            # Convert text to multipart array
                            messages[i] = {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": existing_content},
                                    *media_parts,
                                ],
                            }
                        elif isinstance(existing_content, list):
                            # Already multipart — append media
                            messages[i] = {
                                "role": "user",
                                "content": existing_content + media_parts,
                            }
                        break

            # Log conversation history
            logger.info(
                f"🚀 Starting agentic loop with {len(messages)} messages in history"
            )
        else:
            # Single-turn - build messages array from string
            # Build user content: plain text or multipart with media
            if media_parts:
                user_content: Union[str, list] = [
                    {"type": "text", "text": message},
                    *media_parts,
                ]
            else:
                user_content = message

            # Only include system message if non-empty (Claude API rejects empty system messages)
            if system_content:
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ]
            else:
                # Fallback for edge case where system_content is explicitly empty
                messages = [
                    {"role": "user", "content": user_content},
                ]

            log_msg = message if isinstance(message, str) else str(message)
            logger.info(f"🚀 Starting agentic loop for message: {log_msg[:100]}...")

        # Agentic loop
        while self._iteration_count < self.max_iterations:
            self._iteration_count += 1
            logger.debug(
                f"🔄 Iteration {self._iteration_count}/{self.max_iterations}..."
            )

            try:
                # Call LLM (either direct LiteLLM or mesh-delegated)
                try:
                    # Merge decorator-level defaults with call-time kwargs
                    # Call-time kwargs take precedence over defaults
                    effective_kwargs = {**self._default_model_params, **kwargs}

                    # Pass parallel_tool_calls to the LLM API for providers that support it
                    # (e.g., OpenAI). Provider handlers that don't support it will strip it.
                    if self._parallel_tool_calls:
                        effective_kwargs["parallel_tool_calls"] = True

                    # Build kwargs with output_mode override if set
                    call_kwargs = (
                        {**effective_kwargs, "output_mode": self.output_mode}
                        if self.output_mode
                        else effective_kwargs
                    )

                    # Use provider handler to prepare vendor-specific request
                    # For mesh delegation, enrich tools with endpoint URLs
                    # so the provider can execute tools directly
                    effective_tools = (
                        self._enrich_tools_with_endpoints()
                        if self._is_mesh_delegated and self._tool_schemas
                        else (self._tool_schemas if self._tool_schemas else None)
                    )
                    request_params = self._provider_handler.prepare_request(
                        messages=messages,
                        tools=effective_tools if effective_tools else None,
                        output_type=self.output_type,
                        **call_kwargs,
                    )

                    if self._is_mesh_delegated:
                        # Mesh delegation: extract model_params to send to provider
                        # Exclude messages/tools (separate params), api_key (provider has it),
                        # and output_mode (only used locally by prepare_request)
                        model_params = {
                            k: v
                            for k, v in request_params.items()
                            if k
                            not in [
                                "messages",
                                "tools",
                                "api_key",
                                "output_mode",
                                "model",  # Model handled separately below
                            ]
                        }

                        # Issue #308: Include model override if explicitly set by consumer
                        # This allows consumer to request a specific model from the provider
                        # (e.g., use haiku instead of provider's default sonnet)
                        if self.model:
                            model_params["model"] = self.model

                        # Issue #459: Include output_schema for provider to apply vendor-specific handling
                        # (e.g., OpenAI needs response_format, not prompt-based JSON instructions)
                        if self.output_type is not str and hasattr(
                            self.output_type, "model_json_schema"
                        ):
                            model_params["output_schema"] = (
                                self.output_type.model_json_schema()
                            )
                            model_params["output_type_name"] = self.output_type.__name__

                        # Issue #713: Re-inject parallel_tool_calls for provider-side execution.
                        # Provider handlers strip this from request_params (e.g., Claude handler
                        # pops it since the Claude API doesn't accept it), but the provider's
                        # agentic loop needs it to decide parallel vs sequential execution.
                        if self._parallel_tool_calls:
                            model_params["parallel_tool_calls"] = True

                        logger.debug(
                            f"📤 Delegating to mesh provider with handler-prepared params: "
                            f"keys={list(model_params.keys())}"
                        )

                        response = await self._call_mesh_provider(
                            messages=messages,
                            tools=effective_tools if effective_tools else None,
                            **model_params,
                        )
                    else:
                        # Direct LiteLLM call: add model and API key
                        request_params["model"] = self.model
                        request_params["api_key"] = self.api_key

                        logger.debug(
                            f"📤 Calling LLM with handler-prepared params: "
                            f"keys={list(request_params.keys())}"
                        )

                        response = await asyncio.to_thread(completion, **request_params)
                except Exception as e:
                    # Any exception from completion call is an LLM API error
                    logger.error(f"❌ LLM API error: {e}")
                    raise LLMAPIError(
                        provider=str(self.provider),
                        model=self.model,
                        original_error=e,
                    ) from e

                # Issue #311: Extract token usage from response
                if hasattr(response, "usage") and response.usage:
                    usage = response.usage
                    total_input_tokens += getattr(usage, "prompt_tokens", 0) or 0
                    total_output_tokens += getattr(usage, "completion_tokens", 0) or 0

                # Issue #311: Track effective model (may differ from requested in mesh delegation)
                if hasattr(response, "model") and response.model:
                    effective_model = response.model

                # Publish token data to trace context for ExecutionTracer
                from _mcp_mesh.tracing.context import set_llm_metadata

                set_llm_metadata(
                    model=effective_model,
                    provider=str(self.provider) if self.provider else "",
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

                # Extract response content
                assistant_message = response.choices[0].message

                # Check if LLM wants to use tools
                if (
                    hasattr(assistant_message, "tool_calls")
                    and assistant_message.tool_calls
                ):
                    tool_calls = assistant_message.tool_calls
                    logger.info(f"🛠️  LLM requested {len(tool_calls)} tool calls")

                    # Add assistant message to history
                    messages.append(assistant_message.model_dump())

                    # Execute tool calls (parallel or sequential)
                    if self._parallel_tool_calls and len(tool_calls) > 1:
                        logger.info(
                            f"⚡ Executing {len(tool_calls)} tool calls in parallel"
                        )
                        tool_results = await self._execute_tool_calls_parallel(
                            tool_calls
                        )
                    else:
                        tool_results = await self._execute_tool_calls(tool_calls)

                    # Resolve resource_link items in tool results to
                    # provider-native multimodal content (e.g., base64 images)
                    tool_results = await self._resolve_media_in_tool_results(
                        tool_results
                    )

                    # Add tool results to messages
                    for tool_result in tool_results:
                        messages.append(tool_result)

                    # Continue loop to get final response
                    continue

                # No tool calls - this is the final response
                logger.debug("✅ Final response received from LLM")
                logger.debug(
                    f"📥 Raw LLM response: {assistant_message.content[:500]}..."
                )

                # Parse the response
                result = self._parse_response(assistant_message.content)

                # Issue #311: Calculate latency and attach _mesh_meta
                latency_ms = (time.perf_counter() - start_time) * 1000
                return self._attach_mesh_meta(
                    result=result,
                    model=effective_model,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    latency_ms=latency_ms,
                )

            except LLMAPIError:
                # Re-raise LLM API errors as-is
                raise
            except ToolExecutionError:
                # Re-raise tool execution errors as-is
                raise
            except ResponseParseError:
                # Re-raise response parse errors as-is
                raise

        # Max iterations exceeded
        logger.error(
            f"❌ Max iterations ({self.max_iterations}) exceeded without final response"
        )
        raise MaxIterationsError(
            iteration_count=self._iteration_count,
            max_allowed=self.max_iterations,
        )

    async def _execute_tool_calls(self, tool_calls: list[Any]) -> list[dict[str, Any]]:
        """
        Execute tool calls and return results.

        Delegates to ToolExecutor for actual execution logic.

        Args:
            tool_calls: List of tool call objects from LLM response

        Returns:
            List of tool result messages for LLM conversation

        Raises:
            ToolExecutionError: If tool execution fails
        """
        return await ToolExecutor.execute_calls(tool_calls, self.tool_proxies)

    async def _execute_tool_calls_parallel(
        self, tool_calls: list[Any]
    ) -> list[dict[str, Any]]:
        """Execute tool calls in parallel using asyncio.gather()."""
        import asyncio

        async def execute_single(tool_call):
            """Execute a single tool call, catching errors."""
            try:
                results = await ToolExecutor.execute_calls(
                    [tool_call], self.tool_proxies
                )
                return results[0] if results else None
            except Exception as e:
                logger.error(
                    f"❌ Parallel tool call failed for {tool_call.function.name}: {e}"
                )
                # Return error result so other tools aren't affected
                return {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps({"error": str(e)}),
                }

        results = await asyncio.gather(*[execute_single(tc) for tc in tool_calls])
        filtered = []
        for i, r in enumerate(results):
            if r is not None:
                filtered.append(r)
            else:
                logger.warning(
                    f"Parallel tool call {i} returned no result — substituting error"
                )
                filtered.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_calls[i].id,
                        "content": json.dumps({"error": "Tool returned no result"}),
                    }
                )
        return filtered

    async def _resolve_media_in_tool_results(
        self, tool_results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Resolve resource_link items in tool results to multimodal content.

        Scans each tool result message for resource_link content. When found,
        fetches the media from MediaStore and formats it as provider-native
        multimodal content (e.g., base64 image blocks).

        Args:
            tool_results: List of tool result message dicts (role=tool).

        Returns:
            Updated list with resource_links resolved to multimodal content
            where applicable. Non-resource_link results pass through unchanged.
        """
        from _mcp_mesh.media.resolver import _has_resource_link, resolve_resource_links

        vendor = self._provider_handler.vendor
        resolved = []

        for msg in tool_results:
            content = msg.get("content", "")

            # Content is a JSON string from ToolExecutor._format_tool_result
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, TypeError):
                    resolved.append(msg)
                    continue

                if _has_resource_link(parsed):
                    try:
                        parts = await resolve_resource_links(parsed, vendor)
                    except Exception as e:
                        logger.error(f"Media resolution failed for tool result: {e}")
                        parts = [
                            {
                                "type": "text",
                                "text": (
                                    json.dumps(parsed)
                                    if isinstance(parsed, dict)
                                    else str(parsed)
                                ),
                            }
                        ]
                    has_media = any(
                        p.get("type") in ("image", "image_url", "document")
                        for p in parts
                    )
                    if has_media:
                        resolved.append(
                            {
                                "role": msg["role"],
                                "tool_call_id": msg.get("tool_call_id", ""),
                                "content": parts,
                            }
                        )
                        logger.debug(
                            "Resolved resource_link in tool result to "
                            "%d multimodal parts (vendor=%s)",
                            len(parts),
                            vendor,
                        )
                        continue

            resolved.append(msg)

        return resolved

    def _parse_response(self, content: str) -> Any:
        """
        Parse LLM response into output type.

        For str return type, returns content directly without parsing.
        For Pydantic models, delegates to ResponseParser.

        Args:
            content: Response content from LLM

        Returns:
            Raw string (if output_type is str) or parsed Pydantic model instance

        Raises:
            ResponseParseError: If response doesn't match output_type schema or invalid JSON
        """
        # For str return type, return content directly without parsing
        if self.output_type is str:
            return content

        return ResponseParser.parse(content, self.output_type)
