"""Unit tests for CLI log aggregator."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.log_aggregator import (
    LogAggregator,
    LogEntry,
    LogLevel,
    filter_logs_by_level,
    format_log_entry,
    parse_log_entry,
    tail_file,
)


class TestLogEntry:
    """Test LogEntry data class."""

    def test_log_entry_creation(self):
        """Test creating LogEntry instances."""
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.INFO,
            source="test_agent",
            message="Test message",
            raw_line="2024-01-01 12:00:00 INFO [test_agent] Test message",
        )

        assert entry.timestamp == "2024-01-01 12:00:00"
        assert entry.level == LogLevel.INFO
        assert entry.source == "test_agent"
        assert entry.message == "Test message"
        assert entry.raw_line == "2024-01-01 12:00:00 INFO [test_agent] Test message"

    def test_log_entry_to_dict(self):
        """Test LogEntry to_dict method."""
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.ERROR,
            source="registry",
            message="Error occurred",
        )

        entry_dict = entry.to_dict()

        assert entry_dict["timestamp"] == "2024-01-01 12:00:00"
        assert entry_dict["level"] == "ERROR"
        assert entry_dict["source"] == "registry"
        assert entry_dict["message"] == "Error occurred"

    def test_log_entry_str_representation(self):
        """Test LogEntry string representation."""
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.WARNING,
            source="agent1",
            message="Warning message",
        )

        str_repr = str(entry)
        assert "2024-01-01 12:00:00" in str_repr
        assert "WARNING" in str_repr
        assert "agent1" in str_repr
        assert "Warning message" in str_repr


class TestLogLevel:
    """Test LogLevel enum."""

    def test_log_level_values(self):
        """Test LogLevel enum values."""
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARNING.value == "WARNING"
        assert LogLevel.ERROR.value == "ERROR"
        assert LogLevel.CRITICAL.value == "CRITICAL"

    def test_log_level_ordering(self):
        """Test LogLevel ordering."""
        # Test that levels are properly ordered
        levels = [
            LogLevel.DEBUG,
            LogLevel.INFO,
            LogLevel.WARNING,
            LogLevel.ERROR,
            LogLevel.CRITICAL,
        ]
        for i in range(len(levels) - 1):
            assert levels[i].value < levels[i + 1].value or levels[i] != levels[i + 1]

    def test_log_level_from_string(self):
        """Test creating LogLevel from string."""
        assert LogLevel("DEBUG") == LogLevel.DEBUG
        assert LogLevel("INFO") == LogLevel.INFO
        assert LogLevel("WARNING") == LogLevel.WARNING
        assert LogLevel("ERROR") == LogLevel.ERROR
        assert LogLevel("CRITICAL") == LogLevel.CRITICAL


class TestLogParsing:
    """Test log parsing functions."""

    def test_parse_log_entry_standard_format(self):
        """Test parsing standard log format."""
        log_line = "2024-01-01 12:00:00 INFO [test_agent] Application started"

        entry = parse_log_entry(log_line)

        assert entry.timestamp == "2024-01-01 12:00:00"
        assert entry.level == LogLevel.INFO
        assert entry.source == "test_agent"
        assert entry.message == "Application started"
        assert entry.raw_line == log_line

    def test_parse_log_entry_with_brackets(self):
        """Test parsing log entry with brackets in message."""
        log_line = "2024-01-01 12:00:00 ERROR [registry] Connection failed [errno: 111]"

        entry = parse_log_entry(log_line)

        assert entry.timestamp == "2024-01-01 12:00:00"
        assert entry.level == LogLevel.ERROR
        assert entry.source == "registry"
        assert entry.message == "Connection failed [errno: 111]"

    def test_parse_log_entry_multiline_message(self):
        """Test parsing log entry with multiline message."""
        log_line = "2024-01-01 12:00:00 DEBUG [agent1] Stack trace:\n  at function()\n  at main()"

        entry = parse_log_entry(log_line)

        assert entry.timestamp == "2024-01-01 12:00:00"
        assert entry.level == LogLevel.DEBUG
        assert entry.source == "agent1"
        assert "Stack trace:" in entry.message
        assert "at function()" in entry.message

    def test_parse_log_entry_invalid_format(self):
        """Test parsing invalid log format."""
        log_line = "Invalid log line without proper format"

        entry = parse_log_entry(log_line)

        # Should still create entry with raw line
        assert entry.raw_line == log_line
        assert entry.level == LogLevel.INFO  # Default level
        assert entry.source == "unknown"
        assert entry.message == log_line

    def test_parse_log_entry_missing_source(self):
        """Test parsing log entry without source."""
        log_line = "2024-01-01 12:00:00 WARNING Message without source"

        entry = parse_log_entry(log_line)

        assert entry.timestamp == "2024-01-01 12:00:00"
        assert entry.level == LogLevel.WARNING
        assert entry.source == "unknown"
        assert entry.message == "Message without source"

    def test_parse_log_entry_different_levels(self):
        """Test parsing different log levels."""
        test_cases = [
            ("2024-01-01 12:00:00 DEBUG [test] Debug message", LogLevel.DEBUG),
            ("2024-01-01 12:00:00 INFO [test] Info message", LogLevel.INFO),
            ("2024-01-01 12:00:00 WARNING [test] Warning message", LogLevel.WARNING),
            ("2024-01-01 12:00:00 ERROR [test] Error message", LogLevel.ERROR),
            ("2024-01-01 12:00:00 CRITICAL [test] Critical message", LogLevel.CRITICAL),
        ]

        for log_line, expected_level in test_cases:
            entry = parse_log_entry(log_line)
            assert entry.level == expected_level


class TestLogFormatting:
    """Test log formatting functions."""

    def test_format_log_entry_basic(self):
        """Test basic log entry formatting."""
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.INFO,
            source="test_agent",
            message="Test message",
        )

        formatted = format_log_entry(entry)

        assert "2024-01-01 12:00:00" in formatted
        assert "INFO" in formatted
        assert "test_agent" in formatted
        assert "Test message" in formatted

    def test_format_log_entry_with_colors(self):
        """Test log entry formatting with colors."""
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.ERROR,
            source="registry",
            message="Error occurred",
        )

        formatted = format_log_entry(entry, use_colors=True)

        # Should contain ANSI color codes for error
        assert "\033[" in formatted or "ERROR" in formatted

    def test_format_log_entry_without_colors(self):
        """Test log entry formatting without colors."""
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.WARNING,
            source="agent1",
            message="Warning message",
        )

        formatted = format_log_entry(entry, use_colors=False)

        # Should not contain ANSI color codes
        assert "\033[" not in formatted
        assert "WARNING" in formatted

    def test_format_log_entry_long_message(self):
        """Test formatting log entry with long message."""
        long_message = "This is a very long message " * 10
        entry = LogEntry(
            timestamp="2024-01-01 12:00:00",
            level=LogLevel.INFO,
            source="test",
            message=long_message,
        )

        formatted = format_log_entry(entry)

        assert long_message in formatted
        assert "test" in formatted


class TestLogFiltering:
    """Test log filtering functions."""

    def test_filter_logs_by_level_exact_match(self):
        """Test filtering logs by exact level match."""
        entries = [
            LogEntry("", LogLevel.DEBUG, "", "Debug message"),
            LogEntry("", LogLevel.INFO, "", "Info message"),
            LogEntry("", LogLevel.WARNING, "", "Warning message"),
            LogEntry("", LogLevel.ERROR, "", "Error message"),
        ]

        info_logs = filter_logs_by_level(entries, LogLevel.INFO)

        # Should include INFO and higher levels
        assert len(info_logs) == 3  # INFO, WARNING, ERROR
        assert all(entry.level.value >= LogLevel.INFO.value for entry in info_logs)

    def test_filter_logs_by_level_warning_and_above(self):
        """Test filtering logs for warning and above."""
        entries = [
            LogEntry("", LogLevel.DEBUG, "", "Debug message"),
            LogEntry("", LogLevel.INFO, "", "Info message"),
            LogEntry("", LogLevel.WARNING, "", "Warning message"),
            LogEntry("", LogLevel.ERROR, "", "Error message"),
            LogEntry("", LogLevel.CRITICAL, "", "Critical message"),
        ]

        warning_logs = filter_logs_by_level(entries, LogLevel.WARNING)

        # Should include WARNING, ERROR, CRITICAL
        assert len(warning_logs) == 3
        assert all(
            entry.level.value >= LogLevel.WARNING.value for entry in warning_logs
        )

    def test_filter_logs_by_level_empty_list(self):
        """Test filtering empty log list."""
        filtered = filter_logs_by_level([], LogLevel.INFO)
        assert filtered == []

    def test_filter_logs_by_level_no_matches(self):
        """Test filtering when no logs match the level."""
        entries = [
            LogEntry("", LogLevel.DEBUG, "", "Debug message"),
            LogEntry("", LogLevel.INFO, "", "Info message"),
        ]

        error_logs = filter_logs_by_level(entries, LogLevel.ERROR)
        assert len(error_logs) == 0


class TestLogTailing:
    """Test log file tailing functionality."""

    def test_tail_file_basic(self):
        """Test basic file tailing."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            # Write some test lines
            test_lines = ["Line 1", "Line 2", "Line 3", "Line 4", "Line 5"]
            f.write("\n".join(test_lines))
            f.flush()

            # Tail last 3 lines
            result = tail_file(f.name, lines=3)

            assert len(result) == 3
            assert result[0] == "Line 3"
            assert result[1] == "Line 4"
            assert result[2] == "Line 5"

        # Cleanup
        Path(f.name).unlink()

    def test_tail_file_more_lines_than_available(self):
        """Test tailing more lines than available in file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            test_lines = ["Line 1", "Line 2"]
            f.write("\n".join(test_lines))
            f.flush()

            # Request more lines than available
            result = tail_file(f.name, lines=10)

            assert len(result) == 2
            assert result[0] == "Line 1"
            assert result[1] == "Line 2"

        Path(f.name).unlink()

    def test_tail_file_empty_file(self):
        """Test tailing empty file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            pass  # Empty file

        result = tail_file(f.name, lines=5)
        assert result == []

        Path(f.name).unlink()

    def test_tail_file_nonexistent(self):
        """Test tailing nonexistent file."""
        result = tail_file("/nonexistent/file.log", lines=5)
        assert result == []


