"""
Heartbeat sending step for MCP Mesh pipeline.

Handles sending heartbeat to the mesh registry service.
"""

import logging
from typing import Any

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


class HeartbeatSendStep(PipelineStep):
    """
    Sends heartbeat to the mesh registry.

    Performs the actual registry communication using the prepared
    heartbeat data from previous steps.
    """

    def __init__(self, required: bool = True):
        super().__init__(
            name="heartbeat-send",
            required=required,
            description="Send heartbeat to mesh registry",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Send heartbeat to registry or print JSON in debug mode."""
        result = PipelineResult(message="Heartbeat processed successfully")

        try:
            # Get required context
            health_status = context.get("health_status")
            agent_id = context.get("agent_id", "unknown-agent")
            registration_data = context.get("registration_data")

            if not health_status:
                raise ValueError("Health status not available in context")

            # Prepare heartbeat for registry
            self.logger.debug(f"🔍 Preparing heartbeat for agent '{agent_id}'")

            # Send actual HTTP request to registry
            registry_wrapper = context.get("registry_wrapper")

            if not registry_wrapper:
                # If no registry wrapper, just log the payload and mark as successful
                self.logger.info(
                    f"⚠️ No registry connection - would send heartbeat for agent '{agent_id}'"
                )
                result.add_context(
                    "heartbeat_response", {"status": "no_registry", "logged": True}
                )
                result.add_context("dependencies_resolved", {})
                result.message = (
                    f"Heartbeat logged for agent '{agent_id}' (no registry)"
                )
                return result

            self.logger.info(f"💓 Sending heartbeat for agent '{agent_id}'...")

            response = await registry_wrapper.send_heartbeat_with_dependency_resolution(
                health_status
            )

            if response:
                # Store response data
                result.add_context("heartbeat_response", response)
                result.add_context(
                    "dependencies_resolved",
                    response.get("dependencies_resolved", {}),
                )

                result.message = f"Heartbeat sent successfully for agent '{agent_id}'"
                self.logger.info(f"💚 Heartbeat successful for agent '{agent_id}'")

                # Log dependency resolution info
                deps_resolved = response.get("dependencies_resolved", {})
                if deps_resolved:
                    self.logger.info(
                        f"🔗 Dependencies resolved: {len(deps_resolved)} items"
                    )

            else:
                result.status = PipelineStatus.FAILED
                result.message = "Heartbeat failed - no response from registry"
                self.logger.error("💔 Heartbeat failed - no response")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Heartbeat processing failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Heartbeat processing failed: {e}")

        return result
