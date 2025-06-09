"""Process tracking utilities for MCP Mesh Developer CLI."""

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil

from ..shared.types import HealthStatusType
from .logging import get_logger
from .status import ProcessStatus


class ProcessInfo:
    """Information about a tracked process."""

    def __init__(
        self,
        name: str,
        pid: int,
        command: list[str],
        started_at: datetime,
        service_type: str = "unknown",
    ):
        self.name = name
        self.pid = pid
        self.command = command
        self.started_at = started_at
        self.service_type = service_type
        self.last_health_check = datetime.now()
        self.health_status = HealthStatusType.UNKNOWN
        self.metadata: dict[str, Any] = {}

    def get_uptime(self) -> timedelta:
        """Get process uptime."""
        return datetime.now() - self.started_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "pid": self.pid,
            "command": self.command,
            "started_at": self.started_at.isoformat(),
            "service_type": self.service_type,
            "uptime_seconds": self.get_uptime().total_seconds(),
            "health_status": self.health_status.value,
            "last_health_check": self.last_health_check.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessInfo":
        """Create ProcessInfo from dictionary."""
        process = cls(
            name=data["name"],
            pid=data["pid"],
            command=data["command"],
            started_at=datetime.fromisoformat(data["started_at"]),
            service_type=data.get("service_type", "unknown"),
        )
        process.health_status = HealthStatusType(data.get("health_status", "unknown"))
        process.last_health_check = datetime.fromisoformat(
            data.get("last_health_check", datetime.now().isoformat())
        )
        process.metadata = data.get("metadata", {})
        return process


