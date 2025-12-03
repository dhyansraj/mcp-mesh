"""
MeshLlmAgent proxy implementation.

Provides automatic agentic loop for LLM-based agents with tool integration.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

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

        # DEPRECATED: Legacy cached instructions (now handled by provider handlers)
        # Kept for backward compatibility with tests
        self._cached_tool_instructions = """

IMPORTANT TOOL CALLING RULES:
- You have access to tools that you can call to gather information
- Make ONE tool call at a time - each tool call must be separate
- NEVER combine multiple tools in a single tool_use block
- NEVER use XML-style syntax like <invoke name="tool_name"/>
- Each tool must be called using proper JSON tool_use format
- After receiving results from a tool, you can make additional tool calls if needed
- Once you have gathered all necessary information, provide your final response
"""

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

            # Create mock LiteLLM response structure
            # This mimics litellm.completion() response format
            class MockToolCall:
                """Mock tool call object matching LiteLLM structure."""

                def __init__(self, tc_dict):
                    self.id = tc_dict["id"]
                    self.type = tc_dict["type"]
                    # Create function object
                    self.function = type(
                        "Function",
                        (),
                        {
                            "name": tc_dict["function"]["name"],
                            "arguments": tc_dict["function"]["arguments"],
                        },
                    )()

            class MockMessage:
                def __init__(self, message_dict):
                    self.content = message_dict.get("content")
                    self.role = message_dict.get("role", "assistant")
                    # Extract tool_calls if present (critical for agentic loop!)
                    self.tool_calls = None
                    if "tool_calls" in message_dict and message_dict["tool_calls"]:
                        self.tool_calls = [
                            MockToolCall(tc) for tc in message_dict["tool_calls"]
                        ]

                def model_dump(self):
                    dump = {"role": self.role, "content": self.content}
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

            class MockChoice:
                def __init__(self, message):
                    self.message = message
                    self.finish_reason = "stop"

            class MockResponse:
                def __init__(self, message_dict):
                    self.choices = [MockChoice(MockMessage(message_dict))]

            logger.debug(
                f"📥 Received response from mesh provider: "
                f"content={message_dict.get('content', '')[:200]}..., "
                f"tool_calls={len(message_dict.get('tool_calls', []))}"
            )

            return MockResponse(message_dict)

        except Exception as e:
            logger.error(f"❌ Mesh provider call failed: {e}")
            raise RuntimeError(f"Mesh LLM provider invocation failed: {e}") from e

    async def __call__(
        self,
        message: Union[str, list[dict[str, Any]]],
        *,
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

            # Append extra context (runtime wins on key conflicts)
            result = await llm("What is the answer?", context={"extra": "info"})

            # Prepend context (auto wins on key conflicts)
            result = await llm("What is the answer?", context={"extra": "info"}, context_mode="prepend")

            # Replace context entirely
            result = await llm("What is the answer?", context={"only": "this"}, context_mode="replace")

            # Explicitly clear context
            result = await llm("What is the answer?", context={}, context_mode="replace")
        """
        self._iteration_count = 0

        # Check if litellm is available
        if completion is None:
            raise ImportError(
                "litellm is required for MeshLlmAgent. Install with: pip install litellm"
            )

        # Resolve effective context (merge auto-populated with runtime context)
        effective_context = self._resolve_context(context, context_mode)

        # Render base system prompt (from template or literal) with effective context
        base_system_prompt = self._render_system_prompt(effective_context)

        # Phase 2: Use provider handler to format system prompt
        # This allows vendor-specific optimizations (e.g., OpenAI skips JSON instructions)
        system_content = self._provider_handler.format_system_prompt(
            base_prompt=base_system_prompt,
            tool_schemas=self._tool_schemas,
            output_type=self.output_type,
        )

        # Debug: Log system prompt (truncated for privacy)
        logger.debug(
            f"📝 System prompt (formatted by {self._provider_handler}): {system_content[:200]}..."
        )

        # Build messages array based on input type
        if isinstance(message, list):
            # Multi-turn conversation - use provided messages array
            messages = message.copy()

            # Ensure system prompt is prepended if not already present
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": system_content})
            else:
                # Replace existing system message with our constructed one
                messages[0] = {"role": "system", "content": system_content}

            # Log conversation history
            logger.info(
                f"🚀 Starting agentic loop with {len(messages)} messages in history"
            )
        else:
            # Single-turn - build messages array from string
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": message},
            ]

            logger.info(f"🚀 Starting agentic loop for message: {message[:100]}...")

        # Agentic loop
        while self._iteration_count < self.max_iterations:
            self._iteration_count += 1
            logger.debug(
                f"🔄 Iteration {self._iteration_count}/{self.max_iterations}..."
            )

            try:
                # Call LLM (either direct LiteLLM or mesh-delegated)
                try:
                    # Build kwargs with output_mode override if set
                    call_kwargs = (
                        {**kwargs, "output_mode": self.output_mode}
                        if self.output_mode
                        else kwargs
                    )

                    # Use provider handler to prepare vendor-specific request
                    request_params = self._provider_handler.prepare_request(
                        messages=messages,
                        tools=self._tool_schemas if self._tool_schemas else None,
                        output_type=self.output_type,
                        **call_kwargs,
                    )

                    if self._is_mesh_delegated:
                        # Mesh delegation: extract model_params to send to provider
                        # Exclude messages/tools (separate params), model/api_key (provider has them),
                        # and output_mode (only used locally by prepare_request)
                        model_params = {
                            k: v
                            for k, v in request_params.items()
                            if k
                            not in [
                                "messages",
                                "tools",
                                "model",
                                "api_key",
                                "output_mode",
                            ]
                        }

                        logger.debug(
                            f"📤 Delegating to mesh provider with handler-prepared params: "
                            f"keys={list(model_params.keys())}"
                        )

                        response = await self._call_mesh_provider(
                            messages=messages,
                            tools=self._tool_schemas if self._tool_schemas else None,
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

                # Extract response content
                assistant_message = response.choices[0].message

                # Check if LLM wants to use tools
                if (
                    hasattr(assistant_message, "tool_calls")
                    and assistant_message.tool_calls
                ):
                    tool_calls = assistant_message.tool_calls
                    logger.debug(f"🛠️  LLM requested {len(tool_calls)} tool calls")

                    # Add assistant message to history
                    messages.append(assistant_message.model_dump())

                    # Execute all tool calls
                    tool_results = await self._execute_tool_calls(tool_calls)

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

                return self._parse_response(assistant_message.content)

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
