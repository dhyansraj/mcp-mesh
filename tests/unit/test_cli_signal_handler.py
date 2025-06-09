"""Unit tests for CLI signal handler."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler import (
    ProcessCleanupManager,
    get_cleanup_manager,
    install_signal_handlers,
    register_cleanup_handler,
    track_child_process,
    track_event_loop,
)


class TestProcessCleanupManager:
    """Test ProcessCleanupManager functionality."""

    def test_cleanup_manager_creation(self):
        """Test cleanup manager initialization."""
        manager = ProcessCleanupManager()
        assert manager.cleanup_handlers == []
        assert manager.child_processes == set()
        assert manager.shutdown_in_progress is False

    def test_register_cleanup_handler(self):
        """Test registering cleanup handlers."""
        manager = ProcessCleanupManager()

        mock_cleanup = MagicMock()
        manager.register_cleanup_handler(mock_cleanup)

        assert len(manager.cleanup_handlers) == 1
        assert manager.cleanup_handlers[0] == mock_cleanup

    def test_register_multiple_cleanup_handlers(self):
        """Test registering multiple cleanup handlers."""
        manager = ProcessCleanupManager()

        mock_cleanup1 = MagicMock()
        mock_cleanup2 = MagicMock()

        manager.register_cleanup_handler(mock_cleanup1)
        manager.register_cleanup_handler(mock_cleanup2)

        assert len(manager.cleanup_handlers) == 2
        assert mock_cleanup1 in manager.cleanup_handlers
        assert mock_cleanup2 in manager.cleanup_handlers

    def test_unregister_cleanup_handler(self):
        """Test unregistering cleanup handlers."""
        manager = ProcessCleanupManager()

        mock_cleanup = MagicMock()
        manager.register_cleanup_handler(mock_cleanup)
        manager.unregister_cleanup_handler(mock_cleanup)

        assert len(manager.cleanup_handlers) == 0

    def test_track_child_process(self):
        """Test tracking child processes."""
        manager = ProcessCleanupManager()

        manager.track_child_process(12345)
        assert 12345 in manager.child_processes

        manager.track_child_process(12346)
        assert 12346 in manager.child_processes
        assert len(manager.child_processes) == 2

    def test_untrack_child_process(self):
        """Test untracking child processes."""
        manager = ProcessCleanupManager()

        manager.track_child_process(12345)
        manager.untrack_child_process(12345)

        assert 12345 not in manager.child_processes

    def test_track_event_loop(self):
        """Test tracking event loops."""
        manager = ProcessCleanupManager()

        mock_loop = MagicMock()
        manager.track_event_loop(mock_loop)

        # Should have one weak reference
        assert len(manager.event_loops) == 1

    def test_is_shutdown_in_progress(self):
        """Test checking shutdown status."""
        manager = ProcessCleanupManager()

        assert not manager.is_shutdown_in_progress()

        manager.shutdown_in_progress = True
        assert manager.is_shutdown_in_progress()

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.signal.signal"
    )
    def test_signal_handler_setup(self, mock_signal):
        """Test signal handler setup."""
        manager = ProcessCleanupManager()

        # Should have attempted to set up signal handlers
        mock_signal.assert_called()

    def test_cleanup_handler_execution(self):
        """Test cleanup handler execution."""
        manager = ProcessCleanupManager()

        mock_cleanup1 = MagicMock()
        mock_cleanup2 = MagicMock()

        manager.register_cleanup_handler(mock_cleanup1)
        manager.register_cleanup_handler(mock_cleanup2)

        # Execute cleanup handlers
        manager._run_cleanup_handlers()

        mock_cleanup1.assert_called_once()
        mock_cleanup2.assert_called_once()

    def test_cleanup_handler_exception_handling(self):
        """Test handling exceptions in cleanup handlers."""
        manager = ProcessCleanupManager()

        # Create a cleanup handler that raises an exception
        def failing_cleanup():
            raise RuntimeError("Cleanup failed")

        mock_successful_cleanup = MagicMock()

        manager.register_cleanup_handler(failing_cleanup)
        manager.register_cleanup_handler(mock_successful_cleanup)

        # Should not crash even with failing cleanup
        manager._run_cleanup_handlers()

        # Successful cleanup should still be called
        mock_successful_cleanup.assert_called_once()

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.get_process_tracker"
    )
    def test_terminate_child_processes(self, mock_get_tracker):
        """Test terminating child processes."""
        manager = ProcessCleanupManager()

        # Mock process tracker
        mock_tracker = MagicMock()
        mock_tracker.get_all_processes.return_value = {"test_process": MagicMock()}
        mock_tracker.terminate_all_processes.return_value = {"test_process": True}
        mock_get_tracker.return_value = mock_tracker

        manager._terminate_child_processes()

        mock_tracker.terminate_all_processes.assert_called_once()

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.psutil.Process"
    )
    def test_terminate_additional_children(self, mock_process_class):
        """Test terminating additional child processes."""
        manager = ProcessCleanupManager()

        # Add a child process to track
        manager.track_child_process(12345)

        # Mock psutil process
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process_class.return_value = mock_process

        manager._terminate_additional_children()

        mock_process.terminate.assert_called_once()

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.get_process_tracker"
    )
    def test_cleanup_process_tracker(self, mock_get_tracker):
        """Test cleaning up process tracker."""
        manager = ProcessCleanupManager()

        # Mock process tracker
        mock_tracker = MagicMock()
        mock_tracker.cleanup_dead_processes.return_value = ["dead_process"]
        mock_get_tracker.return_value = mock_tracker

        manager._cleanup_process_tracker()

        mock_tracker.cleanup_dead_processes.assert_called_once()


class TestGlobalFunctions:
    """Test global module functions."""

    def test_get_cleanup_manager_singleton(self):
        """Test that get_cleanup_manager returns singleton."""
        manager1 = get_cleanup_manager()
        manager2 = get_cleanup_manager()

        assert manager1 is manager2

    def test_install_signal_handlers(self):
        """Test installing signal handlers."""
        manager = install_signal_handlers()

        assert isinstance(manager, ProcessCleanupManager)

    def test_register_cleanup_handler_function(self):
        """Test the module-level register_cleanup_handler function."""
        mock_cleanup = MagicMock()

        # This should work without error
        register_cleanup_handler(mock_cleanup)

        # Verify it was registered with the global manager
        manager = get_cleanup_manager()
        assert mock_cleanup in manager.cleanup_handlers

    def test_track_child_process_function(self):
        """Test the module-level track_child_process function."""
        track_child_process(12345)

        # Verify it was tracked with the global manager
        manager = get_cleanup_manager()
        assert 12345 in manager.child_processes

    def test_track_event_loop_function(self):
        """Test the module-level track_event_loop function."""
        mock_loop = MagicMock()

        track_event_loop(mock_loop)

        # Verify it was tracked with the global manager
        manager = get_cleanup_manager()
        assert len(manager.event_loops) > 0


class TestSignalHandlerIntegration:
    """Test signal handler integration scenarios."""

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.threading.Thread"
    )
    def test_graceful_shutdown_workflow(self, mock_thread):
        """Test complete graceful shutdown workflow."""
        manager = ProcessCleanupManager()

        # Mock cleanup operations
        mock_cleanup = MagicMock()
        manager.register_cleanup_handler(mock_cleanup)

        # Mock thread execution
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance
        mock_thread_instance.is_alive.return_value = False  # Thread completes

        with patch.object(manager, "_execute_graceful_shutdown") as mock_execute:
            with patch("sys.exit"):
                manager._initiate_graceful_shutdown(signal.SIGTERM)

                # Should have started cleanup thread
                mock_thread.assert_called_once()
                mock_thread_instance.start.assert_called_once()
                mock_thread_instance.join.assert_called_once()

    def test_signal_handler_with_multiple_managers(self):
        """Test signal handler with multiple manager cleanups."""
        manager = ProcessCleanupManager()

        # Mock multiple managers
        mock_agent_manager = MagicMock()
        mock_registry_manager = MagicMock()
        mock_process_tracker = MagicMock()

        manager.register_cleanup_handler(mock_agent_manager.cleanup)
        manager.register_cleanup_handler(mock_registry_manager.cleanup)
        manager.register_cleanup_handler(mock_process_tracker.cleanup)

        # Execute cleanup
        manager._run_cleanup_handlers()

        # All cleanups should be called
        mock_agent_manager.cleanup.assert_called_once()
        mock_registry_manager.cleanup.assert_called_once()
        mock_process_tracker.cleanup.assert_called_once()

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.asyncio.get_running_loop"
    )
    def test_event_loop_cleanup(self, mock_get_loop):
        """Test event loop cleanup functionality."""
        manager = ProcessCleanupManager()

        # Mock running event loop
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        mock_get_loop.return_value = mock_loop

        manager._close_event_loops()

        mock_loop.stop.assert_called_once()

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.signal_handler.asyncio.get_running_loop"
    )
    def test_event_loop_cleanup_no_loop(self, mock_get_loop):
        """Test event loop cleanup when no loop is running."""
        manager = ProcessCleanupManager()

        # Mock no running event loop
        mock_get_loop.side_effect = RuntimeError("No running event loop")

        # Should not raise exception
        manager._close_event_loops()

    def test_double_shutdown_protection(self):
        """Test protection against double shutdown."""
        manager = ProcessCleanupManager()

        # Set shutdown in progress
        manager.shutdown_in_progress = True

        with patch.object(manager, "_execute_graceful_shutdown") as mock_execute:
            manager._initiate_graceful_shutdown(signal.SIGTERM)

            # Should not execute shutdown again
            mock_execute.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
