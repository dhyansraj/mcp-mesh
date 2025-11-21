"""
Enhanced error classes for LLM engine with structured context.

Provides rich debugging information for better troubleshooting and telemetry.
"""

from typing import Any, Optional


class MaxIterationsError(Exception):
    """
    Raised when max iterations are exceeded in agentic loop.

    Attributes:
        iteration_count: Number of iterations that were attempted
        max_allowed: Maximum iterations allowed
        function_id: Optional function ID for debugging
    """

    def __init__(
        self,
        iteration_count: int,
        max_allowed: int,
        function_id: Optional[str] = None,
    ):
        self.iteration_count = iteration_count
        self.max_allowed = max_allowed
        self.function_id = function_id

        message = (
            f"Exceeded maximum {max_allowed} iterations without reaching final response"
        )
        if function_id:
            message += f" (function_id={function_id})"
        super().__init__(message)


class LLMAPIError(Exception):
    """
    Raised when LLM API call fails.

    Attributes:
        provider: LLM provider name (e.g., 'claude', 'openai')
        model: Model name
        original_error: The underlying exception
        status_code: HTTP status code if available
    """

    def __init__(
        self,
        provider: str,
        model: str,
        original_error: Exception,
        status_code: Optional[int] = None,
    ):
        self.provider = provider
        self.model = model
        self.original_error = original_error
        self.status_code = status_code

        message = f"LLM API call failed: {original_error}"
        if status_code:
            message = f"LLM API call failed (HTTP {status_code}): {original_error}"
        message += f" [provider={provider}, model={model}]"
        super().__init__(message)


class ToolExecutionError(Exception):
    """
    Raised when a tool execution fails.

    Attributes:
        tool_name: Name of the tool that failed
        arguments: Arguments passed to the tool
        original_error: The underlying exception
    """

    def __init__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        original_error: Exception,
    ):
        self.tool_name = tool_name
        self.arguments = arguments
        self.original_error = original_error

        message = f"Tool '{tool_name}' execution failed: {original_error}"
        super().__init__(message)


class ResponseParseError(Exception):
    """
    Raised when response parsing or validation fails.

    Attributes:
        raw_content: Raw response content (truncated to 500 chars)
        expected_schema: Expected Pydantic schema name
        validation_errors: Pydantic validation errors if available
    """

    def __init__(
        self,
        raw_content: str,
        expected_schema: str,
        validation_errors: Optional[str] = None,
    ):
        self.raw_content = raw_content[:500]  # Truncate for logging
        self.expected_schema = expected_schema
        self.validation_errors = validation_errors

        message = f"Response validation failed for schema '{expected_schema}'"
        if validation_errors:
            message += f": {validation_errors}"
        super().__init__(message)