class ProcessTracker:
    """Tracks and manages CLI-related processes."""

    def __init__(self, state_file: Path | None = None):
        self.logger = get_logger("cli.process_tracker")
        self.state_file = state_file or Path.home() / ".mcp_mesh" / "processes.json"
        self.processes: dict[str, ProcessInfo] = {}
        self.registry_state: dict[str, Any] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load process state from file."""
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, encoding="utf-8") as f:
                data = json.load(f)

            # Load registry state
            self.registry_state = data.get("registry_state", {})
            self.logger.debug(f"Restored registry state: {self.registry_state}")

            for name, process_data in data.get("processes", {}).items():
                try:
                    process = ProcessInfo.from_dict(process_data)
                    # Verify process is still running
                    if self._is_process_running(process.pid):
                        self.processes[name] = process
                        self.logger.debug(
                            f"Restored process tracking for {name} (PID: {process.pid})"
                        )
                    else:
                        self.logger.info(
                            f"Process {name} (PID: {process.pid}) is no longer running"
                        )
                        # Clean up registry state if this was the registry process
                        if name == "registry":
                            self._clear_registry_state()
                except Exception as e:
                    self.logger.warning(f"Failed to restore process {name}: {e}")

        except Exception as e:
            self.logger.warning(f"Failed to load process state: {e}")

    def _save_state(self) -> None:
        """Save process state to file."""
        try:
            # Ensure parent directory exists
            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "processes": {
                    name: process.to_dict() for name, process in self.processes.items()
                },
                "registry_state": self.registry_state,
                "last_updated": datetime.now().isoformat(),
            }

            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to save process state: {e}")

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running by PID."""
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _get_process_health(self, process_info: ProcessInfo) -> HealthStatusType:
        """Get health status of a process."""
        try:
            if not self._is_process_running(process_info.pid):
                return HealthStatusType.UNHEALTHY

            # For now, just check if process is running
            # In the future, this could do more sophisticated health checks
            return HealthStatusType.HEALTHY

        except Exception as e:
            self.logger.warning(f"Failed to check health for {process_info.name}: {e}")
            return HealthStatusType.UNKNOWN

    def track_process(
        self,
        name: str,
        pid: int,
        command: list[str],
        service_type: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> ProcessInfo:
        """Start tracking a process."""
        process_info = ProcessInfo(
            name=name,
            pid=pid,
            command=command,
            started_at=datetime.now(),
            service_type=service_type,
        )

        if metadata:
            process_info.metadata.update(metadata)

        self.processes[name] = process_info
        self._save_state()

        self.logger.info(f"Started tracking process {name} (PID: {pid})")
        return process_info

    def untrack_process(self, name: str) -> bool:
        """Stop tracking a process."""
        if name in self.processes:
            process_info = self.processes.pop(name)
            self._save_state()
            self.logger.info(
                f"Stopped tracking process {name} (PID: {process_info.pid})"
            )
            return True
        return False

    def get_process(self, name: str) -> ProcessInfo | None:
        """Get information about a tracked process."""
        return self.processes.get(name)

    def get_all_processes(self) -> dict[str, ProcessInfo]:
        """Get all tracked processes."""
        return self.processes.copy()

    def get_running_processes(self) -> dict[str, ProcessInfo]:
        """Get only running processes."""
        running = {}
        for name, process in self.processes.items():
            if self._is_process_running(process.pid):
                running[name] = process
        return running

    def cleanup_dead_processes(self) -> list[str]:
        """Remove dead processes from tracking."""
        dead_processes = []

        for name, process in list(self.processes.items()):
            if not self._is_process_running(process.pid):
                dead_processes.append(name)
                del self.processes[name]
                self.logger.info(f"Cleaned up dead process {name} (PID: {process.pid})")

        if dead_processes:
            self._save_state()

        return dead_processes

    def update_health_status(self, name: str) -> HealthStatusType | None:
        """Update and return health status for a process."""
        process_info = self.processes.get(name)
        if not process_info:
            return None

        health = self._get_process_health(process_info)
        process_info.health_status = health
        process_info.last_health_check = datetime.now()
        self._save_state()

        return health

    def update_all_health_status(self) -> dict[str, HealthStatusType]:
        """Update health status for all tracked processes."""
        health_status = {}

        for name in list(self.processes.keys()):
            health = self.update_health_status(name)
            if health:
                health_status[name] = health

        return health_status

    def terminate_process(self, name: str, timeout: int = 10) -> bool:
        """Terminate a tracked process gracefully."""
        process_info = self.processes.get(name)
        if not process_info:
            self.logger.warning(f"Process {name} not found for termination")
            return False

        try:
            process = psutil.Process(process_info.pid)

            # Try graceful termination first
            self.logger.info(
                f"Attempting graceful termination of {name} (PID: {process_info.pid})"
            )
            process.terminate()

            # Wait for process to terminate
            try:
                process.wait(timeout=timeout)
                self.logger.info(f"Process {name} terminated gracefully")
            except psutil.TimeoutExpired:
                # Force kill if graceful termination fails
                self.logger.warning(f"Force killing {name} (PID: {process_info.pid})")
                process.kill()
                process.wait(timeout=5)
                self.logger.info(f"Process {name} force killed")

            # Remove from tracking
            self.untrack_process(name)
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Failed to terminate {name}: {e}")
            # Remove from tracking anyway
            self.untrack_process(name)
            return False

    def terminate_all_processes(self, timeout: int = 10) -> dict[str, bool]:
        """Terminate all tracked processes."""
        results = {}

        # Import here to avoid circular imports
        from .process_tree import get_process_tree

        process_tree = get_process_tree()

        # First, try graceful termination of all process trees
        for name in list(self.processes.keys()):
            process_info = self.processes[name]
            self.logger.info(
                f"Terminating process tree for {name} (PID: {process_info.pid})"
            )

            # Use process tree termination for better cleanup
            tree_results = process_tree.terminate_process_tree(
                process_info.pid,
                timeout=timeout,
                force_kill_timeout=min(5, timeout // 2),
            )

            # If root process was terminated successfully, mark as success
            if process_info.pid in tree_results:
                results[name] = tree_results[process_info.pid]
                if results[name]:
                    self.untrack_process(name)
            else:
                # Fallback to single process termination
                results[name] = self.terminate_process(name, timeout)

        return results

    def get_process_status_summary(self) -> dict[str, ProcessStatus]:
        """Get process status summary for display."""
        self.cleanup_dead_processes()

        status_summary = {}

        for name, process_info in self.processes.items():
            health = self.update_health_status(name)

            status = (
                "running" if self._is_process_running(process_info.pid) else "stopped"
            )

            process_status = ProcessStatus(
                name=name,
                pid=process_info.pid,
                status=status,
                uptime=process_info.get_uptime(),
                health=health or HealthStatusType.UNKNOWN,
                details={
                    "service_type": process_info.service_type,
                    "command": " ".join(process_info.command),
                    "started_at": process_info.started_at.isoformat(),
                },
            )

            status_summary[name] = process_status

        return status_summary

    def update_registry_state(
        self,
        url: str,
        host: str,
        port: int,
        database_path: str,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Update registry state information."""
        self.registry_state = {
            "url": url,
            "host": host,
            "port": port,
            "database_path": database_path,
            "config": config or {},
            "last_updated": datetime.now().isoformat(),
        }
        self._save_state()
        self.logger.info(f"Updated registry state: {url}")

    def get_registry_state(self) -> dict[str, Any]:
        """Get the current registry state."""
        return self.registry_state.copy()

    def get_registry_url(self) -> str | None:
        """Get the current registry URL if available."""
        return self.registry_state.get("url")

    def get_registry_database_path(self) -> str | None:
        """Get the current registry database path if available."""
        return self.registry_state.get("database_path")

    def _clear_registry_state(self) -> None:
        """Clear registry state when registry is no longer running."""
        if self.registry_state:
            self.logger.debug("Clearing registry state")
            self.registry_state = {}
            self._save_state()

    def is_registry_state_valid(self) -> bool:
        """Check if the current registry state is valid and the registry is running."""
        if not self.registry_state:
            return False

        registry_process = self.get_process("registry")
        if not registry_process:
            self._clear_registry_state()
            return False

        if not self._is_process_running(registry_process.pid):
            self._clear_registry_state()
            return False

        return True

    def restart_process(
        self,
        name: str,
        new_command: list[str] | None = None,
        new_metadata: dict[str, Any] | None = None,
        timeout: int = 10,
    ) -> ProcessInfo | None:
        """Restart a tracked process with optional new configuration.

        Args:
            name: Process name to restart
            new_command: New command to run (if None, uses original command)
            new_metadata: New metadata (if None, preserves original metadata)
            timeout: Timeout for shutdown

        Returns:
            New ProcessInfo if successful, None if failed
        """
        process_info = self.processes.get(name)
        if not process_info:
            self.logger.warning(f"Process {name} not found for restart")
            return None

        # Store original configuration
        original_command = process_info.command
        original_metadata = process_info.metadata.copy()
        original_service_type = process_info.service_type

        # Use new configuration if provided
        restart_command = new_command or original_command
        restart_metadata = new_metadata or original_metadata

        self.logger.info(f"Restarting process {name} (PID: {process_info.pid})")

        # Step 1: Terminate existing process
        terminate_success = self.terminate_process(name, timeout)
        if not terminate_success:
            self.logger.error(f"Failed to terminate process {name} for restart")
            return None

        # Step 2: Start new process
        try:
            # Add delay to ensure clean shutdown
            time.sleep(0.5)

            # Get working directory from metadata
            working_dir = restart_metadata.get("working_directory", ".")

            # Start new process
            process = subprocess.Popen(
                restart_command,
                cwd=working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,  # Create new process group for better cleanup
            )

            # Track the new process
            new_process_info = self.track_process(
                name=name,
                pid=process.pid,
                command=restart_command,
                service_type=original_service_type,
                metadata=restart_metadata,
            )

            # Verify process started successfully
            time.sleep(0.2)
            if not self._is_process_running(process.pid):
                self.logger.error(f"Restarted process {name} died immediately")
                self.untrack_process(name)
                return None

            self.logger.info(
                f"Successfully restarted {name} with new PID: {process.pid}"
            )
            return new_process_info

        except Exception as e:
            self.logger.error(f"Failed to restart process {name}: {e}")
            return None

    def restart_process_with_dependency_check(
        self, name: str, dependency_names: list[str] = None, timeout: int = 10
    ) -> ProcessInfo | None:
        """Restart a process while ensuring dependencies are running.

        Args:
            name: Process name to restart
            dependency_names: List of dependency process names to check
            timeout: Timeout for shutdown

        Returns:
            New ProcessInfo if successful, None if failed
        """
        # Check dependencies first
        if dependency_names:
            missing_deps = []
            for dep_name in dependency_names:
                dep_process = self.get_process(dep_name)
                if not dep_process or not self._is_process_running(dep_process.pid):
                    missing_deps.append(dep_name)

            if missing_deps:
                self.logger.error(
                    f"Cannot restart {name}: missing dependencies {missing_deps}"
                )
                return None

        return self.restart_process(name, timeout=timeout)

    def get_process_dependencies(self, name: str) -> list[str]:
        """Get process dependencies from metadata.

        Args:
            name: Process name

        Returns:
            List of dependency process names
        """
        process_info = self.get_process(name)
        if not process_info:
            return []

        return process_info.metadata.get("dependencies", [])

    def cleanup_orphaned_processes(self) -> dict[int, bool]:
        """Find and cleanup orphaned MCP Mesh processes.

        Returns:
            Dict mapping PID to cleanup success status
        """
        from .process_tree import get_process_tree

        process_tree = get_process_tree()

        # Get all known PIDs
        known_pids = {proc.pid for proc in self.processes.values()}

        # Find orphaned processes
        orphaned_pids = process_tree.find_orphaned_processes(known_pids)

        if orphaned_pids:
            self.logger.info(
                f"Found {len(orphaned_pids)} orphaned processes to cleanup"
            )
            return process_tree.cleanup_orphaned_processes(orphaned_pids)

        return {}

    def get_cross_platform_process_info(self, pid: int) -> dict[str, Any]:
        """Get cross-platform process information.

        Args:
            pid: Process ID

        Returns:
            Dict with process information
        """
        try:
            process = psutil.Process(pid)

            info = {
                "pid": pid,
                "name": process.name(),
                "status": process.status(),
                "create_time": process.create_time(),
                "num_threads": process.num_threads(),
                "memory_percent": process.memory_percent(),
                "is_running": process.is_running(),
            }

            # Add platform-specific information
            try:
                info["cmdline"] = process.cmdline()
                info["cwd"] = process.cwd()
                info["memory_info"] = process.memory_info()._asdict()
                info["cpu_percent"] = process.cpu_percent(interval=0.1)

                # Unix-specific
                if hasattr(process, "nice"):
                    info["nice"] = process.nice()
                if hasattr(process, "uids"):
                    info["uids"] = process.uids()._asdict()

                # Windows-specific
                if hasattr(process, "num_handles"):
                    info["num_handles"] = process.num_handles()

            except (psutil.AccessDenied, psutil.NoSuchProcess):
                # Some info may not be accessible
                pass

            return info

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return {"pid": pid, "error": str(e), "accessible": False}

    def monitor_process_health(self, name: str) -> dict[str, Any]:
        """Get comprehensive health monitoring for a process.

        Args:
            name: Process name

        Returns:
            Dict with health information
        """
        process_info = self.get_process(name)
        if not process_info:
            return {"error": f"Process {name} not found"}

        health_info = {
            "name": name,
            "basic_health": self._get_process_health(process_info),
            "detailed_info": self.get_cross_platform_process_info(process_info.pid),
            "uptime": process_info.get_uptime().total_seconds(),
            "last_health_check": process_info.last_health_check.isoformat(),
        }

        # Add process tree information
        from .process_tree import get_process_tree

        process_tree = get_process_tree()
        health_info["process_tree"] = process_tree.get_process_info_tree(
            process_info.pid
        )

        return health_info


# Global process tracker instance
_process_tracker: ProcessTracker | None = None


def init_process_tracker(state_file: Path | None = None) -> ProcessTracker:
    """Initialize global process tracker."""
    global _process_tracker
    _process_tracker = ProcessTracker(state_file)
    return _process_tracker


def get_process_tracker() -> ProcessTracker:
    """Get global process tracker instance."""
    global _process_tracker
    if _process_tracker is None:
        _process_tracker = ProcessTracker()
    return _process_tracker


__all__ = [
    "ProcessInfo",
    "ProcessTracker",
    "init_process_tracker",
    "get_process_tracker",
]
