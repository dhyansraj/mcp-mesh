"""Self-dependency proxy for direct function calls within the same process."""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class SelfDependencyProxy:
    """Proxy for self-dependencies that calls original functions directly.

    This proxy is used when a function needs to call another function within
    the same agent/process. It bypasses HTTP/MCP protocol and calls the
    original Python function directly to avoid deadlock issues.

    The original function reference is cached at proxy creation time for
    maximum performance - no runtime lookups or searches.
    """

    def __init__(self, original_func: Callable, function_name: str):
        """Initialize self-dependency proxy with cached function reference.

        Args:
            original_func: The original Python function to call directly
            function_name: Name of the function for logging/debugging
        """
        if not callable(original_func):
            raise ValueError(
                f"original_func must be callable, got {type(original_func)}"
            )

        self.original_func = original_func
        self.function_name = function_name
        self.logger = logger.getChild(f"self_proxy.{function_name}")

        self.logger.info(
            f"🔄 Created SelfDependencyProxy for '{function_name}' -> {original_func.__name__}"
        )

    def __call__(self, **kwargs) -> Any:
        """Call the original function directly with provided arguments.

        This is the fastest possible path - direct function invocation
        with no conditionals, searches, or protocol overhead.
        """
        self.logger.info(
            f"🔄 SELF-CALL: Direct invocation of '{self.function_name}' (bypassing HTTP)"
        )
        self.logger.debug(f"🔄 Direct call args: {kwargs}")

        # ===== EXECUTE WITH SELF-DEPENDENCY TRACING =====
        from ..tracing.execution_tracer import ExecutionTracer

        try:
            # Use helper class for clean execution tracing with self-dependency marker
            tracer = ExecutionTracer(self.function_name, self.logger)
            tracer.start_execution(
                (), kwargs, dependencies=[], mesh_positions=[], injected_count=0
            )

            # Add self-dependency marker to metadata
            tracer.execution_metadata["call_type"] = "self_dependency"

            result = self.original_func(**kwargs)
            tracer.end_execution(result, success=True)

            self.logger.info(
                f"✅ SELF-CALL: Direct call to '{self.function_name}' succeeded"
            )
            self.logger.debug(f"✅ Direct call result: {type(result)} {result}")
            return result

        except Exception as e:
            tracer.end_execution(error=str(e), success=False)
            self.logger.error(
                f"❌ SELF-CALL: Direct call to '{self.function_name}' failed: {e}"
            )
            raise RuntimeError(
                f"Self-dependency call to '{self.function_name}' failed: {e}"
            )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"SelfDependencyProxy(function_name='{self.function_name}', original_func={self.original_func})"
