"""Process monitoring and recovery for MCP Mesh CLI."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..shared.types import HealthStatusType
from .logging import get_logger
from .process_tracker import ProcessInfo, get_process_tracker


@dataclass
class MonitoringPolicy:
    """Policy for process monitoring and recovery."""

    enabled: bool = True
    check_interval: float = 30.0  # seconds
    restart_on_failure: bool = False
    max_restart_attempts: int = 3
    restart_cooldown: float = 60.0  # seconds between restart attempts
    health_check_timeout: float = 10.0
    alert_on_failure: bool = True
    alert_on_recovery: bool = True


@dataclass
class ProcessHealth:
    """Health status of a monitored process."""

    name: str
    status: HealthStatusType
    last_check: datetime
    consecutive_failures: int = 0
    last_restart: datetime | None = None
    restart_count: int = 0
    error_message: str | None = None


class ProcessMonitor:
    """Monitors process health and handles recovery."""

    def __init__(self):
        self.logger = get_logger("cli.process_monitor")
        self.process_tracker = get_process_tracker()

        # Monitoring state
        self.monitoring_enabled = False
        self.monitoring_thread: threading.Thread | None = None
        self.stop_event = threading.Event()

        # Process policies and health
        self.policies: dict[str, MonitoringPolicy] = {}
        self.health_status: dict[str, ProcessHealth] = {}

        # Alert callbacks
        self.alert_callbacks: list[Callable[[str, str, dict], None]] = []

        # Default policy
        self.default_policy = MonitoringPolicy()

    def start_monitoring(self) -> None:
        """Start the process monitoring thread."""
        if self.monitoring_enabled:
            self.logger.warning("Process monitoring is already running")
            return

        self.monitoring_enabled = True
        self.stop_event.clear()

        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop, name="ProcessMonitor", daemon=True
        )
        self.monitoring_thread.start()

        self.logger.info("Process monitoring started")

    def stop_monitoring(self) -> None:
        """Stop the process monitoring thread."""
        if not self.monitoring_enabled:
            return

        self.monitoring_enabled = False
        self.stop_event.set()

        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5.0)

        self.logger.info("Process monitoring stopped")

    def set_process_policy(self, process_name: str, policy: MonitoringPolicy) -> None:
        """Set monitoring policy for a specific process."""
        self.policies[process_name] = policy
        self.logger.debug(f"Set monitoring policy for {process_name}: {policy}")

    def get_process_policy(self, process_name: str) -> MonitoringPolicy:
        """Get monitoring policy for a process."""
        return self.policies.get(process_name, self.default_policy)

    def add_alert_callback(self, callback: Callable[[str, str, dict], None]) -> None:
        """Add a callback for process alerts.

        Args:
            callback: Function with signature (event_type, process_name, details)
        """
        self.alert_callbacks.append(callback)

    def remove_alert_callback(self, callback: Callable[[str, str, dict], None]) -> None:
        """Remove an alert callback."""
        if callback in self.alert_callbacks:
            self.alert_callbacks.remove(callback)

    def _send_alert(self, event_type: str, process_name: str, details: dict) -> None:
        """Send alert to all registered callbacks."""
        for callback in self.alert_callbacks:
            try:
                callback(event_type, process_name, details)
            except Exception as e:
                self.logger.warning(f"Alert callback failed: {e}")

    def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        self.logger.debug("Starting monitoring loop")

        while not self.stop_event.is_set():
            try:
                self._check_all_processes()

                # Wait for next check interval
                min_interval = (
                    min(
                        policy.check_interval
                        for policy in self.policies.values()
                        if policy.enabled
                    )
                    if self.policies
                    else self.default_policy.check_interval
                )

                self.stop_event.wait(timeout=min_interval)

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                self.stop_event.wait(timeout=10.0)  # Brief pause before retry

    def _check_all_processes(self) -> None:
        """Check health of all tracked processes."""
        tracked_processes = self.process_tracker.get_all_processes()

        for process_name, process_info in tracked_processes.items():
            policy = self.get_process_policy(process_name)

            if not policy.enabled:
                continue

            try:
                self._check_process_health(process_name, process_info, policy)
            except Exception as e:
                self.logger.error(f"Error checking health of {process_name}: {e}")

    def _check_process_health(
        self, process_name: str, process_info: ProcessInfo, policy: MonitoringPolicy
    ) -> None:
        """Check health of a single process."""
        current_time = datetime.now()

        # Get or create health status
        if process_name not in self.health_status:
            self.health_status[process_name] = ProcessHealth(
                name=process_name,
                status=HealthStatusType.UNKNOWN,
                last_check=current_time,
            )

        health = self.health_status[process_name]

        # Check if process is running
        if not self.process_tracker._is_process_running(process_info.pid):
            self._handle_process_failure(
                process_name, health, policy, "Process not running"
            )
            return

        # Perform health check
        try:
            detailed_health = self.process_tracker.monitor_process_health(process_name)

            if detailed_health.get("error"):
                self._handle_process_failure(
                    process_name, health, policy, detailed_health["error"]
                )
                return

            # Check process-specific health indicators
            process_health_status = detailed_health.get(
                "basic_health", HealthStatusType.UNKNOWN
            )

            if process_health_status == HealthStatusType.UNHEALTHY:
                self._handle_process_failure(
                    process_name, health, policy, "Process health check failed"
                )
                return

            # Process is healthy
            self._handle_process_recovery(process_name, health, policy)

        except Exception as e:
            self._handle_process_failure(
                process_name, health, policy, f"Health check error: {e}"
            )

    def _handle_process_failure(
        self,
        process_name: str,
        health: ProcessHealth,
        policy: MonitoringPolicy,
        error_message: str,
    ) -> None:
        """Handle process failure detection."""
        previous_status = health.status
        health.status = HealthStatusType.UNHEALTHY
        health.last_check = datetime.now()
        health.consecutive_failures += 1
        health.error_message = error_message

        # Log failure
        if previous_status != HealthStatusType.UNHEALTHY:
            self.logger.warning(
                f"Process {process_name} failure detected: {error_message}"
            )

            # Send alert for new failure
            if policy.alert_on_failure:
                self._send_alert(
                    "process_failed",
                    process_name,
                    {
                        "error": error_message,
                        "consecutive_failures": health.consecutive_failures,
                        "timestamp": health.last_check.isoformat(),
                    },
                )

        # Handle restart if enabled
        if policy.restart_on_failure and self._should_restart_process(health, policy):
            self._attempt_process_restart(process_name, health, policy)

    def _handle_process_recovery(
        self, process_name: str, health: ProcessHealth, policy: MonitoringPolicy
    ) -> None:
        """Handle process recovery detection."""
        previous_status = health.status
        health.status = HealthStatusType.HEALTHY
        health.last_check = datetime.now()

        if health.consecutive_failures > 0:
            self.logger.info(
                f"Process {process_name} recovered after {health.consecutive_failures} failures"
            )

            # Send recovery alert
            if (
                policy.alert_on_recovery
                and previous_status == HealthStatusType.UNHEALTHY
            ):
                self._send_alert(
                    "process_recovered",
                    process_name,
                    {
                        "previous_failures": health.consecutive_failures,
                        "timestamp": health.last_check.isoformat(),
                    },
                )

            # Reset failure count
            health.consecutive_failures = 0
            health.error_message = None

    def _should_restart_process(
        self, health: ProcessHealth, policy: MonitoringPolicy
    ) -> bool:
        """Determine if a process should be restarted."""
        # Check restart attempt limits
        if health.restart_count >= policy.max_restart_attempts:
            self.logger.warning(
                f"Process {health.name} has reached max restart attempts ({policy.max_restart_attempts})"
            )
            return False

        # Check restart cooldown
        if health.last_restart:
            cooldown_elapsed = (datetime.now() - health.last_restart).total_seconds()
            if cooldown_elapsed < policy.restart_cooldown:
                self.logger.debug(
                    f"Process {health.name} restart in cooldown ({cooldown_elapsed:.1f}s < {policy.restart_cooldown}s)"
                )
                return False

        return True

    def _attempt_process_restart(
        self, process_name: str, health: ProcessHealth, policy: MonitoringPolicy
    ) -> None:
        """Attempt to restart a failed process."""
        self.logger.info(
            f"Attempting to restart process {process_name} (attempt {health.restart_count + 1})"
        )

        try:
            # Get dependencies for the process
            dependencies = self.process_tracker.get_process_dependencies(process_name)

            # Attempt restart with dependency check
            new_process_info = (
                self.process_tracker.restart_process_with_dependency_check(
                    process_name,
                    dependency_names=dependencies,
                    timeout=int(policy.health_check_timeout),
                )
            )

            if new_process_info:
                health.restart_count += 1
                health.last_restart = datetime.now()
                health.consecutive_failures = 0  # Reset on successful restart

                self.logger.info(
                    f"Successfully restarted {process_name} with PID {new_process_info.pid}"
                )

                # Send restart alert
                self._send_alert(
                    "process_restarted",
                    process_name,
                    {
                        "new_pid": new_process_info.pid,
                        "restart_count": health.restart_count,
                        "timestamp": health.last_restart.isoformat(),
                    },
                )
            else:
                self.logger.error(f"Failed to restart process {process_name}")

                # Send restart failure alert
                self._send_alert(
                    "process_restart_failed",
                    process_name,
                    {
                        "restart_count": health.restart_count,
                        "timestamp": datetime.now().isoformat(),
                    },
                )

        except Exception as e:
            self.logger.error(f"Error restarting process {process_name}: {e}")

    def get_monitoring_status(self) -> dict[str, dict]:
        """Get current monitoring status for all processes."""
        status = {"monitoring_enabled": self.monitoring_enabled, "processes": {}}

        for process_name, health in self.health_status.items():
            policy = self.get_process_policy(process_name)

            status["processes"][process_name] = {
                "health": health.status.value,
                "last_check": health.last_check.isoformat(),
                "consecutive_failures": health.consecutive_failures,
                "restart_count": health.restart_count,
                "last_restart": (
                    health.last_restart.isoformat() if health.last_restart else None
                ),
                "error_message": health.error_message,
                "policy": {
                    "enabled": policy.enabled,
                    "restart_on_failure": policy.restart_on_failure,
                    "check_interval": policy.check_interval,
                    "max_restart_attempts": policy.max_restart_attempts,
                },
            }

        return status

    def reset_process_health(self, process_name: str) -> bool:
        """Reset health status for a process."""
        if process_name in self.health_status:
            health = self.health_status[process_name]
            health.consecutive_failures = 0
            health.restart_count = 0
            health.last_restart = None
            health.error_message = None
            health.status = HealthStatusType.UNKNOWN

            self.logger.info(f"Reset health status for process {process_name}")
            return True

        return False


# Global process monitor instance
_process_monitor: ProcessMonitor | None = None


def get_process_monitor() -> ProcessMonitor:
    """Get the global process monitor instance."""
    global _process_monitor
    if _process_monitor is None:
        _process_monitor = ProcessMonitor()
    return _process_monitor


def start_process_monitoring() -> ProcessMonitor:
    """Start process monitoring and return monitor instance."""
    monitor = get_process_monitor()
    monitor.start_monitoring()
    return monitor


def stop_process_monitoring() -> None:
    """Stop process monitoring."""
    global _process_monitor
    if _process_monitor:
        _process_monitor.stop_monitoring()


__all__ = [
    "MonitoringPolicy",
    "ProcessHealth",
    "ProcessMonitor",
    "get_process_monitor",
    "start_process_monitoring",
    "stop_process_monitoring",
]
