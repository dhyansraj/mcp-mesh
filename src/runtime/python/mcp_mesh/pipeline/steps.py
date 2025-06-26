"""
Pipeline step implementations for MCP Mesh processing.

Provides concrete implementations of common processing steps like
decorator collection, configuration resolution, and heartbeat preparation.
"""

import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from ..decorator_registry import DecoratorRegistry
from ..shared.registry_client_wrapper import RegistryClientWrapper
from ..shared.support_types import HealthStatus, HealthStatusType
from .pipeline import PipelineResult, PipelineStatus

logger = logging.getLogger(__name__)


class PipelineStep(ABC):
    """
    Abstract base class for pipeline steps.

    Each step performs a specific operation and can access/modify
    the shared pipeline context.
    """

    def __init__(self, name: str, required: bool = True, description: str = ""):
        self.name = name
        self.required = required
        self.description = description
        self.logger = logging.getLogger(f"{__name__}.{name}")

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Execute this pipeline step.

        Args:
            context: Shared pipeline context that can be read/modified

        Returns:
            Result of step execution
        """
        pass

    def __str__(self) -> str:
        return f"PipelineStep(name='{self.name}', required={self.required})"


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
        """Resolve agent configuration."""
        self.logger.debug("Resolving agent configuration...")

        result = PipelineResult(message="Configuration resolution completed")

        try:
            mesh_agents = context.get("mesh_agents", {})
            mesh_tools = context.get("mesh_tools", {})

            # Check if we have explicit @mesh.agent configuration
            agent_config = None
            if mesh_agents:
                # Use first agent configuration found
                for agent_name, decorated_func in mesh_agents.items():
                    agent_config = decorated_func.metadata.copy()
                    self.logger.debug(
                        f"Using @mesh.agent configuration from {agent_name}"
                    )
                    break

            # Apply defaults for missing configuration
            final_config = self._apply_defaults(agent_config, mesh_tools)

            # Store resolved configuration
            result.add_context("agent_config", final_config)
            result.add_context("has_explicit_agent", agent_config is not None)

            # Generate agent ID
            agent_id = self._generate_agent_id(final_config.get("name"))
            result.add_context("agent_id", agent_id)

            result.message = f"Configuration resolved for agent '{agent_id}'"
            self.logger.info(
                f"⚙️ Configuration resolved: agent_id='{agent_id}', explicit_agent={agent_config is not None}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Configuration resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Configuration resolution failed: {e}")

        return result

    def _apply_defaults(
        self, agent_config: Optional[dict[str, Any]], mesh_tools: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply default configuration values."""
        # Start with defaults (matching @mesh.agent parameter defaults)
        defaults = {
            "name": None,  # Will be generated if None
            "version": "1.0.0",
            "description": None,
            "http_host": "0.0.0.0",
            "http_port": 0,  # Auto-assign
            "enable_http": True,
            "namespace": "default",
            "health_interval": 30,
            "auto_run": True,  # This is the key default!
            "auto_run_interval": 10,
        }

        # Apply environment variable overrides
        env_overrides = self._get_env_overrides()
        defaults.update(env_overrides)

        # Apply explicit agent config if available
        if agent_config:
            defaults.update(agent_config)

        return defaults

    def _get_env_overrides(self) -> dict[str, Any]:
        """Get configuration overrides from environment variables."""
        overrides = {}

        if "MCP_MESH_HTTP_HOST" in os.environ:
            overrides["http_host"] = os.environ["MCP_MESH_HTTP_HOST"]

        if "MCP_MESH_HTTP_PORT" in os.environ:
            try:
                overrides["http_port"] = int(os.environ["MCP_MESH_HTTP_PORT"])
            except ValueError:
                self.logger.warning("Invalid MCP_MESH_HTTP_PORT value, ignoring")

        if "MCP_MESH_ENABLE_HTTP" in os.environ:
            overrides["enable_http"] = os.environ["MCP_MESH_ENABLE_HTTP"].lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        if "MCP_MESH_NAMESPACE" in os.environ:
            overrides["namespace"] = os.environ["MCP_MESH_NAMESPACE"]

        if "MCP_MESH_AUTO_RUN" in os.environ:
            overrides["auto_run"] = os.environ["MCP_MESH_AUTO_RUN"].lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        return overrides

    def _generate_agent_id(self, agent_name: Optional[str]) -> str:
        """Generate agent ID using same logic as decorators."""
        import uuid

        # Precedence: env var > agent_name > default "agent"
        if "MCP_MESH_AGENT_NAME" in os.environ:
            prefix = os.environ["MCP_MESH_AGENT_NAME"]
        elif agent_name is not None:
            prefix = agent_name
        else:
            prefix = "agent"

        uuid_suffix = str(uuid.uuid4())[:8]
        return f"{prefix}-{uuid_suffix}"


