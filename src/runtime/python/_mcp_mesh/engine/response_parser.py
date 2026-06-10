"""
Response parser for LLM outputs.

Handles parsing and validation of LLM responses into Pydantic models.
Separated from MeshLlmAgent for better testability and reusability.
"""

import json
import logging
import typing
from typing import Any, TypeVar, Union

import mcp_mesh_core
from pydantic import BaseModel, ValidationError

# Issue #1162 LOW-4: the parser raises the single rich ResponseParseError
# from llm_errors (raw_content / expected_schema / validation_errors attrs).
# Re-exported here for back-compat — callers importing
# `_mcp_mesh.engine.response_parser.ResponseParseError` get the same class
# that `except llm_errors.ResponseParseError` catches.
from .llm_errors import ResponseParseError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


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
            raise ResponseParseError(
                raw_content=str(content),
                expected_schema=output_type.__name__,
                validation_errors=f"Unexpected parsing error: {e}",
            ) from e

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
                raise ResponseParseError(
                    raw_content=content,
                    expected_schema=output_type.__name__,
                    validation_errors=f"Invalid JSON response: {e}",
                ) from e

    @staticmethod
    def _is_list_annotation(annotation: Any) -> bool:
        """
        Return True if the field annotation is (or optionally wraps) a list/sequence.

        Handles ``list[...]``, ``List[...]`` and ``Optional[list[...]]`` /
        ``Union[list[...], None]``. Conservative by design: only annotations that
        clearly denote a list participate in scalar-to-array coercion.
        """
        origin = typing.get_origin(annotation)
        if origin is list:
            return True
        if origin is Union:
            return any(
                ResponseParser._is_list_annotation(arg)
                for arg in typing.get_args(annotation)
                if arg is not type(None)
            )
        return False

    @staticmethod
    def _coerce_scalar_list_fields(
        response_data: dict[str, Any], output_type: type[T]
    ) -> dict[str, Any]:
        """
        Wrap scalar values in a single-element list for list-typed model fields.

        Scoped to structured-output response-model parsing. Only fields whose
        annotation is a list (see :meth:`_is_list_annotation`) and whose received
        value is a non-list, non-None scalar are coerced. All other values pass
        through unchanged, so well-shaped (strict) output is unaffected.
        """
        coerced: dict[str, Any] | None = None
        for field_name, field_info in output_type.model_fields.items():
            if field_name not in response_data:
                continue
            value = response_data[field_name]
            if value is None or isinstance(value, (list, tuple)):
                continue
            if ResponseParser._is_list_annotation(field_info.annotation):
                if coerced is None:
                    coerced = dict(response_data)
                logger.debug(
                    f"📦 Coercing scalar to single-element list for "
                    f"'{field_name}' (hint-mode drift)"
                )
                coerced[field_name] = [value]
        return coerced if coerced is not None else response_data

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
                        raw_content=str(response_data),
                        expected_schema=output_type.__name__,
                        validation_errors=(
                            f"Response is a list but {output_type.__name__} "
                            f"has no list field to wrap into"
                        ),
                    )

            # Defensive unwrap for LLM-side envelope hallucinations.
            # Claude in tool_use mode (and other LLMs in structured-output mode)
            # occasionally wraps the response in a single-key envelope like
            # {"parameter": {<real fields>}} or {"input": {...}} or {"response": {...}}.
            # Detect that shape and unwrap before Pydantic validation.
            # Reference: issue #961 covers a fuller retry-on-validation-failure fix.
            if isinstance(response_data, dict) and len(response_data) == 1:
                sole_key = next(iter(response_data))
                sole_value = response_data[sole_key]
                if (
                    sole_key not in output_type.model_fields
                    and isinstance(sole_value, dict)
                ):
                    # The sole value's keys should plausibly match the output_type.
                    # Don't unwrap if they don't — preserves error fidelity for
                    # genuine schema mismatches.
                    model_field_names = set(output_type.model_fields.keys())
                    required_field_names = {
                        name
                        for name, field in output_type.model_fields.items()
                        if field.is_required()
                    }
                    inner_keys = set(sole_value.keys())
                    if (
                        required_field_names.issubset(inner_keys)
                        or inner_keys.issubset(model_field_names)
                    ):
                        logger.debug(
                            f"📦 Unwrapping single-key envelope '{sole_key}' "
                            f"for {output_type.__name__}"
                        )
                        response_data = sole_value

            # Single-value-as-array leniency for hint-mode drift (issue #1142).
            # Under output_mode=hint the provider embeds the schema in the prompt
            # but does not enforce it natively, so the LLM can emit a scalar where
            # the schema declares a list (e.g. "insights": "x" instead of ["x"]).
            # Wrap such scalars in a single-element list before Pydantic validation.
            # No-op for well-shaped (strict) output where the value is already a list.
            if isinstance(response_data, dict):
                response_data = ResponseParser._coerce_scalar_list_fields(
                    response_data, output_type
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
            raise ResponseParseError(
                raw_content=json.dumps(response_data, default=str),
                expected_schema=output_type.__name__,
                validation_errors=str(e),
            ) from e
