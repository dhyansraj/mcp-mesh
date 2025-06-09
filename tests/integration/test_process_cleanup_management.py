"""Integration tests for process cleanup and management."""

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Add the packages to the path for testing
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "packages" / "mcp_mesh_runtime" / "src"),
)

from mcp_mesh_runtime.cli.process_monitor import (
    MonitoringPolicy,
    ProcessMonitor,
)
from mcp_mesh_runtime.cli.process_tracker import ProcessTracker
from mcp_mesh_runtime.cli.process_tree import ProcessTree
from mcp_mesh_runtime.cli.signal_handler import (
    ProcessCleanupManager,
    install_signal_handlers,
    register_cleanup_handler,
)
from mcp_mesh_runtime.shared.types import HealthStatusType


class TestProcessCleanupManager:
    """Test the process cleanup manager."""

    def test_cleanup_manager_initialization(self):
        """Test cleanup manager can be initialized."""
        cleanup_manager = ProcessCleanupManager()
        assert cleanup_manager is not None
        assert not cleanup_manager.shutdown_in_progress
        assert len(cleanup_manager.cleanup_handlers) == 0
        assert len(cleanup_manager.child_processes) == 0

    def test_signal_handler_installation(self):
        """Test signal handlers can be installed."""
        cleanup_manager = install_signal_handlers()
        assert cleanup_manager is not None

        # Check that signal handlers are set (platform dependent)
        if hasattr(signal, "SIGTERM"):
            current_handler = signal.signal(signal.SIGTERM, signal.SIG_DFL)
            assert current_handler != signal.SIG_DFL
            # Restore the handler
            signal.signal(signal.SIGTERM, current_handler)

    def test_cleanup_handler_registration(self):
        """Test cleanup handler registration and execution."""
        cleanup_manager = ProcessCleanupManager()

        # Mock handler
        handler_called = False

        def test_handler():
            nonlocal handler_called
            handler_called = True

        # Register handler
        cleanup_manager.register_cleanup_handler(test_handler)
        assert len(cleanup_manager.cleanup_handlers) == 1

        # Run cleanup handlers
        cleanup_manager._run_cleanup_handlers()
        assert handler_called

        # Unregister handler
        cleanup_manager.unregister_cleanup_handler(test_handler)
        assert len(cleanup_manager.cleanup_handlers) == 0

    def test_child_process_tracking(self):
        """Test child process tracking."""
        cleanup_manager = ProcessCleanupManager()

        # Track a fake PID
        test_pid = 12345
        cleanup_manager.track_child_process(test_pid)
        assert test_pid in cleanup_manager.child_processes

        # Untrack PID
        cleanup_manager.untrack_child_process(test_pid)
        assert test_pid not in cleanup_manager.child_processes


class TestProcessTree:
    """Test the process tree management."""

    def test_process_tree_initialization(self):
        """Test process tree can be initialized."""
        process_tree = ProcessTree()
        assert process_tree is not None
        assert process_tree.system.lower() in ["linux", "darwin", "windows"]

    def test_get_process_tree_current_process(self):
        """Test getting process tree for current process."""
        process_tree = ProcessTree()
        current_pid = os.getpid()

        tree = process_tree.get_process_tree(current_pid)
        assert isinstance(tree, dict)
        # Current process should have parent
        assert current_pid not in tree or len(tree) >= 0

    def test_get_all_descendants(self):
        """Test getting all descendants of a process."""
        process_tree = ProcessTree()
        current_pid = os.getpid()

        descendants = process_tree.get_all_descendants(current_pid)
        assert isinstance(descendants, list)
        # Current process might not have children in test environment
        assert len(descendants) >= 0

    def test_process_info_tree(self):
        """Test getting detailed process information."""
        process_tree = ProcessTree()
        current_pid = os.getpid()

        info_tree = process_tree.get_process_info_tree(current_pid)
        assert isinstance(info_tree, dict)
        assert current_pid in info_tree

        process_info = info_tree[current_pid]
        assert "pid" in process_info
        assert "name" in process_info
        assert "status" in process_info

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_create_and_terminate_process_tree(self):
        """Test creating and terminating a process tree."""
        process_tree = ProcessTree()

        # Create a simple subprocess that will hang around
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                """
import time
import sys
while True:
    time.sleep(0.1)
"""
            )
            script_path = f.name

        try:
            # Start subprocess
            process = subprocess.Popen([sys.executable, script_path])
            time.sleep(0.2)  # Let it start

            # Terminate process tree
            results = process_tree.terminate_process_tree(process.pid, timeout=2.0)

            assert process.pid in results

            # Wait a bit and check if process is gone
            time.sleep(0.5)
            assert process.poll() is not None  # Process should be terminated

        finally:
            # Cleanup
            try:
                process.kill()
                process.wait(timeout=1)
            except:
                pass
            os.unlink(script_path)


