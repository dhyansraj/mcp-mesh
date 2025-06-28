import logging
from typing import Any

from ...engine.decorator_registry import DecoratorRegistry
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class DecoratorCollectionStep(PipelineStep):
    """
    Collects all registered decorators from DecoratorRegistry.

    This step reads the current state of decorator registrations and
    makes them available for subsequent processing steps.
    """

    def __init__(self):
        super().__init__(
            name="decorator-collection",
            required=True,
            description="Collect all registered @mesh.agent and @mesh.tool decorators",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Collect decorators from registry."""
        self.logger.debug("Collecting decorators from DecoratorRegistry...")

        result = PipelineResult(message="Decorator collection completed")

        try:
            # Get all registered decorators
            mesh_agents = DecoratorRegistry.get_mesh_agents()
            mesh_tools = DecoratorRegistry.get_mesh_tools()

            # Store in context for subsequent steps
            result.add_context("mesh_agents", mesh_agents)
            result.add_context("mesh_tools", mesh_tools)
            result.add_context("agent_count", len(mesh_agents))
            result.add_context("tool_count", len(mesh_tools))

            # Update result message
            result.message = (
                f"Collected {len(mesh_agents)} agents and {len(mesh_tools)} tools"
            )

            self.logger.info(
                f"📦 Collected decorators: {len(mesh_agents)} @mesh.agent, {len(mesh_tools)} @mesh.tool"
            )

            # Validate we have something to process
            if len(mesh_agents) == 0 and len(mesh_tools) == 0:
                result.status = PipelineStatus.SKIPPED
                result.message = "No decorators found to process"
                self.logger.warning("⚠️ No decorators found in registry")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to collect decorators: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Decorator collection failed: {e}")

        return result
