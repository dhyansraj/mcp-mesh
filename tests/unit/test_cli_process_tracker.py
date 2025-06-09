"""Unit tests for CLI process tracking functionality."""

import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.process_tracker import (
    ProcessInfo,
    ProcessTracker,
    get_process_tracker,
    init_process_tracker,
)
from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.shared.types import HealthStatusType


class TestProcessInfo:
    """Test ProcessInfo class."""

    def test_process_info_creation(self):
        """Test creating ProcessInfo instance."""
        command = ["python", "test_agent.py"]
        start_time = datetime.now()

        process_info = ProcessInfo(
            name="test_agent",
            pid=12345,
            command=command,
            started_at=start_time,
            service_type="agent",
        )

        assert process_info.name == "test_agent"
        assert process_info.pid == 12345
        assert process_info.command == command
        assert process_info.started_at == start_time
        assert process_info.service_type == "agent"
        assert process_info.health_status == HealthStatusType.UNKNOWN
        assert isinstance(process_info.metadata, dict)

    def test_process_info_uptime(self):
        """Test process uptime calculation."""
        start_time = datetime.now() - timedelta(seconds=30)

        process_info = ProcessInfo(
            name="test", pid=12345, command=["python", "test.py"], started_at=start_time
        )

        uptime = process_info.get_uptime()
        assert isinstance(uptime, timedelta)
        assert uptime.total_seconds() >= 29  # Allow for small timing differences
        assert uptime.total_seconds() <= 31

    def test_process_info_to_dict(self):
        """Test converting ProcessInfo to dictionary."""
        start_time = datetime.now()
        process_info = ProcessInfo(
            name="test_agent",
            pid=12345,
            command=["python", "test_agent.py"],
            started_at=start_time,
            service_type="agent",
        )
        process_info.metadata = {"key": "value"}

        data = process_info.to_dict()

        assert data["name"] == "test_agent"
        assert data["pid"] == 12345
        assert data["command"] == ["python", "test_agent.py"]
        assert data["started_at"] == start_time.isoformat()
        assert data["service_type"] == "agent"
        assert "uptime_seconds" in data
        assert data["health_status"] == "unknown"
        assert data["metadata"] == {"key": "value"}

    def test_process_info_from_dict(self):
        """Test creating ProcessInfo from dictionary."""
        start_time = datetime.now()
        data = {
            "name": "test_agent",
            "pid": 12345,
            "command": ["python", "test_agent.py"],
            "started_at": start_time.isoformat(),
            "service_type": "agent",
            "health_status": "healthy",
            "last_health_check": datetime.now().isoformat(),
            "metadata": {"key": "value"},
        }

        process_info = ProcessInfo.from_dict(data)

        assert process_info.name == "test_agent"
        assert process_info.pid == 12345
        assert process_info.command == ["python", "test_agent.py"]
        assert process_info.service_type == "agent"
        assert process_info.health_status == HealthStatusType.HEALTHY
        assert process_info.metadata == {"key": "value"}


