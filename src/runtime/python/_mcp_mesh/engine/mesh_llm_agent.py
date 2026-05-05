"""
MeshLlmAgent proxy implementation.

Provides automatic agentic loop for LLM-based agents with tool integration.
"""

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
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
    from litellm import acompletion, completion
except ImportError:
    completion = None
    acompletion = None

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

    async def _build_messages_for_run(
        self,
        message: Union[str, list[dict[str, Any]]],
        media: Union[list, None],
        context: Union[dict, None, object],
        context_mode: Literal["replace", "append", "prepend"],
    ) -> list[dict[str, Any]]:
        """Resolve context, render system prompt, and assemble the messages array.

        Shared by ``__call__`` and ``stream``: identical setup must produce
        the same conversation regardless of whether the final response is
        buffered or streamed.
        """
        effective_context = self._resolve_context(context, context_mode)
        base_system_prompt = self._render_system_prompt(effective_context)

        if self._is_mesh_delegated:
            system_content = base_system_prompt
            if self._tool_schemas:
                if self._parallel_tool_calls:
                    system_content += "\n\nYou have access to tools. You CAN and SHOULD call multiple tools simultaneously when the calls are independent."
                else:
                    system_content += "\n\nYou have access to tools. Use them when needed to gather information."
        else:
            system_content = self._provider_handler.format_system_prompt(
                base_prompt=base_system_prompt,
                tool_schemas=self._tool_schemas,
                output_type=self.output_type,
            )
            if self._parallel_tool_calls and self._tool_schemas:
                system_content += "\n\nYou CAN and SHOULD call multiple tools simultaneously when the calls are independent. Return all independent tool calls in a single response."

        logger.debug(
            f"📝 System prompt (formatted by {self._provider_handler}): {system_content[:200]}..."
        )

        media_parts: list[dict] = []
        if media:
            media_parts = await self._resolve_media_inputs(media)
            if media_parts:
                logger.info(f"Resolved {len(media_parts)} media items for user message")

        if isinstance(message, list):
            messages = message.copy()
            if system_content:
                if not messages or messages[0].get("role") != "system":
                    messages.insert(0, {"role": "system", "content": system_content})
                else:
                    messages[0] = {"role": "system", "content": system_content}
            if media_parts:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i].get("role") == "user":
                        existing_content = messages[i].get("content", "")
                        if isinstance(existing_content, str):
                            messages[i] = {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": existing_content},
                                    *media_parts,
                                ],
                            }
                        elif isinstance(existing_content, list):
                            messages[i] = {
                                "role": "user",
                                "content": existing_content + media_parts,
                            }
                        break
            logger.info(
                f"🚀 Starting agentic loop with {len(messages)} messages in history"
            )
        else:
            if media_parts:
                user_content: Union[str, list] = [
                    {"type": "text", "text": message},
                    *media_parts,
                ]
            else:
                user_content = message

            if system_content:
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ]
            else:
                messages = [
                    {"role": "user", "content": user_content},
                ]

            log_msg = message if isinstance(message, str) else str(message)
            logger.info(f"🚀 Starting agentic loop for message: {log_msg[:100]}...")

        return messages

    def _build_request_params(self, messages: list[dict[str, Any]], **kwargs) -> dict:
        """Run the provider handler over ``messages`` to produce LiteLLM-ready kwargs.

        Mirrors the ``__call__`` per-iteration request build; extracted so
        ``stream()`` can reuse it without duplicating provider-handler logic.
        """
        effective_kwargs = {**self._default_model_params, **kwargs}
        if self._parallel_tool_calls:
            effective_kwargs["parallel_tool_calls"] = True
        call_kwargs = (
            {**effective_kwargs, "output_mode": self.output_mode}
            if self.output_mode
            else effective_kwargs
        )
        effective_tools = (
            self._enrich_tools_with_endpoints()
            if self._is_mesh_delegated and self._tool_schemas
            else (self._tool_schemas if self._tool_schemas else None)
        )
        return self._provider_handler.prepare_request(
            messages=messages,
            tools=effective_tools if effective_tools else None,
            output_type=self.output_type,
            **call_kwargs,
        )

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

        messages = await self._build_messages_for_run(
            message, media, context, context_mode
        )

        # Import once before loop (avoid per-iteration import overhead)
        from _mcp_mesh.tracing.context import set_llm_metadata

        # Agentic loop
        while self._iteration_count < self.max_iterations:
            self._iteration_count += 1
            logger.debug(
                f"🔄 Iteration {self._iteration_count}/{self.max_iterations}..."
            )

            try:
                # Call LLM (either direct LiteLLM or mesh-delegated)
                try:
                    request_params = self._build_request_params(messages, **kwargs)
                    effective_tools = (
                        self._enrich_tools_with_endpoints()
                        if self._is_mesh_delegated and self._tool_schemas
                        else (self._tool_schemas if self._tool_schemas else None)
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

    @staticmethod
    def _merge_streamed_tool_calls(buffered: list[Any]) -> list[dict]:
        """Reassemble fragmented ``tool_calls`` deltas into complete tool calls.

        LiteLLM yields ``tool_calls`` across chunks: ``id``/``type``/``name``
        arrive once with ``index=N``, and JSON ``arguments`` accrue across
        subsequent chunks at the same index. We coalesce by index and drop
        any partial entries (defensive — providers very rarely truncate
        mid-stream, but the math still works).

        Gemini-only: deltas may carry a ``_thought_signature`` (bytes) — the
        opaque blob from Gemini 2.0+ thought-mode functionCall Parts that the
        API requires to be echoed back on the next-turn functionCall. Forward
        it onto the merged dict as ``_gemini_thought_signature`` (base64-
        encoded so JSON-shaped consumers can round-trip it). Other vendors
        don't set this attribute so the branch is a no-op for them.
        """
        import base64 as _base64

        merged: dict[int, dict[str, Any]] = {}
        for chunk in buffered:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            tcs = getattr(delta, "tool_calls", None)
            if not tcs:
                continue
            for tc in tcs:
                idx = getattr(tc, "index", 0) or 0
                slot = merged.setdefault(
                    idx,
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                if getattr(tc, "type", None):
                    slot["type"] = tc.type
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["function"]["arguments"] += fn.arguments
                # Gemini-only thought_signature passthrough (last fragment
                # wins; Gemini emits the whole functionCall Part in a single
                # chunk so coalescing isn't a real concern in practice).
                # Strict ``bytes`` check — MagicMock test doubles otherwise
                # auto-generate truthy attributes that aren't bytes-like
                # and break b64encode (and other vendors will never set
                # this attr to anything but bytes / None).
                sig = getattr(tc, "_thought_signature", None)
                if isinstance(sig, (bytes, bytearray)) and sig:
                    slot["_gemini_thought_signature"] = _base64.b64encode(
                        sig
                    ).decode("ascii")
        return [tc for tc in merged.values() if tc["id"] is not None]

    async def _stream_mesh_delegated(
        self,
        message: Union[str, list[dict[str, Any]]],
        media: Union[list, None],
        context: Union[dict, None, object],
        context_mode: Literal["replace", "append", "prepend"],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream from a mesh-delegated provider (provider={"capability": ...}).

        Routes to the provider's auto-generated ``<name>_stream`` MCP tool
        when present (Python providers built with @mesh.llm_provider after
        Phase 3 expose this side-by-side with the buffered ``<name>``
        tool). When the provider does NOT expose a streaming variant — for
        example older Python providers, TS / Java SDK providers, or any
        provider where the streaming tool was disabled — we soft-fall-back
        to the buffered ``provider_proxy(request=...)`` and yield its
        content as a single chunk so the consumer's ``async for`` always
        observes at least one item on a successful call.

        Request shape is identical to ``_call_mesh_provider``: same five
        fields go into the ``MeshLlmRequest`` dict (messages, tools,
        model_params, context, request_id, caller_agent). The provider
        side reconstructs a ``MeshLlmRequest`` and delegates to its own
        provider-managed loop (buffered or streaming).
        """
        from mesh.types import MeshLlmRequest

        provider_proxy = await self._get_mesh_provider()

        messages = await self._build_messages_for_run(
            message, media, context, context_mode
        )

        try:
            request_params = self._build_request_params(messages, **kwargs)
        except Exception as e:
            logger.error(f"❌ stream(mesh): failed to build request params: {e}")
            raise LLMAPIError(
                provider=str(self.provider),
                model=self.model,
                original_error=e,
            ) from e

        effective_tools = (
            self._enrich_tools_with_endpoints()
            if self._tool_schemas
            else None
        )

        # Mesh delegation: extract model_params to send to provider.
        # Mirrors __call__'s mesh-delegate branch (mesh_llm_agent.py:929-963)
        # so the streaming and buffered paths land identical request shapes
        # on the provider side.
        model_params = {
            k: v
            for k, v in request_params.items()
            if k
            not in [
                "messages",
                "tools",
                "api_key",
                "output_mode",
                "model",
            ]
        }
        if self.model:
            model_params["model"] = self.model
        if self.output_type is not str and hasattr(
            self.output_type, "model_json_schema"
        ):
            model_params["output_schema"] = self.output_type.model_json_schema()
            model_params["output_type_name"] = self.output_type.__name__
        if self._parallel_tool_calls:
            model_params["parallel_tool_calls"] = True

        request = MeshLlmRequest(
            messages=messages,
            tools=effective_tools if effective_tools else None,
            model_params=model_params if model_params else None,
        )
        request_dict = {
            "messages": request.messages,
            "tools": request.tools,
            "model_params": request.model_params,
            "context": request.context,
            "request_id": request.request_id,
            "caller_agent": request.caller_agent,
        }

        # Phase 5C: tag-based discrimination (ai.mcpmesh.stream) makes the
        # registry resolver return the streaming variant directly when the
        # consumer's @mesh.llm function returns Stream[str]. provider_proxy
        # .function_name is already the streaming tool name — no suffix
        # mangling needed. (Pre-Phase-5C this was f"{name}_stream" because
        # the resolver was non-deterministic; that's no longer the case.)
        stream_tool_name = provider_proxy.function_name
        logger.debug(
            f"📤 stream(mesh): routing to {provider_proxy.endpoint}/"
            f"{stream_tool_name} (messages={len(messages)}, "
            f"tools={len(effective_tools) if effective_tools else 0})"
        )

        try:
            async for chunk in provider_proxy.stream(
                name=stream_tool_name, request=request_dict
            ):
                yield chunk
            return
        except Exception as e:
            # FastMCP surfaces an unknown tool as fastmcp.exceptions.ToolError
            # with message "Unknown tool: ..." (server raises NotFoundError,
            # client._parse_call_tool_result re-raises as ToolError). We only
            # fall back on that specific shape so genuine provider errors
            # (timeout, network, model API failure) still surface to the
            # consumer with the original exception class intact.
            err_msg = str(e).lower()
            looks_like_missing_tool = (
                "unknown tool" in err_msg or "tool not found" in err_msg
            )
            if not looks_like_missing_tool:
                raise

            # With Phase 5C tag-based discrimination the resolver will not
            # normally hand us a provider that lacks the streaming tool —
            # this branch fires only in the rare race where a provider
            # advertised the ai.mcpmesh.stream tag but the streaming MCP
            # tool itself is unreachable (e.g. transient registration
            # mismatch). Defensive single-chunk degrade keeps the consumer
            # alive instead of bubbling a hard failure.
            logger.warning(
                f"Provider {provider_proxy.endpoint} advertised the streaming "
                f"variant but tool '{stream_tool_name}' is not exposed; "
                f"degrading to a single buffered chunk via "
                f"'{provider_proxy.function_name}'."
            )

        # Buffered fallback: call the provider's NON-streaming sibling tool
        # (strip the trailing ``_stream`` suffix from the resolved name) and
        # yield the full content as one chunk. Calling provider_proxy(...)
        # directly would re-invoke ``self.function_name`` — i.e. the same
        # streaming tool we just got "unknown tool" for — so we explicitly
        # name the buffered variant. Cross-runtime providers (Java, TS) may
        # return a JSON string instead of a dict; normalize the shape.
        if stream_tool_name.endswith("_stream"):
            buffered_tool_name = stream_tool_name[: -len("_stream")]
        else:
            buffered_tool_name = stream_tool_name
        result = await provider_proxy.call_tool_with_tracing(
            buffered_tool_name, {"request": request_dict}
        )
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                message_dict = parsed if isinstance(parsed, dict) else {
                    "role": "assistant",
                    "content": result,
                }
            except (json.JSONDecodeError, TypeError):
                message_dict = {"role": "assistant", "content": result}
        elif isinstance(result, dict):
            message_dict = result
        else:
            message_dict = {"role": "assistant", "content": str(result)}

        content = message_dict.get("content") or ""
        if content:
            yield content

    async def stream(
        self,
        message: Union[str, list[dict[str, Any]]],
        *,
        media: Union[list, None] = None,
        context: Union[dict, None, object] = _CONTEXT_NOT_PROVIDED,
        context_mode: Literal["replace", "append", "prepend"] = "append",
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream the final assistant text token-by-token via the agentic loop.

        Each iteration opens ``litellm.acompletion(stream=True, ...)`` and
        consumes chunks live as they arrive. Text deltas are yielded to the
        consumer immediately; the moment a ``tool_calls`` delta appears we
        stop yielding text from this iteration, drain the rest of the stream
        to collect tool_call argument fragments and the trailing usage block,
        execute the tools, append assistant + tool messages, and continue
        the loop. An iteration that produces no tool_calls IS the final
        answer — we return after the stream exhausts.

        Why stop yielding text once a tool_call is seen:
            Anthropic emits text only BEFORE a tool_call within a single
            assistant turn (Claude does not interleave text and tool_calls
            inside one content block). Any further "text" deltas after a
            tool_call delta are typically empty / whitespace and would just
            muddy the consumer's view of the preamble. If a future provider
            DOES interleave, we can revisit. The earlier "peek-then-stream"
            design (Option A) decided text-vs-tool BEFORE the stream began,
            which dropped the entire tool_call branch when Claude prefaced
            its tool calls with text like "I'll check the weather..." —
            this Option B implementation handles that case correctly.

        Token usage is captured AFTER full stream consumption per iteration
        (LiteLLM emits ``usage`` in the final chunk when
        ``stream_options={"include_usage": True}`` is requested) so
        ExecutionTracer's post-call read still sees accurate counts.

        Constraints:
            - String output only — typed Pydantic outputs cannot be
              meaningfully streamed and would defeat token-by-token UX.
            - Mesh-delegated providers route through the provider's
              auto-generated ``<name>_stream`` tool when present, falling
              back to a single-chunk yield from the buffered ``<name>``
              tool when the provider does not advertise a streaming
              variant (e.g., older Python providers and TS / Java SDKs).

        Yields:
            ``str`` chunks from the final assistant message (and any
            preamble text that precedes intermediate tool calls).
        """
        if self.output_type is not str:
            raise NotImplementedError(
                "MeshLlmAgent.stream() supports only str output_type; got "
                f"{getattr(self.output_type, '__name__', self.output_type)!r}. "
                "Use MeshLlmAgent.__call__() for typed responses."
            )

        if self._is_mesh_delegated:
            # Forward call-time kwargs (temperature, max_tokens, etc.) so
            # mesh-delegated streaming honors the same overrides as the
            # buffered __call__ path.
            async for chunk in self._stream_mesh_delegated(
                message, media, context, context_mode, **kwargs
            ):
                yield chunk
            return

        if acompletion is None:
            raise ImportError(
                "litellm is required for MeshLlmAgent.stream(). "
                "Install with: pip install litellm"
            )

        from _mcp_mesh.tracing.context import set_llm_metadata

        self._iteration_count = 0
        total_input_tokens = 0
        total_output_tokens = 0
        effective_model = self.model

        messages = await self._build_messages_for_run(
            message, media, context, context_mode
        )

        while self._iteration_count < self.max_iterations:
            self._iteration_count += 1
            logger.debug(
                f"🔄 stream iteration {self._iteration_count}/{self.max_iterations}"
            )

            try:
                request_params = self._build_request_params(messages, **kwargs)
            except Exception as e:
                logger.error(f"❌ stream: failed to build request params: {e}")
                raise LLMAPIError(
                    provider=str(self.provider),
                    model=self.model,
                    original_error=e,
                ) from e

            request_params["model"] = self.model
            request_params["api_key"] = self.api_key
            request_params["stream"] = True
            existing_stream_opts = request_params.get("stream_options") or {}
            request_params["stream_options"] = {
                **existing_stream_opts,
                "include_usage": True,
            }

            try:
                stream_iter = await acompletion(**request_params)
            except Exception as e:
                logger.error(f"❌ stream: acompletion failed: {e}")
                raise LLMAPIError(
                    provider=str(self.provider),
                    model=self.model,
                    original_error=e,
                ) from e

            chunks: list[Any] = []
            saw_tool_call = False
            stream_completed = False

            try:
                async for chunk in stream_iter:
                    chunks.append(chunk)

                    if self._chunk_has_tool_call(chunk):
                        # First tool_call delta of this iteration: stop
                        # yielding text immediately. We continue draining
                        # the stream so we collect remaining tool_call
                        # argument fragments AND the trailing usage chunk;
                        # we do NOT break out of the loop.
                        saw_tool_call = True
                        continue

                    if saw_tool_call:
                        # Already in tool-call mode; ignore any further
                        # text deltas (per the docstring: Claude doesn't
                        # interleave text and tool_calls).
                        continue

                    text = self._extract_text_from_chunk(chunk)
                    if text:
                        yield text
                stream_completed = True

                final_usage = self._extract_usage_from_chunks(chunks)
                if final_usage:
                    total_input_tokens += final_usage.get("prompt_tokens", 0) or 0
                    total_output_tokens += (
                        final_usage.get("completion_tokens", 0) or 0
                    )
                model_from_chunks = self._extract_model_from_chunks(chunks)
                if model_from_chunks:
                    effective_model = model_from_chunks

                if saw_tool_call:
                    merged_tool_calls = self._merge_streamed_tool_calls(chunks)
                    if not merged_tool_calls:
                        raise LLMAPIError(
                            provider=str(self.provider),
                            model=self.model,
                            original_error=RuntimeError(
                                "stream produced tool_call deltas but no complete "
                                "tool_call could be merged"
                            ),
                        )

                    preamble_text = self._join_text_from_chunks(chunks)
                    mock = _MockResponse(
                        {
                            "role": "assistant",
                            "content": preamble_text or None,
                            "tool_calls": merged_tool_calls,
                        }
                    )

                    set_llm_metadata(
                        model=effective_model,
                        provider=str(self.provider) if self.provider else "",
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                    )

                    assistant_message = mock.choices[0].message
                    logger.info(
                        f"🛠️  stream: LLM requested {len(assistant_message.tool_calls)} tool calls"
                    )
                    messages.append(assistant_message.model_dump())

                    if (
                        self._parallel_tool_calls
                        and len(assistant_message.tool_calls) > 1
                    ):
                        tool_results = await self._execute_tool_calls_parallel(
                            assistant_message.tool_calls
                        )
                    else:
                        tool_results = await self._execute_tool_calls(
                            assistant_message.tool_calls
                        )
                    tool_results = await self._resolve_media_in_tool_results(
                        tool_results
                    )
                    for tr in tool_results:
                        messages.append(tr)
                    continue

                # No tool_calls observed this iteration → final answer.
                # All text was already yielded live above; usage + model
                # metadata is published, and we're done.
                set_llm_metadata(
                    model=effective_model,
                    provider=str(self.provider) if self.provider else "",
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )
                return
            finally:
                if not stream_completed:
                    aclose = getattr(stream_iter, "aclose", None)
                    if aclose is not None:
                        try:
                            await aclose()
                        except Exception as e:
                            logger.debug(
                                f"stream: aclose() failed during teardown: {e}"
                            )

        logger.error(
            f"❌ stream: max iterations ({self.max_iterations}) exceeded without final response"
        )
        raise MaxIterationsError(
            iteration_count=self._iteration_count,
            max_allowed=self.max_iterations,
        )

    @staticmethod
    def _chunk_has_tool_call(chunk: Any) -> bool:
        """True iff a streaming chunk carries any ``tool_calls`` delta."""
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return False
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return False
        return bool(getattr(delta, "tool_calls", None))

    @staticmethod
    def _extract_text_from_chunk(chunk: Any) -> str:
        """Pull ``delta.content`` from a streaming chunk; '' if none."""
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return ""
        content = getattr(delta, "content", None)
        return content or ""

    @staticmethod
    def _join_text_from_chunks(chunks: list[Any]) -> str:
        return "".join(
            MeshLlmAgent._extract_text_from_chunk(c) for c in chunks
        )

    @staticmethod
    def _extract_usage_from_chunks(chunks: list[Any]) -> dict[str, int] | None:
        """Last non-empty ``usage`` block across ``chunks`` (LiteLLM emits at end)."""
        for chunk in reversed(chunks):
            usage = getattr(chunk, "usage", None)
            if usage is None:
                continue
            return {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
        return None

    @staticmethod
    def _extract_model_from_chunks(chunks: list[Any]) -> str | None:
        for chunk in chunks:
            model = getattr(chunk, "model", None)
            if model:
                return model
        return None
