"""
Base provider handler interface for vendor-specific LLM behavior.

This module defines the abstract base class for provider-specific handlers
that customize how different LLM vendors (Claude, OpenAI, Gemini, etc.) are called.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import mcp_mesh_core
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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

    # ------------------------------------------------------------------
    # Native SDK dispatch (issue #834)
    # ------------------------------------------------------------------
    # Each subclass that ships a native vendor SDK adapter overrides
    # ``has_native()`` to gate the dispatch on the relevant SDK actually
    # being importable. Native dispatch is enabled by default; the
    # ``MCP_MESH_NATIVE_LLM=0`` env flag is the explicit opt-out.
    # The default implementation here returns False so the buffered /
    # streaming call sites in mesh.helpers transparently keep using
    # LiteLLM for vendors that have not migrated yet.

    def has_native(self) -> bool:
        """Return True if this handler can dispatch via a native vendor SDK.

        Default: False. Override in subclasses that ship a native adapter.
        Subclass implementations honor ``MCP_MESH_NATIVE_LLM=0`` as an
        explicit opt-out and return False when the relevant SDK is not
        importable.
        """
        return False

    async def complete(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ) -> Any:
        """Run a buffered completion via the vendor's native SDK.

        Default: NotImplementedError. Subclasses with ``has_native() == True``
        MUST override this to return a litellm-shaped response object (see
        ``_mcp_mesh.engine.mesh_llm_agent._MockResponse`` for the shape).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement native complete()"
        )

    async def complete_stream(
        self,
        request_params: dict[str, Any],
        *,
        model: str,
        **kwargs: Any,
    ):
        """Stream a completion via the vendor's native SDK.

        Default: NotImplementedError. Subclasses with ``has_native() == True``
        MUST override this to return an async iterator yielding chunks
        matching the litellm streaming shape consumed by
        ``mesh.helpers._provider_agentic_loop_stream`` and the legacy
        no-tools branch of ``llm_provider``'s stream tool.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement native complete_stream()"
        )

    def __repr__(self) -> str:
        """String representation of handler."""
        return f"{self.__class__.__name__}(vendor='{self.vendor}')"
