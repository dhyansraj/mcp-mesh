import logging
from typing import Any

from ...decorator_registry import DecoratorRegistry
from ..pipeline import PipelineResult, PipelineStatus
from .base_step import PipelineStep


class ConfigurationStep(PipelineStep):
    """
    Resolves configuration for the agent.

    Applies defaults from @mesh.agent decorator or creates synthetic defaults
    when only @mesh.tool decorators are present.
    """

    def __init__(self):
        super().__init__(
            name="configuration",
            required=True,
            description="Resolve agent configuration with defaults",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Resolve agent configuration using DecoratorRegistry."""
        self.logger.debug("Resolving agent configuration...")

        result = PipelineResult(message="Configuration resolution completed")

        try:
            # Get resolved configuration directly from DecoratorRegistry
            config = DecoratorRegistry.get_resolved_agent_config()
            
            # Check if we have explicit @mesh.agent decorators
            mesh_agents = DecoratorRegistry.get_mesh_agents()
            has_explicit_agent = bool(mesh_agents)

            # Store in pipeline context for backward compatibility
            result.add_context("agent_config", config)
            result.add_context("agent_id", config["agent_id"])
            result.add_context("has_explicit_agent", has_explicit_agent)

            result.message = f"Configuration resolved for agent '{config['agent_id']}'"
            self.logger.info(
                f"⚙️ Configuration resolved: agent_id='{config['agent_id']}', explicit_agent={has_explicit_agent}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Configuration resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Configuration resolution failed: {e}")

        return result

