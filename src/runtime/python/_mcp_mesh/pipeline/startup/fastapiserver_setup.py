import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from ..shared import PipelineResult, PipelineStatus, PipelineStep


class FastAPIServerSetupStep(PipelineStep):
    """
    Sets up FastAPI server with K8s endpoints and mounts FastMCP servers.

    FastAPI server binds to the port specified in @mesh.agent configuration.
    FastMCP servers are mounted at /mcp endpoint for MCP protocol communication.
    Includes Kubernetes health endpoints (/health, /ready, /metrics).
    """

    def __init__(self):
        super().__init__(
            name="fastapi-server-setup",
            required=False,  # Optional - may not have FastMCP instances to mount
            description="Prepare FastAPI app with K8s endpoints and mount FastMCP servers",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Setup FastAPI server."""
        self.logger.debug("Setting up FastAPI server with mounted FastMCP servers...")

        result = PipelineResult(message="FastAPI server setup completed")

        try:
            # Get configuration and discovered servers
            agent_config = context.get("agent_config", {})
            fastmcp_servers = context.get("fastmcp_servers", {})

            # Check if HTTP transport is enabled
            if not self._is_http_enabled():
                result.status = PipelineStatus.SKIPPED
                result.message = "HTTP transport disabled"
                self.logger.info("⚠️ HTTP transport disabled via MCP_MESH_HTTP_ENABLED")
                return result

            # Resolve binding and advertisement configuration
            binding_config = self._resolve_binding_config(agent_config)
            advertisement_config = self._resolve_advertisement_config(agent_config)

            # Get heartbeat config for lifespan integration
            heartbeat_config = context.get("heartbeat_config")

            # Create HTTP wrappers for FastMCP servers FIRST (so we can use their lifespans)
            mcp_wrappers = {}
            if fastmcp_servers:
                for server_key, server_instance in fastmcp_servers.items():
                    try:
                        # Create HttpMcpWrapper for FastMCP app creation and mounting
                        from ...engine.http_wrapper import HttpMcpWrapper

                        mcp_wrapper = HttpMcpWrapper(server_instance)
                        await mcp_wrapper.setup()

                        mcp_wrappers[server_key] = {
                            "wrapper": mcp_wrapper,
                            "server_instance": server_instance,
                        }
                        self.logger.info(
                            f"🔌 Created MCP wrapper for FastMCP server '{server_key}'"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"❌ Failed to create MCP wrapper for server '{server_key}': {e}"
                        )
                        result.add_error(f"Failed to wrap server '{server_key}': {e}")

            # Create FastAPI application with proper FastMCP lifespan integration (AFTER wrappers)
            fastapi_app = self._create_fastapi_app(
                agent_config, fastmcp_servers, heartbeat_config, mcp_wrappers
            )

            # Add K8s health endpoints
            self._add_k8s_endpoints(fastapi_app, agent_config, mcp_wrappers)

            # Integrate MCP wrappers into the main FastAPI app
            for server_key, wrapper_data in mcp_wrappers.items():
                try:
                    mcp_wrapper = wrapper_data["wrapper"]
                    # Add MCP endpoints to our main FastAPI app
                    self._integrate_mcp_wrapper(fastapi_app, mcp_wrapper, server_key)
                    self.logger.info(
                        f"🔌 Integrated MCP wrapper for FastMCP server '{server_key}'"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Failed to integrate MCP wrapper for server '{server_key}': {e}"
                    )
                    result.add_error(f"Failed to integrate server '{server_key}': {e}")

            # Store results in context (app prepared, but server not started yet)
            result.add_context("fastapi_app", fastapi_app)
            result.add_context("mcp_wrappers", mcp_wrappers)
            result.add_context("fastapi_binding_config", binding_config)
            result.add_context("fastapi_advertisement_config", advertisement_config)

            bind_host = binding_config["bind_host"]
            bind_port = binding_config["bind_port"]
            external_host = advertisement_config["external_host"]
            external_endpoint = (
                advertisement_config.get("external_endpoint")
                or f"http://{external_host}:{bind_port}"
            )

            result.message = f"FastAPI app prepared for {bind_host}:{bind_port} (external: {external_endpoint})"
            self.logger.info(
                f"📦 FastAPI app prepared with {len(mcp_wrappers)} MCP wrappers (ready for uvicorn.run)"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastAPI server setup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastAPI server setup failed: {e}")

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
        from ...shared.host_resolver import HostResolver

        # Use centralized binding host resolution (always 0.0.0.0 for all interfaces)
        bind_host = HostResolver.get_binding_host()

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
        from ...shared.host_resolver import HostResolver

        # Use centralized host resolution for external hostname
        external_host = HostResolver.get_external_host()

        # Full endpoint override (if provided)
        external_endpoint = os.getenv("MCP_MESH_HTTP_ENDPOINT")

        return {
            "external_host": external_host,
            "external_endpoint": external_endpoint,  # May be None - will build dynamically
        }

    def _create_fastapi_app(
        self,
        agent_config: dict[str, Any],
        fastmcp_servers: dict[str, Any],
        heartbeat_config: dict[str, Any] = None,
        mcp_wrappers: dict[str, Any] = None,
    ) -> Any:
        """Create FastAPI application with proper FastMCP lifespan integration."""
        try:
            import asyncio
            from contextlib import asynccontextmanager

            from fastapi import FastAPI

            agent_name = agent_config.get("name", "mcp-mesh-agent")
            agent_description = agent_config.get(
                "description", "MCP Mesh Agent with FastAPI integration"
            )

            # Determine lifespan strategy based on configuration
            primary_lifespan = None

            # Helper function to get FastMCP lifespan from wrapper
            def get_fastmcp_lifespan():
                if mcp_wrappers:
                    wrapper_key = next(iter(mcp_wrappers.keys()))
                    mcp_wrapper = mcp_wrappers[wrapper_key]["wrapper"]
                    if (
                        hasattr(mcp_wrapper, "_mcp_app")
                        and mcp_wrapper._mcp_app
                        and hasattr(mcp_wrapper._mcp_app, "lifespan")
                    ):
                        return mcp_wrapper._mcp_app.lifespan
                return None

            if heartbeat_config and len(fastmcp_servers) == 1:
                # Single FastMCP server with heartbeat - combine FastMCP lifespan + heartbeat
                self.logger.debug(
                    "Creating combined lifespan for single FastMCP server with heartbeat"
                )

                fastmcp_lifespan = get_fastmcp_lifespan()
                if not fastmcp_lifespan:
                    self.logger.warning(
                        "No FastMCP lifespan available for heartbeat combination"
                    )

                # Create combined lifespan for single FastMCP + heartbeat
                @asynccontextmanager
                async def single_fastmcp_with_heartbeat_lifespan(main_app):
                    """Lifespan manager for single FastMCP + heartbeat."""
                    # Start FastMCP lifespan - use main app as recommended by FastMCP docs
                    fastmcp_ctx = None
                    if fastmcp_lifespan:
                        try:
                            fastmcp_ctx = fastmcp_lifespan(main_app)
                            await fastmcp_ctx.__aenter__()
                            self.logger.debug(
                                "Started FastMCP lifespan with main app context"
                            )
                        except Exception as e:
                            self.logger.error(f"Failed to start FastMCP lifespan: {e}")

                    # Start heartbeat task
                    heartbeat_task = None
                    heartbeat_task_fn = heartbeat_config.get("heartbeat_task_fn")
                    if heartbeat_task_fn:
                        heartbeat_task = asyncio.create_task(
                            heartbeat_task_fn(heartbeat_config)
                        )
                        self.logger.info(
                            f"💓 Started heartbeat task with {heartbeat_config['interval']}s interval"
                        )

                    try:
                        yield
                    finally:
                        # Clean up heartbeat task
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                self.logger.info(
                                    "🛑 Heartbeat task cancelled during shutdown"
                                )

                        # Clean up FastMCP lifespan
                        if fastmcp_ctx:
                            try:
                                await fastmcp_ctx.__aexit__(None, None, None)
                                self.logger.debug("FastMCP lifespan stopped")
                            except Exception as e:
                                self.logger.warning(
                                    f"Error closing FastMCP lifespan: {e}"
                                )

                primary_lifespan = single_fastmcp_with_heartbeat_lifespan

            elif heartbeat_config and len(fastmcp_servers) == 0:
                # Heartbeat only - no FastMCP servers
                self.logger.debug(
                    "Creating lifespan for heartbeat only (no FastMCP servers)"
                )

                @asynccontextmanager
                async def heartbeat_only_lifespan(main_app):
                    """Lifespan manager for heartbeat only."""
                    # Start heartbeat task
                    heartbeat_task = None
                    heartbeat_task_fn = heartbeat_config.get("heartbeat_task_fn")
                    if heartbeat_task_fn:
                        heartbeat_task = asyncio.create_task(
                            heartbeat_task_fn(heartbeat_config)
                        )
                        self.logger.info(
                            f"💓 Started heartbeat task with {heartbeat_config['interval']}s interval"
                        )

                    try:
                        yield
                    finally:
                        # Clean up heartbeat task
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                self.logger.info(
                                    "🛑 Heartbeat task cancelled during shutdown"
                                )

                primary_lifespan = heartbeat_only_lifespan

            elif len(fastmcp_servers) > 1:
                # Multiple FastMCP servers - use combined lifespan
                self.logger.debug(
                    "Creating combined lifespan for multiple FastMCP servers"
                )

                # Collect FastMCP lifespans from pre-created wrappers
                fastmcp_lifespans = []
                for server_key, wrapper_data in mcp_wrappers.items():
                    mcp_wrapper = wrapper_data["wrapper"]
                    if (
                        hasattr(mcp_wrapper, "_mcp_app")
                        and mcp_wrapper._mcp_app
                        and hasattr(mcp_wrapper._mcp_app, "lifespan")
                    ):
                        fastmcp_lifespans.append(mcp_wrapper._mcp_app.lifespan)
                        self.logger.debug(
                            f"Collected lifespan from FastMCP wrapper '{server_key}'"
                        )
                    else:
                        self.logger.warning(
                            f"No lifespan available from wrapper '{server_key}'"
                        )

                # Create combined lifespan manager for multiple servers
                @asynccontextmanager
                async def multiple_fastmcp_lifespan(main_app):
                    """Combined lifespan manager for multiple FastMCP servers."""
                    # Start all FastMCP lifespans
                    lifespan_contexts = []
                    for lifespan in fastmcp_lifespans:
                        try:
                            ctx = lifespan(main_app)
                            await ctx.__aenter__()
                            lifespan_contexts.append(ctx)
                        except Exception as e:
                            self.logger.error(f"Failed to start FastMCP lifespan: {e}")

                    try:
                        yield
                    finally:
                        # Clean up all lifespans in reverse order
                        for ctx in reversed(lifespan_contexts):
                            try:
                                await ctx.__aexit__(None, None, None)
                            except Exception as e:
                                self.logger.warning(
                                    f"Error closing FastMCP lifespan: {e}"
                                )

                primary_lifespan = multiple_fastmcp_lifespan

            elif len(fastmcp_servers) == 1:
                # Single FastMCP server without heartbeat - use its lifespan directly
                self.logger.debug(
                    "Using direct FastMCP lifespan for single server (no heartbeat)"
                )
                primary_lifespan = get_fastmcp_lifespan()
                if not primary_lifespan:
                    self.logger.warning(
                        "No FastMCP lifespan available for single server"
                    )

            app = FastAPI(
                title=f"MCP Mesh Agent: {agent_name}",
                description=agent_description,
                version=agent_config.get("version", "1.0.0"),
                docs_url="/docs",  # Enable OpenAPI docs
                redoc_url="/redoc",
                lifespan=primary_lifespan,
            )

            self.logger.debug(
                f"Created FastAPI app for agent '{agent_name}' with lifespan: {primary_lifespan is not None}"
            )
            return app

        except ImportError as e:
            raise Exception(f"FastAPI not available: {e}")

    def _add_k8s_endpoints(
        self, app: Any, agent_config: dict[str, Any], mcp_wrappers: dict[str, Any]
    ) -> None:
        """Add Kubernetes health and metrics endpoints."""
        agent_name = agent_config.get("name", "mcp-mesh-agent")

        @app.get("/health")
        async def health():
            """Basic health check endpoint for Kubernetes."""
            return {
                "status": "healthy",
                "agent": agent_name,
                "timestamp": self._get_timestamp(),
            }

        @app.get("/ready")
        async def ready():
            """Readiness check for Kubernetes."""
            # Simple readiness check - always ready for now
            # TODO: Update this to check MCP wrapper status
            return {
                "ready": True,
                "agent": agent_name,
                "mcp_wrappers": len(mcp_wrappers),
                "timestamp": self._get_timestamp(),
            }

        @app.get("/livez")
        async def livez():
            """Liveness check for Kubernetes."""
            return {
                "alive": True,
                "agent": agent_name,
                "timestamp": self._get_timestamp(),
            }

        @app.get("/metrics")
        async def metrics():
            """Basic metrics endpoint for Prometheus."""
            # Simple text format metrics
            # TODO: Update to get tools count from MCP wrappers

            metrics_text = f"""# HELP mcp_mesh_wrappers_total Total number of MCP wrappers
# TYPE mcp_mesh_wrappers_total gauge
mcp_mesh_wrappers_total{{agent="{agent_name}"}} {len(mcp_wrappers)}

# HELP mcp_mesh_up Agent uptime indicator
# TYPE mcp_mesh_up gauge
mcp_mesh_up{{agent="{agent_name}"}} 1
"""
            from fastapi.responses import PlainTextResponse

            return PlainTextResponse(content=metrics_text, media_type="text/plain")

        self.logger.debug(
            "Added K8s health endpoints: /health, /ready, /livez, /metrics"
        )

    def _integrate_mcp_wrapper(
        self, app: Any, mcp_wrapper: Any, server_key: str
    ) -> None:
        """Integrate HttpMcpWrapper FastMCP app into the main FastAPI app."""
        try:
            # The HttpMcpWrapper provides a FastMCP app for direct mounting
            fastmcp_app = mcp_wrapper._mcp_app

            if fastmcp_app is not None:
                # Mount the FastMCP app at root since it already provides /mcp routes
                # FastMCP creates routes like /mcp/, so mounting at root gives us the correct paths
                app.mount("", fastmcp_app)
                self.logger.debug(
                    f"Mounted FastMCP app from wrapper '{server_key}' at root (provides /mcp routes)"
                )
            else:
                self.logger.warning(
                    f"No FastMCP app available in wrapper '{server_key}'"
                )

        except Exception as e:
            self.logger.error(f"Failed to integrate MCP wrapper '{server_key}': {e}")
            raise

    def _mount_fastmcp_server(
        self, app: Any, server_key: str, server_instance: Any
    ) -> str:
        """Mount a FastMCP server onto FastAPI."""
        try:
            # Try to get FastMCP's HTTP app
            if hasattr(server_instance, "http_app") and callable(
                server_instance.http_app
            ):
                fastmcp_app = server_instance.http_app()
                # Mount at /mcp path for MCP protocol access
                mount_path = "/mcp"
                app.mount(mount_path, fastmcp_app)
                self.logger.debug(
                    f"Mounted FastMCP server '{server_key}' at {mount_path}"
                )
                return mount_path  # Return the actual endpoint users will access
            else:
                raise Exception(
                    f"FastMCP server '{server_key}' does not have http_app() method"
                )

        except Exception as e:
            self.logger.error(f"Failed to mount FastMCP server '{server_key}': {e}")
            raise

    async def _start_fastapi_server(
        self,
        app: Any,
        binding_config: dict[str, Any],
        advertisement_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Start FastAPI server with uvicorn."""
        bind_host = binding_config["bind_host"]
        bind_port = binding_config["bind_port"]
        external_host = advertisement_config["external_host"]
        external_endpoint = advertisement_config["external_endpoint"]

        try:
            import asyncio

            import uvicorn

            # Create uvicorn config
            config = uvicorn.Config(
                app=app,
                host=bind_host,
                port=bind_port,
                log_level="info",
                access_log=False,  # Reduce noise
            )

            # Create and start server
            server = uvicorn.Server(config)

            # Start server as background task
            async def run_server():
                try:
                    await server.serve()
                except Exception as e:
                    self.logger.error(f"FastAPI server stopped with error: {e}")

            server_task = asyncio.create_task(run_server())

            # Give server a moment to start up
            await asyncio.sleep(0.2)

            # Determine actual port (for now, assume it started on requested port)
            actual_port = bind_port if bind_port != 0 else 8080

            # Build external endpoint
            final_external_endpoint = (
                external_endpoint or f"http://{external_host}:{actual_port}"
            )

            return {
                "server": server,
                "server_task": server_task,
                "actual_port": actual_port,
                "bind_address": f"{bind_host}:{actual_port}",
                "external_endpoint": final_external_endpoint,
            }

        except ImportError as e:
            raise Exception(f"uvicorn not available: {e}")
        except Exception as e:
            self.logger.error(f"Failed to start FastAPI server: {e}")
            raise

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""

        return datetime.now(UTC).isoformat()
