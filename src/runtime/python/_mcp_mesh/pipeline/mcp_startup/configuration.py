import logging
import os
from typing import Any

from ...engine.decorator_registry import DecoratorRegistry
from ...shared.config_resolver import ValidationRule, get_config_value
from ..shared import PipelineResult, PipelineStatus, PipelineStep


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

            # Resolve registry URL (not part of agent parameters)
            registry_url = get_config_value(
                "MCP_MESH_REGISTRY_URL",
                override=None,  # No decorator override for registry URL
                default="http://localhost:8000",
                rule=ValidationRule.URL_RULE,
            )

            # Store in pipeline context
            result.add_context("agent_config", config)
            result.add_context("agent_id", config["agent_id"])
            result.add_context("has_explicit_agent", has_explicit_agent)
            result.add_context("registry_url", registry_url)

            # Log tracing configuration status
            tracing_enabled = os.getenv(
                "MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "false"
            ).lower() in ("true", "1", "yes", "on")
            self.logger.info(
                f"Distributed tracing: {'enabled' if tracing_enabled else 'disabled'}"
            )

            result.message = f"Configuration resolved for agent '{config['agent_id']}'"
            self.logger.info(
                f"⚙️ Configuration resolved: agent_id='{config['agent_id']}', registry_url='{registry_url}', explicit_agent={has_explicit_agent}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Configuration resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Configuration resolution failed: {e}")

        return result
