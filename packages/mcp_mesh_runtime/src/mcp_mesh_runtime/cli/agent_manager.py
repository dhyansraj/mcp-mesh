"""Agent process management for MCP Mesh Developer CLI."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..shared.registry_client import RegistryClient
from ..shared.types import HealthStatusType
from .config import CLIConfig
from .logging import get_logger
from .process_tracker import ProcessInfo, get_process_tracker


class AgentManager:
    """Manages agent process lifecycle and coordination with registry."""

    def __init__(self, config: CLIConfig, registry_manager=None):
        self.config = config
        self.logger = get_logger("cli.agent_manager")
        self.process_tracker = get_process_tracker()
        self.registry_manager = registry_manager
        self._registry_client: RegistryClient | None = None

    def _get_registry_client(self) -> RegistryClient:
        """Get or create registry client."""
        if not self._registry_client:
            registry_url = (
                f"http://{self.config.registry_host}:{self.config.registry_port}"
            )
            self._registry_client = RegistryClient(registry_url)
        return self._registry_client

    def _validate_agent_file(self, agent_file: str) -> bool:
        """Validate that agent file exists and is a valid Python file."""
        agent_path = Path(agent_file)

        if not agent_path.exists():
            self.logger.error(f"Agent file not found: {agent_file}")
            return False

        if not agent_path.is_file():
            self.logger.error(f"Agent path is not a file: {agent_file}")
            return False

        if agent_path.suffix != ".py":
            self.logger.warning(f"Agent file does not have .py extension: {agent_file}")

        # Check if file is readable
        if not os.access(agent_path, os.R_OK):
            self.logger.error(f"Agent file is not readable: {agent_file}")
            return False

        self.logger.debug(f"Agent file validation passed: {agent_file}")
        return True

    def _prepare_agent_environment(self) -> dict[str, str]:
        """Prepare environment variables for agent processes."""
        env = os.environ.copy()

        # Get registry environment variables from registry manager
        if self.registry_manager:
            registry_env = self.registry_manager.get_registry_env_vars()

            # If no registry environment vars available, try to get current registry info
            if not registry_env and self.process_tracker.is_registry_state_valid():
                registry_state = self.process_tracker.get_registry_state()
                registry_env = {
                    "MCP_MESH_REGISTRY_URL": registry_state["url"],
                    "MCP_MESH_REGISTRY_HOST": registry_state["host"],
                    "MCP_MESH_REGISTRY_PORT": str(registry_state["port"]),
                    "MCP_MESH_DATABASE_URL": f"sqlite:///{registry_state['database_path']}",
                }
                self.logger.debug(
                    f"Retrieved registry environment from process tracker: {registry_env.get('MCP_MESH_REGISTRY_URL')}"
                )

            if registry_env:
                env.update(registry_env)
                self.logger.debug(
                    f"Added registry environment variables: {list(registry_env.keys())}"
                )
            else:
                self.logger.warning(
                    "No registry environment variables available from registry manager"
                )

        # Fallback: create registry environment from config if no other source available
        if "MCP_MESH_REGISTRY_URL" not in env:
            registry_url = (
                f"http://{self.config.registry_host}:{self.config.registry_port}"
            )
            env.update(
                {
                    "MCP_MESH_REGISTRY_URL": registry_url,
                    "MCP_MESH_REGISTRY_HOST": self.config.registry_host,
                    "MCP_MESH_REGISTRY_PORT": str(self.config.registry_port),
                }
            )
            self.logger.debug(
                f"Added fallback registry environment: MCP_MESH_REGISTRY_URL={registry_url}"
            )

        # Add additional mesh-specific environment variables
        env.update(
            {
                "MCP_MESH_DEBUG": "1" if self.config.debug_mode else "0",
                "MCP_MESH_LOG_LEVEL": self.config.log_level,
            }
        )

        return env

    def start_agent_process(self, agent_file: str) -> ProcessInfo:
        """Start a single agent process with registry environment injection."""
        # Validate agent file
        if not self._validate_agent_file(agent_file):
            raise ValueError(f"Invalid agent file: {agent_file}")

        agent_path = Path(agent_file).resolve()
        agent_name = agent_path.stem

        # Check if agent is already running
        existing_process = self.process_tracker.get_process(agent_name)
        if existing_process and self.process_tracker._is_process_running(
            existing_process.pid
        ):
            self.logger.info(
                f"Agent {agent_name} already running (PID: {existing_process.pid})"
            )
            return existing_process

        # Ensure registry state is available for proper environment setup
        if self.registry_manager and not self.process_tracker.is_registry_state_valid():
            self.logger.warning(
                f"Registry state not available when starting agent {agent_name}. "
                "Agent may not connect to registry properly."
            )

        # Prepare environment with registry integration
        env = self._prepare_agent_environment()

        # Build command to start agent
        cmd = [sys.executable, str(agent_path)]

        self.logger.info(f"Starting agent {agent_name} from {agent_path}")
        self.logger.debug(f"Agent command: {' '.join(cmd)}")
        self.logger.debug(
            f"Registry URL: {env.get('MCP_MESH_REGISTRY_URL', 'Not set')}"
        )
        # Log all mesh-related environment variables for debugging
        mesh_env_vars = {k: v for k, v in env.items() if k.startswith("MCP_MESH_")}
        self.logger.debug(f"Mesh environment variables: {mesh_env_vars}")

        try:
            # Start the agent process
            # Note: MCP agents use stdio transport, so we need to keep pipes open
            process = subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.PIPE,  # MCP agents need stdin for protocol
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=agent_path.parent,  # Run from agent file directory
            )

            # Track the process
            process_info = self.process_tracker.track_process(
                name=agent_name,
                pid=process.pid,
                command=cmd,
                service_type="agent",
                metadata={
                    "agent_file": str(agent_path),
                    "working_directory": str(agent_path.parent),
                    "registry_url": env.get("MCP_MESH_REGISTRY_URL"),
                },
            )

            # Wait for the agent to initialize (MCP stdio transport setup)
            time.sleep(1.5)

            # Check if the process started successfully
            # For MCP agents, we expect them to stay running waiting for input
            if process.poll() is not None:
                # Process has already exited, which indicates a startup error
                stdout, stderr = process.communicate()
                stdout_msg = stdout.decode() if stdout else ""
                stderr_msg = stderr.decode() if stderr else ""
                error_msg = (
                    stderr_msg
                    or stdout_msg
                    or f"Process exited with code {process.returncode}"
                )

                self.logger.error(
                    f"Agent {agent_name} exited during startup. Return code: {process.returncode}"
                )
                if stdout_msg:
                    self.logger.error(f"Agent {agent_name} stdout: {stdout_msg}")
                if stderr_msg:
                    self.logger.error(f"Agent {agent_name} stderr: {stderr_msg}")

                self.process_tracker.untrack_process(agent_name)
                raise RuntimeError(f"Agent {agent_name} failed to start: {error_msg}")

            # Process is running - this is expected for MCP agents
            if not self.process_tracker._is_process_running(process.pid):
                # Double-check with psutil
                self.logger.error(
                    f"Agent {agent_name} process {process.pid} not found by psutil"
                )
                self.process_tracker.untrack_process(agent_name)
                raise RuntimeError(f"Agent {agent_name} process not running")

            self.logger.info(
                f"Agent {agent_name} started successfully (PID: {process.pid})"
            )
            return process_info

        except Exception as e:
            self.logger.error(f"Failed to start agent {agent_name}: {e}")
            raise

    def start_multiple_agents(self, agent_files: list[str]) -> dict[str, ProcessInfo]:
        """Start multiple agent processes."""
        results = {}
        failed_agents = []

        for agent_file in agent_files:
            try:
                process_info = self.start_agent_process(agent_file)
                agent_name = Path(agent_file).stem
                results[agent_name] = process_info
            except Exception as e:
                agent_name = Path(agent_file).stem
                failed_agents.append((agent_name, str(e)))
                self.logger.error(f"Failed to start agent {agent_name}: {e}")

        if failed_agents:
            self.logger.warning(f"Some agents failed to start: {failed_agents}")

        return results

    def stop_agent_process(self, agent_name: str, timeout: int = 10) -> bool:
        """Stop a specific agent process gracefully."""
        self.logger.info(f"Stopping agent {agent_name}...")

        success = self.process_tracker.terminate_process(agent_name, timeout)

        if success:
            self.logger.info(f"Agent {agent_name} stopped successfully")
        else:
            self.logger.warning(f"Failed to stop agent {agent_name} gracefully")

        return success

    def stop_all_agents(self, timeout: int = 10) -> dict[str, bool]:
        """Stop all running agent processes."""
        self.logger.info("Stopping all agent processes...")

        agent_processes = {
            name: process
            for name, process in self.process_tracker.get_all_processes().items()
            if process.service_type == "agent"
        }

        results = {}
        for agent_name in agent_processes:
            results[agent_name] = self.stop_agent_process(agent_name, timeout)

        return results

    async def check_agent_health(self, agent_name: str) -> bool:
        """Check if an agent is healthy by querying the registry."""
        try:
            registry_client = self._get_registry_client()
            agents = await registry_client.get_all_agents()

            # Check if agent is registered and healthy
            for agent_info in agents:
                if agent_info.get("name") == agent_name:
                    health_status = agent_info.get("health_status", "unknown")
                    return health_status == "healthy"

            return False

        except Exception as e:
            self.logger.debug(f"Agent health check failed for {agent_name}: {e}")
            return False

    async def get_agent_status(self, agent_name: str) -> dict[str, Any]:
        """Get detailed status of a specific agent."""
        process_info = self.process_tracker.get_process(agent_name)

        if not process_info:
            return {
                "status": "not_running",
                "health": HealthStatusType.UNKNOWN.value,
                "message": f"Agent {agent_name} is not tracked",
                "registered": False,
            }

        is_running = self.process_tracker._is_process_running(process_info.pid)

        status = {
            "status": "running" if is_running else "stopped",
            "pid": process_info.pid,
            "uptime": process_info.get_uptime().total_seconds() if is_running else 0,
            "agent_file": process_info.metadata.get("agent_file", "unknown"),
            "working_directory": process_info.metadata.get(
                "working_directory", "unknown"
            ),
            "registry_url": process_info.metadata.get("registry_url", "unknown"),
            "health": HealthStatusType.UNKNOWN.value,
            "registered": False,
            "message": "",
        }

        if is_running:
            # Check registration status with registry
            try:
                is_healthy = await self.check_agent_health(agent_name)
                status["registered"] = True
                status["health"] = (
                    HealthStatusType.HEALTHY.value
                    if is_healthy
                    else HealthStatusType.UNHEALTHY.value
                )
                status["message"] = f"Agent {agent_name} is running and registered"
            except Exception as e:
                status["registered"] = False
                status["health"] = HealthStatusType.UNKNOWN.value
                status["message"] = (
                    f"Agent {agent_name} is running but registration status unknown: {e}"
                )
        else:
            status["health"] = HealthStatusType.UNHEALTHY.value
            status["message"] = f"Agent {agent_name} process has stopped"

        return status

    async def get_all_agents_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all tracked agent processes."""
        agent_processes = {
            name: process
            for name, process in self.process_tracker.get_all_processes().items()
            if process.service_type == "agent"
        }

        status_results = {}
        for agent_name in agent_processes:
            status_results[agent_name] = await self.get_agent_status(agent_name)

        return status_results

    async def wait_for_agent_registration(
        self, agent_name: str, timeout: int = 30
    ) -> bool:
        """Wait for an agent to register with the registry."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                if await self.check_agent_health(agent_name):
                    self.logger.info(f"Agent {agent_name} is registered and healthy")
                    return True
            except Exception as e:
                self.logger.debug(f"Agent {agent_name} not registered yet: {e}")

            await asyncio.sleep(1.0)

        self.logger.warning(
            f"Agent {agent_name} not registered after {timeout} seconds"
        )
        return False

    async def ensure_registry_running(self) -> bool:
        """Ensure the registry is running before starting agents."""
        if not self.registry_manager:
            self.logger.error("No registry manager available")
            return False

        # Check if registry is already running and healthy
        if self.process_tracker.is_registry_state_valid():
            try:
                is_healthy = await self.registry_manager.check_registry_health()
                if is_healthy:
                    self.logger.debug("Registry is already running and healthy")
                    return True
            except Exception as e:
                self.logger.debug(f"Registry health check failed: {e}")

        # Start registry if not running
        try:
            self.logger.info("Registry not running, starting it automatically...")
            process_info = self.registry_manager.start_registry_service()
            self.logger.info(f"Registry started (PID: {process_info.pid})")

            # Wait for registry to be ready
            is_ready = await self.registry_manager.wait_for_registry_ready(
                timeout=self.config.startup_timeout
            )
            if not is_ready:
                self.logger.error("Registry started but not ready within timeout")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Failed to start registry: {e}")
            return False

    def restart_agent_process(self, agent_name: str, timeout: int = 30) -> ProcessInfo:
        """Restart a specific agent process, preserving configuration."""
        self.logger.info(f"Restarting agent {agent_name}...")

        # Get existing process info to preserve configuration
        existing_process = self.process_tracker.get_process(agent_name)
        if not existing_process:
            raise ValueError(f"Agent {agent_name} is not currently tracked")

        # Get the agent file from metadata
        agent_file = existing_process.metadata.get("agent_file")
        if not agent_file:
            raise ValueError(f"Agent {agent_name} missing agent_file metadata")

        # Stop the current process
        stop_success = self.stop_agent_process(agent_name, timeout)
        if not stop_success:
            self.logger.warning(
                f"Failed to stop agent {agent_name} gracefully, proceeding with restart"
            )

        # Wait a moment for cleanup
        time.sleep(1.0)

        # Start the agent again with the same configuration
        try:
            new_process = self.start_agent_process(agent_file)
            self.logger.info(
                f"Agent {agent_name} restarted successfully (PID: {new_process.pid})"
            )
            return new_process
        except Exception as e:
            self.logger.error(f"Failed to restart agent {agent_name}: {e}")
            raise

    async def restart_agent_with_registration_wait(
        self, agent_name: str, timeout: int = 30
    ) -> bool:
        """Restart agent and wait for registry registration."""
        try:
            # Restart the process
            self.restart_agent_process(agent_name, timeout)

            # Wait for agent to register with registry
            registered = await self.wait_for_agent_registration(
                agent_name, timeout=self.config.startup_timeout
            )

            if registered:
                self.logger.info(
                    f"Agent {agent_name} restarted and registered successfully"
                )
                return True
            else:
                self.logger.warning(
                    f"Agent {agent_name} restarted but did not register within timeout"
                )
                return False

        except Exception as e:
            self.logger.error(f"Failed to restart agent {agent_name}: {e}")
            return False

    async def close(self) -> None:
        """Close the agent manager and cleanup resources."""
        if self._registry_client:
            await self._registry_client.close()


__all__ = [
    "AgentManager",
]