class TestProcessTracker:
    """Test ProcessTracker class."""

    def test_process_tracker_creation(self):
        """Test creating ProcessTracker instance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            assert tracker.state_file == state_file
            assert isinstance(tracker.processes, dict)
            assert isinstance(tracker.registry_state, dict)

    def test_track_process(self):
        """Test tracking a new process."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            process_info = tracker.track_process(
                name="test_agent",
                pid=12345,
                command=["python", "test_agent.py"],
                service_type="agent",
                metadata={"key": "value"},
            )

            assert process_info.name == "test_agent"
            assert process_info.pid == 12345
            assert process_info.metadata["key"] == "value"
            assert "test_agent" in tracker.processes

    def test_untrack_process(self):
        """Test untracking a process."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track a process first
            tracker.track_process("test_agent", 12345, ["python", "test.py"])
            assert "test_agent" in tracker.processes

            # Untrack the process
            result = tracker.untrack_process("test_agent")
            assert result is True
            assert "test_agent" not in tracker.processes

            # Try to untrack non-existent process
            result = tracker.untrack_process("non_existent")
            assert result is False

    def test_get_process(self):
        """Test getting process information."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track a process
            original_info = tracker.track_process(
                "test_agent", 12345, ["python", "test.py"]
            )

            # Get process info
            retrieved_info = tracker.get_process("test_agent")
            assert retrieved_info is not None
            assert retrieved_info.name == "test_agent"
            assert retrieved_info.pid == 12345

            # Try to get non-existent process
            missing_info = tracker.get_process("non_existent")
            assert missing_info is None

    def test_get_all_processes(self):
        """Test getting all tracked processes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track multiple processes
            tracker.track_process("agent1", 12345, ["python", "agent1.py"])
            tracker.track_process("agent2", 12346, ["python", "agent2.py"])
            tracker.track_process(
                "registry", 12347, ["python", "registry.py"], "registry"
            )

            all_processes = tracker.get_all_processes()
            assert len(all_processes) == 3
            assert "agent1" in all_processes
            assert "agent2" in all_processes
            assert "registry" in all_processes

    @patch("psutil.Process")
    def test_is_process_running(self, mock_process_class):
        """Test checking if process is running."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Mock running process
            mock_process = MagicMock()
            mock_process.is_running.return_value = True
            mock_process.status.return_value = psutil.STATUS_RUNNING
            mock_process_class.return_value = mock_process

            assert tracker._is_process_running(12345) is True

            # Mock non-existent process
            mock_process_class.side_effect = psutil.NoSuchProcess(12346)
            assert tracker._is_process_running(12346) is False

            # Mock zombie process
            mock_process_class.side_effect = None
            mock_process.status.return_value = psutil.STATUS_ZOMBIE
            assert tracker._is_process_running(12347) is False

    @patch("psutil.Process")
    def test_get_running_processes(self, mock_process_class):
        """Test getting only running processes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track processes
            tracker.track_process("running_agent", 12345, ["python", "running.py"])
            tracker.track_process("stopped_agent", 12346, ["python", "stopped.py"])

            # Mock one running, one stopped
            def mock_process_side_effect(pid):
                mock_process = MagicMock()
                if pid == 12345:
                    mock_process.is_running.return_value = True
                    mock_process.status.return_value = psutil.STATUS_RUNNING
                else:
                    mock_process.is_running.return_value = False
                return mock_process

            mock_process_class.side_effect = mock_process_side_effect

            running_processes = tracker.get_running_processes()
            assert len(running_processes) == 1
            assert "running_agent" in running_processes
            assert "stopped_agent" not in running_processes

    @patch("psutil.Process")
    def test_cleanup_dead_processes(self, mock_process_class):
        """Test cleaning up dead processes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track processes
            tracker.track_process("running_agent", 12345, ["python", "running.py"])
            tracker.track_process("dead_agent", 12346, ["python", "dead.py"])

            # Mock one running, one dead
            def mock_process_side_effect(pid):
                mock_process = MagicMock()
                if pid == 12345:
                    mock_process.is_running.return_value = True
                    mock_process.status.return_value = psutil.STATUS_RUNNING
                else:
                    raise psutil.NoSuchProcess(pid)
                return mock_process

            mock_process_class.side_effect = mock_process_side_effect

            dead_processes = tracker.cleanup_dead_processes()

            assert len(dead_processes) == 1
            assert "dead_agent" in dead_processes
            assert "running_agent" in tracker.processes
            assert "dead_agent" not in tracker.processes

    def test_update_registry_state(self):
        """Test updating registry state."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            tracker.update_registry_state(
                url="http://localhost:8080",
                host="localhost",
                port=8080,
                database_path="/tmp/registry.db",
                config={"key": "value"},
            )

            registry_state = tracker.get_registry_state()
            assert registry_state["url"] == "http://localhost:8080"
            assert registry_state["host"] == "localhost"
            assert registry_state["port"] == 8080
            assert registry_state["database_path"] == "/tmp/registry.db"
            assert registry_state["config"] == {"key": "value"}

    def test_get_registry_url(self):
        """Test getting registry URL."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # No registry state initially
            assert tracker.get_registry_url() is None

            # Update registry state
            tracker.update_registry_state(
                url="http://localhost:8080",
                host="localhost",
                port=8080,
                database_path="/tmp/registry.db",
            )

            assert tracker.get_registry_url() == "http://localhost:8080"

    @patch("psutil.Process")
    def test_is_registry_state_valid(self, mock_process_class):
        """Test checking if registry state is valid."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # No registry state initially
            assert tracker.is_registry_state_valid() is False

            # Add registry state but no process
            tracker.update_registry_state(
                url="http://localhost:8080",
                host="localhost",
                port=8080,
                database_path="/tmp/registry.db",
            )
            assert tracker.is_registry_state_valid() is False

            # Add registry process
            tracker.track_process(
                "registry", 12345, ["python", "registry.py"], "registry"
            )

            # Mock running process
            mock_process = MagicMock()
            mock_process.is_running.return_value = True
            mock_process.status.return_value = psutil.STATUS_RUNNING
            mock_process_class.return_value = mock_process

            assert tracker.is_registry_state_valid() is True

            # Mock stopped process
            mock_process.is_running.return_value = False
            assert tracker.is_registry_state_valid() is False

    @patch("subprocess.Popen")
    @patch("psutil.Process")
    def test_restart_process(self, mock_process_class, mock_popen):
        """Test restarting a process."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track a process
            tracker.track_process(
                "test_agent",
                12345,
                ["python", "test_agent.py"],
                metadata={"working_directory": "/tmp"},
            )

            # Mock terminate process
            mock_process = MagicMock()
            mock_process.terminate.return_value = None
            mock_process.wait.return_value = None
            mock_process_class.return_value = mock_process

            # Mock new process
            mock_new_process = MagicMock()
            mock_new_process.pid = 54321
            mock_popen.return_value = mock_new_process

            # Mock process running check for new process
            def running_check_side_effect(pid):
                if pid == 54321:
                    new_mock = MagicMock()
                    new_mock.is_running.return_value = True
                    new_mock.status.return_value = psutil.STATUS_RUNNING
                    return new_mock
                return mock_process

            mock_process_class.side_effect = running_check_side_effect

            new_process_info = tracker.restart_process("test_agent")

            assert new_process_info is not None
            assert new_process_info.pid == 54321
            assert new_process_info.name == "test_agent"

    def test_state_persistence(self):
        """Test process state persistence across instances."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"

            # Create tracker and add processes
            tracker1 = ProcessTracker(state_file=state_file)
            tracker1.track_process("test_agent", 12345, ["python", "test.py"])
            tracker1.update_registry_state(
                url="http://localhost:8080",
                host="localhost",
                port=8080,
                database_path="/tmp/registry.db",
            )

            # Create new tracker instance and verify state is loaded
            with patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.process_tracker.ProcessTracker._is_process_running",
                return_value=True,
            ):
                tracker2 = ProcessTracker(state_file=state_file)

                assert "test_agent" in tracker2.processes
                assert tracker2.processes["test_agent"].pid == 12345
                assert tracker2.get_registry_url() == "http://localhost:8080"

    def test_get_process_status_summary(self):
        """Test getting process status summary."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track processes
            tracker.track_process("agent1", 12345, ["python", "agent1.py"], "agent")
            tracker.track_process(
                "registry", 12346, ["python", "registry.py"], "registry"
            )

            with patch.object(tracker, "_is_process_running", return_value=True):
                with patch.object(
                    tracker,
                    "update_health_status",
                    return_value=HealthStatusType.HEALTHY,
                ):
                    status_summary = tracker.get_process_status_summary()

            assert len(status_summary) == 2
            assert "agent1" in status_summary
            assert "registry" in status_summary

            agent_status = status_summary["agent1"]
            assert agent_status.name == "agent1"
            assert agent_status.pid == 12345
            assert agent_status.status == "running"

    @patch(
        "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.process_tracker.get_process_tree"
    )
    def test_cleanup_orphaned_processes(self, mock_get_process_tree):
        """Test cleaning up orphaned processes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track a process
            tracker.track_process("agent1", 12345, ["python", "agent1.py"])

            # Mock process tree
            mock_tree = MagicMock()
            mock_tree.find_orphaned_processes.return_value = [54321, 54322]
            mock_tree.cleanup_orphaned_processes.return_value = {
                54321: True,
                54322: False,
            }
            mock_get_process_tree.return_value = mock_tree

            result = tracker.cleanup_orphaned_processes()

            assert result == {54321: True, 54322: False}
            mock_tree.find_orphaned_processes.assert_called_once_with({12345})
            mock_tree.cleanup_orphaned_processes.assert_called_once_with([54321, 54322])

    @patch("psutil.Process")
    def test_get_cross_platform_process_info(self, mock_process_class):
        """Test getting cross-platform process information."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Mock process
            mock_process = MagicMock()
            mock_process.name.return_value = "python"
            mock_process.status.return_value = psutil.STATUS_RUNNING
            mock_process.create_time.return_value = time.time()
            mock_process.num_threads.return_value = 4
            mock_process.memory_percent.return_value = 5.2
            mock_process.is_running.return_value = True
            mock_process.cmdline.return_value = ["python", "test.py"]
            mock_process.cwd.return_value = "/tmp"
            mock_process.memory_info.return_value._asdict.return_value = {
                "rss": 1024000
            }
            mock_process.cpu_percent.return_value = 2.5
            mock_process_class.return_value = mock_process

            info = tracker.get_cross_platform_process_info(12345)

            assert info["pid"] == 12345
            assert info["name"] == "python"
            assert info["status"] == psutil.STATUS_RUNNING
            assert info["num_threads"] == 4
            assert info["memory_percent"] == 5.2
            assert info["is_running"] is True
            assert info["cmdline"] == ["python", "test.py"]
            assert info["cwd"] == "/tmp"


