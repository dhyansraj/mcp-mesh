"""
Heartbeat pipeline for MCP Mesh periodic operations.

Provides structured execution of heartbeat operations with proper error handling
and logging. Runs every 30 seconds to maintain registry communication and
dependency resolution.
"""

import logging
from typing import Any

from ..shared import PipelineResult, PipelineStatus
from ..shared.mesh_pipeline import MeshPipeline
from .dependency_resolution import DependencyResolutionStep
from .heartbeat_send import HeartbeatSendStep
from .registry_connection import RegistryConnectionStep

logger = logging.getLogger(__name__)


class HeartbeatPipeline(MeshPipeline):
    """
    Specialized pipeline for heartbeat operations.

    Executes the three core heartbeat steps in sequence:
    1. Registry connection preparation
    2. Heartbeat sending
    3. Dependency resolution

    Each step only runs if the previous step succeeds.
    """

    def __init__(self):
        super().__init__(name="heartbeat-pipeline")
        self._setup_heartbeat_steps()

    def _setup_heartbeat_steps(self) -> None:
        """Setup the heartbeat pipeline steps."""
        steps = [
            RegistryConnectionStep(),
            HeartbeatSendStep(required=True),
            DependencyResolutionStep(),
        ]

        self.add_steps(steps)
        self.logger.debug(f"Heartbeat pipeline configured with {len(steps)} steps")

    async def execute_heartbeat_cycle(
        self, heartbeat_context: dict[str, Any]
    ) -> PipelineResult:
        """
        Execute a complete heartbeat cycle with enhanced error handling.

        Args:
            heartbeat_context: Context containing registry_wrapper, agent_id, health_status, etc.

        Returns:
            PipelineResult with execution status and any context updates
        """
        self.logger.debug("Starting heartbeat pipeline execution")

        # Initialize pipeline context with heartbeat-specific data
        self.context.clear()
        self.context.update(heartbeat_context)

        try:
            # Execute the pipeline with step-by-step error tracking
            result = await self.execute()

            if result.is_success():
                self.logger.debug("✅ Heartbeat pipeline completed successfully")
            elif result.status == PipelineStatus.PARTIAL:
                self.logger.warning(
                    f"⚠️ Heartbeat pipeline completed partially: {result.message}"
                )
                # Log which steps failed
                if result.errors:
                    for error in result.errors:
                        self.logger.warning(f"  - Step error: {error}")
            else:
                self.logger.error(f"❌ Heartbeat pipeline failed: {result.message}")
                # Log detailed error information
                if result.errors:
                    for error in result.errors:
                        self.logger.error(f"  - Pipeline error: {error}")

            return result

        except Exception as e:
            # Log detailed error information for debugging
            import traceback

            self.logger.error(
                f"❌ Heartbeat pipeline failed with exception: {e}\n"
                f"Context keys: {list(self.context.keys())}\n"
                f"Traceback: {traceback.format_exc()}"
            )

            # Create failure result with detailed context
            failure_result = PipelineResult(
                status=PipelineStatus.FAILED,
                message=f"Heartbeat pipeline exception: {str(e)[:200]}...",  # Truncate long error messages
                context=self.context,
            )
            failure_result.add_error(str(e))

            return failure_result
