"""
Heartbeat pipeline for MCP Mesh periodic operations.

Provides structured execution of heartbeat operations with proper error handling
and logging. Runs every 30 seconds to maintain registry communication and
dependency resolution.
"""

import logging
from typing import Any

from ...shared.fast_heartbeat_status import FastHeartbeatStatus, FastHeartbeatStatusUtil
from ..shared import PipelineResult, PipelineStatus
from ..shared.mesh_pipeline import MeshPipeline
from .dependency_resolution import DependencyResolutionStep
from .fast_heartbeat_check import FastHeartbeatStep
from .heartbeat_send import HeartbeatSendStep
from .llm_tools_resolution import LLMToolsResolutionStep
from .registry_connection import RegistryConnectionStep

logger = logging.getLogger(__name__)


class HeartbeatPipeline(MeshPipeline):
    """
    Specialized pipeline for heartbeat operations with fast optimization.

    Executes the five core heartbeat steps in sequence:
    1. Registry connection preparation
    2. Fast heartbeat check (HEAD request)
    3. Heartbeat sending (conditional POST request)
    4. Dependency resolution (conditional)
    5. LLM tools resolution (conditional)

    Steps 3, 4, and 5 only run if fast heartbeat indicates changes are needed.
    Provides optimization for NO_CHANGES and resilience for error conditions.
    """

    def __init__(self):
        super().__init__(name="heartbeat-pipeline")
        self._setup_heartbeat_steps()

    def _setup_heartbeat_steps(self) -> None:
        """Setup the heartbeat pipeline steps."""
        steps = [
            RegistryConnectionStep(),
            FastHeartbeatStep(),
            HeartbeatSendStep(required=True),
            DependencyResolutionStep(),
            LLMToolsResolutionStep(),
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
            # Execute the pipeline with conditional logic for fast optimization
            result = await self._execute_with_conditional_logic()

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

    async def _execute_with_conditional_logic(self) -> PipelineResult:
        """
        Execute pipeline with conditional logic based on fast heartbeat status.

        Always executes:
        - RegistryConnectionStep
        - FastHeartbeatStep

        Conditionally executes based on fast heartbeat status:
        - NO_CHANGES: Skip remaining steps (optimization)
        - TOPOLOGY_CHANGED, AGENT_UNKNOWN: Execute all remaining steps
        - REGISTRY_ERROR, NETWORK_ERROR: Skip remaining steps (resilience)

        Returns:
            PipelineResult with execution status and context
        """
        overall_result = PipelineResult(
            message="Heartbeat pipeline execution completed"
        )

        # Track which steps were executed for logging
        executed_steps = []
        skipped_steps = []

        try:
            # Always execute registry connection and fast heartbeat steps
            mandatory_steps = self.steps[
                :2
            ]  # RegistryConnectionStep, FastHeartbeatStep
            conditional_steps = self.steps[
                2:
            ]  # HeartbeatSendStep, DependencyResolutionStep, LLMToolsResolutionStep

            # Execute mandatory steps
            for step in mandatory_steps:
                self.logger.debug(f"Executing mandatory step: {step.name}")

                step_result = await step.execute(self.context)
                executed_steps.append(step.name)

                # Merge step context into pipeline context
                self.context.update(step_result.context)

                # If step fails, handle accordingly
                if not step_result.is_success():
                    overall_result.status = PipelineStatus.FAILED
                    overall_result.message = (
                        f"Mandatory step '{step.name}' failed: {step_result.message}"
                    )
                    overall_result.add_error(
                        f"Step '{step.name}': {step_result.message}"
                    )

                    if step.required:
                        # Stop execution if required step fails
                        for key, value in self.context.items():
                            overall_result.add_context(key, value)
                        return overall_result

            # Check fast heartbeat status for conditional execution
            fast_heartbeat_status = self.context.get("fast_heartbeat_status")

            if fast_heartbeat_status is None:
                # Fast heartbeat step failed to set status - fallback to full execution
                self.logger.warning(
                    "⚠️ Fast heartbeat status not found - falling back to full execution"
                )
                should_execute_remaining = True
                reason = "fallback (missing status)"
            elif FastHeartbeatStatusUtil.should_skip_for_optimization(
                fast_heartbeat_status
            ):
                # NO_CHANGES - skip for optimization
                should_execute_remaining = False
                reason = "optimization (no changes detected)"
                self.logger.debug(
                    f"🚀 Skipping remaining steps for optimization: {reason}"
                )
            elif FastHeartbeatStatusUtil.should_skip_for_resilience(
                fast_heartbeat_status
            ):
                # REGISTRY_ERROR, NETWORK_ERROR - skip for resilience
                should_execute_remaining = False
                reason = "resilience (preserve existing state)"
                self.logger.warning(
                    f"⚠️ Skipping remaining steps for resilience: {reason}"
                )
            elif FastHeartbeatStatusUtil.requires_full_heartbeat(fast_heartbeat_status):
                # TOPOLOGY_CHANGED, AGENT_UNKNOWN - execute full pipeline
                should_execute_remaining = True
                reason = "changes detected or re-registration needed"
                self.logger.info(f"🔄 Executing remaining steps: {reason}")
            else:
                # Unknown status - fallback to full execution
                self.logger.warning(
                    f"⚠️ Unknown fast heartbeat status '{fast_heartbeat_status}' - falling back to full execution"
                )
                should_execute_remaining = True
                reason = "fallback (unknown status)"

            # Execute or skip conditional steps based on decision
            if should_execute_remaining:
                for step in conditional_steps:
                    self.logger.debug(f"Executing conditional step: {step.name}")

                    step_result = await step.execute(self.context)
                    executed_steps.append(step.name)

                    # Merge step context into pipeline context
                    self.context.update(step_result.context)

                    # Handle step failure
                    if not step_result.is_success():
                        if step.required:
                            overall_result.status = PipelineStatus.FAILED
                            overall_result.message = f"Required step '{step.name}' failed: {step_result.message}"
                            overall_result.add_error(
                                f"Step '{step.name}': {step_result.message}"
                            )
                            break
                        else:
                            # Optional step failed - mark as partial success
                            if overall_result.status == PipelineStatus.SUCCESS:
                                overall_result.status = PipelineStatus.PARTIAL
                            overall_result.add_error(
                                f"Optional step '{step.name}': {step_result.message}"
                            )
                            self.logger.warning(
                                f"⚠️ Optional step '{step.name}' failed: {step_result.message}"
                            )
            else:
                # Mark skipped steps
                for step in conditional_steps:
                    skipped_steps.append(step.name)

            # Set final result message
            if executed_steps and skipped_steps:
                overall_result.message = (
                    f"Pipeline completed with conditional execution - "
                    f"executed: {executed_steps}, skipped: {skipped_steps} ({reason})"
                )
            elif executed_steps:
                overall_result.message = (
                    f"Pipeline completed - executed: {executed_steps} ({reason})"
                )
            else:
                overall_result.message = (
                    f"Pipeline completed - all steps skipped ({reason})"
                )

            # Add final context
            for key, value in self.context.items():
                overall_result.add_context(key, value)

            return overall_result

        except Exception as e:
            # Handle unexpected exceptions
            overall_result.status = PipelineStatus.FAILED
            overall_result.message = f"Pipeline execution failed with exception: {e}"
            overall_result.add_error(str(e))
            for key, value in self.context.items():
                overall_result.add_context(key, value)

            self.logger.error(f"❌ Conditional pipeline execution failed: {e}")
            return overall_result
