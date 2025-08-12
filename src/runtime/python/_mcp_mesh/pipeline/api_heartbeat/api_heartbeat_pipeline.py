"""
API heartbeat pipeline for FastAPI service health monitoring.

Provides structured execution of API service heartbeat operations with proper 
error handling and logging. Runs periodically to maintain registry communication 
and service health status for FastAPI applications using @mesh.route decorators.
"""

import logging
from typing import Any

from ...shared.fast_heartbeat_status import FastHeartbeatStatus, FastHeartbeatStatusUtil
from ..shared.mesh_pipeline import MeshPipeline
from ..shared.pipeline_types import PipelineStatus
from .api_registry_connection import APIRegistryConnectionStep
from .api_health_check import APIHealthCheckStep  
from .api_fast_heartbeat_check import APIFastHeartbeatStep
from .api_heartbeat_send import APIHeartbeatSendStep
from .api_dependency_resolution import APIDependencyResolutionStep

logger = logging.getLogger(__name__)


class APIHeartbeatPipeline(MeshPipeline):
    """
    Specialized pipeline for API service heartbeat operations with fast optimization.

    Executes the core API heartbeat steps in sequence:
    1. Registry connection preparation
    2. API health check (validate FastAPI app status)
    3. Fast heartbeat check (HEAD request)
    4. Heartbeat sending (conditional POST request)
    5. Dependency resolution (conditional)

    Steps 4 and 5 only run if fast heartbeat indicates changes are needed.
    Provides optimization for NO_CHANGES and resilience for error conditions.

    API services now support:
    - Service availability and health status monitoring
    - Efficient HEAD->conditional POST pattern (like MCP agents)
    - Dynamic dependency resolution and injection
    - Route handler dependency updates from registry responses
    """

    def __init__(self, name: str = "api-heartbeat-pipeline"):
        super().__init__(name=name)
        self._setup_api_heartbeat_steps()

    def _setup_api_heartbeat_steps(self) -> None:
        """Setup the API heartbeat pipeline steps with fast optimization."""
        # API heartbeat steps with fast optimization pattern
        steps = [
            APIRegistryConnectionStep(),    # Prepare registry communication
            APIHealthCheckStep(),           # Check FastAPI app health status
            APIFastHeartbeatStep(),         # Fast heartbeat check (HEAD request)
            APIHeartbeatSendStep(),         # Conditional heartbeat send (POST request)
            APIDependencyResolutionStep(),  # Conditional dependency resolution
        ]

        self.add_steps(steps)
        self.logger.debug(f"API heartbeat pipeline configured with {len(steps)} steps")
        
        # Log the pipeline strategy
        self.logger.info(
            f"🌐 API Heartbeat Pipeline initialized: fast optimization for FastAPI apps"
        )
        self.logger.debug(
            f"📋 Pipeline steps: {[step.name for step in steps]}"
        )

    async def execute_api_heartbeat_cycle(
        self, heartbeat_context: dict[str, Any]
    ) -> Any:
        """
        Execute a complete API heartbeat cycle with fast optimization and enhanced error handling.

        Args:
            heartbeat_context: Context containing registry_wrapper, service_id, 
                              health_status, fastapi_app, etc.

        Returns:
            PipelineResult with execution status and any context updates
        """
        self.logger.debug("Starting API heartbeat pipeline execution")

        # Initialize pipeline context with heartbeat-specific data
        self.context.clear()
        self.context.update(heartbeat_context)

        try:
            # Execute the pipeline with conditional logic for fast optimization
            result = await self._execute_with_conditional_logic()

            if result.is_success():
                self.logger.debug("✅ API heartbeat pipeline completed successfully")
            elif result.status == PipelineStatus.PARTIAL:
                self.logger.warning(
                    f"⚠️ API heartbeat pipeline completed partially: {result.message}"
                )
                # Log which steps failed
                if result.errors:
                    for error in result.errors:
                        self.logger.warning(f"  - Step error: {error}")
            else:
                self.logger.error(f"❌ API heartbeat pipeline failed: {result.message}")
                # Log detailed error information
                if result.errors:
                    for error in result.errors:
                        self.logger.error(f"  - Pipeline error: {error}")

            return result

        except Exception as e:
            # Log detailed error information for debugging
            import traceback
            
            self.logger.error(
                f"❌ API heartbeat pipeline failed with exception: {e}\n"
                f"Context keys: {list(self.context.keys())}\n"
                f"Traceback: {traceback.format_exc()}"
            )

            # Create failure result with detailed context
            from ..shared.pipeline_types import PipelineResult
            
            failure_result = PipelineResult(
                status=PipelineStatus.FAILED,
                message=f"API heartbeat pipeline exception: {str(e)[:200]}...",
                context=self.context,
            )
            failure_result.add_error(str(e))

            return failure_result

    async def _execute_with_conditional_logic(self) -> "PipelineResult":
        """
        Execute API pipeline with conditional logic based on fast heartbeat status.

        Always executes:
        - APIRegistryConnectionStep
        - APIHealthCheckStep  
        - APIFastHeartbeatStep

        Conditionally executes based on fast heartbeat status:
        - NO_CHANGES: Skip remaining steps (optimization)
        - TOPOLOGY_CHANGED, AGENT_UNKNOWN: Execute all remaining steps
        - REGISTRY_ERROR, NETWORK_ERROR: Skip remaining steps (resilience)

        Returns:
            PipelineResult with execution status and context
        """
        from ..shared.pipeline_types import PipelineResult
        
        overall_result = PipelineResult(
            message="API heartbeat pipeline execution completed"
        )

        # Track which steps were executed for logging
        executed_steps = []
        skipped_steps = []

        try:
            # Always execute registry connection, health check, and fast heartbeat steps
            mandatory_steps = self.steps[
                :3
            ]  # APIRegistryConnectionStep, APIHealthCheckStep, APIFastHeartbeatStep
            conditional_steps = self.steps[
                3:
            ]  # APIHeartbeatSendStep, APIDependencyResolutionStep

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
                    "⚠️ API fast heartbeat status not found - falling back to full execution"
                )
                should_execute_remaining = True
                reason = "fallback (missing status)"
            elif FastHeartbeatStatusUtil.should_skip_for_optimization(
                fast_heartbeat_status
            ):
                # NO_CHANGES - skip for optimization
                should_execute_remaining = False
                reason = "optimization (no changes detected)"
                self.logger.info(
                    f"🚀 API heartbeat: Skipping remaining steps for optimization: {reason}"
                )
            elif FastHeartbeatStatusUtil.should_skip_for_resilience(
                fast_heartbeat_status
            ):
                # REGISTRY_ERROR, NETWORK_ERROR - skip for resilience
                should_execute_remaining = False
                reason = "resilience (preserve existing state)"
                self.logger.warning(
                    f"⚠️ API heartbeat: Skipping remaining steps for resilience: {reason}"
                )
            elif FastHeartbeatStatusUtil.requires_full_heartbeat(fast_heartbeat_status):
                # TOPOLOGY_CHANGED, AGENT_UNKNOWN - execute full pipeline
                should_execute_remaining = True
                reason = "changes detected or re-registration needed"
                self.logger.info(f"🔄 API heartbeat: Executing remaining steps: {reason}")
            else:
                # Unknown status - fallback to full execution
                self.logger.warning(
                    f"⚠️ Unknown API fast heartbeat status '{fast_heartbeat_status}' - falling back to full execution"
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
                
                # For skipped heartbeat due to NO_CHANGES, set success context
                if fast_heartbeat_status == FastHeartbeatStatus.NO_CHANGES:
                    overall_result.add_context("heartbeat_success", True)
                    overall_result.add_context("heartbeat_skipped", True)
                    overall_result.add_context("skip_reason", "no_changes_optimization")

            # Set final result message
            if executed_steps and skipped_steps:
                overall_result.message = (
                    f"API pipeline completed with conditional execution - "
                    f"executed: {executed_steps}, skipped: {skipped_steps} ({reason})"
                )
            elif executed_steps:
                overall_result.message = (
                    f"API pipeline completed - executed: {executed_steps} ({reason})"
                )
            else:
                overall_result.message = (
                    f"API pipeline completed - all steps skipped ({reason})"
                )

            # Add final context
            for key, value in self.context.items():
                overall_result.add_context(key, value)

            return overall_result

        except Exception as e:
            # Handle unexpected exceptions
            overall_result.status = PipelineStatus.FAILED
            overall_result.message = f"API pipeline execution failed with exception: {e}"
            overall_result.add_error(str(e))
            for key, value in self.context.items():
                overall_result.add_context(key, value)

            self.logger.error(f"❌ API conditional pipeline execution failed: {e}")
            return overall_result