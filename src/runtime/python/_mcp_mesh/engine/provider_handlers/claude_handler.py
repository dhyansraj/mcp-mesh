"""
Claude/Anthropic provider handler.

Optimized for Claude API (Claude 3.x, Sonnet, Opus, Haiku)
using Anthropic's best practices for tool calling and JSON responses.
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .base_provider_handler import BaseProviderHandler


class ClaudeHandler(BaseProviderHandler):
    """
    Provider handler for Claude/Anthropic models.

    Claude Characteristics:
    - Excellent at following detailed instructions
    - Prefers verbose system prompts with explicit guidelines
    - Handles JSON output well with schema instructions
    - Native tool calling (via Anthropic messages API)
    - Performs best with anti-XML tool calling instructions

    Best Practices (from Anthropic docs):
    - Provide clear, detailed system prompts
    - Include explicit JSON schema in prompt for structured output
    - Add anti-XML instructions to prevent <invoke> style tool calls
    - Use one tool call at a time for better reliability
    """

    def __init__(self):
        """Initialize Claude handler."""
        super().__init__(vendor="anthropic")

    def prepare_request(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        output_type: type[BaseModel],
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Prepare request parameters for Claude API.

        Claude uses standard LiteLLM interface with:
        - Standard messages format
        - OpenAI-compatible tools format (LiteLLM converts to Anthropic format)
        - No special response_format needed (uses prompt-based JSON instructions)

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Pydantic model for response
            **kwargs: Additional model parameters

        Returns:
            Dictionary of parameters for litellm.completion()
        """
        request_params = {
            "messages": messages,
            **kwargs,  # Pass through temperature, max_tokens, etc.
        }

        # Add tools if provided
        # LiteLLM will convert OpenAI tool format to Anthropic's format
        if tools:
            request_params["tools"] = tools

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[List[Dict[str, Any]]],
        output_type: type[BaseModel]
    ) -> str:
        """
        Format system prompt for Claude with detailed instructions.

        Claude Strategy:
        1. Use base prompt as-is (detailed is better for Claude)
        2. Add anti-XML tool calling instructions if tools present
        3. Add explicit JSON schema instructions for final response
        4. Claude performs best with verbose, explicit guidelines

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type

        Returns:
            Formatted system prompt optimized for Claude
        """
        system_content = base_prompt

        # Add tool calling instructions if tools available
        # These prevent Claude from using XML-style <invoke> syntax
        if tool_schemas:
            system_content += """

IMPORTANT TOOL CALLING RULES:
- You have access to tools that you can call to gather information
- Make ONE tool call at a time - each tool call must be separate
- NEVER combine multiple tools in a single tool_use block
- NEVER use XML-style syntax like <invoke name="tool_name"/>
- Each tool must be called using proper JSON tool_use format
- After receiving results from a tool, you can make additional tool calls if needed
- Once you have gathered all necessary information, provide your final response
"""

        # Add JSON schema instructions for final response
        # Claude needs explicit schema in prompt (no native response_format)
        schema = output_type.model_json_schema()
        schema_str = json.dumps(schema, indent=2)
        system_content += (
            f"\n\nIMPORTANT: You must return your final response as valid JSON matching this schema:\n"
            f"{schema_str}\n\nReturn ONLY the JSON object, no additional text."
        )

        return system_content

    def get_vendor_capabilities(self) -> Dict[str, bool]:
        """
        Return Claude-specific capabilities.

        Returns:
            Capability flags for Claude
        """
        return {
            "native_tool_calling": True,  # Claude has native function calling
            "structured_output": False,  # No response_format, uses prompt-based JSON
            "streaming": True,  # Supports streaming
            "vision": True,  # Claude 3+ supports vision
            "json_mode": False,  # No dedicated JSON mode, uses prompting
        }
