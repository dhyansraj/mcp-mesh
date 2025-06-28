import asyncio
import logging
import os
import socket
from typing import Any, Dict, List, Optional, Tuple

from ..shared import PipelineResult, PipelineStatus
from ..shared import PipelineStep


class FastMCPServerStartupStep(PipelineStep):
    """
    Starts discovered FastMCP server instances with HTTP transport.

    Handles local binding configuration and prepares external advertisement info.
    Binds servers locally (HOST env var, default: 0.0.0.0) while preparing external 
    endpoints for registry (MCP_MESH_HTTP_HOST, default: localhost).
    """

    def __init__(self):
        super().__init__(
            name="fastmcp-server-startup",
            required=False,  # Optional - may not have FastMCP instances
            description="Start FastMCP servers with HTTP transport",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Start FastMCP servers."""
        self.logger.debug("Starting FastMCP server instances...")

        result = PipelineResult(message="FastMCP server startup completed")

        try:
            # Get discovered servers from previous step
            fastmcp_servers = context.get("fastmcp_servers", {})
            agent_config = context.get("agent_config", {})

            if not fastmcp_servers:
                result.status = PipelineStatus.SKIPPED
                result.message = "No FastMCP servers to start"
                self.logger.info("⚠️ No FastMCP servers found to start")
                return result

            # Check if HTTP transport is enabled
            http_enabled = self._is_http_enabled()
            if not http_enabled:
                result.status = PipelineStatus.SKIPPED
                result.message = "HTTP transport disabled"
                self.logger.info("⚠️ HTTP transport disabled via MCP_MESH_HTTP_ENABLED")
                return result

            # Resolve binding and advertisement configuration
            binding_config = self._resolve_binding_config(agent_config)
            advertisement_config = self._resolve_advertisement_config(agent_config)

            # Start each FastMCP server
            running_servers = {}
            server_endpoints = {}
            actual_ports = {}

            for server_key, server_instance in fastmcp_servers.items():
                try:
                    startup_result = await self._start_fastmcp_server(
                        server_key,
                        server_instance,
                        binding_config,
                        advertisement_config,
                    )

                    running_servers[server_key] = startup_result["server_instance"]
                    actual_ports[server_key] = startup_result["actual_port"]
                    server_endpoints[server_key] = startup_result["external_endpoint"]

                    self.logger.info(
                        f"🚀 Started FastMCP server '{server_key}' on {startup_result['bind_address']} "
                        f"(external: {startup_result['external_endpoint']})"
                    )

                except Exception as e:
                    self.logger.error(
                        f"❌ Failed to start FastMCP server '{server_key}': {e}"
                    )
                    result.add_error(f"Server startup failed for '{server_key}': {e}")

            # Store results in context
            result.add_context("running_fastmcp_servers", running_servers)
            result.add_context("fastmcp_actual_ports", actual_ports)
            result.add_context("fastmcp_server_endpoints", server_endpoints)
            result.add_context("fastmcp_binding_config", binding_config)
            result.add_context("fastmcp_advertisement_config", advertisement_config)

            if running_servers:
                result.message = f"Started {len(running_servers)} FastMCP servers"
                self.logger.info(
                    f"🎯 FastMCP startup complete: {len(running_servers)} servers running"
                )
            else:
                result.status = PipelineStatus.FAILED
                result.message = "No FastMCP servers started successfully"

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastMCP server startup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastMCP server startup failed: {e}")

        return result

    def _is_http_enabled(self) -> bool:
        """Check if HTTP transport is enabled."""

        return os.getenv("MCP_MESH_HTTP_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    def _resolve_binding_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Resolve local server binding configuration."""
        from mcp_mesh.shared.config_resolver import get_config_value, ValidationRule

        # Local binding - HOST env var controls server binding (default: 0.0.0.0 for all interfaces)  
        bind_host = get_config_value("HOST", override=None, default="0.0.0.0", rule=ValidationRule.STRING_RULE)

        # Port from agent config or environment
        bind_port = int(os.getenv("MCP_MESH_HTTP_PORT", 0)) or agent_config.get(
            "http_port", 8080
        )

        return {
            "bind_host": bind_host,
            "bind_port": bind_port,
        }

    def _resolve_advertisement_config(
        self, agent_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve external advertisement configuration for registry."""

        # External hostname - for registry advertisement (MCP_MESH_HTTP_HOST)
        # This is what other agents will use to connect to this agent 
        # Examples: localhost (dev), mcp-mesh-hello-world (K8s service name)
        external_host = (
            os.getenv("MCP_MESH_HTTP_HOST")
            or os.getenv("POD_IP")
            or self._auto_detect_external_ip()
        )

        # Full endpoint override
        external_endpoint = os.getenv("MCP_MESH_HTTP_ENDPOINT")

        return {
            "external_host": external_host,
            "external_endpoint": external_endpoint,  # May be None - will build dynamically
        }

    def _auto_detect_external_ip(self) -> str:
        """Auto-detect external IP address for advertisement."""
        try:
            import socket

            # Try to get the IP that would be used to reach external hosts
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                self.logger.debug(f"Auto-detected external IP: {local_ip}")
                return local_ip

        except Exception as e:
            self.logger.warning(
                f"Failed to auto-detect external IP: {e}, using localhost"
            )
            return "localhost"

    async def _start_fastmcp_server(
        self,
        server_key: str,
        server_instance: Any,
        binding_config: dict[str, Any],
        advertisement_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Start a single FastMCP server instance."""
        bind_host = binding_config["bind_host"]
        bind_port = binding_config["bind_port"]
        external_host = advertisement_config["external_host"]
        external_endpoint = advertisement_config["external_endpoint"]

        try:
            # Verify server has required async methods
            if not (
                hasattr(server_instance, "run_http_async")
                and callable(server_instance.run_http_async)
            ):
                raise Exception(
                    f"Server '{server_key}' does not have run_http_async method"
                )

            self.logger.debug(
                f"Starting FastMCP HTTP server '{server_key}' on {bind_host}:{bind_port}"
            )

            # Start FastMCP HTTP server in background task
            # NOTE: We're starting it as a background task so the pipeline can continue
            import asyncio

            async def run_server():
                try:
                    await server_instance.run_http_async(host=bind_host, port=bind_port)
                except Exception as e:
                    self.logger.error(
                        f"FastMCP server '{server_key}' stopped with error: {e}"
                    )

            # Start server as background task
            server_task = asyncio.create_task(run_server())

            # Give server a moment to start up
            await asyncio.sleep(0.1)

            # Determine actual port (for now, assume it started on requested port)
            # TODO: In the future, we could inspect the server to get the actual bound port
            actual_port = bind_port if bind_port != 0 else 8080

            # Build external endpoint
            final_external_endpoint = (
                external_endpoint or f"http://{external_host}:{actual_port}"
            )

            self.logger.info(
                f"FastMCP server '{server_key}' starting on {bind_host}:{actual_port}"
            )

            return {
                "server_instance": server_instance,
                "server_task": server_task,  # Store task reference for lifecycle management
                "actual_port": actual_port,
                "bind_address": f"{bind_host}:{actual_port}",
                "external_endpoint": final_external_endpoint,
            }

        except Exception as e:
            self.logger.error(f"Failed to start server '{server_key}': {e}")
            raise
