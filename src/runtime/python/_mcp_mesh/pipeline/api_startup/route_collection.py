import logging
from typing import Any

from ...engine.decorator_registry import DecoratorRegistry
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class RouteCollectionStep(PipelineStep):
    """
    Collects all registered @mesh.route decorators from DecoratorRegistry.

    This step reads the current state of route decorator registrations and
    makes them available for subsequent processing steps.
    """

    def __init__(self):
        super().__init__(
            name="route-collection",
            required=True,
            description="Collect all registered @mesh.route decorators",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Collect route decorators from registry."""
        self.logger.debug("Collecting route decorators from DecoratorRegistry...")

        result = PipelineResult(message="Route collection completed")

        try:
            # Get all registered route decorators
            mesh_routes = DecoratorRegistry.get_all_by_type("mesh_route")

            # Store in context for subsequent steps
            result.add_context("mesh_routes", mesh_routes)
            result.add_context("route_count", len(mesh_routes))

            # Update result message
            result.message = f"Collected {len(mesh_routes)} routes"

            self.logger.info(
                f"📦 Collected decorators: {len(mesh_routes)} @mesh.route"
            )

            # Validate we have routes to process
            if len(mesh_routes) == 0:
                result.status = PipelineStatus.SKIPPED
                result.message = "No route decorators found to process"
                self.logger.warning("⚠️ No route decorators found in registry")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to collect route decorators: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Route collection failed: {e}")

        return result