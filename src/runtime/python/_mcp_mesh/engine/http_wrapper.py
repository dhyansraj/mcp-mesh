"""HTTP wrapper for MCP servers to enable distributed communication.

This module provides HTTP transport capabilities for MCP servers,
allowing them to communicate across network boundaries in containerized
and distributed environments.
"""

import logging
from typing import Any

from fastmcp import FastMCP

from ..shared.logging_config import configure_logging

# Ensure logging is configured
configure_logging()

logger = logging.getLogger(__name__)


class HttpMcpWrapper:
    """Wraps FastMCP server for mounting into main FastAPI application."""

    def __init__(self, mcp_server: FastMCP):
        self.mcp_server = mcp_server

        # FastMCP app for mounting into main FastAPI app
        self._mcp_app = None
        self._lifespan = None

        # Get FastMCP's lifespan if available (for new FastMCP integration)
        if hasattr(mcp_server, "http_app") and callable(mcp_server.http_app):
            try:
                # Create FastMCP HTTP app with stateless transport
                logger.debug("🔍 Creating FastMCP HTTP app with stateless transport")
                self._mcp_app = mcp_server.http_app(
                    stateless_http=True, transport="streamable-http"
                )
                logger.debug(f"✅ Created FastMCP app: {type(self._mcp_app)}")
                if hasattr(self._mcp_app, "lifespan"):
                    self._lifespan = self._mcp_app.lifespan
                    logger.debug("✅ Got FastMCP lifespan for FastAPI app")
            except Exception as e:
                logger.warning(f"Could not create FastMCP stateless app: {e}")
                # Try without stateless_http parameter
                try:
                    logger.debug("🔄 Trying FastMCP HTTP app without stateless_http")
                    self._mcp_app = mcp_server.http_app()
                    if hasattr(self._mcp_app, "lifespan"):
                        self._lifespan = self._mcp_app.lifespan
                        logger.debug("✅ Got FastMCP lifespan (fallback)")
                except Exception as e2:
                    logger.warning(f"FastMCP HTTP app creation failed entirely: {e2}")

    async def setup(self):
        """Set up FastMCP app for integration (no separate wrapper app)."""

        # Debug the FastMCP server instance first
        logger.debug(f"🔍 DEBUG: FastMCP server type: {type(self.mcp_server)}")
        logger.debug(
            f"🔍 DEBUG: FastMCP server module: {type(self.mcp_server).__module__}"
        )

        # Using FastMCP library (fastmcp>=2.8.0)
        logger.info(
            "🆕 HTTP Wrapper: Server instance is from FastMCP library (fastmcp)"
        )

        logger.debug(
            f"🔍 DEBUG: FastMCP server dir: {[attr for attr in dir(self.mcp_server) if 'app' in attr.lower()]}"
        )
        logger.debug(f"🔍 DEBUG: Has http_app: {hasattr(self.mcp_server, 'http_app')}")

        if self._mcp_app is not None:
            logger.debug("🔍 DEBUG: FastMCP app prepared for integration")
            logger.debug(f"🔍 DEBUG: FastMCP app type: {type(self._mcp_app)}")

            # Debug: Check what routes the FastMCP app has
            if hasattr(self._mcp_app, "routes"):
                logger.debug(
                    f"🔍 DEBUG: FastMCP app routes: {[route.path for route in self._mcp_app.routes if hasattr(route, 'path')]}"
                )

            logger.debug("🌐 FastMCP app ready for integration with main FastAPI app")
        else:
            logger.warning(
                "❌ FastMCP server doesn't have any supported HTTP app method"
            )
            raise AttributeError("No supported HTTP app method")

    def _get_external_host(self) -> str:
        """Get external hostname for endpoint display."""
        from _mcp_mesh.shared.host_resolver import HostResolver

        return HostResolver.get_external_host()

    def _get_capabilities(self) -> list[str]:
        """Extract capabilities from registered tools."""
        capabilities = set()

        # Look for mesh metadata on tools
        if hasattr(self.mcp_server, "_tool_manager"):
            for _, tool in self.mcp_server._tool_manager._tools.items():
                # Check for mesh metadata
                if hasattr(tool.fn, "_mesh_agent_metadata"):
                    metadata = tool.fn._mesh_agent_metadata
                    if "capability" in metadata:
                        capabilities.add(metadata["capability"])

        return list(capabilities)

    def _get_dependencies(self) -> list[str]:
        """Extract dependencies from registered tools."""
        dependencies = set()

        # Look for mesh metadata on tools
        if hasattr(self.mcp_server, "_tool_manager"):
            for _, tool in self.mcp_server._tool_manager._tools.items():
                # Check for mesh dependencies
                if hasattr(tool.fn, "_mesh_agent_dependencies"):
                    deps = tool.fn._mesh_agent_dependencies
                    dependencies.update(deps)

        return list(dependencies)

    def _extract_tool_params(self, tool: Any) -> dict:
        """Extract parameter schema from tool."""
        # This is a simplified version - real implementation would
        # introspect function signature and type hints
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def get_endpoint(self, port: int) -> str:
        """Get the full HTTP endpoint URL using the main FastAPI app's port."""
        return f"http://{self._get_external_host()}:{port}"