class TestProcessTracker:
    """Test the process tracker with enhanced features."""

    def test_process_tracker_initialization(self):
        """Test process tracker initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file)
            assert tracker is not None
            assert tracker.state_file == state_file

    def test_process_tracking_lifecycle(self):
        """Test complete process tracking lifecycle."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file)

            # Create a test process
            process = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(10)"]
            )

            try:
                # Track the process
                process_info = tracker.track_process(
                    name="test_process",
                    pid=process.pid,
                    command=[sys.executable, "-c", "import time; time.sleep(10)"],
                    service_type="test",
                    metadata={"test": "data"},
                )

                assert process_info.name == "test_process"
                assert process_info.pid == process.pid
                assert process_info.service_type == "test"
                assert process_info.metadata["test"] == "data"

                # Get process
                retrieved = tracker.get_process("test_process")
                assert retrieved is not None
                assert retrieved.pid == process.pid

                # Update health
                health = tracker.update_health_status("test_process")
                assert health == HealthStatusType.HEALTHY

                # Terminate process
                success = tracker.terminate_process("test_process", timeout=5)
                assert success

                # Process should be untracked
                assert tracker.get_process("test_process") is None

            finally:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except:
                    pass

    def test_process_restart_functionality(self):
        """Test process restart capabilities."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file)

            # Create a test script
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                """
import time
import sys
import os
print(f"Process started with PID {os.getpid()}")
sys.stdout.flush()
time.sleep(10)
"""
            )

            # Track initial process
            initial_process = subprocess.Popen([sys.executable, str(script_path)])

            try:
                tracker.track_process(
                    name="restart_test",
                    pid=initial_process.pid,
                    command=[sys.executable, str(script_path)],
                    service_type="test",
                    metadata={"working_directory": str(temp_dir)},
                )

                original_pid = initial_process.pid

                # Restart the process
                new_process_info = tracker.restart_process("restart_test", timeout=5)

                assert new_process_info is not None
                assert new_process_info.pid != original_pid
                assert tracker._is_process_running(new_process_info.pid)

                # Clean up
                tracker.terminate_process("restart_test", timeout=5)

            finally:
                try:
                    initial_process.kill()
                    initial_process.wait(timeout=1)
                except:
                    pass

    def test_orphaned_process_cleanup(self):
        """Test orphaned process detection and cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file)

            # This test is conceptual since we can't easily create real orphans
            # in a test environment, but we can test the interface

            orphaned_results = tracker.cleanup_orphaned_processes()
            assert isinstance(orphaned_results, dict)

    def test_cross_platform_process_info(self):
        """Test cross-platform process information gathering."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file)

            current_pid = os.getpid()
            info = tracker.get_cross_platform_process_info(current_pid)

            assert isinstance(info, dict)
            assert info["pid"] == current_pid
            assert "name" in info
            assert "status" in info
            assert "is_running" in info


class TestProcessMonitor:
    """Test the process monitoring system."""

    def test_process_monitor_initialization(self):
        """Test process monitor initialization."""
        monitor = ProcessMonitor()
        assert monitor is not None
        assert not monitor.monitoring_enabled
        assert len(monitor.policies) == 0
        assert len(monitor.health_status) == 0

    def test_monitoring_policy_management(self):
        """Test monitoring policy setting and retrieval."""
        monitor = ProcessMonitor()

        # Create a custom policy
        policy = MonitoringPolicy(
            enabled=True,
            check_interval=10.0,
            restart_on_failure=True,
            max_restart_attempts=5,
        )

        # Set policy for a process
        monitor.set_process_policy("test_process", policy)

        # Retrieve policy
        retrieved_policy = monitor.get_process_policy("test_process")
        assert retrieved_policy.enabled == True
        assert retrieved_policy.check_interval == 10.0
        assert retrieved_policy.restart_on_failure == True
        assert retrieved_policy.max_restart_attempts == 5

    def test_alert_callback_management(self):
        """Test alert callback registration and execution."""
        monitor = ProcessMonitor()

        # Mock callback
        alerts_received = []

        def test_callback(event_type, process_name, details):
            alerts_received.append((event_type, process_name, details))

        # Register callback
        monitor.add_alert_callback(test_callback)
        assert len(monitor.alert_callbacks) == 1

        # Send test alert
        monitor._send_alert("test_event", "test_process", {"key": "value"})

        assert len(alerts_received) == 1
        assert alerts_received[0][0] == "test_event"
        assert alerts_received[0][1] == "test_process"
        assert alerts_received[0][2]["key"] == "value"

        # Remove callback
        monitor.remove_alert_callback(test_callback)
        assert len(monitor.alert_callbacks) == 0

    def test_monitoring_status_reporting(self):
        """Test monitoring status reporting."""
        monitor = ProcessMonitor()

        status = monitor.get_monitoring_status()
        assert isinstance(status, dict)
        assert "monitoring_enabled" in status
        assert "processes" in status
        assert status["monitoring_enabled"] == False


class TestIntegratedProcessManagement:
    """Test integrated process management scenarios."""

    def test_signal_handler_integration(self):
        """Test signal handler integration with cleanup."""
        # This test verifies that components work together
        cleanup_manager = install_signal_handlers()

        # Register a test cleanup handler
        cleanup_called = False

        def test_cleanup():
            nonlocal cleanup_called
            cleanup_called = True

        register_cleanup_handler(test_cleanup)

        # Simulate cleanup (without actually sending signals)
        cleanup_manager._run_cleanup_handlers()
        assert cleanup_called

    def test_process_lifecycle_with_monitoring(self):
        """Test complete process lifecycle with monitoring."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Initialize components
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file)
            monitor = ProcessMonitor()

            # Create test script
            script_path = Path(temp_dir) / "monitored_script.py"
            script_path.write_text(
                """
import time
import os
print(f"Monitored process started: {os.getpid()}")
for i in range(30):
    time.sleep(0.1)
    if i % 10 == 0:
        print(f"Heartbeat {i}")
"""
            )

            # Start and track process
            process = subprocess.Popen([sys.executable, str(script_path)])

            try:
                # Track process
                process_info = tracker.track_process(
                    name="monitored_process",
                    pid=process.pid,
                    command=[sys.executable, str(script_path)],
                    service_type="test",
                    metadata={"working_directory": str(temp_dir)},
                )

                # Set monitoring policy
                policy = MonitoringPolicy(
                    enabled=True,
                    check_interval=1.0,
                    restart_on_failure=False,  # Don't auto-restart in test
                )
                monitor.set_process_policy("monitored_process", policy)

                # Simulate health check
                time.sleep(0.2)  # Let process start
                health_info = tracker.monitor_process_health("monitored_process")

                assert health_info["name"] == "monitored_process"
                assert "basic_health" in health_info
                assert "detailed_info" in health_info

                # Clean up
                tracker.terminate_process("monitored_process", timeout=5)

            finally:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except:
                    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