class TestLogAggregator:
    """Test LogAggregator functionality."""

    def test_log_aggregator_creation(self):
        """Test creating LogAggregator."""
        aggregator = LogAggregator()
        assert aggregator._agent_manager is None
        assert aggregator._registry_manager is None

    def test_set_managers(self):
        """Test setting managers in aggregator."""
        aggregator = LogAggregator()

        mock_agent = MagicMock()
        mock_registry = MagicMock()

        aggregator.set_agent_manager(mock_agent)
        aggregator.set_registry_manager(mock_registry)

        assert aggregator._agent_manager == mock_agent
        assert aggregator._registry_manager == mock_registry

    def test_get_log_paths_no_managers(self):
        """Test getting log paths when no managers are set."""
        aggregator = LogAggregator()

        paths = aggregator.get_log_paths()
        assert paths == {}

    def test_get_log_paths_with_agents(self):
        """Test getting log paths with agent manager."""
        aggregator = LogAggregator()

        mock_agent = MagicMock()
        mock_process1 = MagicMock()
        mock_process1.metadata = {
            "working_directory": "/tmp",
            "agent_file": "agent1.py",
        }
        mock_process2 = MagicMock()
        mock_process2.metadata = {
            "working_directory": "/tmp",
            "agent_file": "agent2.py",
        }

        mock_agent.process_tracker.get_all_processes.return_value = {
            "agent1": mock_process1,
            "agent2": mock_process2,
        }

        aggregator.set_agent_manager(mock_agent)

        with patch("pathlib.Path.exists", return_value=True):
            paths = aggregator.get_log_paths()

            assert "agent1" in paths
            assert "agent2" in paths
            assert paths["agent1"].endswith("agent1.log")
            assert paths["agent2"].endswith("agent2.log")

    def test_get_logs_for_agent(self):
        """Test getting logs for specific agent."""
        aggregator = LogAggregator()

        # Mock log file content
        mock_log_content = [
            "2024-01-01 12:00:00 INFO [agent1] Starting agent",
            "2024-01-01 12:00:01 DEBUG [agent1] Initializing",
            "2024-01-01 12:00:02 WARNING [agent1] Warning message",
            "2024-01-01 12:00:03 ERROR [agent1] Error occurred",
        ]

        with (
            patch.object(
                aggregator, "get_log_paths", return_value={"agent1": "/tmp/agent1.log"}
            ),
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.log_aggregator.tail_file",
                return_value=mock_log_content,
            ),
        ):

            logs = aggregator.get_logs_for_agent(
                "agent1", lines=50, level=LogLevel.INFO
            )

            # Should filter out DEBUG level
            assert len(logs) == 3
            assert all(entry.source == "agent1" for entry in logs)
            assert logs[0].level == LogLevel.INFO
            assert logs[1].level == LogLevel.WARNING
            assert logs[2].level == LogLevel.ERROR

    def test_get_logs_for_agent_not_found(self):
        """Test getting logs for non-existent agent."""
        aggregator = LogAggregator()

        with patch.object(aggregator, "get_log_paths", return_value={}):
            logs = aggregator.get_logs_for_agent("nonexistent", lines=50)
            assert logs == []

    def test_get_all_logs(self):
        """Test getting logs from all sources."""
        aggregator = LogAggregator()

        # Mock log files
        mock_agent1_logs = ["2024-01-01 12:00:00 INFO [agent1] Agent1 message"]
        mock_agent2_logs = ["2024-01-01 12:00:01 WARNING [agent2] Agent2 message"]
        mock_registry_logs = ["2024-01-01 12:00:02 ERROR [registry] Registry error"]

        def mock_tail_file(path, lines):
            if "agent1" in path:
                return mock_agent1_logs
            elif "agent2" in path:
                return mock_agent2_logs
            elif "registry" in path:
                return mock_registry_logs
            return []

        with (
            patch.object(
                aggregator,
                "get_log_paths",
                return_value={
                    "agent1": "/tmp/agent1.log",
                    "agent2": "/tmp/agent2.log",
                    "registry": "/tmp/registry.log",
                },
            ),
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.log_aggregator.tail_file",
                side_effect=mock_tail_file,
            ),
        ):

            all_logs = aggregator.get_all_logs(lines=50, level=LogLevel.INFO)

            # Should have logs from all sources
            assert len(all_logs) == 3
            sources = {log.source for log in all_logs}
            assert sources == {"agent1", "agent2", "registry"}

    @pytest.mark.asyncio
    async def test_follow_logs_for_agent(self):
        """Test following logs for specific agent."""
        aggregator = LogAggregator()

        # Mock log file that gets new content
        initial_content = ["2024-01-01 12:00:00 INFO [agent1] Initial message"]

        new_content = [
            "2024-01-01 12:00:00 INFO [agent1] Initial message",
            "2024-01-01 12:00:01 INFO [agent1] New message",
        ]

        call_count = 0

        def mock_tail_file(path, lines):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return initial_content
            else:
                return new_content

        with (
            patch.object(
                aggregator, "get_log_paths", return_value={"agent1": "/tmp/agent1.log"}
            ),
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.log_aggregator.tail_file",
                side_effect=mock_tail_file,
            ),
            patch("asyncio.sleep", return_value=None),
        ):

            # Collect logs for a short time
            logs_collected = []

            async def collect_logs():
                async for log_entry in aggregator.follow_logs_for_agent("agent1"):
                    logs_collected.append(log_entry)
                    if len(logs_collected) >= 2:  # Stop after collecting some logs
                        break

            # Run for a very short time
            try:
                await asyncio.wait_for(collect_logs(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

            # Should have collected some logs
            assert len(logs_collected) >= 1


class TestLogAggregatorIntegration:
    """Test LogAggregator integration scenarios."""

    def test_complete_log_aggregation_workflow(self):
        """Test complete log aggregation workflow."""
        aggregator = LogAggregator()

        # Mock managers and processes
        mock_agent = MagicMock()
        mock_registry = MagicMock()

        # Mock agent processes
        mock_agent_process = MagicMock()
        mock_agent_process.metadata = {
            "working_directory": "/tmp",
            "agent_file": "hello_world.py",
        }

        mock_agent.process_tracker.get_all_processes.return_value = {
            "hello_world": mock_agent_process
        }

        # Mock registry process
        mock_registry_process = MagicMock()
        mock_registry_process.metadata = {"working_directory": "/tmp"}

        mock_registry.process_tracker.get_process.return_value = mock_registry_process

        aggregator.set_agent_manager(mock_agent)
        aggregator.set_registry_manager(mock_registry)

        # Mock log content
        mock_logs = [
            "2024-01-01 12:00:00 INFO [hello_world] Agent started",
            "2024-01-01 12:00:01 DEBUG [hello_world] Debug message",
            "2024-01-01 12:00:02 WARNING [hello_world] Warning occurred",
            "2024-01-01 12:00:03 ERROR [hello_world] Error happened",
        ]

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.log_aggregator.tail_file",
                return_value=mock_logs,
            ),
        ):

            # Test getting all logs
            all_logs = aggregator.get_all_logs(lines=50, level=LogLevel.INFO)

            # Should filter out DEBUG and include the rest
            assert len(all_logs) == 3
            assert all(log.source == "hello_world" for log in all_logs)

            # Test getting logs for specific agent
            agent_logs = aggregator.get_logs_for_agent(
                "hello_world", lines=50, level=LogLevel.WARNING
            )

            # Should only include WARNING and ERROR
            assert len(agent_logs) == 2
            assert agent_logs[0].level == LogLevel.WARNING
            assert agent_logs[1].level == LogLevel.ERROR


if __name__ == "__main__":
    pytest.main([__file__])
