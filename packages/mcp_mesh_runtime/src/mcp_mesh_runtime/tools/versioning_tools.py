"""MCP-compliant versioning tools for agent version management."""

from typing import Any

from fastmcp import FastMCP

from ..shared.versioning import AgentVersionManager


class VersioningTools:
    """MCP-compliant tools for agent versioning operations."""

    def __init__(self, app: FastMCP, db_path: str = ":memory:"):
        self.app = app
        self.version_manager = AgentVersionManager(db_path)
        self._initialized = False
        self._register_tools()

    async def _ensure_initialized(self):
        """Ensure the version manager is initialized."""
        if not self._initialized:
            await self.version_manager.initialize()
            self._initialized = True

    def _register_tools(self):
        """Register all versioning tools with the MCP app."""

        @self.app.tool()
        async def get_agent_versions(agent_id: str) -> list[dict[str, Any]]:
            """
            Get all versions for a specific agent.

            Args:
                agent_id: The unique identifier of the agent

            Returns:
                List of version information for the agent
            """
            await self._ensure_initialized()

            versions = await self.version_manager.get_agent_versions(agent_id)

            # Convert to serializable format
            result = []
            for version in versions:
                result.append(
                    {
                        "agent_id": version.agent_id,
                        "version": str(version.version),
                        "created_at": version.created_at.isoformat(),
                        "created_by": version.created_by,
                        "description": version.description,
                        "changelog": version.changelog,
                        "metadata": version.metadata or {},
                    }
                )

            return result

        @self.app.tool()
        async def get_agent_version(
            agent_id: str, version: str
        ) -> dict[str, Any] | None:
            """
            Get specific version information for an agent.

            Args:
                agent_id: The unique identifier of the agent
                version: The semantic version string (e.g., "1.2.3")

            Returns:
                Version information if found, None otherwise
            """
            await self._ensure_initialized()

            version_info = await self.version_manager.get_agent_version(
                agent_id, version
            )

            if not version_info:
                return None

            return {
                "agent_id": version_info.agent_id,
                "version": str(version_info.version),
                "created_at": version_info.created_at.isoformat(),
                "created_by": version_info.created_by,
                "description": version_info.description,
                "changelog": version_info.changelog,
                "metadata": version_info.metadata or {},
            }

        @self.app.tool()
        async def create_agent_version(
            agent_id: str,
            version: str,
            description: str | None = None,
            changelog: str | None = None,
            metadata: dict[str, str] | None = None,
            created_by: str = "system",
        ) -> dict[str, Any]:
            """
            Create a new version for an agent.

            Args:
                agent_id: The unique identifier of the agent
                version: The semantic version string (e.g., "1.2.3")
                description: Optional description of the version
                changelog: Optional changelog for the version
                metadata: Optional metadata dictionary
                created_by: Who created the version

            Returns:
                Created version information
            """
            await self._ensure_initialized()

            version_info = await self.version_manager.create_agent_version(
                agent_id=agent_id,
                version=version,
                description=description,
                changelog=changelog,
                metadata=metadata,
                created_by=created_by,
            )

            return {
                "agent_id": version_info.agent_id,
                "version": str(version_info.version),
                "created_at": version_info.created_at.isoformat(),
                "created_by": version_info.created_by,
                "description": version_info.description,
                "changelog": version_info.changelog,
                "metadata": version_info.metadata or {},
            }

        @self.app.tool()
        async def deploy_agent_version(
            agent_id: str,
            version: str,
            environment: str = "production",
            deployed_by: str = "system",
        ) -> dict[str, Any]:
            """
            Deploy a specific agent version to an environment.

            Args:
                agent_id: The unique identifier of the agent
                version: The semantic version string to deploy
                environment: Target environment (default: "production")
                deployed_by: Who initiated the deployment

            Returns:
                Deployment result with success status and details
            """
            await self._ensure_initialized()

            result = await self.version_manager.deploy_agent_version(
                agent_id=agent_id,
                version=version,
                environment=environment,
                deployed_by=deployed_by,
            )

            deployment_dict = None
            if result.deployment_info:
                deployment_dict = {
                    "deployment_id": result.deployment_info.deployment_id,
                    "agent_id": result.deployment_info.agent_id,
                    "version": str(result.deployment_info.version),
                    "status": result.deployment_info.status.value,
                    "deployed_at": result.deployment_info.deployed_at.isoformat(),
                    "deployed_by": result.deployment_info.deployed_by,
                    "environment": result.deployment_info.environment,
                    "error_message": result.deployment_info.error_message,
                    "metadata": result.deployment_info.metadata or {},
                }

            return {
                "success": result.success,
                "deployment_id": result.deployment_id,
                "error_message": result.error_message,
                "deployment_info": deployment_dict,
            }

        @self.app.tool()
        async def get_deployment_history(agent_id: str) -> list[dict[str, Any]]:
            """
            Get deployment history for an agent.

            Args:
                agent_id: The unique identifier of the agent

            Returns:
                List of deployment information ordered by deployment time (newest first)
            """
            await self._ensure_initialized()

            deployments = await self.version_manager.get_deployment_history(agent_id)

            result = []
            for deployment in deployments:
                rollback_version = None
                if deployment.rollback_version:
                    rollback_version = str(deployment.rollback_version)

                result.append(
                    {
                        "deployment_id": deployment.deployment_id,
                        "agent_id": deployment.agent_id,
                        "version": str(deployment.version),
                        "status": deployment.status.value,
                        "deployed_at": deployment.deployed_at.isoformat(),
                        "deployed_by": deployment.deployed_by,
                        "environment": deployment.environment,
                        "rollback_version": rollback_version,
                        "error_message": deployment.error_message,
                        "metadata": deployment.metadata or {},
                    }
                )

            return result

        @self.app.tool()
        async def get_active_deployment(
            agent_id: str, environment: str = "production"
        ) -> dict[str, Any] | None:
            """
            Get the currently active deployment for an agent in a specific environment.

            Args:
                agent_id: The unique identifier of the agent
                environment: The target environment (default: "production")

            Returns:
                Active deployment information if found, None otherwise
            """
            await self._ensure_initialized()

            deployment = await self.version_manager.get_active_deployment(
                agent_id, environment
            )

            if not deployment:
                return None

            return {
                "deployment_id": deployment.deployment_id,
                "agent_id": deployment.agent_id,
                "version": str(deployment.version),
                "status": deployment.status.value,
                "deployed_at": deployment.deployed_at.isoformat(),
                "deployed_by": deployment.deployed_by,
                "environment": deployment.environment,
                "error_message": deployment.error_message,
                "metadata": deployment.metadata or {},
            }

        @self.app.tool()
        async def rollback_deployment(
            agent_id: str,
            to_version: str,
            reason: str | None = None,
            environment: str = "production",
            initiated_by: str = "system",
        ) -> dict[str, Any]:
            """
            Rollback an agent deployment to a previous version.

            Args:
                agent_id: The unique identifier of the agent
                to_version: The semantic version string to rollback to
                reason: Optional reason for the rollback
                environment: Target environment (default: "production")
                initiated_by: Who initiated the rollback

            Returns:
                Rollback result with success status and details
            """
            await self._ensure_initialized()

            result = await self.version_manager.rollback_deployment(
                agent_id=agent_id,
                to_version=to_version,
                reason=reason,
                environment=environment,
                initiated_by=initiated_by,
            )

            deployment_dict = None
            if result.deployment_info:
                deployment_dict = {
                    "deployment_id": result.deployment_info.deployment_id,
                    "agent_id": result.deployment_info.agent_id,
                    "version": str(result.deployment_info.version),
                    "status": result.deployment_info.status.value,
                    "deployed_at": result.deployment_info.deployed_at.isoformat(),
                    "deployed_by": result.deployment_info.deployed_by,
                    "environment": result.deployment_info.environment,
                    "error_message": result.deployment_info.error_message,
                    "metadata": result.deployment_info.metadata or {},
                }

            return {
                "success": result.success,
                "deployment_id": result.deployment_id,
                "error_message": result.error_message,
                "deployment_info": deployment_dict,
            }

        @self.app.tool()
        async def compare_versions(version1: str, version2: str) -> dict[str, Any]:
            """
            Compare two semantic versions.

            Args:
                version1: First version to compare
                version2: Second version to compare

            Returns:
                Comparison result with numeric comparison and compatibility info
            """
            await self._ensure_initialized()

            try:
                comparison = self.version_manager.compare_versions(version1, version2)
                is_compatible = self.version_manager.is_compatible(version1, version2)

                return {
                    "version1": version1,
                    "version2": version2,
                    "comparison": comparison,  # -1, 0, 1
                    "is_compatible": is_compatible,
                    "version1_parsed": str(
                        self.version_manager.parse_version(version1)
                    ),
                    "version2_parsed": str(
                        self.version_manager.parse_version(version2)
                    ),
                }
            except ValueError as e:
                return {"error": str(e), "version1": version1, "version2": version2}

        @self.app.tool()
        async def get_latest_version(agent_id: str) -> dict[str, Any] | None:
            """
            Get the latest version for an agent.

            Args:
                agent_id: The unique identifier of the agent

            Returns:
                Latest version information if found, None otherwise
            """
            await self._ensure_initialized()

            versions = await self.version_manager.get_agent_versions(agent_id)

            if not versions:
                return None

            # Versions are already sorted by version desc in get_agent_versions
            latest = versions[0]

            return {
                "agent_id": latest.agent_id,
                "version": str(latest.version),
                "created_at": latest.created_at.isoformat(),
                "created_by": latest.created_by,
                "description": latest.description,
                "changelog": latest.changelog,
                "metadata": latest.metadata or {},
            }


def create_versioning_tools(app: FastMCP, db_path: str = ":memory:") -> VersioningTools:
    """
    Create and register versioning tools with a FastMCP app.

    Args:
        app: The FastMCP application instance
        db_path: Path to the SQLite database (default: in-memory)

    Returns:
        VersioningTools instance
    """
    return VersioningTools(app, db_path)
