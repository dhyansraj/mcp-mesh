"""Status display formatting utilities for MCP Mesh Developer CLI."""

import sys
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from ..shared.types import HealthStatusType


class StatusLevel(str, Enum):
    """Status level enumeration."""

    SUCCESS = "success"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StatusFormatter:
    """Formatter for status information with optional colors."""

    # Color codes for terminal output
    COLORS = {
        StatusLevel.SUCCESS: "\033[32m",  # Green
        StatusLevel.INFO: "\033[36m",  # Cyan
        StatusLevel.WARNING: "\033[33m",  # Yellow
        StatusLevel.ERROR: "\033[31m",  # Red
        StatusLevel.CRITICAL: "\033[35m",  # Magenta
        "BOLD": "\033[1m",
        "RESET": "\033[0m",
    }

    # Unicode symbols
    SYMBOLS = {
        StatusLevel.SUCCESS: "✓",
        StatusLevel.INFO: "ℹ",
        StatusLevel.WARNING: "⚠",
        StatusLevel.ERROR: "✗",
        StatusLevel.CRITICAL: "💥",
    }

    def __init__(self, use_colors: bool = True, use_symbols: bool = True):
        self.use_colors = (
            use_colors and hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        )
        self.use_symbols = use_symbols

    def format_status(
        self, level: StatusLevel, message: str, details: dict[str, Any] | None = None
    ) -> str:
        """Format a status message with level, color and symbol."""

        # Get symbol
        symbol = self.SYMBOLS.get(level, "") if self.use_symbols else ""

        # Get color
        if self.use_colors:
            color = self.COLORS.get(level, "")
            reset = self.COLORS["RESET"]
            bold = self.COLORS["BOLD"]
        else:
            color = reset = bold = ""

        # Format base message
        base = f"{color}{symbol} {bold}{level.value.upper()}{reset}{color}: {message}{reset}"

        # Add details if provided
        if details:
            detail_lines = []
            for key, value in details.items():
                detail_lines.append(f"  {key}: {value}")
            if detail_lines:
                base += "\n" + "\n".join(detail_lines)

        return base

    def format_health_status(self, status: HealthStatusType | str, name: str) -> str:
        """Format health status display."""
        level_map = {
            HealthStatusType.HEALTHY: StatusLevel.SUCCESS,
            HealthStatusType.DEGRADED: StatusLevel.WARNING,
            HealthStatusType.UNHEALTHY: StatusLevel.ERROR,
            HealthStatusType.UNKNOWN: StatusLevel.INFO,
        }

        # Handle string status values
        if isinstance(status, str):
            try:
                status = HealthStatusType(status)
            except ValueError:
                status = HealthStatusType.UNKNOWN

        level = level_map.get(status, StatusLevel.INFO)
        status_value = status.value if hasattr(status, "value") else str(status)
        return self.format_status(level, f"{name} is {status_value}")

    def format_table(
        self, headers: list[str], rows: list[list[str]], title: str | None = None
    ) -> str:
        """Format data as a table."""
        if not headers or not rows:
            return "No data to display"

        # Calculate column widths
        col_widths = [len(header) for header in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(str(cell)))

        # Format separator
        separator = "+" + "+".join("-" * (width + 2) for width in col_widths) + "+"

        # Format header
        header_row = (
            "|"
            + "|".join(f" {headers[i]:<{col_widths[i]}} " for i in range(len(headers)))
            + "|"
        )

        # Format rows
        data_rows = []
        for row in rows:
            formatted_row = (
                "|"
                + "|".join(
                    (
                        f" {str(row[i]):<{col_widths[i]}} "
                        if i < len(row)
                        else f' {"":< {col_widths[i]}} '
                    )
                    for i in range(len(headers))
                )
                + "|"
            )
            data_rows.append(formatted_row)

        # Combine all parts
        parts = []
        if title:
            if self.use_colors:
                parts.append(f"{self.COLORS['BOLD']}{title}{self.COLORS['RESET']}")
            else:
                parts.append(title)
            parts.append("")

        parts.extend([separator, header_row, separator, *data_rows, separator])

        return "\n".join(parts)

    def format_list(
        self, items: list[str], title: str | None = None, bullet: str = "•"
    ) -> str:
        """Format data as a bulleted list."""
        parts = []

        if title:
            if self.use_colors:
                parts.append(f"{self.COLORS['BOLD']}{title}{self.COLORS['RESET']}")
            else:
                parts.append(title)
            parts.append("")

        if not items:
            parts.append("No items to display")
        else:
            for item in items:
                parts.append(f"{bullet} {item}")

        return "\n".join(parts)

    def format_key_value(self, data: dict[str, Any], title: str | None = None) -> str:
        """Format data as key-value pairs."""
        parts = []

        if title:
            if self.use_colors:
                parts.append(f"{self.COLORS['BOLD']}{title}{self.COLORS['RESET']}")
            else:
                parts.append(title)
            parts.append("")

        if not data:
            parts.append("No data to display")
        else:
            # Find max key width for alignment
            max_key_width = max(len(str(key)) for key in data.keys()) if data else 0

            for key, value in data.items():
                if self.use_colors:
                    formatted_line = f"{self.COLORS['BOLD']}{key:<{max_key_width}}{self.COLORS['RESET']}: {value}"
                else:
                    formatted_line = f"{key:<{max_key_width}}: {value}"
                parts.append(formatted_line)

        return "\n".join(parts)


