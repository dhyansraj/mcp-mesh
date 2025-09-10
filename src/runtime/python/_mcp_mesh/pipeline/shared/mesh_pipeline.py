"""
Core pipeline infrastructure for MCP Mesh processing.

Provides explicit, sequential execution of processing steps with clear
error handling and detailed logging.
"""

import logging
from typing import Any, Optional

from .base_step import PipelineStep
from .pipeline_types import PipelineResult, PipelineStatus

logger = logging.getLogger(__name__)


class MeshPipeline:
    """
    Generic base class for MCP Mesh processing pipelines.

    Executes a sequence of pipeline steps with explicit control flow,
    detailed logging, and error handling. This is a pure orchestration
    class with no business logic - specific pipeline types should extend
    this class and add their domain-specific step configuration.
    """

    def __init__(self, name: str = "mesh-pipeline"):
        self.name = name
        self.steps: list[PipelineStep] = []
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self.context: dict[str, Any] = {}
        self._last_context: dict[str, Any] = (
            {}
        )  # Store final context for graceful shutdown

    def add_step(self, step: PipelineStep) -> None:
        """Add a step to the pipeline."""
        self.steps.append(step)
        self.logger.debug(f"Added step: {step.name}")

    def add_steps(self, steps: list[PipelineStep]) -> None:
        """Add multiple steps to the pipeline."""
        for step in steps:
            self.add_step(step)

    def clear_steps(self) -> None:
        """Remove all steps from the pipeline."""
        self.steps.clear()
        self.context.clear()
        self.logger.debug("Pipeline steps cleared")

    async def execute(self) -> PipelineResult:
        """
        Execute all pipeline steps in sequence.

        Returns:
            Aggregated result from all steps
        """
        self.logger.info(
            f"🚀 Starting pipeline '{self.name}' with {len(self.steps)} steps"
        )

        overall_result = PipelineResult(
            message=f"Pipeline '{self.name}' execution",
            context={"pipeline_name": self.name, "total_steps": len(self.steps)},
        )

        executed_steps = 0

        try:
            for i, step in enumerate(self.steps):
                step_num = i + 1
                self.logger.info(f"📋 Step {step_num}/{len(self.steps)}: {step.name}")

                try:

                    # Execute the step with current context
                    step_result = await step.execute(self.context)
                    executed_steps += 1


                    # Log step result
                    if step_result.is_success():
                        self.logger.info(
                            f"✅ Step {step_num} completed: {step_result.message}"
                        )
                    else:
                        self.logger.error(
                            f"❌ Step {step_num} failed: {step_result.message}"
                        )

                    # Merge step context into pipeline context
                    self.context.update(step_result.context)

                    # Merge step errors into overall result
                    overall_result.errors.extend(step_result.errors)

                    # Handle step failure
                    if not step_result.is_success():
                        if step.required:
                            overall_result.status = PipelineStatus.FAILED
                            overall_result.message = f"Required step '{step.name}' failed: {step_result.message}"
                            self.logger.error(
                                f"💥 Pipeline failed at required step {step_num}: {step.name}"
                            )
                            break
                        else:
                            overall_result.status = PipelineStatus.PARTIAL
                            self.logger.warning(
                                f"⚠️ Optional step {step_num} failed, continuing: {step.name}"
                            )

                except Exception as e:
                    executed_steps += 1


                    error_msg = f"Step '{step.name}' threw exception: {e}"
                    overall_result.add_error(error_msg)
                    self.logger.error(
                        f"💥 Step {step_num} exception: {e}", exc_info=True
                    )

                    if step.required:
                        overall_result.status = PipelineStatus.FAILED
                        overall_result.message = (
                            f"Required step '{step.name}' threw exception"
                        )
                        break
                    else:
                        overall_result.status = PipelineStatus.PARTIAL

        except Exception as e:
            # Pipeline-level exception
            overall_result.status = PipelineStatus.FAILED
            overall_result.message = f"Pipeline execution failed: {e}"
            overall_result.add_error(str(e))
            self.logger.error(
                f"💥 Pipeline '{self.name}' failed with exception: {e}", exc_info=True
            )

        # Finalize result
        overall_result.add_context("executed_steps", executed_steps)
        overall_result.add_context("pipeline_context", self.context.copy())

        # Log final status
        if overall_result.is_success():
            self.logger.info(
                f"🎉 Pipeline '{self.name}' completed successfully ({executed_steps}/{len(self.steps)} steps)"
            )
        else:
            self.logger.error(
                f"💔 Pipeline '{self.name}' failed (status: {overall_result.status.value}, {executed_steps}/{len(self.steps)} steps)"
            )

        # Store final context for graceful shutdown access
        self._last_context = self.context.copy()

        return overall_result

    def get_step(self, name: str) -> Optional[PipelineStep]:
        """Get a step by name."""
        for step in self.steps:
            if step.name == name:
                return step
        return None

    def remove_step(self, name: str) -> bool:
        """Remove a step by name."""
        for i, step in enumerate(self.steps):
            if step.name == name:
                del self.steps[i]
                self.logger.debug(f"Removed step: {name}")
                return True
        return False

    def list_steps(self) -> list[str]:
        """Get list of step names."""
        return [step.name for step in self.steps]
