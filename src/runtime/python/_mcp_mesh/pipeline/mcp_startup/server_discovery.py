"""
Server discovery step for MCP pipeline.

This step discovers existing uvicorn servers that may have been started immediately
in @mesh.agent decorators to prevent Python interpreter shutdown.
"""

import logging
from typing import Any, Dict, Optional

from ...shared.server_discovery import ServerDiscoveryUtil
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class ServerDiscoveryStep(PipelineStep):
    """
    Discovers existing uvicorn servers that may be running.

    This step checks if there's already a uvicorn server running on the target port,
    which could happen when @mesh.agent(auto_run=True) starts an immediate uvicorn
    server to prevent Python interpreter shutdown.
    """

    def __init__(self):
        super().__init__(
            name="server-discovery",
            required=False,  # Not required - pipeline can still start new server if none found
            description="Discover existing uvicorn servers",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Discover existing uvicorn servers."""
        self.logger.debug("🔍 DISCOVERY: Checking for existing uvicorn servers...")

        result = PipelineResult(message="Server discovery completed")

        try:
            # Get agent configuration from context
            agent_config = context.get("agent_config", {})
            target_port = agent_config.get("http_port", 8080)
            target_host = agent_config.get("http_host", "0.0.0.0")

            self.logger.debug(
                "🔍 DISCOVERY: Looking for immediate uvicorn server from DecoratorRegistry"
            )

            # Check DecoratorRegistry for immediate uvicorn server (much more reliable)
            from ...engine.decorator_registry import DecoratorRegistry

            existing_server = DecoratorRegistry.get_immediate_uvicorn_server()

            # Debug: Show what we found
            if existing_server:
                server_status = existing_server.get("status", "unknown")
                server_type = existing_server.get("type", "unknown")
                self.logger.debug(
                    f"🔍 DISCOVERY: Found server - status='{server_status}', type='{server_type}'"
                )
            else:
                self.logger.debug(
                    "🔍 DISCOVERY: No immediate uvicorn server found in registry"
                )

            if existing_server:
                # Found existing immediate uvicorn server
                server_host = existing_server.get("host", "unknown")
                server_port = existing_server.get("port", 0)

                result.add_context("existing_server", existing_server)
                result.add_context("server_reuse", True)

                # Get the FastAPI app directly from server info
                existing_app = existing_server.get("app")
                if existing_app:
                    app_info = {
                        "instance": existing_app,
                        "title": getattr(
                            existing_app, "title", "MCP Mesh Agent (Starting)"
                        ),
                        "version": getattr(existing_app, "version", "unknown"),
                        "object_id": id(existing_app),
                        "type": "immediate_uvicorn",
                    }
                    result.add_context("existing_fastapi_app", app_info)
                    result.message = (
                        f"Found immediate uvicorn server on {server_host}:{server_port} "
                        f"with FastAPI app '{app_info.get('title', 'Unknown')}'"
                    )
                    self.logger.debug(
                        f"✅ DISCOVERY: Found immediate uvicorn server on {server_host}:{server_port} "
                        f"with FastAPI app '{app_info.get('title', 'Unknown')}'"
                    )
                else:
                    result.message = f"Found immediate uvicorn server on {server_host}:{server_port} (no FastAPI app reference)"
                    self.logger.warning(
                        "⚠️ DISCOVERY: Found immediate uvicorn server but no FastAPI app reference"
                    )

            else:
                # No existing server found
                result.add_context("existing_server", None)
                result.add_context("server_reuse", False)
                result.message = (
                    "No immediate uvicorn server found in DecoratorRegistry"
                )
                self.logger.info(
                    "🔍 DISCOVERY: No immediate uvicorn server found - pipeline will start new server"
                )

            # Only discover FastAPI apps if no immediate uvicorn server was found
            if not existing_server:
                self.logger.debug(
                    "🔍 DISCOVERY: No immediate uvicorn server found, discovering FastAPI apps via garbage collection"
                )
                fastapi_apps = ServerDiscoveryUtil.discover_fastapi_instances()
                result.add_context("discovered_fastapi_apps", fastapi_apps)

                if fastapi_apps:
                    app_count = len(fastapi_apps)
                    result.message += f" | Discovered {app_count} FastAPI app(s)"
                    self.logger.info(
                        f"📦 DISCOVERY: Discovered {app_count} FastAPI application(s) for potential mounting"
                    )

                    # Log details about discovered apps
                    for app_id, app_info in fastapi_apps.items():
                        app_title = app_info.get("title", "Unknown")
                        route_count = len(app_info.get("routes", []))
                        self.logger.debug(
                            f"  📦 App '{app_title}' ({app_id}): {route_count} routes"
                        )
            else:
                self.logger.debug(
                    "🔍 DISCOVERY: Using FastAPI app from immediate uvicorn server, skipping garbage collection discovery"
                )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Server discovery failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ DISCOVERY: Server discovery failed: {e}")

        return result

    def _find_associated_fastapi_app(
        self, server_info: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """
        Try to find the FastAPI app associated with the existing server.

        Args:
            server_info: Server information from discovery

        Returns:
            FastAPI app info if found, None otherwise
        """
        try:
            # Check if server info already has an app
            if "app" in server_info:
                app = server_info["app"]
                return {
                    "instance": app,
                    "title": getattr(app, "title", "Unknown"),
                    "version": getattr(app, "version", "unknown"),
                    "routes": ServerDiscoveryUtil._extract_route_info(app),
                    "object_id": id(app),
                }

            # If not, discover all FastAPI apps and try to match
            fastapi_apps = ServerDiscoveryUtil.discover_fastapi_instances()

            # For immediate uvicorn servers, look for apps with specific titles
            for app_id, app_info in fastapi_apps.items():
                app_title = app_info.get("title", "")
                if "MCP Mesh Agent" in app_title and "Starting" in app_title:
                    # This looks like our immediate uvicorn app
                    self.logger.debug(
                        f"🔍 DISCOVERY: Found immediate uvicorn FastAPI app: {app_title}"
                    )
                    return app_info

            # If no immediate uvicorn app found, return the first available app
            if fastapi_apps:
                first_app = next(iter(fastapi_apps.values()))
                self.logger.debug(
                    f"🔍 DISCOVERY: Using first available FastAPI app: {first_app.get('title', 'Unknown')}"
                )
                return first_app

        except Exception as e:
            self.logger.warning(f"Error finding associated FastAPI app: {e}")

        return None
