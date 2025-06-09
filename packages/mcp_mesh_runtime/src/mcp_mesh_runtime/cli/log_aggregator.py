"""Log aggregation system for MCP Mesh Developer CLI."""

import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from .logging import get_logger


class LogEntry:
    """Represents a single log entry."""

    def __init__(
        self,
        timestamp: datetime,
        level: str,
        source: str,
        message: str,
        raw_line: str,
        metadata: dict[str, Any] | None = None,
    ):
        self.timestamp = timestamp
        self.level = level
        self.source = source
        self.message = message
        self.raw_line = raw_line
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        """String representation for display."""
        timestamp_str = self.timestamp.strftime("%H:%M:%S")
        return f"[{timestamp_str}] {self.level:8} {self.source}: {self.message}"


class LogParser:
    """Parses log lines from different sources."""

    # Common log patterns
    PATTERNS = {
        # Standard Python logging format: 2024-01-01 12:00:00 - name - LEVEL - message
        "python_standard": re.compile(
            r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*-\s*(?P<source>\S+)\s*-\s*(?P<level>\w+)\s*-\s*(?P<message>.*)"
        ),
        # CLI colored format: LEVEL    HH:MM:SS [source] message
        "cli_colored": re.compile(
            r"\x1b\[[0-9;]*m.*?(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL).*?\x1b\[[0-9;]*m\s*(?P<timestamp>\d{2}:\d{2}:\d{2})\s*\x1b\[[0-9;]*m\s*\[(?P<source>[^\]]+)\]\s*(?P<message>.*)"
        ),
        # Simple CLI format: LEVEL    HH:MM:SS [source] message
        "cli_simple": re.compile(
            r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(?P<timestamp>\d{2}:\d{2}:\d{2})\s+\[(?P<source>[^\]]+)\]\s+(?P<message>.*)"
        ),
        # JSON log format
        "json": None,  # Handled separately
        # Generic fallback pattern
        "generic": re.compile(
            r"(?P<timestamp>\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*(?P<level>\w+)?\s*(?P<message>.*)"
        ),
    }

    def __init__(self, default_source: str = "unknown"):
        self.default_source = default_source
        self.logger = get_logger("cli.log_parser")

    def parse_line(self, line: str, source_hint: str | None = None) -> LogEntry | None:
        """Parse a single log line into a LogEntry."""
        line = line.strip()
        if not line:
            return None

        # Try JSON parsing first
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                timestamp = self._parse_timestamp(data.get("timestamp", ""))
                return LogEntry(
                    timestamp=timestamp or datetime.now(),
                    level=data.get("level", "INFO"),
                    source=data.get("source", source_hint or self.default_source),
                    message=data.get("message", line),
                    raw_line=line,
                    metadata=data.get("metadata", {}),
                )
            except json.JSONDecodeError:
                pass

        # Try pattern matching
        for pattern_name, pattern in self.PATTERNS.items():
            if pattern is None:
                continue

            match = pattern.match(line)
            if match:
                groups = match.groupdict()

                timestamp = self._parse_timestamp(groups.get("timestamp", ""))
                level = groups.get("level", "INFO").upper()
                source = groups.get("source", source_hint or self.default_source)
                message = groups.get("message", line)

                return LogEntry(
                    timestamp=timestamp or datetime.now(),
                    level=level,
                    source=source,
                    message=message,
                    raw_line=line,
                )

        # Fallback: create entry with minimal parsing
        return LogEntry(
            timestamp=datetime.now(),
            level="INFO",
            source=source_hint or self.default_source,
            message=line,
            raw_line=line,
        )

    def _parse_timestamp(self, timestamp_str: str) -> datetime | None:
        """Parse timestamp string into datetime object."""
        if not timestamp_str:
            return None

        # Try different timestamp formats
        formats = [
            "%Y-%m-%d %H:%M:%S.%f",  # Full with microseconds
            "%Y-%m-%d %H:%M:%S",  # Full without microseconds
            "%H:%M:%S.%f",  # Time only with microseconds
            "%H:%M:%S",  # Time only
            "%Y-%m-%dT%H:%M:%S.%fZ",  # ISO format with Z
            "%Y-%m-%dT%H:%M:%S.%f",  # ISO format
            "%Y-%m-%dT%H:%M:%SZ",  # ISO format without microseconds
            "%Y-%m-%dT%H:%M:%S",  # ISO format without microseconds
        ]

        for fmt in formats:
            try:
                if "%Y" not in fmt:
                    # For time-only formats, use today's date
                    today = datetime.now().date()
                    parsed_time = datetime.strptime(timestamp_str, fmt).time()
                    return datetime.combine(today, parsed_time)
                else:
                    return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue

        return None