class HeartbeatPreparationStep(PipelineStep):
    """
    Prepares heartbeat data for registry communication.

    Builds the complete agent registration payload including tools,
    dependencies, and metadata.
    """

    def __init__(self):
        super().__init__(
            name="heartbeat-preparation",
            required=True,
            description="Prepare heartbeat payload with tools and metadata",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Prepare heartbeat data."""
        self.logger.debug("Preparing heartbeat payload...")

        result = PipelineResult(message="Heartbeat preparation completed")

        try:
            mesh_tools = context.get("mesh_tools", {})
            agent_config = context.get("agent_config", {})
            agent_id = context.get("agent_id", "unknown-agent")

            # Build tools list for registration
            tools_list = self._build_tools_list(mesh_tools)

            # Build agent registration payload
            registration_data = self._build_registration_payload(
                agent_id, agent_config, tools_list
            )

            # Build health status for heartbeat
            health_status = self._build_health_status(
                agent_id, agent_config, tools_list
            )

            # Store in context
            result.add_context("registration_data", registration_data)
            result.add_context("health_status", health_status)
            result.add_context("tools_list", tools_list)
            result.add_context("tool_count", len(tools_list))

            result.message = f"Heartbeat prepared for agent '{agent_id}' with {len(tools_list)} tools"
            self.logger.info(
                f"💓 Heartbeat prepared: agent='{agent_id}', tools={len(tools_list)}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Heartbeat preparation failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Heartbeat preparation failed: {e}")

        return result

    def _build_tools_list(self, mesh_tools: dict[str, Any]) -> list[dict[str, Any]]:
        """Build tools list from mesh_tools."""
        tools_list = []

        for func_name, decorated_func in mesh_tools.items():
            metadata = decorated_func.metadata

            # Build tool registration data
            tool_data = {
                "function_name": func_name,
                "capability": metadata.get("capability"),
                "tags": metadata.get("tags", []),
                "version": metadata.get("version", "1.0.0"),
                "description": metadata.get("description"),
                "dependencies": self._process_dependencies(
                    metadata.get("dependencies", [])
                ),
            }

            tools_list.append(tool_data)

        return tools_list

    def _process_dependencies(self, dependencies: list[Any]) -> list[dict[str, Any]]:
        """Process and normalize dependencies."""
        processed = []

        for dep in dependencies:
            if isinstance(dep, str):
                processed.append(
                    {
                        "capability": dep,
                        "tags": [],
                        "version": "",
                        "namespace": "default",
                    }
                )
            elif isinstance(dep, dict):
                processed.append(
                    {
                        "capability": dep.get("capability", ""),
                        "tags": dep.get("tags", []),
                        "version": dep.get("version", ""),
                        "namespace": dep.get("namespace", "default"),
                    }
                )

        return processed

    def _build_registration_payload(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        tools_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build agent registration payload."""
        return {
            "agent_id": agent_id,
            "agent_type": "mcp_agent",
            "name": agent_id,
            "version": agent_config.get("version", "1.0.0"),
            "http_host": agent_config.get("http_host", "0.0.0.0"),
            "http_port": agent_config.get("http_port", 0),
            "timestamp": datetime.now(UTC),
            "namespace": agent_config.get("namespace", "default"),
            "tools": tools_list,
        }

    def _build_health_status(
        self,
        agent_id: str,
        agent_config: dict[str, Any],
        tools_list: list[dict[str, Any]],
    ) -> HealthStatus:
        """Build health status for heartbeat."""
        # Extract capabilities from tools list
        capabilities = []

        for tool in tools_list:
            capability = tool.get("capability")
            if capability:
                capabilities.append(capability)

        # Ensure we have at least one capability for validation
        if not capabilities:
            capabilities = ["default"]

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=capabilities,
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=agent_config,
        )
