"""
Fast Heartbeat Check Step for MCP Mesh pipeline.

Performs lightweight HEAD requests to registry for fast topology change detection
before expensive full POST heartbeat operations.
"""

import logging
from typing import Any

from ...shared.fast_heartbeat_status import FastHeartbeatStatus, FastHeartbeatStatusUtil
from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


class FastHeartbeatStep(PipelineStep):
    """
    Fast heartbeat check step for optimization and resilience.

    Performs lightweight HEAD request to registry to check for topology changes
    before deciding whether to execute expensive full POST heartbeat.

    Stores semantic status in context for pipeline conditional execution.
    """

    def __init__(self):
        super().__init__(
            name="fast-heartbeat-check",
            required=True,
            description="Lightweight HEAD request for fast topology change detection",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Execute fast heartbeat check and store semantic status.

        Args:
            context: Pipeline context containing agent_id and registry_wrapper

        Returns:
            PipelineResult with fast_heartbeat_status in context
        """
        self.logger.debug("Starting fast heartbeat check...")

        result = PipelineResult(message="Fast heartbeat check completed")

        try:
            # Validate required context
            agent_id = context.get("agent_id")
            registry_wrapper = context.get("registry_wrapper")

            if not agent_id:
                raise ValueError("agent_id is required in context")

            if not registry_wrapper:
                raise ValueError("registry_wrapper is required in context")

            self.logger.debug(
                f"🚀 Performing fast heartbeat check for agent '{agent_id}'"
            )

            # Perform fast heartbeat check
            status = await registry_wrapper.check_fast_heartbeat(agent_id)

            # Store semantic status in context
            result.add_context("fast_heartbeat_status", status)

            # Set appropriate message based on status
            action_description = FastHeartbeatStatusUtil.get_action_description(status)
            result.message = f"Fast heartbeat check: {action_description}"

            # Log status and action
            if status == FastHeartbeatStatus.NO_CHANGES:
                self.logger.debug(
                    f"✅ Fast heartbeat: No changes detected for agent '{agent_id}'"
                )
            elif status == FastHeartbeatStatus.TOPOLOGY_CHANGED:
                self.logger.debug(
                    f"🔄 Fast heartbeat: Topology changed for agent '{agent_id}' - full refresh needed"
                )
            elif status == FastHeartbeatStatus.AGENT_UNKNOWN:
                self.logger.debug(
                    f"❓ Fast heartbeat: Agent '{agent_id}' unknown - re-registration needed"
                )
            elif status == FastHeartbeatStatus.REGISTRY_ERROR:
                self.logger.warning(
                    f"⚠️ Fast heartbeat: Registry error for agent '{agent_id}' - skipping for resilience"
                )
            elif status == FastHeartbeatStatus.NETWORK_ERROR:
                self.logger.warning(
                    f"⚠️ Fast heartbeat: Network error for agent '{agent_id}' - skipping for resilience"
                )

        except Exception as e:
            # Convert any exception to NETWORK_ERROR for resilient handling
            status = FastHeartbeatStatusUtil.from_exception(e)
            result.add_context("fast_heartbeat_status", status)

            action_description = FastHeartbeatStatusUtil.get_action_description(status)
            result.message = f"Fast heartbeat check: {action_description}"

            self.logger.warning(
                f"⚠️ Fast heartbeat check failed for agent '{agent_id}': {e}"
            )
            self.logger.debug(f"Exception details: {e}", exc_info=True)

            # Step succeeds but sets error status for pipeline decision
            # This ensures pipeline can handle errors gracefully

        # Always preserve existing context
        for key, value in context.items():
            if key not in result.context:
                result.add_context(key, value)

        return result
