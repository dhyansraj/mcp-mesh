"""Self-dependency proxy for direct function calls within the same process."""

import inspect
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
        # Per-call ``headers=`` is transport metadata, never a tool argument —
        # popped exactly as ``UnifiedMCPProxy.__call__`` pops it (issue #1593).
        # A self-call has no wire, so the headers apply as this invocation's
        # propagated-header scope, which is what a remote callee would see.
        per_call_headers = kwargs.pop("headers", None)
        scoped_headers = self._scoped_headers(per_call_headers)

        self.logger.info(
            f"🔄 SELF-CALL: Direct invocation of '{self.function_name}' (bypassing HTTP)"
        )
        self.logger.debug(f"🔄 Direct call args: {kwargs}")

        if scoped_headers is None:
            return self._invoke(kwargs)

        from ..tracing.context import TraceContext

        previous = TraceContext.get_propagated_headers()
        TraceContext.set_propagated_headers(scoped_headers)
        try:
            result = self._invoke(kwargs)
        finally:
            TraceContext.set_propagated_headers(previous)
        if inspect.isawaitable(result):
            # An async target runs when the caller awaits it, after this frame
            # has restored the outer scope — re-enter the scope for that await.
            return self._await_in_scope(result, scoped_headers)
        return result

    @staticmethod
    def _scoped_headers(per_call_headers: dict[str, str] | None) -> dict | None:
        """Propagated headers for this call, merged the way the remote proxy
        merges per-call headers: allowlist-filtered, keys lowercased, per-call
        wins, and the inbound-only dispatch headers scrubbed (#1570).
        ``None`` when there is nothing to apply."""
        if not per_call_headers:
            return None
        from ..tracing.context import (
            DISPATCH_HEADERS,
            TraceContext,
            matches_propagate_header,
        )

        merged = dict(TraceContext.get_propagated_headers())
        for key, value in per_call_headers.items():
            if matches_propagate_header(key):
                merged[key.lower()] = value
        for dispatch_only in DISPATCH_HEADERS:
            merged.pop(dispatch_only, None)
        return merged

    @staticmethod
    async def _await_in_scope(awaitable: Any, headers: dict[str, str]) -> Any:
        from ..tracing.context import TraceContext

        previous = TraceContext.get_propagated_headers()
        TraceContext.set_propagated_headers(headers)
        try:
            return await awaitable
        finally:
            TraceContext.set_propagated_headers(previous)

    def _invoke(self, kwargs: dict) -> Any:
        """Run the original function under self-dependency tracing."""
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
            # Loop-aware publish (issue #1363): a self-dependency consumed by an
            # async tool or @mesh.route handler runs this __call__ synchronously
            # ON the event-loop thread, so a blocking Redis publish would stall
            # the loop when telemetry Redis is unreachable. end_execution_loop_aware
            # offloads the publish when a running loop is detected and falls back
            # to the blocking path only when genuinely off-loop.
            tracer.end_execution_loop_aware(result, success=True)

            self.logger.info(
                f"✅ SELF-CALL: Direct call to '{self.function_name}' succeeded"
            )
            self.logger.debug(f"✅ Direct call result: {type(result)} {result}")
            return result

        except Exception as e:
            tracer.end_execution_loop_aware(error=str(e), success=False)
            self.logger.error(
                f"❌ SELF-CALL: Direct call to '{self.function_name}' failed: {e}"
            )
            raise RuntimeError(
                f"Self-dependency call to '{self.function_name}' failed: {e}"
            )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"SelfDependencyProxy(function_name='{self.function_name}', original_func={self.original_func})"
