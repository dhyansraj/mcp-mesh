"""
Trace context management for distributed tracing

Provides async-safe trace context storage using contextvars.
Inspired by the dev branch implementation but simplified for this feature branch.
"""

import contextvars
import os

import mcp_mesh_core

# Parse MCP_MESH_PROPAGATE_HEADERS env var once at import time
_raw = os.environ.get("MCP_MESH_PROPAGATE_HEADERS", "")
PROPAGATE_HEADERS: list[str] = [h.strip().lower() for h in _raw.split(",") if h.strip()]
PROPAGATE_HEADERS_CSV: str = ",".join(PROPAGATE_HEADERS)


def matches_propagate_header(name: str) -> bool:
    """Check if a header name matches any prefix in the propagate headers allowlist.

    Uses prefix matching: if PROPAGATE_HEADERS contains 'x-audit', it will match
    'x-audit', 'x-audit-id', 'x-audit-source', etc.
    """
    if not PROPAGATE_HEADERS:
        return False
    return mcp_mesh_core.matches_propagate_header_py(name, PROPAGATE_HEADERS_CSV)


# Payload sizes from proxy calls (set in call_tool, read in ExecutionTracer.end_execution)
_payload_sizes: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "_payload_sizes", default=None
)


def get_payload_sizes() -> dict[str, int] | None:
    """Get current payload sizes from context."""
    return _payload_sizes.get()


def set_payload_sizes(request_bytes: int = 0, response_bytes: int = 0) -> None:
    """Set payload sizes in context for ExecutionTracer to pick up."""
    _payload_sizes.set(
        {"request_bytes": request_bytes, "response_bytes": response_bytes}
    )


def clear_payload_sizes() -> None:
    """Clear payload sizes from context."""
    _payload_sizes.set(None)


class TraceInfo:
    """Container for trace context information"""

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        parent_span: str | None = None,
    ):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span = parent_span


class TraceContext:
    """Async-safe trace context using contextvars for proper async request correlation"""

    _current_trace: contextvars.ContextVar[TraceInfo | None] = contextvars.ContextVar(
        "current_trace", default=None
    )
    _propagated_headers: contextvars.ContextVar[dict[str, str] | None] = (
        contextvars.ContextVar("propagated_headers", default=None)
    )

    @classmethod
    def set_current(
        cls,
        trace_id: str,
        span_id: str,
        parent_span: str | None = None,
    ):
        """Set current trace context for this async context"""
        trace_info = TraceInfo(trace_id, span_id, parent_span)
        cls._current_trace.set(trace_info)

    @classmethod
    def get_current(cls) -> TraceInfo | None:
        """Get current trace context for this async context"""
        return cls._current_trace.get()

    @classmethod
    def clear_current(cls):
        """Clear current trace context"""
        cls._current_trace.set(None)

    @classmethod
    def get_propagated_headers(cls) -> dict[str, str]:
        """Get current propagated headers for this async context"""
        return cls._propagated_headers.get() or {}

    @classmethod
    def set_propagated_headers(cls, headers: dict[str, str]):
        """Set propagated headers for this async context"""
        cls._propagated_headers.set(headers)

    @classmethod
    def clear_propagated_headers(cls):
        """Clear propagated headers"""
        cls._propagated_headers.set({})

    @classmethod
    def generate_new(cls) -> TraceInfo:
        """Generate new trace context"""
        from .utils import generate_span_id, generate_trace_id

        trace_id = generate_trace_id()
        span_id = generate_span_id()
        return TraceInfo(trace_id, span_id)

    @classmethod
    def from_headers(cls, trace_id: str, parent_span: str | None = None) -> TraceInfo:
        """Create trace context from incoming request headers"""
        from .utils import generate_span_id

        span_id = generate_span_id()
        return TraceInfo(trace_id, span_id, parent_span)

    @classmethod
    def set_from_headers(cls, trace_id: str, parent_span: str | None = None):
        """Set current trace context from incoming request headers"""
        if trace_id:
            # Generate new span ID for this service, but keep the trace ID and parent span
            from .utils import generate_span_id

            span_id = generate_span_id()
            cls.set_current(trace_id, span_id, parent_span)
            return True
        return False
