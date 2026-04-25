"""Per-async-context storage for provider handler state.

Provider handlers are cached as singletons in ProviderHandlerRegistry, so any
instance state shared between methods (e.g., the pending output schema set by
apply_structured_output and read by format_system_prompt) is racy under
concurrent async requests with different parameters.

This module wraps the shared state in contextvars.ContextVar so each async
context (asyncio.Task, contextvars.copy_context, etc.) sees its own value.
"""
from __future__ import annotations

import contextvars
from typing import Any

# Per-async-context output-schema state. Set by apply_structured_output (and
# any other writer such as prepare_request); read by format_system_prompt.
_current_output_schema: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar(
        "mesh_handler_current_output_schema", default=None
    )
)
_current_output_type_name: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar(
        "mesh_handler_current_output_type_name", default=None
    )
)


def set_pending_output_schema(
    schema: dict[str, Any] | None, type_name: str | None
) -> None:
    """Set the output schema + type-name for the current async context."""
    _current_output_schema.set(schema)
    _current_output_type_name.set(type_name)


def get_pending_output_schema() -> tuple[dict[str, Any] | None, str | None]:
    """Read the output schema + type-name from the current async context."""
    return _current_output_schema.get(), _current_output_type_name.get()


def clear_pending_output_schema() -> None:
    """Clear the output schema + type-name for the current async context."""
    _current_output_schema.set(None)
    _current_output_type_name.set(None)