class TestGlobalProcessTracker:
    """Test global process tracker functions."""

    def test_init_process_tracker(self):
        """Test initializing global process tracker."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"

            tracker = init_process_tracker(state_file)
            assert isinstance(tracker, ProcessTracker)
            assert tracker.state_file == state_file

    def test_get_process_tracker_singleton(self):
        """Test global process tracker singleton behavior."""
        # Clear global tracker
        import packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.process_tracker as pt_module

        pt_module._process_tracker = None

        # First call creates new instance
        tracker1 = get_process_tracker()
        assert isinstance(tracker1, ProcessTracker)

        # Second call returns same instance
        tracker2 = get_process_tracker()
        assert tracker1 is tracker2


class TestProcessTrackerErrorHandling:
    """Test error handling in ProcessTracker."""

    def test_load_state_file_not_found(self):
        """Test loading state when file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "non_existent.json"

            # Should not raise exception
            tracker = ProcessTracker(state_file=state_file)
            assert len(tracker.processes) == 0
            assert len(tracker.registry_state) == 0

    def test_load_state_invalid_json(self):
        """Test loading state from invalid JSON file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "invalid.json"

            # Create invalid JSON file
            with open(state_file, "w") as f:
                f.write("invalid json content")

            # Should handle gracefully and not crash
            tracker = ProcessTracker(state_file=state_file)
            assert len(tracker.processes) == 0

    def test_save_state_permission_error(self):
        """Test saving state with permission error."""
        # Use a path that would cause permission error
        read_only_path = Path("/root/test_processes.json")  # Assuming no write access

        tracker = ProcessTracker(state_file=read_only_path)
        tracker.track_process("test", 12345, ["python", "test.py"])

        # Should handle save error gracefully (logged but not raised)
        # The actual test depends on system permissions

    @patch("psutil.Process")
    def test_terminate_process_not_found(self, mock_process_class):
        """Test terminating a process that doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            # Track a process
            tracker.track_process("test_agent", 12345, ["python", "test.py"])

            # Mock process not found
            mock_process_class.side_effect = psutil.NoSuchProcess(12345)

            result = tracker.terminate_process("test_agent")

            # Should return False but handle gracefully
            assert result is False
            # Process should be untracked
            assert "test_agent" not in tracker.processes

    def test_restart_process_not_found(self):
        """Test restarting a process that's not tracked."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "test_processes.json"
            tracker = ProcessTracker(state_file=state_file)

            result = tracker.restart_process("non_existent")
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__])
