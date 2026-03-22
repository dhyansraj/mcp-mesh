"""
Tool schema builder for LLM tool integration.

Builds OpenAI-format tool schemas from MCP tool metadata.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolSchemaBuilder:
    """
    Utility for building LLM tool schemas.

    Converts MCP tool metadata into OpenAI-format schemas
    compatible with LiteLLM.
    """

    @staticmethod
    def build_schemas(tools: list[Any]) -> list[dict[str, Any]]:
        """
        Build tool schemas in OpenAI format for LiteLLM.

        Args:
            tools: List of tool metadata (dict or object format)

        Returns:
            List of tool schemas in OpenAI format
        """
        if not tools:
            return []

        tool_schemas = []

        for tool in tools:
            schema = ToolSchemaBuilder._build_single_schema(tool)
            if schema:
                tool_schemas.append(schema)

        logger.debug(f"🔧 Built {len(tool_schemas)} tool schemas for LLM")
        return tool_schemas

    @staticmethod
    def _build_single_schema(tool: Any) -> dict[str, Any] | None:
        """
        Build schema for a single tool.

        Supports both dict-based metadata (from registry) and
        object-based proxies (for tests).

        Args:
            tool: Tool metadata or proxy object

        Returns:
            Tool schema in OpenAI format, or None if invalid
        """
        # Support both dict format and object format
        if isinstance(tool, dict):
            # Dict-based metadata (from registry)
            return ToolSchemaBuilder._build_from_dict(tool)
        else:
            # Object-based proxy (for tests)
            return ToolSchemaBuilder._build_from_object(tool)

    @staticmethod
    def _build_from_dict(tool: dict[str, Any]) -> dict[str, Any]:
        """
        Build schema from dict-based tool metadata.

        Args:
            tool: Tool metadata dict (must match OpenAPI spec field names)

        Returns:
            Tool schema in OpenAI format
        """
        # OpenAPI spec uses "name" (camelCase) - enforce strict contract
        function_name = tool.get("name")
        if not function_name:
            logger.error(f"❌ Tool missing 'name' field: {tool}")
            raise ValueError(
                f"Tool metadata missing required 'name' field (OpenAPI contract): {tool}"
            )

        description = tool.get("description", "")

        # Registry returns "input_schema" (snake_case) in JSON
        # Note: Pydantic model has alias="inputSchema" but we receive raw dicts
        input_schema = tool.get("input_schema")

        # Enrich description with media parameter info
        if input_schema and "properties" in input_schema:
            media_params = []
            for prop_name, prop_schema in input_schema["properties"].items():
                if "x-media-type" in prop_schema:
                    media_params.append(
                        f"'{prop_name}' accepts {prop_schema['x-media-type']} URIs"
                    )
            if media_params:
                media_note = "Accepts media: " + ", ".join(media_params) + "."
                description = (
                    description + " " + media_note if description else media_note
                )

        tool_schema = {
            "type": "function",
            "function": {
                "name": function_name,
                "description": description,
            },
        }

        if input_schema:
            tool_schema["function"]["parameters"] = input_schema

        logger.debug(f"🔧 Built tool schema for '{function_name}'")
        return tool_schema

    @staticmethod
    def _build_from_object(tool: Any) -> dict[str, Any]:
        """
        Build schema from object-based tool proxy.

        Args:
            tool: Tool proxy object

        Returns:
            Tool schema in OpenAI format
        """
        description = getattr(tool, "description", "")
        input_schema = getattr(tool, "input_schema", None)

        # Enrich description with media parameter info
        if input_schema and isinstance(input_schema, dict) and "properties" in input_schema:
            media_params = []
            for prop_name, prop_schema in input_schema["properties"].items():
                if isinstance(prop_schema, dict) and "x-media-type" in prop_schema:
                    media_params.append(
                        f"'{prop_name}' accepts {prop_schema['x-media-type']} URIs"
                    )
            if media_params:
                media_note = "Accepts media: " + ", ".join(media_params) + "."
                description = (
                    description + " " + media_note if description else media_note
                )

        tool_schema = {
            "type": "function",
            "function": {
                "name": getattr(tool, "name", "unknown"),
                "description": description,
            },
        }

        # Add input_schema if available
        if input_schema is not None:
            tool_schema["function"]["parameters"] = input_schema

        return tool_schema
