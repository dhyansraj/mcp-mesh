"""
Port bridge for communicating actual port from server to heartbeat.

When port=0 is used (auto-assign), the actual port is only known after
uvicorn binds. This bridge allows the heartbeat to get the actual port
and call handle.update_port().
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Global port bridge instance
_port_bridge: Optional["PortBridge"] = None
_lock = threading.Lock()


class PortBridge:
    """Thread-safe bridge for port updates between server and heartbeat."""

    def __init__(self):
        self._actual_port: int | None = None
        self._configured_port: int = 0
        self._lock = threading.Lock()
        self._updated = threading.Event()

    def set_configured_port(self, port: int) -> None:
        """Set the configured port (before server starts)."""
        with self._lock:
            self._configured_port = port

    def set_actual_port(self, port: int) -> None:
        """Set the actual port (after server binds)."""
        with self._lock:
            if port != self._configured_port and port > 0:
                logger.info(
                    f"Port bridge: actual port {port} (configured: {self._configured_port})"
                )
                self._actual_port = port
                self._updated.set()

    def get_actual_port(self) -> int | None:
        """Get the actual port if different from configured."""
        with self._lock:
            return self._actual_port

    def wait_for_port(self, timeout: float = 5.0) -> int | None:
        """Wait for actual port to be set (with timeout)."""
        if self._updated.wait(timeout):
            return self.get_actual_port()
        return None

    def needs_update(self) -> bool:
        """Check if port update is needed."""
        with self._lock:
            return (
                self._actual_port is not None
                and self._actual_port != self._configured_port
            )


def get_port_bridge() -> PortBridge:
    """Get or create the global port bridge."""
    global _port_bridge
    with _lock:
        if _port_bridge is None:
            _port_bridge = PortBridge()
        return _port_bridge


def reset_port_bridge() -> None:
    """Reset the global port bridge (for testing)."""
    global _port_bridge
    with _lock:
        _port_bridge = None
