"""
API registry connection step for API heartbeat pipeline.

Prepares registry communication for FastAPI service heartbeat operations.
Simpler than MCP registry connection since API services don't require
complex dependency resolution.
"""

import logging
from typing import Any

from ..shared.base_step import PipelineStep
from ..shared.pipeline_types import PipelineResult

logger = logging.getLogger(__name__)


class APIRegistryConnectionStep(PipelineStep):
    """
    Prepare registry connection for API service heartbeat.
    
    Ensures registry client is available and properly configured for
    FastAPI service registration and health monitoring.
    """

    def __init__(self, required: bool = True):
        super().__init__(
            name="api-registry-connection",
            required=required,
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Prepare registry connection for API heartbeat operations.

        Args:
            context: Pipeline context containing agent_config and registration_data

        Returns:
            PipelineResult with registry_wrapper in context
        """
        self.logger.info("🔗 [DEBUG] Preparing API registry connection for heartbeat")

        try:
            # Check if registry_wrapper already exists in context
            registry_wrapper = context.get("registry_wrapper")
            
            if registry_wrapper is not None:
                self.logger.debug("✅ Registry wrapper already available in context")
                return PipelineResult(
                    message="Registry connection already established",
                    context={"registry_wrapper": registry_wrapper}
                )

            # Get registry configuration from context and environment
            agent_config = context.get("agent_config", {})
            registration_data = context.get("registration_data", {})
            
            # Use proper config resolver to respect environment variables first
            from ...shared.config_resolver import ValidationRule, get_config_value
            
            registry_url = get_config_value(
                "MCP_MESH_REGISTRY_URL",
                override=(
                    agent_config.get("registry_url") 
                    or registration_data.get("registry_url")
                ),
                default="http://localhost:8000",
                rule=ValidationRule.URL_RULE,
            )

            self.logger.debug(f"🔍 Using registry URL: {registry_url}")

            # Create registry client wrapper
            from ...generated.mcp_mesh_registry_client.api_client import ApiClient
            from ...generated.mcp_mesh_registry_client.configuration import Configuration
            from ...shared.registry_client_wrapper import RegistryClientWrapper

            config = Configuration(host=registry_url)
            api_client = ApiClient(configuration=config)
            registry_wrapper = RegistryClientWrapper(api_client)

            self.logger.info(f"🔗 API registry connection prepared: {registry_url}")

            return PipelineResult(
                message=f"Registry connection prepared for {registry_url}",
                context={
                    "registry_wrapper": registry_wrapper,
                    "registry_url": registry_url,
                }
            )

        except Exception as e:
            error_msg = f"Failed to prepare API registry connection: {e}"
            self.logger.error(f"❌ {error_msg}")

            from ..shared.pipeline_types import PipelineStatus
            result = PipelineResult(
                status=PipelineStatus.FAILED,
                message=error_msg,
                context=context
            )
            result.add_error(str(e))
            return result