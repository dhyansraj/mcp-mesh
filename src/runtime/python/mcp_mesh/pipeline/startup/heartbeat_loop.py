import asyncio
import logging
import os
from typing import Any, Dict, Optional

from ...shared.registry_client_wrapper import RegistryClientWrapper
from ..shared import PipelineResult, PipelineStatus
from ..shared import PipelineStep


class HeartbeatLoopStep(PipelineStep):
    """
    Starts background heartbeat loop for continuous registry communication.

    This step starts an asyncio background task that sends periodic heartbeats
    to the mesh registry using the existing registry client wrapper. The task
    runs independently and doesn't block pipeline progression.
    """

    def __init__(self):
        super().__init__(
            name="heartbeat-loop",
            required=False,  # Optional - agent can run standalone without registry
            description="Start background heartbeat loop for registry communication",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Start background heartbeat task."""
        self.logger.debug("Starting background heartbeat loop...")

        result = PipelineResult(message="Heartbeat loop started")

        try:
            # Get configuration
            agent_config = context.get("agent_config", {})
            registry_wrapper = context.get("registry_wrapper")

            # Get agent ID and heartbeat interval configuration
            agent_id = context.get("agent_id", "unknown-agent")
            heartbeat_interval = self._get_heartbeat_interval(agent_config)

            # Import heartbeat task function
            from ..heartbeat import heartbeat_lifespan_task

            # Create heartbeat config for standalone mode (registry_wrapper may be None)
            heartbeat_config = {
                "registry_wrapper": registry_wrapper,  # May be None in standalone mode
                "agent_id": agent_id,
                "interval": heartbeat_interval,
                "context": context,  # Pass full context for health status building
                "heartbeat_task_fn": heartbeat_lifespan_task,  # Pass function to avoid cross-imports
                "standalone_mode": registry_wrapper is None,
            }

            # Store heartbeat config for FastAPI lifespan
            result.add_context("heartbeat_config", heartbeat_config)

            if registry_wrapper:
                result.message = (
                    f"Heartbeat config prepared (interval: {heartbeat_interval}s)"
                )
                self.logger.info(
                    f"💓 Heartbeat config prepared for FastAPI lifespan with {heartbeat_interval}s interval"
                )
            else:
                result.message = (
                    f"Heartbeat config prepared for standalone mode (interval: {heartbeat_interval}s, no registry)"
                )
                self.logger.info(
                    f"💓 Heartbeat config prepared for standalone mode - {heartbeat_interval}s interval (no registry communication)"
                )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to start heartbeat loop: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Failed to start heartbeat loop: {e}")

        return result

    def _get_heartbeat_interval(self, agent_config: dict[str, Any]) -> int:
        """Get heartbeat interval from configuration sources."""

        # Priority order: ENV > agent_config > default
        env_interval = os.getenv("MCP_MESH_HEARTBEAT_INTERVAL")
        if env_interval:
            try:
                return int(env_interval)
            except ValueError:
                self.logger.warning(
                    f"Invalid MCP_MESH_HEARTBEAT_INTERVAL: {env_interval}"
                )

        # Check agent config
        health_interval = agent_config.get("health_interval")
        if health_interval:
            return int(health_interval)

        # Default to 30 seconds
        return 30