class ProcessStatus:
    """Represents the status of a process."""

    def __init__(
        self,
        name: str,
        pid: int | None = None,
        status: str = "unknown",
        uptime: timedelta | None = None,
        health: HealthStatusType | str = HealthStatusType.UNKNOWN,
        details: dict[str, Any] | None = None,
    ):
        self.name = name
        self.pid = pid
        self.status = status
        self.uptime = uptime
        # Ensure health is a HealthStatusType
        if isinstance(health, str):
            try:
                self.health = HealthStatusType(health)
            except ValueError:
                self.health = HealthStatusType.UNKNOWN
        else:
            self.health = health
        self.details = details or {}
        self.last_updated = datetime.now()

    def is_running(self) -> bool:
        """Check if process is running."""
        return self.pid is not None and self.status.lower() in [
            "running",
            "active",
            "healthy",
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "pid": self.pid,
            "status": self.status,
            "uptime": str(self.uptime) if self.uptime else None,
            "health": self.health.value,
            "last_updated": self.last_updated.isoformat(),
            "details": self.details,
        }


class StatusDisplay:
    """High-level status display manager."""

    def __init__(self, use_colors: bool = True, use_symbols: bool = True):
        self.formatter = StatusFormatter(use_colors, use_symbols)
        self.processes: dict[str, ProcessStatus] = {}

    def add_process(self, process: ProcessStatus) -> None:
        """Add or update a process status."""
        self.processes[process.name] = process

    def remove_process(self, name: str) -> None:
        """Remove a process status."""
        self.processes.pop(name, None)

    def get_process(self, name: str) -> ProcessStatus | None:
        """Get process status by name."""
        return self.processes.get(name)

    def show_success(self, message: str, details: dict[str, Any] | None = None) -> str:
        """Display a success message."""
        return self.formatter.format_status(StatusLevel.SUCCESS, message, details)

    def show_info(self, message: str, details: dict[str, Any] | None = None) -> str:
        """Display an info message."""
        return self.formatter.format_status(StatusLevel.INFO, message, details)

    def show_warning(self, message: str, details: dict[str, Any] | None = None) -> str:
        """Display a warning message."""
        return self.formatter.format_status(StatusLevel.WARNING, message, details)

    def show_error(self, message: str, details: dict[str, Any] | None = None) -> str:
        """Display an error message."""
        return self.formatter.format_status(StatusLevel.ERROR, message, details)

    def show_critical(self, message: str, details: dict[str, Any] | None = None) -> str:
        """Display a critical message."""
        return self.formatter.format_status(StatusLevel.CRITICAL, message, details)

    def show_process_status(self, name: str) -> str:
        """Display status for a specific process."""
        process = self.processes.get(name)
        if not process:
            return self.show_error(f"Process '{name}' not found")

        return self.formatter.format_health_status(process.health, process.name)

    def show_all_processes(self) -> str:
        """Display status for all processes."""
        if not self.processes:
            return self.show_info("No processes being tracked")

        headers = ["Name", "PID", "Status", "Health", "Uptime"]
        rows = []

        for process in self.processes.values():
            uptime_str = str(process.uptime) if process.uptime else "N/A"
            rows.append(
                [
                    process.name,
                    str(process.pid) if process.pid else "N/A",
                    process.status,
                    process.health.value,
                    uptime_str,
                ]
            )

        return self.formatter.format_table(headers, rows, "Process Status")

    def show_configuration(self, config_data: dict[str, Any]) -> str:
        """Display configuration information."""
        return self.formatter.format_key_value(config_data, "Configuration")

    def show_logs_summary(self, log_files: list[str]) -> str:
        """Display logs summary."""
        return self.formatter.format_list(log_files, "Available Log Files")


# Global status display instance
_status_display: StatusDisplay | None = None


def init_status_display(
    use_colors: bool = True, use_symbols: bool = True
) -> StatusDisplay:
    """Initialize global status display."""
    global _status_display
    _status_display = StatusDisplay(use_colors, use_symbols)
    return _status_display


def get_status_display() -> StatusDisplay:
    """Get global status display instance."""
    global _status_display
    if _status_display is None:
        _status_display = StatusDisplay()
    return _status_display


__all__ = [
    "StatusLevel",
    "StatusFormatter",
    "ProcessStatus",
    "StatusDisplay",
    "init_status_display",
    "get_status_display",
]
