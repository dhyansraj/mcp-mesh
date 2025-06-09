"""Signal handling for graceful shutdown and process cleanup."""

import asyncio
import atexit
import os
import signal
import sys
import threading
import time
import weakref
from collections.abc import Callable

from .logging import get_logger
from .process_tracker import get_process_tracker


class ProcessCleanupManager:
    """Manages cleanup of child processes and resources on shutdown."""

    def __init__(self):
        self.logger = get_logger("cli.cleanup_manager")
        self.cleanup_handlers: list[Callable[[], None]] = []
        self.child_processes: set[int] = set()
        self.shutdown_in_progress = False
        self.lock = threading.Lock()

        # Track running event loops for cleanup
        self.event_loops: list[weakref.ref] = []

        # Platform-specific signal handling
        self._setup_signal_handlers()
        self._setup_atexit_handler()

    def _setup_signal_handlers(self) -> None:
        """Setup platform-appropriate signal handlers."""
        try:
            # Unix-like systems (Linux, macOS)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, self._handle_termination_signal)
            if hasattr(signal, "SIGINT"):
                signal.signal(signal.SIGINT, self._handle_interrupt_signal)
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, self._handle_hangup_signal)

            # Windows-specific signals
            if sys.platform == "win32":
                if hasattr(signal, "SIGBREAK"):
                    signal.signal(signal.SIGBREAK, self._handle_termination_signal)

            self.logger.debug("Signal handlers installed successfully")

        except Exception as e:
            self.logger.warning(f"Failed to setup some signal handlers: {e}")

    def _setup_atexit_handler(self) -> None:
        """Setup atexit handler for final cleanup."""
        atexit.register(self._final_cleanup)
        self.logger.debug("Atexit handler registered")

    def _handle_termination_signal(self, signum: int, frame) -> None:
        """Handle SIGTERM for graceful shutdown."""
        self.logger.info(
            f"Received termination signal {signum}, initiating graceful shutdown"
        )
        self._initiate_graceful_shutdown(signum)

    def _handle_interrupt_signal(self, signum: int, frame) -> None:
        """Handle SIGINT (Ctrl+C) for graceful shutdown."""
        self.logger.info(
            f"Received interrupt signal {signum} (Ctrl+C), initiating graceful shutdown"
        )
        self._initiate_graceful_shutdown(signum)

    def _handle_hangup_signal(self, signum: int, frame) -> None:
        """Handle SIGHUP for graceful restart (Unix only)."""
        self.logger.info(
            f"Received hangup signal {signum}, initiating graceful restart"
        )
        # For now, treat as shutdown. Future enhancement could implement restart
        self._initiate_graceful_shutdown(signum)

    def _initiate_graceful_shutdown(self, signum: int) -> None:
        """Initiate graceful shutdown process."""
        with self.lock:
            if self.shutdown_in_progress:
                self.logger.warning("Shutdown already in progress, ignoring signal")
                return

            self.shutdown_in_progress = True

        self.logger.info("Starting graceful shutdown process")

        # Run cleanup in a separate thread to avoid blocking signal handler
        cleanup_thread = threading.Thread(
            target=self._execute_graceful_shutdown,
            args=(signum,),
            name="CleanupThread",
            daemon=True,
        )
        cleanup_thread.start()

        # Give cleanup thread time to work, then force exit if necessary
        cleanup_thread.join(timeout=30.0)

        if cleanup_thread.is_alive():
            self.logger.error("Graceful shutdown timed out, forcing exit")
            self._force_shutdown()
        else:
            self.logger.info("Graceful shutdown completed successfully")
            sys.exit(0)

    def _execute_graceful_shutdown(self, signum: int) -> None:
        """Execute the graceful shutdown process."""
        try:
            # Step 1: Stop accepting new requests/operations
            self.logger.debug("Step 1: Stopping new operations")

            # Step 2: Close event loops gracefully
            self.logger.debug("Step 2: Closing event loops")
            self._close_event_loops()

            # Step 3: Run registered cleanup handlers
            self.logger.debug("Step 3: Running cleanup handlers")
            self._run_cleanup_handlers()

            # Step 4: Terminate child processes
            self.logger.debug("Step 4: Terminating child processes")
            self._terminate_child_processes()

            # Step 5: Cleanup process tracker
            self.logger.debug("Step 5: Cleaning up process tracker")
            self._cleanup_process_tracker()

            self.logger.info("Graceful shutdown completed")

        except Exception as e:
            self.logger.error(f"Error during graceful shutdown: {e}")
            self._force_shutdown()

    def _close_event_loops(self) -> None:
        """Close any running asyncio event loops."""
        try:
            # Check for running event loop in current thread
            try:
                loop = asyncio.get_running_loop()
                if loop and not loop.is_closed():
                    self.logger.debug("Stopping current event loop")
                    loop.stop()
                    # Give it time to stop gracefully
                    time.sleep(0.5)
            except RuntimeError:
                # No event loop running in current thread
                pass

            # Clean up tracked event loops
            for loop_ref in self.event_loops[:]:
                loop = loop_ref()
                if loop and not loop.is_closed():
                    try:
                        if loop.is_running():
                            loop.call_soon_threadsafe(loop.stop)
                        time.sleep(0.1)
                    except Exception as e:
                        self.logger.warning(f"Failed to stop event loop: {e}")
                self.event_loops.remove(loop_ref)

        except Exception as e:
            self.logger.warning(f"Error closing event loops: {e}")

    def _run_cleanup_handlers(self) -> None:
        """Run all registered cleanup handlers."""
        for handler in self.cleanup_handlers[:]:
            try:
                self.logger.debug(f"Running cleanup handler: {handler.__name__}")
                handler()
            except Exception as e:
                self.logger.error(f"Cleanup handler {handler.__name__} failed: {e}")

    def _terminate_child_processes(self) -> None:
        """Terminate all tracked child processes."""
        process_tracker = get_process_tracker()

        try:
            # Get all tracked processes
            processes = process_tracker.get_all_processes()

            if processes:
                self.logger.info(f"Terminating {len(processes)} tracked processes")

                # Terminate all processes with timeout
                results = process_tracker.terminate_all_processes(timeout=10)

                successful = sum(1 for success in results.values() if success)
                self.logger.info(
                    f"Successfully terminated {successful}/{len(results)} processes"
                )

            # Also terminate any additional child processes we're tracking
            self._terminate_additional_children()

        except Exception as e:
            self.logger.error(f"Error terminating child processes: {e}")

    def _terminate_additional_children(self) -> None:
        """Terminate additional child processes tracked separately."""
        if not self.child_processes:
            return

        import psutil

        for pid in list(self.child_processes):
            try:
                process = psutil.Process(pid)
                if process.is_running():
                    self.logger.debug(f"Terminating additional child process {pid}")
                    process.terminate()

                    # Wait for graceful termination
                    try:
                        process.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        # Force kill if needed
                        self.logger.warning(f"Force killing child process {pid}")
                        process.kill()
                        process.wait(timeout=2)

                self.child_processes.discard(pid)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process already gone or can't access it
                self.child_processes.discard(pid)
            except Exception as e:
                self.logger.warning(f"Failed to terminate child process {pid}: {e}")

    def _cleanup_process_tracker(self) -> None:
        """Clean up process tracker state."""
        try:
            process_tracker = get_process_tracker()

            # Clean up dead processes
            dead_processes = process_tracker.cleanup_dead_processes()
            if dead_processes:
                self.logger.debug(f"Cleaned up {len(dead_processes)} dead processes")

        except Exception as e:
            self.logger.warning(f"Error cleaning up process tracker: {e}")

    def _force_shutdown(self) -> None:
        """Force immediate shutdown when graceful shutdown fails."""
        self.logger.warning("Forcing immediate shutdown")

        try:
            # Try to kill any remaining child processes
            import psutil

            current_process = psutil.Process()
            children = current_process.children(recursive=True)

            for child in children:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

        os._exit(1)

    def _final_cleanup(self) -> None:
        """Final cleanup called by atexit handler."""
        if not self.shutdown_in_progress:
            self.logger.debug("Final cleanup: terminating any remaining processes")
            self._terminate_child_processes()

    def register_cleanup_handler(self, handler: Callable[[], None]) -> None:
        """Register a cleanup handler to be called on shutdown."""
        self.cleanup_handlers.append(handler)
        self.logger.debug(f"Registered cleanup handler: {handler.__name__}")

    def unregister_cleanup_handler(self, handler: Callable[[], None]) -> None:
        """Unregister a cleanup handler."""
        if handler in self.cleanup_handlers:
            self.cleanup_handlers.remove(handler)
            self.logger.debug(f"Unregistered cleanup handler: {handler.__name__}")

    def track_child_process(self, pid: int) -> None:
        """Track an additional child process for cleanup."""
        self.child_processes.add(pid)
        self.logger.debug(f"Tracking child process {pid}")

    def untrack_child_process(self, pid: int) -> None:
        """Stop tracking a child process."""
        self.child_processes.discard(pid)
        self.logger.debug(f"Stopped tracking child process {pid}")

    def track_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Track an event loop for cleanup."""
        self.event_loops.append(weakref.ref(loop))
        self.logger.debug("Tracking event loop for cleanup")

    def is_shutdown_in_progress(self) -> bool:
        """Check if shutdown is currently in progress."""
        return self.shutdown_in_progress


# Global cleanup manager instance
_cleanup_manager: ProcessCleanupManager | None = None


def get_cleanup_manager() -> ProcessCleanupManager:
    """Get the global cleanup manager instance."""
    global _cleanup_manager
    if _cleanup_manager is None:
        _cleanup_manager = ProcessCleanupManager()
    return _cleanup_manager


def install_signal_handlers() -> ProcessCleanupManager:
    """Install signal handlers and return cleanup manager."""
    return get_cleanup_manager()


def register_cleanup_handler(handler: Callable[[], None]) -> None:
    """Register a cleanup handler."""
    get_cleanup_manager().register_cleanup_handler(handler)


def track_child_process(pid: int) -> None:
    """Track a child process for cleanup."""
    get_cleanup_manager().track_child_process(pid)


def track_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Track an event loop for cleanup."""
    get_cleanup_manager().track_event_loop(loop)


__all__ = [
    "ProcessCleanupManager",
    "get_cleanup_manager",
    "install_signal_handlers",
    "register_cleanup_handler",
    "track_child_process",
    "track_event_loop",
]
