"""
Generic provider handler for unknown/unsupported vendors.

Provides sensible defaults using prompt-based approach similar to Claude.
"""

import json
from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import BaseProviderHandler


class GenericHandler(BaseProviderHandler):
    """
    Generic provider handler for vendors without specific handlers.

    This handler provides a safe, conservative approach that should work
    with most LLM providers that follow OpenAI-compatible APIs:
    - Uses prompt-based JSON instructions (like Claude)
    - Standard tool calling format (via LiteLLM normalization)
    - No vendor-specific features
    - Maximum compatibility

    Use Cases:
    - Fallback for unknown vendors
    - New providers before dedicated handler is created
    - Testing with custom/local models
    - Providers like: Cohere, Together, Replicate, Ollama, etc.

    Strategy:
    - Conservative, prompt-based approach
    - Relies on LiteLLM to normalize vendor differences
    - Works with any provider that LiteLLM supports
    """

    def __init__(self, vendor: str = "unknown"):
        """
        Initialize generic handler.

        Args:
            vendor: Vendor name (e.g., "cohere", "together", "unknown")
        """
        super().__init__(vendor=vendor)

    def prepare_request(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]],
        output_type: type[BaseModel],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Prepare request with standard parameters.

        Generic Strategy:
        - Use standard message format
        - Include tools if provided (LiteLLM will normalize)
        - No vendor-specific parameters
        - Let LiteLLM handle vendor differences

        Args:
            messages: List of message dicts
            tools: Optional list of tool schemas
            output_type: Pydantic model for response
            **kwargs: Additional model parameters

        Returns:
            Dictionary of standard parameters for litellm.completion()
        """
        request_params = {
            "messages": messages,
            **kwargs,
        }

        # Add tools if provided (LiteLLM will convert to vendor format)
        if tools:
            request_params["tools"] = tools

        # Don't add response_format - not all vendors support it
        # Rely on prompt-based JSON instructions instead

        return request_params

    def format_system_prompt(
        self,
        base_prompt: str,
        tool_schemas: Optional[list[dict[str, Any]]],
        output_type: type,
    ) -> str:
        """
        Format system prompt with explicit JSON instructions.

        Generic Strategy:
        - Use detailed prompt instructions (works with most models)
        - Explicit JSON schema (since we can't assume response_format)
        - Clear tool calling guidelines
        - Maximum explicitness for compatibility
        - Skip JSON schema for str return type (text mode)

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt with explicit instructions
        """
        system_content = base_prompt

        # Add tool calling instructions if tools available
        if tool_schemas:
            system_content += """

TOOL CALLING RULES:
- You can call tools to gather information
- Make one tool call at a time
- Wait for tool results before making additional calls
- Use standard JSON function calling format
- Provide your final response after gathering needed information
"""

        # Skip JSON schema for str return type (text mode)
        if output_type is str:
            return system_content

        # Add explicit JSON schema instructions for Pydantic models
        # (since we can't rely on vendor-specific structured output)
        if isinstance(output_type, type) and issubclass(output_type, BaseModel):
            schema = output_type.model_json_schema()
            schema_str = json.dumps(schema, indent=2)
            system_content += (
                f"\n\nIMPORTANT: Return your final response as valid JSON matching this exact schema:\n"
                f"{schema_str}\n\n"
                f"Rules:\n"
                f"- Return ONLY the JSON object, no markdown, no additional text\n"
                f"- Ensure all required fields are present\n"
                f"- Match the schema exactly\n"
                f"- Use double quotes for strings\n"
                f"- Do not include comments"
            )

        return system_content

    def get_vendor_capabilities(self) -> dict[str, bool]:
        """
        Return conservative capability flags.

        For generic handler, we assume minimal capabilities
        to ensure maximum compatibility.

        Returns:
            Conservative capability flags
        """
        return {
            "native_tool_calling": True,  # Most modern LLMs support this via LiteLLM
            "structured_output": False,  # Can't assume all vendors support response_format
            "streaming": False,  # Conservative - not all vendors support streaming
            "vision": False,  # Conservative - not all models support vision
            "json_mode": False,  # Conservative - use prompt-based JSON instead
        }
