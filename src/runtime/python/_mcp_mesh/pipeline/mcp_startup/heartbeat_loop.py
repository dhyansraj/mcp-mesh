import asyncio
import logging
import os
from typing import Any, Dict, Optional

from ...shared.config_resolver import ValidationRule, get_config_value
from ...shared.registry_client_wrapper import RegistryClientWrapper
from ..shared import PipelineResult, PipelineStatus, PipelineStep


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

            # Get agent ID and heartbeat interval configuration using centralized defaults
            from ...shared.defaults import MeshDefaults

            agent_id = context.get("agent_id", "unknown-agent")
            heartbeat_interval = get_config_value(
                "MCP_MESH_HEALTH_INTERVAL",
                override=agent_config.get("health_interval"),
                default=MeshDefaults.HEALTH_INTERVAL,
                rule=ValidationRule.NONZERO_RULE,
            )

            # Check for explicit standalone mode configuration
            standalone_mode = self._get_standalone_mode()

            # Import heartbeat task function
            from ..mcp_heartbeat import heartbeat_lifespan_task

            # Create heartbeat config - registry connection will be attempted in heartbeat pipeline
            heartbeat_config = {
                "registry_wrapper": None,  # Will be created in heartbeat pipeline
                "agent_id": agent_id,
                "interval": heartbeat_interval,
                "context": context,  # Pass full context for health status building
                "heartbeat_task_fn": heartbeat_lifespan_task,  # Pass function to avoid cross-imports
                "standalone_mode": standalone_mode,
            }

            # Store heartbeat config for FastAPI lifespan
            result.add_context("heartbeat_config", heartbeat_config)

            if standalone_mode:
                result.message = (
                    "Heartbeat disabled for standalone mode (no registry communication)"
                )
                self.logger.info(
                    "💓 Heartbeat disabled for standalone mode - no registry communication"
                )
            else:
                result.message = (
                    f"Heartbeat config prepared (interval: {heartbeat_interval}s)"
                )
                self.logger.info(
                    f"💓 Heartbeat config prepared for FastAPI lifespan with {heartbeat_interval}s interval (registry connection in heartbeat pipeline)"
                )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to start heartbeat loop: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Failed to start heartbeat loop: {e}")

        return result

    def _get_standalone_mode(self) -> bool:
        """Check if standalone mode is explicitly enabled."""
        return get_config_value(
            "MCP_MESH_STANDALONE", default=False, rule=ValidationRule.TRUTHY_RULE
        )
