"""
FastAPI Tracing Middleware - Dedicated route-level tracing for FastAPI applications.

This middleware provides clean separation from MCP agent tracing while ensuring
FastAPI routes get comprehensive execution tracking and distributed tracing support.
"""

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class FastAPITracingMiddleware(BaseHTTPMiddleware):
    """Dedicated tracing middleware for FastAPI routes.

    Provides route-level execution tracing with:
    - Performance monitoring (request duration)
    - Distributed tracing context setup
    - Redis trace publishing
    - Route name extraction
    - Zero overhead when tracing disabled
    """

    def __init__(self, app, logger_instance: logging.Logger = None):
        super().__init__(app)
        self.logger = logger_instance or logger

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process FastAPI request with comprehensive tracing."""

        # If tracing is disabled, process request directly with zero overhead
        from .utils import is_tracing_enabled

        if not is_tracing_enabled():
            return await call_next(request)


        # Setup distributed tracing context from request headers
        try:
            from .trace_context_helper import TraceContextHelper

            # Extract trace context from request headers
            trace_context = await TraceContextHelper.extract_trace_context_from_request(
                request
            )


            # Setup trace context for this request lifecycle
            TraceContextHelper.setup_request_trace_context(trace_context, self.logger)

        except Exception as e:
            # Never fail request due to tracing issues
            pass

        # Extract route information for tracing
        route_name = self._extract_route_name(request)
        start_time = time.time()


        try:
            # Process the request
            response = await call_next(request)

            # Calculate performance metrics
            end_time = time.time()
            duration_ms = round((end_time - start_time) * 1000, 2)

            # Publish route execution trace
            self._publish_route_trace(
                route_name=route_name,
                request_method=request.method,
                request_path=str(request.url.path),
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                success=True,
                status_code=response.status_code,
            )


            return response

        except Exception as e:
            # Calculate performance metrics for failed request
            end_time = time.time()
            duration_ms = round((end_time - start_time) * 1000, 2)

            # Publish failed route execution trace
            self._publish_route_trace(
                route_name=route_name,
                request_method=request.method,
                request_path=str(request.url.path),
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                success=False,
                error=str(e),
            )


            raise  # Re-raise the original exception

    def _extract_route_name(self, request: Request) -> str:
        """Extract meaningful route name for tracing."""
        try:
            # Try to get route from FastAPI request state
            if hasattr(request, "scope") and "route" in request.scope:
                route = request.scope["route"]
                if hasattr(route, "path"):
                    return f"{request.method} {route.path}"

            # Fallback to URL path
            path = str(request.url.path)
            return f"{request.method} {path}"

        except Exception as e:
            self.logger.debug(f"Failed to extract route name: {e}")
            return f"{request.method} {request.url.path}"

    def _publish_route_trace(
        self,
        route_name: str,
        request_method: str,
        request_path: str,
        start_time: float,
        end_time: float,
        duration_ms: float,
        success: bool,
        status_code: int = None,
        error: str = None,
    ) -> None:
        """Publish route execution trace to Redis."""
        try:
            from .context import TraceContext
            from .redis_metadata_publisher import get_trace_publisher

            # Get current trace context
            current_trace = TraceContext.get_current()

            if not current_trace:
                return

            # Generate a unique span ID for this route execution
            from .utils import generate_span_id

            route_span_id = generate_span_id()

            # Build route execution metadata
            execution_metadata = {
                "function_name": route_name,
                "route_name": route_name,
                "request_method": request_method,
                "request_path": request_path,
                "start_time": start_time,
                "end_time": end_time,
                "duration_ms": duration_ms,
                "success": success,
                "error": error,
                "status_code": status_code,
                "trace_id": current_trace.trace_id,
                "span_id": route_span_id,
                "parent_span": (
                    current_trace.span_id
                    if current_trace.parent_span is not None
                    else None
                ),
                "call_context": "fastapi_route_execution",
                "agent_type": "fastapi_app",
            }

            # Add agent context metadata
            from .utils import get_agent_metadata_with_fallback

            agent_metadata = get_agent_metadata_with_fallback(self.logger)
            # Override with FastAPI-specific values if fallback was used
            if agent_metadata.get("agent_id") == "unknown":
                agent_metadata.update(
                    {"agent_id": "fastapi_app", "agent_name": "fastapi_app"}
                )
            execution_metadata.update(agent_metadata)

            # Publish to Redis
            from .utils import publish_trace_with_fallback

            publish_trace_with_fallback(execution_metadata, self.logger)

        except Exception as e:
            # Never fail requests due to trace publishing
            pass


def get_fastapi_tracing_middleware() -> FastAPITracingMiddleware:
    """Get FastAPI tracing middleware instance.

    Returns:
        Configured FastAPITracingMiddleware instance
    """
    return FastAPITracingMiddleware
