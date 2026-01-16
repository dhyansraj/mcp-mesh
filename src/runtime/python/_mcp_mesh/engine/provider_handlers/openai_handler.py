"""
OpenAI provider handler.

Optimized for OpenAI models (GPT-4, GPT-4 Turbo, GPT-3.5-turbo)
using OpenAI's native structured output capabilities.
"""

from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import (
    BASE_TOOL_INSTRUCTIONS,
    BaseProviderHandler,
    make_schema_strict,
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
            schema = output_type.model_json_schema()

            # Transform schema for OpenAI strict mode
            # OpenAI requires additionalProperties: false and all properties in required
            schema = make_schema_strict(schema, add_all_required=True)

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

        OpenAI Strategy:
        1. Use base prompt as-is
        2. Add tool calling instructions if tools present
        3. NO JSON schema instructions (response_format handles this)
        4. Keep prompt concise - OpenAI works well with shorter prompts
        5. Skip JSON note for str return type (text mode)

        Key Difference from Claude:
        - No JSON schema in prompt (response_format ensures compliance)
        - Shorter, more focused instructions
        - Let response_format handle output structure

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt optimized for OpenAI
        """
        system_content = base_prompt

        # Add tool calling instructions if tools available
        if tool_schemas:
            system_content += BASE_TOOL_INSTRUCTIONS

        # Skip JSON note for str return type (text mode)
        if output_type is str:
            return system_content

        # NOTE: We do NOT add JSON schema instructions here!
        # OpenAI's response_format parameter handles JSON structure automatically.
        # Adding explicit JSON instructions can actually confuse the model.

        # Optional: Add a brief note that response should be JSON
        # (though response_format enforces this anyway)
        system_content += f"\n\nYour final response will be structured as JSON matching the {output_type.__name__} format."

        return system_content

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