class LogFile:
    """Represents a log file source."""

    def __init__(
        self,
        path: Path,
        source_name: str,
        encoding: str = "utf-8",
        max_lines: int = 1000,
    ):
        self.path = path
        self.source_name = source_name
        self.encoding = encoding
        self.max_lines = max_lines
        self.last_position = 0
        self.last_size = 0

    def read_new_lines(self) -> Iterator[str]:
        """Read new lines since last read."""
        if not self.path.exists():
            return

        try:
            current_size = self.path.stat().st_size

            # If file was truncated, restart from beginning
            if current_size < self.last_size:
                self.last_position = 0

            with open(self.path, encoding=self.encoding, errors="ignore") as f:
                f.seek(self.last_position)

                for line in f:
                    yield line.rstrip("\n\r")

                self.last_position = f.tell()

            self.last_size = current_size

        except Exception:
            # Log error but don't fail
            pass

    def read_tail(self, lines: int = 100) -> list[str]:
        """Read last N lines from file."""
        if not self.path.exists():
            return []

        try:
            with open(self.path, encoding=self.encoding, errors="ignore") as f:
                return self._tail_lines(f, lines)
        except Exception:
            return []

    def _tail_lines(self, file, lines: int) -> list[str]:
        """Read last N lines from file object."""
        # Simple implementation - for large files, a more efficient approach would be needed
        all_lines = file.readlines()
        return [line.rstrip("\n\r") for line in all_lines[-lines:]]


