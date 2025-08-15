"""
Trace context management for distributed tracing

Provides async-safe trace context storage using contextvars.
Inspired by the dev branch implementation but simplified for this feature branch.
"""

import contextvars
import os
import uuid
from typing import Optional


class TraceInfo:
    """Container for trace context information"""

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        parent_span: Optional[str] = None,
    ):
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span = parent_span


class TraceContext:
    """Async-safe trace context using contextvars for proper async request correlation"""

    _current_trace: contextvars.ContextVar[Optional[TraceInfo]] = (
        contextvars.ContextVar("current_trace", default=None)
    )

    @classmethod
    def set_current(
        cls,
        trace_id: str,
        span_id: str,
        parent_span: Optional[str] = None,
    ):
        """Set current trace context for this async context"""
        trace_info = TraceInfo(trace_id, span_id, parent_span)
        cls._current_trace.set(trace_info)

    @classmethod
    def get_current(cls) -> Optional[TraceInfo]:
        """Get current trace context for this async context"""
        return cls._current_trace.get()

    @classmethod
    def clear_current(cls):
        """Clear current trace context"""
        cls._current_trace.set(None)

    @classmethod
    def generate_new(cls) -> TraceInfo:
        """Generate new trace context"""
        from .utils import generate_span_id, generate_trace_id

        trace_id = generate_trace_id()
        span_id = generate_span_id()
        return TraceInfo(trace_id, span_id)

    @classmethod
    def from_headers(
        cls, trace_id: str, parent_span: Optional[str] = None
    ) -> TraceInfo:
        """Create trace context from incoming request headers"""
        from .utils import generate_span_id

        span_id = generate_span_id()
        return TraceInfo(trace_id, span_id, parent_span)

    @classmethod
    def set_from_headers(cls, trace_id: str, parent_span: Optional[str] = None):
        """Set current trace context from incoming request headers"""
        if trace_id:
            # Generate new span ID for this service, but keep the trace ID and parent span
            from .utils import generate_span_id

            span_id = generate_span_id()
            cls.set_current(trace_id, span_id, parent_span)
            return True
        return False
