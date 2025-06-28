import asyncio
import logging
import os
from typing import Any, Dict, Optional

from ...shared.registry_client_wrapper import RegistryClientWrapper
from ..startup_pipeline import PipelineResult, PipelineStatus
from .base_step import PipelineStep


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

            # Check if registry is available
            if not registry_wrapper:
                result.status = PipelineStatus.SKIPPED
                result.message = (
                    "No registry connection - agent running in standalone mode"
                )
                self.logger.info("⚠️ No registry connection, skipping heartbeat loop")
                return result

            # Get agent ID and heartbeat interval configuration
            agent_id = context.get("agent_id", "unknown-agent")
            heartbeat_interval = self._get_heartbeat_interval(agent_config)

            # Store heartbeat config for FastAPI lifespan (don't start task in this event loop)
            result.add_context(
                "heartbeat_config",
                {
                    "registry_wrapper": registry_wrapper,
                    "agent_id": agent_id,
                    "interval": heartbeat_interval,
                    "context": context,  # Pass full context for health status building
                },
            )

            result.message = (
                f"Heartbeat config prepared (interval: {heartbeat_interval}s)"
            )
            self.logger.info(
                f"💓 Heartbeat config prepared for FastAPI lifespan with {heartbeat_interval}s interval"
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
