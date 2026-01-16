"""
Base provider handler interface for vendor-specific LLM behavior.

This module defines the abstract base class for provider-specific handlers
that customize how different LLM vendors (Claude, OpenAI, Gemini, etc.) are called.
"""

import copy
from abc import ABC, abstractmethod
from typing import Any, Optional

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
CLAUDE_ANTI_XML_INSTRUCTION = "- NEVER use XML-style syntax like <invoke name=\"tool_name\"/>"


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
    if "items" in obj:
        _add_strict_constraints_recursive(obj["items"], add_all_required)

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
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        output_type: type[BaseModel],
        **kwargs: Any,
    ) -> Dict[str, Any]:
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
        tool_schemas: Optional[List[Dict[str, Any]]],
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

    def get_vendor_capabilities(self) -> Dict[str, bool]:
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

    def __repr__(self) -> str:
        """String representation of handler."""
        return f"{self.__class__.__name__}(vendor='{self.vendor}')"
