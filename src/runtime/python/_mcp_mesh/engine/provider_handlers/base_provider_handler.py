"""
Base provider handler interface for vendor-specific LLM behavior.

This module defines the abstract base class for provider-specific handlers
that customize how different LLM vendors (Claude, OpenAI, Gemini, etc.) are called.
"""

import copy
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger(__name__)

from pydantic import BaseModel

# ============================================================================
# Shared Constants
# ============================================================================

# Base tool calling instructions shared across all providers.
# Claude handler adds anti-XML instruction on top of this.
BASE_TOOL_INSTRUCTIONS = """
IMPORTANT TOOL CALLING RULES:
- You have access to tools that you can call to gather information
- Make ONE tool call at a time
- After receiving tool results, you can make additional calls if needed
- Once you have all needed information, provide your final response
"""

# Anti-XML instruction for Claude (prevents <invoke> style tool calls).
CLAUDE_ANTI_XML_INSTRUCTION = (
    '- NEVER use XML-style syntax like <invoke name="tool_name"/>'
)


# ============================================================================
# Shared Schema Utilities
# ============================================================================


def make_schema_strict(
    schema: dict[str, Any],
    add_all_required: bool = True,
) -> dict[str, Any]:
    """
    Make a JSON schema strict for structured output.

    This is a shared utility used by OpenAI, Gemini, and Claude handlers.
    Adds additionalProperties: false to all object types and optionally
    ensures 'required' includes all property keys.

    Args:
        schema: JSON schema to make strict
        add_all_required: If True, set 'required' to include ALL property keys.
                         OpenAI and Gemini require this; Claude does not.
                         Default: True

    Returns:
        New schema with strict constraints (original not mutated)
    """
    result = copy.deepcopy(schema)
    _add_strict_constraints_recursive(result, add_all_required)
    return result


def is_simple_schema(schema: dict[str, Any]) -> bool:
    """
    Check if a JSON schema is simple enough for hint mode.

    Simple schema criteria:
    - Less than 5 fields
    - All fields are basic types (str, int, float, bool, list)
    - No nested Pydantic models ($ref or nested objects with properties)

    This is used by provider handlers to decide between hint mode
    (prompt-based JSON instructions) and strict mode (response_format).

    Args:
        schema: JSON schema dict

    Returns:
        True if schema is simple, False otherwise
    """
    try:
        properties = schema.get("properties", {})

        # Check field count
        if len(properties) >= 5:
            return False

        # Check for nested objects or complex types
        for field_name, field_schema in properties.items():
            field_type = field_schema.get("type")

            # Check for nested objects (indicates nested Pydantic model)
            if field_type == "object" and "properties" in field_schema:
                return False

            # Check for $ref (nested model reference)
            if "$ref" in field_schema:
                return False

            # Check array items for complex types
            if field_type == "array":
                items = field_schema.get("items", {})
                if items.get("type") == "object" or "$ref" in items:
                    return False

        return True
    except Exception:
        return False


def sanitize_schema_for_structured_output(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize a JSON schema by removing validation keywords unsupported by LLM APIs.

    LLM structured output APIs (Claude, OpenAI, Gemini) typically only support
    the structural parts of JSON Schema, not validation constraints. This function
    removes unsupported keywords to ensure uniform behavior across all providers.

    Removed keywords:
    - minimum, maximum (number range)
    - exclusiveMinimum, exclusiveMaximum (exclusive bounds)
    - minLength, maxLength (string length)
    - minItems, maxItems (array size)
    - pattern (regex validation)
    - multipleOf (divisibility)

    Args:
        schema: JSON schema dict (will not be mutated)

    Returns:
        New schema with unsupported validation keywords removed
    """
    result = copy.deepcopy(schema)
    _strip_unsupported_keywords_recursive(result)
    logger.debug(
        "Sanitized schema for structured output (removed validation-only keywords)"
    )
    return result


# Keywords that are validation-only and not supported by LLM structured output APIs
_UNSUPPORTED_SCHEMA_KEYWORDS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "pattern",
    "multipleOf",
}


def _strip_unsupported_keywords_recursive(obj: Any) -> None:
    """
    Recursively strip unsupported validation keywords from a schema object.

    Args:
        obj: Schema object to process (mutated in place)
    """
    if not isinstance(obj, dict):
        return

    # Remove unsupported keywords at this level
    for keyword in _UNSUPPORTED_SCHEMA_KEYWORDS:
        obj.pop(keyword, None)

    # Process $defs (Pydantic uses this for nested models)
    if "$defs" in obj:
        for def_schema in obj["$defs"].values():
            _strip_unsupported_keywords_recursive(def_schema)

    # Process properties
    if "properties" in obj:
        for prop_schema in obj["properties"].values():
            _strip_unsupported_keywords_recursive(prop_schema)

    # Process items (for arrays)
    if "items" in obj:
        items = obj["items"]
        if isinstance(items, dict):
            _strip_unsupported_keywords_recursive(items)
        elif isinstance(items, list):
            for item in items:
                _strip_unsupported_keywords_recursive(item)

    # Process prefixItems (tuple validation)
    if "prefixItems" in obj:
        for item in obj["prefixItems"]:
            _strip_unsupported_keywords_recursive(item)

    # Process anyOf, oneOf, allOf
    for key in ("anyOf", "oneOf", "allOf"):
        if key in obj:
            for item in obj[key]:
                _strip_unsupported_keywords_recursive(item)


def _add_strict_constraints_recursive(obj: Any, add_all_required: bool) -> None:
    """
    Recursively add strict constraints to a schema object.

    Args:
        obj: Schema object to process (mutated in place)
        add_all_required: Whether to set required to all property keys
    """
    if not isinstance(obj, dict):
        return

    # If this is an object type, add additionalProperties: false
    if obj.get("type") == "object":
        obj["additionalProperties"] = False

        # Optionally set required to include all property keys
        if add_all_required and "properties" in obj:
            obj["required"] = list(obj["properties"].keys())

    # Process $defs (Pydantic uses this for nested models)
    if "$defs" in obj:
        for def_schema in obj["$defs"].values():
            _add_strict_constraints_recursive(def_schema, add_all_required)

    # Process properties
    if "properties" in obj:
        for prop_schema in obj["properties"].values():
            _add_strict_constraints_recursive(prop_schema, add_all_required)

    # Process items (for arrays)
    # items can be an object (single schema) or a list (tuple validation in older drafts)
    if "items" in obj:
        items = obj["items"]
        if isinstance(items, dict):
            _add_strict_constraints_recursive(items, add_all_required)
        elif isinstance(items, list):
            for item in items:
                _add_strict_constraints_recursive(item, add_all_required)

    # Process prefixItems (tuple validation in JSON Schema draft 2020-12)
    if "prefixItems" in obj:
        for item in obj["prefixItems"]:
            _add_strict_constraints_recursive(item, add_all_required)

    # Process anyOf, oneOf, allOf
    for key in ("anyOf", "oneOf", "allOf"):
        if key in obj:
            for item in obj[key]:
                _add_strict_constraints_recursive(item, add_all_required)


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

    def __repr__(self) -> str:
        """String representation of handler."""
        return f"{self.__class__.__name__}(vendor='{self.vendor}')"
