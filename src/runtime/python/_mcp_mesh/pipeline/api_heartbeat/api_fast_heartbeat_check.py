"""
Fast Heartbeat Check Step for API heartbeat pipeline.

Performs lightweight HEAD requests to registry for fast topology change detection
before expensive full POST heartbeat operations for FastAPI services.
"""

import logging
from typing import Any

from ...shared.fast_heartbeat_status import FastHeartbeatStatus, FastHeartbeatStatusUtil
from ..shared.base_step import PipelineStep
from ..shared.pipeline_types import PipelineResult

logger = logging.getLogger(__name__)


class APIFastHeartbeatStep(PipelineStep):
    """
    Fast heartbeat check step for API services optimization and resilience.

    Performs lightweight HEAD request to registry to check for topology changes
    before deciding whether to execute expensive full POST heartbeat for API services.

    Stores semantic status in context for pipeline conditional execution.
    """

    def __init__(self):
        super().__init__(
            name="api-fast-heartbeat-check",
            required=True,
            description="Lightweight HEAD request for fast topology change detection (API services)",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Execute fast heartbeat check for API service and store semantic status.

        Args:
            context: Pipeline context containing service_id/agent_id and registry_wrapper

        Returns:
            PipelineResult with fast_heartbeat_status in context
        """
        self.logger.debug("Starting API fast heartbeat check...")

        result = PipelineResult(message="API fast heartbeat check completed")

        try:
            # Validate required context - API services use service_id or agent_id
            service_id = context.get("service_id") or context.get("agent_id")
            registry_wrapper = context.get("registry_wrapper")

            if not service_id:
                raise ValueError("service_id or agent_id is required in context")

            if not registry_wrapper:
                raise ValueError("registry_wrapper is required in context")

            self.logger.debug(
                f"🚀 Performing API fast heartbeat check for service '{service_id}'"
            )

            # Perform fast heartbeat check using same method as MCP agents
            status = await registry_wrapper.check_fast_heartbeat(service_id)

            # Store semantic status in context
            result.add_context("fast_heartbeat_status", status)

            # Set appropriate message based on status
            action_description = FastHeartbeatStatusUtil.get_action_description(status)
            result.message = f"API fast heartbeat check: {action_description}"

            # Log status and action with API-specific messaging
            if status == FastHeartbeatStatus.NO_CHANGES:
                self.logger.info(
                    f"✅ API fast heartbeat: No changes detected for service '{service_id}'"
                )
            elif status == FastHeartbeatStatus.TOPOLOGY_CHANGED:
                self.logger.info(
                    f"🔄 API fast heartbeat: Topology changed for service '{service_id}' - full refresh needed"
                )
            elif status == FastHeartbeatStatus.AGENT_UNKNOWN:
                self.logger.info(
                    f"❓ API fast heartbeat: Service '{service_id}' unknown - re-registration needed"
                )
            elif status == FastHeartbeatStatus.REGISTRY_ERROR:
                self.logger.warning(
                    f"⚠️ API fast heartbeat: Registry error for service '{service_id}' - skipping for resilience"
                )
            elif status == FastHeartbeatStatus.NETWORK_ERROR:
                self.logger.warning(
                    f"⚠️ API fast heartbeat: Network error for service '{service_id}' - skipping for resilience"
                )

        except Exception as e:
            # Convert any exception to NETWORK_ERROR for resilient handling
            status = FastHeartbeatStatusUtil.from_exception(e)
            result.add_context("fast_heartbeat_status", status)

            action_description = FastHeartbeatStatusUtil.get_action_description(status)
            result.message = f"API fast heartbeat check: {action_description}"

            self.logger.warning(
                f"⚠️ API fast heartbeat check failed for service '{service_id}': {e}"
            )
            self.logger.debug(f"Exception details: {e}", exc_info=True)

            # Step succeeds but sets error status for pipeline decision
            # This ensures pipeline can handle errors gracefully

        # Always preserve existing context
        for key, value in context.items():
            if key not in result.context:
                result.add_context(key, value)

        return result