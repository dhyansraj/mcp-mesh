"""
Registry connection step for MCP Mesh pipeline.

Handles establishing connection to the mesh registry service.
"""

import logging
import os
from typing import Any

from ...generated.mcp_mesh_registry_client.api_client import ApiClient
from ...generated.mcp_mesh_registry_client.configuration import Configuration
from ...shared.registry_client_wrapper import RegistryClientWrapper
from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


class RegistryConnectionStep(PipelineStep):
    """
    Establishes connection to the mesh registry.

    Creates and configures the registry client for subsequent
    communication steps.
    """

    def __init__(self):
        super().__init__(
            name="registry-connection",
            required=True,
            description="Connect to mesh registry service",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Establish registry connection or reuse existing one."""
        self.logger.debug("Checking registry connection...")

        result = PipelineResult(message="Registry connection ready")

        try:
            # Check if registry wrapper already exists in context (for heartbeat pipeline)
            existing_wrapper = context.get("registry_wrapper")

            if existing_wrapper:
                # Reuse existing connection for efficiency
                result.add_context("registry_wrapper", existing_wrapper)
                result.message = "Reusing existing registry connection"
                self.logger.debug("🔄 Reusing existing registry connection")
                return result

            # Create new connection if none exists
            registry_url = self._get_registry_url()

            # Create registry client configuration
            config = Configuration(host=registry_url)
            registry_client = ApiClient(config)

            # Create wrapper for type-safe operations
            registry_wrapper = RegistryClientWrapper(registry_client)

            # Store in context
            result.add_context("registry_url", registry_url)
            result.add_context("registry_client", registry_client)
            result.add_context("registry_wrapper", registry_wrapper)

            result.message = f"Connected to registry at {registry_url}"
            self.logger.info(f"🔗 Registry connection established: {registry_url}")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Registry connection failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Registry connection failed: {e}")

        return result

    def _get_registry_url(self) -> str:
        """Get registry URL from environment."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8000")
