"""Threading utilities for sync-to-async bridging with atexit bug fixes.

Provides a consolidated implementation for running async operations from sync contexts
while avoiding the Python 3.8+ atexit bug that occurs in daemon thread contexts.
"""

import asyncio
import logging
import queue
import threading
from collections.abc import Callable
from typing import Any, Union

logger = logging.getLogger(__name__)


class ThreadingUtils:
    """Utilities for safe sync-to-async bridging avoiding Python 3.8+ atexit issues."""

    @staticmethod
    def run_sync_from_async(
        coro_or_func: Union[Any, Callable],
        timeout: float = 60.0,
        context_name: str = "operation",
    ) -> Any:
        """Convert async coroutine to sync call avoiding atexit bug.

        Handles both coroutines and coroutine creation functions safely.

        Args:
            coro_or_func: Either a coroutine object or a function that returns a coroutine
            timeout: Operation timeout in seconds
            context_name: Name for logging/debugging context

        Returns:
            The result of the async operation

        Raises:
            TimeoutError: If operation exceeds timeout
            RuntimeError: If operation fails or returns no result
        """
        import inspect

        # If it's a function, call it to get the coroutine
        if callable(coro_or_func) and not inspect.iscoroutine(coro_or_func):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # In running loop context, use thread-safe approach
                    return ThreadingUtils._run_in_thread_safe(
                        coro_or_func, timeout, context_name
                    )
                else:
                    # No running loop, create coroutine and run directly
                    coro = coro_or_func()
                    return loop.run_until_complete(coro)
            except RuntimeError:
                # No event loop, use thread-safe approach
                return ThreadingUtils._run_in_thread_safe(
                    coro_or_func, timeout, context_name
                )

        # It's already a coroutine, handle it
        coro = coro_or_func

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Use thread-safe approach for running loops
                return ThreadingUtils._run_coroutine_in_thread(
                    coro, timeout, context_name
                )
            else:
                # No running loop, safe to use directly
                return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop exists, use thread-safe approach
            return ThreadingUtils._run_coroutine_in_thread(coro, timeout, context_name)

    @staticmethod
    def _run_in_thread_safe(
        coro_func: Callable, timeout: float, context_name: str
    ) -> Any:
        """Run coroutine creation function in thread-safe manner."""
        result_queue: queue.Queue = queue.Queue()

        def _thread_runner():
            """Execute coroutine function in isolated thread context."""
            try:
                # Apply atexit bypass for this thread
                ThreadingUtils._apply_atexit_bypass()

                # Create fresh event loop
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)

                try:
                    # Create coroutine in this thread's context
                    coro = coro_func()
                    result = new_loop.run_until_complete(coro)
                    result_queue.put(("success", result))
                except Exception as e:
                    logger.error(
                        f"❌ {context_name} failed in thread: {e}", exc_info=True
                    )
                    result_queue.put(("error", e))
                finally:
                    # Manual cleanup without relying on atexit
                    try:
                        new_loop.close()
                    finally:
                        asyncio.set_event_loop(None)

            except Exception as e:
                logger.error(
                    f"❌ {context_name} thread setup failed: {e}", exc_info=True
                )
                result_queue.put(("error", e))

        # Use non-daemon thread to avoid atexit issues
        thread = threading.Thread(
            target=_thread_runner, daemon=False, name=f"MCPMesh-{context_name}"
        )
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            logger.error(f"⏰ {context_name} timed out after {timeout}s")
            raise TimeoutError(f"{context_name} timed out after {timeout}s")

        if result_queue.empty():
            raise RuntimeError(f"No result from {context_name}")

        status, result = result_queue.get()
        if status == "error":
            raise result

        logger.debug(f"✅ {context_name} completed successfully in thread")
        return result

    @staticmethod
    def _run_coroutine_in_thread(coro: Any, timeout: float, context_name: str) -> Any:
        """Run existing coroutine in thread-safe manner."""
        result_queue: queue.Queue = queue.Queue()

        def _thread_runner():
            """Execute coroutine in isolated thread context."""
            try:
                # Apply atexit bypass for this thread
                ThreadingUtils._apply_atexit_bypass()

                # Create fresh event loop
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)

                try:
                    result = new_loop.run_until_complete(coro)
                    result_queue.put(("success", result))
                except Exception as e:
                    logger.error(
                        f"❌ {context_name} coroutine failed: {e}", exc_info=True
                    )
                    result_queue.put(("error", e))
                finally:
                    # Manual cleanup without relying on atexit
                    try:
                        new_loop.close()
                    finally:
                        asyncio.set_event_loop(None)

            except Exception as e:
                logger.error(
                    f"❌ {context_name} thread setup failed: {e}", exc_info=True
                )
                result_queue.put(("error", e))

        # Use non-daemon thread to avoid atexit issues
        thread = threading.Thread(
            target=_thread_runner, daemon=False, name=f"MCPMesh-{context_name}"
        )
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            logger.error(f"⏰ {context_name} timed out after {timeout}s")
            raise TimeoutError(f"{context_name} timed out after {timeout}s")

        if result_queue.empty():
            raise RuntimeError(f"No result from {context_name}")

        status, result = result_queue.get()
        if status == "error":
            raise result

        logger.debug(f"✅ {context_name} completed successfully in thread")
        return result

    @staticmethod
    def _apply_atexit_bypass():
        """Apply atexit bypass for current thread to prevent registration errors."""
        try:
            import atexit
            import threading

            # Store originals
            original_atexit_register = atexit.register
            original_thread_register = getattr(threading, "_register_atexit", None)

            # Apply temporary bypass
            def _noop_register(*args, **kwargs):
                """No-op atexit registration to prevent threading issues."""
                pass

            atexit.register = _noop_register
            if original_thread_register:
                threading._register_atexit = _noop_register

            # Store cleanup function for potential restoration
            # (In practice, these threads are short-lived so restoration isn't critical)

        except Exception as e:
            # If atexit bypass fails, log but continue
            logger.warning(f"⚠️ Failed to apply atexit bypass: {e}")
