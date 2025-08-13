"""
Execution Tracer - Helper class for function execution logging and Redis metadata preparation.

This class encapsulates all the execution logging logic to keep the dependency injector clean.
"""

import logging
import os
import time
from collections.abc import Callable
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _is_tracing_enabled() -> bool:
    """Check if distributed tracing is enabled via environment variable."""
    return os.getenv("MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


class ExecutionTracer:
    """Helper class to handle function execution tracing and Redis metadata preparation."""

    def __init__(self, function_name: str, logger_instance: logging.Logger):
        self.function_name = function_name
        self.logger = logger_instance
        self.start_time: Optional[float] = None
        self.trace_context: Optional[Any] = None
        self.execution_metadata: dict = {}

    def start_execution(
        self,
        args: tuple,
        kwargs: dict,
        dependencies: list[str],
        mesh_positions: list[int],
        injected_count: int = 0,
    ) -> None:
        """Start execution tracking and log function start."""
        try:
            from .context import TraceContext

            self.start_time = time.time()
            self.trace_context = TraceContext.get_current()

            # Build execution metadata for future Redis storage
            self.execution_metadata = {
                "function_name": self.function_name,
                "start_time": self.start_time,
                "args_count": len(args),
                "kwargs_count": len(kwargs),
                "injected_dependencies": injected_count,
                "dependencies": dependencies,
                "mesh_positions": mesh_positions,
            }

            # Add agent context metadata for distributed tracing
            try:
                from .agent_context_helper import get_trace_metadata

                agent_metadata = get_trace_metadata()
                self.execution_metadata.update(agent_metadata)
            except Exception as e:
                # Never fail execution due to agent metadata collection
                self.logger.debug(f"Failed to get agent metadata: {e}")
                # Add minimal fallback metadata
                self.execution_metadata.update(
                    {
                        "agent_id": "unknown",
                        "agent_name": "unknown",
                        "agent_hostname": "unknown",
                        "agent_ip": "unknown",
                    }
                )

            if self.trace_context:
                self.execution_metadata.update(
                    {
                        "trace_id": self.trace_context.trace_id,
                        "span_id": self.trace_context.span_id,
                        "parent_span": self.trace_context.parent_span,
                    }
                )

        except Exception as e:
            self.logger.warning(
                f"Failed to setup execution logging for {self.function_name}: {e}"
            )

    def end_execution(
        self, result: Any = None, success: bool = True, error: Optional[str] = None
    ) -> None:
        """End execution tracking and log function completion."""
        try:
            if not self.start_time:
                return

            end_time = time.time()
            duration = end_time - self.start_time

            # Update execution metadata with results
            self.execution_metadata.update(
                {
                    "end_time": end_time,
                    "duration_ms": round(duration * 1000, 2),
                    "success": success,
                    "error": error,
                    "result_type": (
                        str(type(result).__name__) if result is not None else "None"
                    ),
                }
            )

            # Save execution trace to Redis for distributed tracing storage
            try:
                from .redis_metadata_publisher import get_trace_publisher

                publisher = get_trace_publisher()
                if publisher.is_available:
                    publisher.publish_execution_trace(self.execution_metadata)
            except Exception as e:
                # Never fail agent operations due to trace publishing
                pass

        except Exception as e:
            self.logger.warning(
                f"Failed to complete execution logging for {self.function_name}: {e}"
            )

    @staticmethod
    def trace_function_execution(
        func: Callable,
        args: tuple,
        kwargs: dict,
        dependencies: list[str],
        mesh_positions: list[int],
        injected_count: int,
        logger_instance: logging.Logger,
    ) -> Any:
        """
        Trace function execution with comprehensive logging.

        This is a static method that handles the complete execution flow with proper
        exception handling and cleanup. If tracing is disabled, calls function directly.
        """
        # If tracing is disabled, call function directly without any overhead
        if not _is_tracing_enabled():
            return func(*args, **kwargs)

        tracer = ExecutionTracer(func.__name__, logger_instance)
        tracer.start_execution(
            args, kwargs, dependencies, mesh_positions, injected_count
        )

        try:
            result = func(*args, **kwargs)
            tracer.end_execution(result, success=True)
            return result
        except Exception as e:
            tracer.end_execution(error=str(e), success=False)
            raise  # Re-raise the exception

    @staticmethod
    def trace_original_function(
        func: Callable, args: tuple, kwargs: dict, logger_instance: logging.Logger
    ) -> Any:
        """
        Trace execution of original function (without dependencies) with comprehensive logging.

        This is used for functions that don't have dependencies but still need execution logging.
        If tracing is disabled, calls function directly.
        """
        # If tracing is disabled, call function directly without any overhead
        if not _is_tracing_enabled():
            return func(*args, **kwargs)

        tracer = ExecutionTracer(func.__name__, logger_instance)
        tracer.start_execution(
            args, kwargs, dependencies=[], mesh_positions=[], injected_count=0
        )

        try:
            result = func(*args, **kwargs)
            tracer.end_execution(result, success=True)
            return result
        except Exception as e:
            tracer.end_execution(error=str(e), success=False)
            raise  # Re-raise the exception

    @staticmethod
    async def trace_function_execution_async(
        func: Callable,
        args: tuple,
        kwargs: dict,
        dependencies: list[str],
        mesh_positions: list[int],
        injected_count: int,
        logger_instance: logging.Logger,
    ) -> Any:
        """
        Trace async function execution with comprehensive logging.

        This is a static method that handles the complete execution flow with proper
        exception handling and cleanup. If tracing is disabled, calls function directly.
        """
        import inspect
        
        # If tracing is disabled, call function directly without any overhead
        if not _is_tracing_enabled():
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        tracer = ExecutionTracer(func.__name__, logger_instance)
        tracer.start_execution(
            args, kwargs, dependencies, mesh_positions, injected_count
        )

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            tracer.end_execution(result, success=True)
            return result
        except Exception as e:
            tracer.end_execution(error=str(e), success=False)
            raise  # Re-raise the exception
