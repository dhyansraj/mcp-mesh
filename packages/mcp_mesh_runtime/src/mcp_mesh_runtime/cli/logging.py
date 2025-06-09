"""Logging infrastructure for MCP Mesh Developer CLI."""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

from .config import CLIConfig


class ColoredFormatter(logging.Formatter):
    """Colored formatter for CLI output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def __init__(self, use_colors: bool = True):
        super().__init__()
        self.use_colors = (
            use_colors and hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
        )

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors if enabled."""
        # Create base formatter
        if self.use_colors:
            formatter = logging.Formatter(
                f'{self.COLORS.get(record.levelname, "")}{self.BOLD}%(levelname)-8s{self.RESET} '
                f'{self.COLORS.get(record.levelname, "")}%(asctime)s{self.RESET} '
                f"[%(name)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        else:
            formatter = logging.Formatter(
                "%(levelname)-8s %(asctime)s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        return formatter.format(record)


class CLILogger:
    """Centralized logging for CLI operations."""

    def __init__(self, config: CLIConfig):
        self.config = config
        self._loggers: dict[str, logging.Logger] = {}
        self._file_handler: logging.handlers.RotatingFileHandler | None = None
        self._console_handler: logging.StreamHandler | None = None
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Setup logging configuration."""
        # Set root logger level
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.log_level.upper()))

        # Clear existing handlers
        root_logger.handlers.clear()

        # Setup console handler
        self._setup_console_handler()

        # Setup file handler if debug mode
        if self.config.debug_mode:
            self._setup_file_handler()

    def _setup_console_handler(self) -> None:
        """Setup console logging handler."""
        self._console_handler = logging.StreamHandler(sys.stderr)
        self._console_handler.setLevel(getattr(logging, self.config.log_level.upper()))

        # Use colored formatter for console
        formatter = ColoredFormatter(use_colors=True)
        self._console_handler.setFormatter(formatter)

        # Add to root logger
        logging.getLogger().addHandler(self._console_handler)

    def _setup_file_handler(self) -> None:
        """Setup file logging handler for debug mode."""
        try:
            # Create logs directory
            log_dir = Path.home() / ".mcp_mesh" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            # Setup rotating file handler
            log_file = log_dir / "cli.log"
            self._file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
            )
            self._file_handler.setLevel(logging.DEBUG)

            # Use plain formatter for file
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            self._file_handler.setFormatter(formatter)

            # Add to root logger
            logging.getLogger().addHandler(self._file_handler)

        except Exception as e:
            # Don't fail CLI startup for logging issues
            self.get_logger("cli.logging").warning(f"Failed to setup file logging: {e}")

    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance with the given name."""
        if name not in self._loggers:
            logger = logging.getLogger(name)
            self._loggers[name] = logger

        return self._loggers[name]

    def log_operation(
        self,
        operation: str,
        status: str = "started",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log CLI operation with structured format."""
        logger = self.get_logger("cli.operations")

        message = f"Operation {operation}: {status}"
        if details:
            detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
            message += f" ({detail_str})"

        if status.lower() in ["error", "failed", "critical"]:
            logger.error(message)
        elif status.lower() in ["warning", "degraded"]:
            logger.warning(message)
        else:
            logger.info(message)

    def log_service_event(
        self, service: str, event: str, details: dict[str, Any] | None = None
    ) -> None:
        """Log service-related events."""
        logger = self.get_logger(f"cli.services.{service}")

        message = f"Service {service}: {event}"
        if details:
            detail_str = ", ".join(f"{k}={v}" for k, v in details.items())
            message += f" ({detail_str})"

        logger.info(message)

    def get_log_file_path(self) -> Path | None:
        """Get the current log file path."""
        if self._file_handler and hasattr(self._file_handler, "baseFilename"):
            return Path(self._file_handler.baseFilename)
        return None

    def set_level(self, level: str) -> None:
        """Change logging level at runtime."""
        try:
            log_level = getattr(logging, level.upper())

            # Update root logger
            logging.getLogger().setLevel(log_level)

            # Update console handler
            if self._console_handler:
                self._console_handler.setLevel(log_level)

            # File handler keeps DEBUG level

            self.get_logger("cli.logging").info(f"Log level changed to {level.upper()}")

        except AttributeError:
            self.get_logger("cli.logging").error(f"Invalid log level: {level}")

    def flush_logs(self) -> None:
        """Flush all log handlers."""
        for handler in logging.getLogger().handlers:
            handler.flush()

    def shutdown(self) -> None:
        """Shutdown logging infrastructure."""
        self.flush_logs()

        # Close file handler
        if self._file_handler:
            self._file_handler.close()

        # Remove handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)


def setup_cli_logging(config: CLIConfig) -> CLILogger:
    """Setup CLI logging with configuration."""
    return CLILogger(config)


# Global logger instance
_cli_logger: CLILogger | None = None


def get_cli_logger() -> CLILogger | None:
    """Get the global CLI logger instance."""
    return _cli_logger


def init_cli_logging(config: CLIConfig) -> CLILogger:
    """Initialize CLI logging with configuration."""
    global _cli_logger

    if _cli_logger:
        _cli_logger.shutdown()

    _cli_logger = setup_cli_logging(config)
    return _cli_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance (convenience function)."""
    if _cli_logger:
        return _cli_logger.get_logger(name)
    else:
        # Fallback to standard logging
        return logging.getLogger(name)


__all__ = [
    "ColoredFormatter",
    "CLILogger",
    "setup_cli_logging",
    "init_cli_logging",
    "get_cli_logger",
    "get_logger",
]