class LogAggregator:
    """Aggregates logs from multiple sources."""

    def __init__(self):
        self.logger = get_logger("cli.log_aggregator")
        self.parser = LogParser()
        self.log_files: dict[str, LogFile] = {}
        self.entries: list[LogEntry] = []
        self.max_entries = 10000

        # Auto-discover log files
        self._discover_log_files()

    def _discover_log_files(self) -> None:
        """Discover log files automatically."""
        log_dirs = [
            Path.home() / ".mcp_mesh" / "logs",
            Path.cwd() / "logs",
            Path("/tmp/mcp_mesh_logs"),
        ]

        for log_dir in log_dirs:
            if log_dir.exists() and log_dir.is_dir():
                for log_file in log_dir.glob("*.log"):
                    source_name = log_file.stem
                    self.add_log_file(log_file, source_name)

    def add_log_file(self, path: Path, source_name: str) -> None:
        """Add a log file to monitor."""
        self.log_files[source_name] = LogFile(path, source_name)
        self.logger.debug(f"Added log file: {path} as source '{source_name}'")

    def remove_log_file(self, source_name: str) -> None:
        """Remove a log file from monitoring."""
        if source_name in self.log_files:
            del self.log_files[source_name]
            self.logger.debug(f"Removed log file source: {source_name}")

    def refresh_logs(self) -> list[LogEntry]:
        """Refresh logs from all sources and return new entries."""
        new_entries = []

        for source_name, log_file in self.log_files.items():
            for line in log_file.read_new_lines():
                entry = self.parser.parse_line(line, source_name)
                if entry:
                    new_entries.append(entry)

        # Add to internal storage
        self.entries.extend(new_entries)

        # Trim if too many entries
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries :]

        # Sort by timestamp
        self.entries.sort(key=lambda e: e.timestamp)

        return new_entries

    def get_recent_logs(
        self,
        limit: int = 100,
        level_filter: set[str] | None = None,
        source_filter: set[str] | None = None,
        since: datetime | None = None,
    ) -> list[LogEntry]:
        """Get recent log entries with optional filtering."""
        # Refresh first
        self.refresh_logs()

        filtered_entries = []

        for entry in reversed(self.entries):  # Most recent first
            # Apply filters
            if since and entry.timestamp < since:
                continue

            if level_filter and entry.level not in level_filter:
                continue

            if source_filter and entry.source not in source_filter:
                continue

            filtered_entries.append(entry)

            if len(filtered_entries) >= limit:
                break

        return filtered_entries

    def get_tail_logs(self, source: str, lines: int = 100) -> list[LogEntry]:
        """Get tail logs from specific source."""
        log_file = self.log_files.get(source)
        if not log_file:
            return []

        tail_lines = log_file.read_tail(lines)
        entries = []

        for line in tail_lines:
            entry = self.parser.parse_line(line, source)
            if entry:
                entries.append(entry)

        return entries

    def search_logs(
        self, query: str, limit: int = 100, case_sensitive: bool = False
    ) -> list[LogEntry]:
        """Search logs for specific text."""
        # Refresh first
        self.refresh_logs()

        if not case_sensitive:
            query = query.lower()

        matching_entries = []

        for entry in reversed(self.entries):
            message = entry.message if case_sensitive else entry.message.lower()

            if query in message:
                matching_entries.append(entry)

                if len(matching_entries) >= limit:
                    break

        return matching_entries

    def get_log_summary(self) -> dict[str, Any]:
        """Get summary of log aggregation status."""
        # Refresh first
        self.refresh_logs()

        # Count entries by level and source
        level_counts = {}
        source_counts = {}

        for entry in self.entries:
            level_counts[entry.level] = level_counts.get(entry.level, 0) + 1
            source_counts[entry.source] = source_counts.get(entry.source, 0) + 1

        # Get file status
        file_status = {}
        for source_name, log_file in self.log_files.items():
            file_status[source_name] = {
                "path": str(log_file.path),
                "exists": log_file.path.exists(),
                "size": log_file.path.stat().st_size if log_file.path.exists() else 0,
                "last_position": log_file.last_position,
            }

        return {
            "total_entries": len(self.entries),
            "level_counts": level_counts,
            "source_counts": source_counts,
            "monitored_files": len(self.log_files),
            "file_status": file_status,
            "last_updated": datetime.now().isoformat(),
        }

    def export_logs(
        self, output_file: Path, format: str = "json", limit: int | None = None
    ) -> bool:
        """Export logs to file."""
        try:
            # Refresh first
            self.refresh_logs()

            entries_to_export = self.entries
            if limit:
                entries_to_export = self.entries[-limit:]

            output_file.parent.mkdir(parents=True, exist_ok=True)

            if format.lower() == "json":
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [entry.to_dict() for entry in entries_to_export], f, indent=2
                    )
            else:
                # Text format
                with open(output_file, "w", encoding="utf-8") as f:
                    for entry in entries_to_export:
                        f.write(str(entry) + "\n")

            self.logger.info(
                f"Exported {len(entries_to_export)} log entries to {output_file}"
            )
            return True

        except Exception as e:
            self.logger.error(f"Failed to export logs: {e}")
            return False


# Global log aggregator instance
_log_aggregator: LogAggregator | None = None


def init_log_aggregator() -> LogAggregator:
    """Initialize global log aggregator."""
    global _log_aggregator
    _log_aggregator = LogAggregator()
    return _log_aggregator


def get_log_aggregator() -> LogAggregator:
    """Get global log aggregator instance."""
    global _log_aggregator
    if _log_aggregator is None:
        _log_aggregator = LogAggregator()
    return _log_aggregator


__all__ = [
    "LogEntry",
    "LogParser",
    "LogFile",
    "LogAggregator",
    "init_log_aggregator",
    "get_log_aggregator",
]
