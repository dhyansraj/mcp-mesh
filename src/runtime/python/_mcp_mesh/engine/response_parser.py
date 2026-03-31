"""
Response parser for LLM outputs.

Handles parsing and validation of LLM responses into Pydantic models.
Separated from MeshLlmAgent for better testability and reusability.
"""

import json
import logging
from typing import Any, TypeVar, Union

import mcp_mesh_core
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ResponseParseError(Exception):
    """Raised when response parsing or validation fails."""

    pass


class ResponseParser:
    """
    Utility class for parsing LLM responses into Pydantic models.

    Handles:
    - Markdown code fence stripping (```json ... ```)
    - JSON parsing with fallback wrapping
    - Pydantic validation
    """

    @staticmethod
    def parse(content: Any, output_type: type[T]) -> T:
        """
        Parse LLM response into Pydantic model.

        Args:
            content: Raw response content from LLM (string or pre-parsed dict/list)
            output_type: Pydantic BaseModel class to parse into

        Returns:
            Parsed and validated Pydantic model instance

        Raises:
            ResponseParseError: If response doesn't match schema or invalid JSON
        """
        logger.debug(f"📝 Parsing response into {output_type.__name__}...")

        try:
            # If content is already parsed (e.g., OpenAI strict mode), skip string processing
            if isinstance(content, (dict, list)):
                logger.debug("📦 Content already parsed, skipping string processing")
                response_data = content
            else:
                # String processing for Claude, Gemini, and non-strict OpenAI
                # Extract JSON from mixed content (narrative + XML + JSON)
                extracted_content = ResponseParser._extract_json_from_mixed_content(
                    content
                )

                # Strip markdown code fences if present
                cleaned_content = ResponseParser._strip_markdown_fences(
                    extracted_content
                )

                # Try to parse as JSON
                response_data = ResponseParser._parse_json_with_fallback(
                    cleaned_content, output_type
                )

            # Validate against output type
            return ResponseParser._validate_and_create(response_data, output_type)

        except ResponseParseError:
            raise
        except Exception as e:
            logger.error(f"❌ Unexpected error parsing response: {e}")
            raise ResponseParseError(f"Unexpected parsing error: {e}")

    @staticmethod
    def _extract_json_from_mixed_content(content: str) -> str:
        """
        Extract JSON from mixed content (narrative + XML + JSON).

        Delegates to Rust core for extraction. Returns original content if
        no JSON is found.

        Args:
            content: Raw content that may contain narrative, XML, and JSON

        Returns:
            Extracted JSON string or original content
        """
        result = mcp_mesh_core.extract_json_py(content)
        return result if result is not None else content

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        """
        Strip markdown code fences from content.

        Delegates to Rust core for fence stripping.

        Args:
            content: Raw content

        Returns:
            Content with fences removed
        """
        return mcp_mesh_core.strip_code_fences_py(content)

    @staticmethod
    def _parse_json_with_fallback(content: str, output_type: type[T]) -> dict[str, Any]:
        """
        Parse content as JSON with fallback wrapping.

        If direct JSON parsing fails, tries to wrap content in {"response": content}
        to handle plain text responses.

        Args:
            content: Cleaned content
            output_type: Target Pydantic model

        Returns:
            Parsed JSON dict

        Raises:
            ResponseParseError: If JSON parsing fails even with fallback
        """
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            # If not JSON, try wrapping it as a simple response
            logger.warning(
                f"⚠️ Response is not valid JSON, attempting to wrap: {content[:100]}..."
            )
            try:
                # Try to match it to the output type as a simple string
                response_data = {"response": content}
                # Test if wrapping works by validating
                output_type(**response_data)
                logger.debug("✅ Response wrapped successfully")
                return response_data
            except ValidationError:
                # If wrapping doesn't work, raise the original JSON error
                raise ResponseParseError(f"Invalid JSON response: {e}")

    @staticmethod
    def _validate_and_create(response_data: Any, output_type: type[T]) -> T:
        """
        Validate data against Pydantic model and create instance.

        Handles both dict and list responses:
        - Dict: Direct unpacking into model
        - List: Auto-wrap into first list field of model (for OpenAI strict mode)

        Args:
            response_data: Parsed JSON data (dict or list)
            output_type: Target Pydantic model

        Returns:
            Validated Pydantic model instance

        Raises:
            ResponseParseError: If validation fails
        """
        try:
            # Handle list responses - wrap into first list field of model
            if isinstance(response_data, list):
                # Find the first list field in the model
                model_fields = output_type.model_fields
                list_field_name = None
                for field_name, field_info in model_fields.items():
                    # Check if field annotation is a list type
                    field_type = field_info.annotation
                    if (
                        hasattr(field_type, "__origin__")
                        and field_type.__origin__ is list
                    ):
                        list_field_name = field_name
                        break

                if list_field_name:
                    logger.debug(
                        f"📦 Wrapping list response into '{list_field_name}' field"
                    )
                    response_data = {list_field_name: response_data}
                else:
                    raise ResponseParseError(
                        f"Response is a list but {output_type.__name__} has no list field to wrap into"
                    )

            parsed = output_type(**response_data)
            logger.debug(f"✅ Response parsed successfully: {parsed}")
            return parsed
        except ValidationError as e:
            # Enhanced error logging with schema diff
            expected_schema = output_type.model_json_schema()
            logger.error(
                f"❌ Schema validation failed:\n"
                f"Expected schema: {json.dumps(expected_schema, indent=2)}\n"
                f"Received data: {json.dumps(response_data, indent=2)}\n"
                f"Validation errors: {e}"
            )
            raise ResponseParseError(f"Response validation failed: {e}")
