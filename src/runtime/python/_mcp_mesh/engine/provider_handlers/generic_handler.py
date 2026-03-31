"""
Generic provider handler for unknown/unsupported vendors.

Provides sensible defaults using prompt-based approach similar to Claude.
"""

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from .base_provider_handler import (
    BaseProviderHandler,
    has_media_params,
)

logger = logging.getLogger(__name__)


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

        Delegates to Rust core for prompt construction.

        Args:
            base_prompt: Base system prompt
            tool_schemas: Optional tool schemas
            output_type: Expected response type (str or Pydantic model)

        Returns:
            Formatted system prompt with explicit instructions
        """
        import mcp_mesh_core

        is_string = output_type is str
        output_mode = "text" if is_string else "hint"

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
            self.vendor,
            base_prompt,
            bool(tool_schemas),
            has_media_params(tool_schemas),
            schema_json,
            schema_name,
            output_mode,
        )

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

    def apply_structured_output(
        self,
        output_schema: dict[str, Any],
        output_type_name: Optional[str],
        model_params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Apply structured output for generic vendors.

        Generic strategy: Don't use response_format since not all vendors support it.
        The consumer should rely on prompt-based instructions instead.

        Args:
            output_schema: JSON schema dict from consumer
            output_type_name: Name of the output type
            model_params: Current model parameters dict

        Returns:
            Unmodified model_params (no response_format added)
        """
        # Don't add response_format - generic vendors may not support it
        # The consumer's system prompt should include JSON instructions
        logger.debug(
            f"⚠️ Generic handler: skipping response_format for '{output_type_name}' "
            f"(vendor '{self.vendor}' may not support structured output)"
        )
        return model_params
