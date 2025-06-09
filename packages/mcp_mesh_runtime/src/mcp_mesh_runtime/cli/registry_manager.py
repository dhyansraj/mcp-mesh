"""Registry service process management for MCP Mesh Developer CLI."""

import asyncio
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ImportError:
    aiohttp = None

from ..shared.registry_client import RegistryClient
from ..shared.types import HealthStatusType
from .config import CLIConfig
from .logging import get_logger
from .process_tracker import ProcessInfo, get_process_tracker


class RegistryManager:
    """Manages the registry service process lifecycle."""

    def __init__(self, config: CLIConfig):
        self.config = config
        self.logger = get_logger("cli.registry_manager")
        self.process_tracker = get_process_tracker()
        self._registry_client: RegistryClient | None = None

    def _get_registry_client(self) -> RegistryClient:
        """Get or create registry client."""
        if not self._registry_client:
            registry_url = (
                f"http://{self.config.registry_host}:{self.config.registry_port}"
            )
            self._registry_client = RegistryClient(registry_url)
        return self._registry_client

    def _is_port_available(self, port: int, host: str = "localhost") -> bool:
        """Check if a port is available for binding."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex((host, port))
                return result != 0  # Port is available if connection fails
        except Exception:
            return False

    def _find_available_port(self, start_port: int, max_attempts: int = 10) -> int:
        """Find an available port starting from start_port."""
        for port in range(start_port, start_port + max_attempts):
            if self._is_port_available(port, self.config.registry_host):
                return port

        raise RuntimeError(
            f"No available ports found in range {start_port}-{start_port + max_attempts}"
        )

    def _check_database_health(self, db_path: str) -> dict[str, Any]:
        """Check database health and accessibility."""
        try:
            db_file = Path(db_path)

            # Check if database file exists and is accessible
            if not db_file.exists():
                return {
                    "status": "missing",
                    "message": "Database file does not exist",
                    "size": 0,
                    "tables": [],
                }

            # Check file permissions
            if not os.access(db_file, os.R_OK | os.W_OK):
                return {
                    "status": "inaccessible",
                    "message": "Database file permissions issue",
                    "size": db_file.stat().st_size,
                    "tables": [],
                }

            # Try to connect and check tables
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [row[0] for row in cursor.fetchall()]

                return {
                    "status": "healthy",
                    "message": "Database is accessible and contains tables",
                    "size": db_file.stat().st_size,
                    "tables": tables,
                }

        except sqlite3.Error as e:
            return {
                "status": "error",
                "message": f"SQLite error: {e}",
                "size": db_file.stat().st_size if db_file.exists() else 0,
                "tables": [],
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Unexpected error: {e}",
                "size": 0,
                "tables": [],
            }

    def _initialize_database(self, db_path: str) -> bool:
        """Initialize database if needed."""
        try:
            # Ensure parent directory exists
            db_file = Path(db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

            # Test database connectivity
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                # Check if database has been initialized (has any tables)
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()

                if not tables:
                    self.logger.info(
                        "Database is empty, will be initialized by registry service"
                    )
                else:
                    self.logger.debug(f"Database contains {len(tables)} tables")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize database {db_path}: {e}")
            return False

    def get_registry_url_from_state(self) -> str | None:
        """Get registry URL from persisted state."""
        if self.process_tracker.is_registry_state_valid():
            return self.process_tracker.get_registry_url()
        return None

    def set_registry_env_vars(self) -> dict[str, str]:
        """Set environment variables for registry connection and return them."""
        env_vars = {}

        if self.process_tracker.is_registry_state_valid():
            registry_state = self.process_tracker.get_registry_state()

            env_vars = {
                "MCP_MESH_REGISTRY_URL": registry_state["url"],
                "MCP_MESH_REGISTRY_HOST": registry_state["host"],
                "MCP_MESH_REGISTRY_PORT": str(registry_state["port"]),
                "MCP_MESH_DATABASE_URL": f"sqlite:///{registry_state['database_path']}",
            }

            # Set environment variables for current process
            for key, value in env_vars.items():
                os.environ[key] = value

            self.logger.debug(
                f"Set registry environment variables: {list(env_vars.keys())}"
            )

        return env_vars

    def get_registry_env_vars(self) -> dict[str, str]:
        """Get registry environment variables without setting them."""
        env_vars = {}

        if self.process_tracker.is_registry_state_valid():
            registry_state = self.process_tracker.get_registry_state()

            env_vars = {
                "MCP_MESH_REGISTRY_URL": registry_state["url"],
                "MCP_MESH_REGISTRY_HOST": registry_state["host"],
                "MCP_MESH_REGISTRY_PORT": str(registry_state["port"]),
                "MCP_MESH_DATABASE_URL": f"sqlite:///{registry_state['database_path']}",
            }

        return env_vars

    def start_registry_service(
        self, port: int | None = None, db_path: str | None = None
    ) -> ProcessInfo:
        """Start the registry service using the mcp-mesh-registry entry point."""

        # Use provided port or default from config
        target_port = port or self.config.registry_port
        actual_db_path = db_path or self.config.db_path

        # Check if registry is already running
        existing_process = self.process_tracker.get_process("registry")
        if existing_process and self.process_tracker._is_process_running(
            existing_process.pid
        ):
            self.logger.info(
                f"Registry service already running (PID: {existing_process.pid})"
            )
            return existing_process

        # Check and initialize database
        db_health = self._check_database_health(actual_db_path)
        self.logger.debug(f"Database health check: {db_health}")

        if db_health["status"] in ["missing", "inaccessible"]:
            if not self._initialize_database(actual_db_path):
                raise RuntimeError(f"Failed to initialize database at {actual_db_path}")
        elif db_health["status"] == "error":
            raise RuntimeError(f"Database error: {db_health['message']}")

        # Handle port conflicts
        if not self._is_port_available(target_port, self.config.registry_host):
            self.logger.warning(f"Port {target_port} is already in use")
            try:
                target_port = self._find_available_port(target_port + 1)
                self.logger.info(f"Using alternative port: {target_port}")
            except RuntimeError as e:
                self.logger.error(f"Failed to find available port: {e}")
                raise

        # Build command to start registry service
        cmd = [
            sys.executable,
            "-m",
            "mcp_mesh_runtime.server.registry_server",
            "--host",
            self.config.registry_host,
            "--port",
            str(target_port),
        ]

        self.logger.info(
            f"Starting registry service on {self.config.registry_host}:{target_port}"
        )
        self.logger.debug(f"Registry command: {' '.join(cmd)}")

        try:
            # Start the process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"MCP_MESH_DATABASE_URL": f"sqlite:///{actual_db_path}"},
            )

            # Track the process
            registry_url = f"http://{self.config.registry_host}:{target_port}"
            process_info = self.process_tracker.track_process(
                name="registry",
                pid=process.pid,
                command=cmd,
                service_type="registry",
                metadata={
                    "host": self.config.registry_host,
                    "port": target_port,
                    "database_path": actual_db_path,
                    "url": registry_url,
                },
            )

            # Update registry state in process tracker
            self.process_tracker.update_registry_state(
                url=registry_url,
                host=self.config.registry_host,
                port=target_port,
                database_path=actual_db_path,
                config=self.config.to_dict(),
            )

            # Wait a moment for startup
            time.sleep(2)

            # Verify the process is still running
            if not self.process_tracker._is_process_running(process.pid):
                # Process failed to start, get error output
                stdout, stderr = process.communicate()
                error_msg = stderr.decode() if stderr else "Unknown error"
                self.logger.error(f"Registry service failed to start: {error_msg}")
                self.process_tracker.untrack_process("registry")
                raise RuntimeError(f"Registry service failed to start: {error_msg}")

            self.logger.info(
                f"Registry service started successfully (PID: {process.pid})"
            )

            # Update config with actual port if it changed
            if target_port != self.config.registry_port:
                self.config.registry_port = target_port

            # Set environment variables for agents to use
            # This ensures the environment vars reflect the actual running registry
            env_vars = self.set_registry_env_vars()
            self.logger.debug(f"Set environment variables for registry: {env_vars}")

            return process_info

        except Exception as e:
            self.logger.error(f"Failed to start registry service: {e}")
            raise

    async def check_registry_health(self, timeout: int = 5) -> bool:
        """Check if the registry service is healthy."""
        try:
            self._get_registry_client()

            # Simple HTTP health check
            if aiohttp is None:
                self.logger.warning("aiohttp not available, skipping health check")
                return True

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                url = f"http://{self.config.registry_host}:{self.config.registry_port}/health"
                async with session.get(url) as response:
                    return response.status == 200

        except Exception as e:
            self.logger.debug(f"Registry health check failed: {e}")
            return False

    def stop_registry_service(self, timeout: int = 10) -> bool:
        """Stop the registry service gracefully."""
        self.logger.info("Stopping registry service...")

        success = self.process_tracker.terminate_process("registry", timeout)

        if success:
            self.logger.info("Registry service stopped successfully")
        else:
            self.logger.warning("Failed to stop registry service gracefully")

        return success

    def get_registry_status(self) -> dict[str, Any]:
        """Get detailed status of the registry service."""
        process_info = self.process_tracker.get_process("registry")

        if not process_info:
            return {
                "status": "not_running",
                "health": HealthStatusType.UNKNOWN.value,
                "message": "Registry service is not tracked",
                "database": {
                    "status": "unknown",
                    "message": "No database path available",
                },
            }

        is_running = self.process_tracker._is_process_running(process_info.pid)
        database_path = process_info.metadata.get("database_path", "unknown")

        status = {
            "status": "running" if is_running else "stopped",
            "pid": process_info.pid,
            "uptime": process_info.get_uptime().total_seconds() if is_running else 0,
            "host": process_info.metadata.get("host", "unknown"),
            "port": process_info.metadata.get("port", "unknown"),
            "url": process_info.metadata.get("url", "unknown"),
            "database_path": database_path,
            "health": HealthStatusType.UNKNOWN.value,
            "message": "",
        }

        # Check database health if we have a path
        if database_path != "unknown":
            db_health = self._check_database_health(database_path)
            status["database"] = db_health
        else:
            status["database"] = {
                "status": "unknown",
                "message": "No database path available",
            }

        if is_running:
            # Update health status
            health = self.process_tracker.update_health_status("registry")
            status["health"] = (
                health.value if health else HealthStatusType.UNKNOWN.value
            )
            status["message"] = "Registry service is running"
        else:
            status["health"] = HealthStatusType.UNHEALTHY.value
            status["message"] = "Registry service process has stopped"

        return status

    async def get_registry_status_async(self) -> dict[str, Any]:
        """Get detailed status of the registry service with async health check."""
        status = self.get_registry_status()

        # If the process is running, do an actual health check
        if status["status"] == "running":
            try:
                is_healthy = await self.check_registry_health()
                if is_healthy:
                    status["health"] = HealthStatusType.HEALTHY.value
                    status["message"] = "Registry service is healthy"
                else:
                    status["health"] = HealthStatusType.UNHEALTHY.value
                    status["message"] = (
                        "Registry service is not responding to health checks"
                    )
            except Exception as e:
                status["health"] = HealthStatusType.UNKNOWN.value
                status["message"] = f"Health check failed: {e}"

        return status

    def restart_registry_service(
        self, timeout: int = 10, preserve_config: bool = True
    ) -> ProcessInfo:
        """Restart the registry service."""
        self.logger.info("Restarting registry service...")

        # Preserve registry state for restoration
        old_state = None
        if preserve_config and self.process_tracker.is_registry_state_valid():
            old_state = self.process_tracker.get_registry_state()
            self.logger.debug(f"Preserving registry state: {old_state}")

        # Stop existing service
        self.stop_registry_service(timeout)

        # Wait a moment for cleanup
        time.sleep(1)

        # Start the service again - use preserved config if available
        if old_state:
            return self.start_registry_service(
                port=old_state.get("port"), db_path=old_state.get("database_path")
            )
        else:
            return self.start_registry_service()

    async def wait_for_registry_ready(
        self, timeout: int = 30, check_interval: float = 1.0
    ) -> bool:
        """Wait for the registry service to be ready and healthy."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                if await self.check_registry_health():
                    self.logger.info("Registry service is ready")
                    return True
            except Exception as e:
                self.logger.debug(f"Registry not ready yet: {e}")

            await asyncio.sleep(check_interval)

        self.logger.warning(f"Registry service not ready after {timeout} seconds")
        return False

    async def close(self) -> None:
        """Close the registry manager and cleanup resources."""
        if self._registry_client:
            await self._registry_client.close()


__all__ = [
    "RegistryManager",
]
