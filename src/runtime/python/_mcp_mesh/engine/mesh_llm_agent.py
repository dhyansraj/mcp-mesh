"""
MeshLlmAgent proxy implementation.

Provides automatic agentic loop for LLM-based agents with tool integration.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from .llm_config import LLMConfig
from .llm_errors import (
    LLMAPIError,
    MaxIterationsError,
    ResponseParseError,
    ToolExecutionError,
)
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
        output_type: type[BaseModel],
        tool_proxies: Optional[dict[str, Any]] = None,
        template_path: Optional[str] = None,
        context_value: Optional[Any] = None,
    ):
        """
        Initialize MeshLlmAgent proxy.

        Args:
            config: LLM configuration (provider, model, api_key, etc.)
            filtered_tools: List of tool metadata from registry (for schema building)
            output_type: Pydantic BaseModel for response validation
            tool_proxies: Optional map of function_name -> proxy for tool execution
            template_path: Optional path to Jinja2 template file for system prompt
            context_value: Optional context for template rendering (MeshContextModel, dict, or None)
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
        self._iteration_count = 0

        # Template rendering support (Phase 3)
        self._template_path = template_path
        self._context_value = context_value
        self._template: Optional[Any] = None  # Cached template object

        # Load template if path provided
        if template_path:
            self._template = self._load_template(template_path)

        # Build tool schemas for LLM (OpenAI format used by LiteLLM)
        self._tool_schemas = ToolSchemaBuilder.build_schemas(self.tools_metadata)

        # Cache tool calling instructions to prevent XML-style invocations
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

        # Cache JSON schema instructions (output_type never changes after init)
        # This avoids regenerating the schema on every __call__
        schema = self.output_type.model_json_schema()
        schema_str = json.dumps(schema, indent=2)
        self._cached_json_instructions = (
            f"\n\nIMPORTANT: You must return your final response as valid JSON matching this schema:\n"
            f"{schema_str}\n\nReturn ONLY the JSON object, no additional text."
        )

        logger.debug(
            f"🤖 MeshLlmAgent initialized: provider={config.provider}, model={config.model}, "
            f"tools={len(filtered_tools)}, max_iterations={config.max_iterations}"
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
        if hasattr(context_value, "model_dump") and callable(
            context_value.model_dump
        ):
            return context_value.model_dump()

        # Check if it's a dict
        if isinstance(context_value, dict):
            return context_value

        # Invalid type
        raise TypeError(
            f"Invalid context type: {type(context_value).__name__}. "
            f"Expected MeshContextModel, dict, or None."
        )

    def _render_system_prompt(self) -> str:
        """
        Render system prompt from template or return literal.

        If template_path was provided in __init__, renders template with context.
        If system_prompt was set via set_system_prompt(), uses that override.
        Otherwise, uses config.system_prompt as literal.

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
            context = self._prepare_context(self._context_value)
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

    async def __call__(self, message: str, **kwargs) -> Any:
        """
        Execute automatic agentic loop and return typed response.

        Args:
            message: User message to process
            **kwargs: Additional arguments passed to LLM

        Returns:
            Parsed response matching output_type

        Raises:
            MaxIterationsError: If max iterations exceeded
            ToolExecutionError: If tool execution fails
            ValidationError: If response doesn't match output_type schema
        """
        self._iteration_count = 0

        # Check if litellm is available
        if completion is None:
            raise ImportError(
                "litellm is required for MeshLlmAgent. Install with: pip install litellm"
            )

        # Build initial messages
        messages = []

        # Render system prompt (from template or literal)
        base_system_prompt = self._render_system_prompt()

        # Build system prompt with tool calling and JSON schema instructions
        system_content = base_system_prompt

        # Add tool calling instructions if tools are available
        if self._tool_schemas:
            system_content += self._cached_tool_instructions

        # Add JSON schema instructions for final response
        system_content += self._cached_json_instructions

        # Debug: Log system prompt (truncated for privacy)
        logger.debug(f"📝 System prompt: {system_content[:200]}...")

        messages.append({"role": "system", "content": system_content})
        messages.append({"role": "user", "content": message})

        logger.info(f"🚀 Starting agentic loop for message: {message[:100]}...")

        # Agentic loop
        while self._iteration_count < self.max_iterations:
            self._iteration_count += 1
            logger.debug(
                f"🔄 Iteration {self._iteration_count}/{self.max_iterations}..."
            )

            try:
                # Call LLM with tools
                try:
                    response = await asyncio.to_thread(
                        completion,
                        model=self.model,
                        messages=messages,
                        tools=self._tool_schemas if self._tool_schemas else None,
                        api_key=self.api_key,
                        **kwargs,
                    )
                except Exception as e:
                    # Any exception from completion call is an LLM API error
                    logger.error(f"❌ LLM API error: {e}")
                    raise LLMAPIError(
                        provider=self.provider,
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

                # REMOVE_LATER: Debug full LLM response
                logger.warning(
                    f"🔍 REMOVE_LATER: assistant_message type: {type(assistant_message)}"
                )
                logger.warning(
                    f"🔍 REMOVE_LATER: assistant_message.content type: {type(assistant_message.content)}"
                )
                logger.warning(
                    f"🔍 REMOVE_LATER: assistant_message.content is None: {assistant_message.content is None}"
                )
                if assistant_message.content:
                    logger.warning(
                        f"🔍 REMOVE_LATER: Full LLM response length: {len(assistant_message.content)}"
                    )
                    logger.warning(
                        f"🔍 REMOVE_LATER: Full LLM response: {assistant_message.content!r}"
                    )
                else:
                    logger.warning(
                        "🔍 REMOVE_LATER: assistant_message.content is empty or None!"
                    )
                    logger.warning(
                        f"🔍 REMOVE_LATER: Full assistant_message: {assistant_message}"
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

        Delegates to ResponseParser for actual parsing logic.

        Args:
            content: Response content from LLM

        Returns:
            Parsed Pydantic model instance

        Raises:
            ResponseParseError: If response doesn't match output_type schema or invalid JSON
        """
        return ResponseParser.parse(content, self.output_type)
