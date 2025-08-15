"""
Trace Context Helper - Helper class for HTTP request trace context setup.

This class encapsulates all the trace context setup logic to keep HTTP wrappers clean.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TraceContextHelper:
    """Helper class to handle HTTP request trace context setup and distributed tracing."""

    @staticmethod
    def setup_request_trace_context(
        trace_context: dict[str, Any], logger_instance: logging.Logger
    ) -> None:
        """
        Setup trace context for incoming HTTP request.

        Handles both existing distributed traces and new root traces with proper logging.
        If tracing is disabled, this function returns immediately without setting up trace context.
        """
        # If tracing is disabled, skip all trace context setup
        from .utils import is_tracing_enabled

        if not is_tracing_enabled():
            return

        try:
            from .context import TraceContext

            # Check if we have a valid trace_id (not None and not empty)
            extracted_trace_id = trace_context.get("trace_id")
            if extracted_trace_id and extracted_trace_id.strip():
                # EXISTING TRACE: This service is being called by another service
                from .utils import generate_span_id

                current_span_id = generate_span_id()
                parent_span_id = trace_context.get("parent_span")

                # Set context that will be used throughout request lifecycle
                TraceContext.set_current(
                    trace_id=extracted_trace_id,
                    span_id=current_span_id,
                    parent_span=parent_span_id,
                )
            else:
                # NEW ROOT TRACE: This service is the entry point (no incoming trace headers)
                from .utils import generate_span_id, generate_trace_id

                root_trace_id = generate_trace_id()
                root_span_id = generate_span_id()

                # Set context for root trace (no parent_span)
                TraceContext.set_current(
                    trace_id=root_trace_id,
                    span_id=root_span_id,
                    parent_span=None,  # Root trace has no parent
                )

        except Exception as e:
            logger_instance.warning(f"Failed to setup trace context: {e}")
            raise  # Re-raise to maintain error handling behavior

    @staticmethod
    def extract_trace_headers(headers: dict[str, str]) -> dict[str, Optional[str]]:
        """
        Extract trace headers from HTTP request headers.

        Returns standardized trace context dictionary.
        """
        return {
            "trace_id": headers.get("X-Trace-ID"),
            "parent_span": headers.get("X-Parent-Span"),
        }

    @staticmethod
    async def extract_trace_context_from_request(request) -> dict[str, Any]:
        """
        Extract trace context from HTTP request headers and body for distributed tracing.

        This method tries multiple extraction methods:
        1. HTTP headers (X-Trace-ID, X-Parent-Span)
        2. JSON-RPC body arguments as fallback

        Returns a dictionary with trace context information.
        """
        # Extract trace headers first
        trace_id = request.headers.get("X-Trace-ID")
        parent_span = request.headers.get("X-Parent-Span")

        # Try extracting from JSON-RPC body as fallback
        if not trace_id:
            try:
                body = await request.body()
                if body:
                    payload = json.loads(body.decode("utf-8"))
                    if payload.get("method") == "tools/call":
                        arguments = payload.get("params", {}).get("arguments", {})
                        trace_id = arguments.get("trace_id")
                        parent_span = arguments.get("parent_span")
            except Exception:
                pass

        return {
            "trace_id": trace_id,
            "parent_span": parent_span,
            "method": request.method,
            "path": request.url.path,
        }

    @staticmethod
    def propagate_trace_headers(trace_context: Optional[Any] = None) -> dict[str, str]:
        """
        Generate trace headers for outgoing HTTP requests.

        Creates headers for trace context propagation to downstream services.
        """
        try:
            from .context import TraceContext

            if trace_context is None:
                trace_context = TraceContext.get_current()

            if trace_context:
                return {
                    "X-Trace-ID": trace_context.trace_id,
                    "X-Parent-Span": trace_context.span_id,  # Current span becomes parent for downstream
                }
            else:
                return {}

        except Exception as e:
            logger.warning(f"Failed to generate trace headers: {e}")
            return {}

    @staticmethod
    def inject_trace_headers_to_request(
        headers: dict[str, str], endpoint_url: str, logger_instance: logging.Logger
    ) -> None:
        """
        Inject trace headers into outgoing HTTP request headers.

        Handles trace context propagation for distributed tracing with proper logging.
        If tracing is disabled, this function returns immediately without modifying headers.
        """
        # If tracing is disabled, skip all trace header injection
        from .utils import is_tracing_enabled

        if not is_tracing_enabled():
            return

        try:
            from .context import TraceContext

            trace_context = TraceContext.get_current()
            if trace_context:
                headers["X-Trace-ID"] = trace_context.trace_id
                headers["X-Parent-Span"] = trace_context.span_id
        except Exception as e:
            # Tracing injection should never break MCP calls
            pass
