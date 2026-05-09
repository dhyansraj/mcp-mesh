"""
A2A surface collection step.

Reads ``@mesh.a2a`` markers from the DecoratorRegistry and emits the
shared surfaces array (registry shape) onto the pipeline context. This
mirrors ``api_startup/route_collection.py`` for the A2A flow.
"""

import logging
from typing import Any

from ...engine.a2a_surfaces import collect_a2a_surfaces
from ...engine.decorator_registry import DecoratorRegistry
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class A2ASurfaceCollectionStep(PipelineStep):
    """
    Collects all registered ``@mesh.a2a`` decorators from DecoratorRegistry.

    Stamps both the raw decorator dict (``mesh_a2a_decorators``) and the
    registry-shape surfaces array (``a2a_surfaces``) onto the context for
    downstream steps and the heartbeat AgentSpec builder.
    """

    def __init__(self):
        super().__init__(
            name="a2a-surface-collection",
            required=True,
            description="Collect all registered @mesh.a2a / mesh.a2a.mount surfaces",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Collect A2A surface decorators from registry."""
        self.logger.debug("Collecting A2A surfaces from DecoratorRegistry...")

        result = PipelineResult(message="A2A surface collection completed")

        try:
            mesh_a2a_decorators = DecoratorRegistry.get_all_by_type("mesh_a2a")
            a2a_surfaces = collect_a2a_surfaces()

            result.add_context("mesh_a2a_decorators", mesh_a2a_decorators)
            result.add_context("a2a_surfaces", a2a_surfaces)
            result.add_context("a2a_surface_count", len(a2a_surfaces))

            result.message = f"Collected {len(a2a_surfaces)} A2A surface(s)"

            self.logger.info(
                f"🌐 Collected decorators: {len(a2a_surfaces)} @mesh.a2a surface(s)"
            )

            if len(a2a_surfaces) == 0:
                result.status = PipelineStatus.SKIPPED
                result.message = "No A2A surfaces found to process"
                self.logger.warning("⚠️ No A2A surfaces found in registry")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Failed to collect A2A surfaces: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ A2A surface collection failed: {e}")

        return result
