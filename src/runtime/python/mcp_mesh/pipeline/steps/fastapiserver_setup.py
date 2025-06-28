import asyncio
import logging
import os
import socket
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from ...shared.support_types import HealthStatus, HealthStatusType
from ..pipeline import PipelineResult, PipelineStatus
from .base_step import PipelineStep


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

            # Create FastAPI application with proper FastMCP lifespan integration
            fastapi_app = self._create_fastapi_app(
                agent_config, fastmcp_servers, heartbeat_config
            )

            # Add K8s health endpoints
            self._add_k8s_endpoints(fastapi_app, agent_config, {})

            # Create HTTP wrappers for FastMCP servers (instead of direct mounting)
            mcp_wrappers = {}
            if fastmcp_servers:
                for server_key, server_instance in fastmcp_servers.items():
                    try:
                        # Create HttpMcpWrapper for proper MCP protocol handling
                        from ...engine.http_wrapper import HttpConfig, HttpMcpWrapper

                        # Use wrapper config - it will create its own FastAPI app
                        http_config = HttpConfig(
                            host=binding_config["bind_host"],
                            port=binding_config["bind_port"],
                        )

                        mcp_wrapper = HttpMcpWrapper(server_instance, http_config)
                        await mcp_wrapper.setup()

                        # Add MCP endpoints to our main FastAPI app
                        self._integrate_mcp_wrapper(
                            fastapi_app, mcp_wrapper, server_key
                        )

                        mcp_wrappers[server_key] = {
                            "wrapper": mcp_wrapper,
                            "server_instance": server_instance,
                        }
                        self.logger.info(
                            f"🔌 Integrated MCP wrapper for FastMCP server '{server_key}'"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"❌ Failed to create MCP wrapper for server '{server_key}': {e}"
                        )
                        result.add_error(f"Failed to wrap server '{server_key}': {e}")

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
        import os

        return os.getenv("MCP_MESH_HTTP_ENABLED", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

    def _resolve_binding_config(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Resolve local server binding configuration."""
        import os

        # Local binding - always use 0.0.0.0 to bind to all interfaces
        bind_host = "0.0.0.0"

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
        import os

        # External hostname - for registry advertisement
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

    def _create_fastapi_app(
        self,
        agent_config: dict[str, Any],
        fastmcp_servers: dict[str, Any],
        heartbeat_config: dict[str, Any] = None,
    ) -> Any:
        """Create FastAPI application with FastMCP lifespan integration."""
        try:
            import asyncio
            from contextlib import asynccontextmanager

            from fastapi import FastAPI

            agent_name = agent_config.get("name", "mcp-mesh-agent")
            agent_description = agent_config.get(
                "description", "MCP Mesh Agent with FastAPI integration"
            )

            # Collect lifespans from FastMCP servers
            fastmcp_lifespans = []
            for server_key, server_instance in fastmcp_servers.items():
                if hasattr(server_instance, "http_app") and callable(
                    server_instance.http_app
                ):
                    http_app = server_instance.http_app()
                    if hasattr(http_app, "lifespan"):
                        fastmcp_lifespans.append(http_app.lifespan)
                        self.logger.debug(
                            f"Collected lifespan from FastMCP server '{server_key}'"
                        )

            # Create combined lifespan manager
            @asynccontextmanager
            async def combined_lifespan(app):
                """Combined lifespan manager for FastAPI + FastMCP + Heartbeat."""
                # Start all FastMCP lifespans
                lifespan_contexts = []
                for lifespan in fastmcp_lifespans:
                    ctx = lifespan(app)
                    await ctx.__aenter__()
                    lifespan_contexts.append(ctx)

                # Start heartbeat task if configured
                heartbeat_task = None
                if heartbeat_config:
                    import asyncio

                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_lifespan_task(heartbeat_config)
                    )
                    self.logger.info(
                        f"💓 Started heartbeat task in FastAPI lifespan with {heartbeat_config['interval']}s interval"
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

                    # Clean up all lifespans in reverse order
                    for ctx in reversed(lifespan_contexts):
                        try:
                            await ctx.__aexit__(None, None, None)
                        except Exception as e:
                            self.logger.warning(f"Error closing FastMCP lifespan: {e}")

            app = FastAPI(
                title=f"MCP Mesh Agent: {agent_name}",
                description=agent_description,
                version=agent_config.get("version", "1.0.0"),
                docs_url="/docs",  # Enable OpenAPI docs
                redoc_url="/redoc",
                lifespan=(
                    combined_lifespan
                    if (fastmcp_lifespans or heartbeat_config)
                    else None
                ),
            )

            self.logger.debug(
                f"Created FastAPI app for agent '{agent_name}' with {len(fastmcp_lifespans)} FastMCP lifespans"
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
        """Integrate HttpMcpWrapper MCP endpoints into the main FastAPI app."""
        try:
            # The HttpMcpWrapper creates its own FastAPI app with MCP endpoints
            # We need to extract the MCP endpoint handlers and add them to our main app

            # Get the MCP route handlers from the wrapper's app
            wrapper_app = mcp_wrapper.app

            # Find the /mcp route and copy it to our main app
            for route in wrapper_app.routes:
                if hasattr(route, "path") and route.path == "/mcp":
                    # Add the MCP endpoint to our main app
                    app.add_route("/mcp", route.endpoint, methods=["POST"])
                    self.logger.debug(
                        f"Added /mcp endpoint from wrapper '{server_key}'"
                    )
                    break
            else:
                self.logger.warning(f"No /mcp route found in wrapper '{server_key}'")

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

    async def _heartbeat_lifespan_task(self, heartbeat_config: dict[str, Any]) -> None:
        """Heartbeat task that runs in FastAPI lifespan."""
        registry_wrapper = heartbeat_config["registry_wrapper"]
        agent_id = heartbeat_config["agent_id"]
        interval = heartbeat_config["interval"]
        context = heartbeat_config["context"]

        self.logger.info(f"💓 Starting heartbeat lifespan task for agent '{agent_id}'")

        heartbeat_count = 0
        try:
            while True:
                heartbeat_count += 1

                try:
                    # Build health status from context (reuse existing logic)
                    health_status = self._build_health_status_from_context(context)

                    # Debug: Log heartbeat request details
                    import json

                    # Convert health status to dict for logging
                    if hasattr(health_status, "__dict__"):
                        health_dict = {
                            "agent_name": getattr(
                                health_status, "agent_name", agent_id
                            ),
                            "status": (
                                getattr(health_status, "status", "healthy").value
                                if hasattr(
                                    getattr(health_status, "status", "healthy"), "value"
                                )
                                else str(getattr(health_status, "status", "healthy"))
                            ),
                            "capabilities": getattr(health_status, "capabilities", []),
                            "timestamp": (
                                getattr(health_status, "timestamp", "").isoformat()
                                if hasattr(
                                    getattr(health_status, "timestamp", ""), "isoformat"
                                )
                                else str(getattr(health_status, "timestamp", ""))
                            ),
                            "version": getattr(health_status, "version", "1.0.0"),
                            "metadata": getattr(health_status, "metadata", {}),
                        }
                    else:
                        health_dict = health_status

                    request_json = json.dumps(health_dict, indent=2, default=str)
                    self.logger.debug(
                        f"🔍 Heartbeat request #{heartbeat_count}:\n{request_json}"
                    )

                    # Send heartbeat first
                    response = await registry_wrapper.send_heartbeat_with_dependency_resolution(
                        health_status
                    )

                    # Debug: Log heartbeat response details
                    if response:
                        response_json = json.dumps(response, indent=2, default=str)
                        self.logger.debug(
                            f"🔍 Heartbeat response #{heartbeat_count}:\n{response_json}"
                        )
                    else:
                        self.logger.debug(
                            f"🔍 Heartbeat response #{heartbeat_count}: None (no response)"
                        )

                    # Process heartbeat response for dynamic dependency rewiring
                    if response:
                        await self._process_heartbeat_for_rewiring(response)

                    # Log success
                    if response:
                        self.logger.info(
                            f"💚 Heartbeat #{heartbeat_count} sent successfully for agent '{agent_id}'"
                        )
                    else:
                        self.logger.warning(
                            f"💔 Heartbeat #{heartbeat_count} failed for agent '{agent_id}' - no response"
                        )

                    # Log every 10th heartbeat for visibility
                    if heartbeat_count % 10 == 0:
                        elapsed_time = heartbeat_count * interval
                        self.logger.info(
                            f"💓 Heartbeat #{heartbeat_count} for agent '{agent_id}' - "
                            f"running for {elapsed_time} seconds"
                        )

                except Exception as e:
                    self.logger.error(
                        f"❌ Heartbeat #{heartbeat_count} error for agent '{agent_id}': {e}"
                    )
                    # Continue to next cycle

                # Wait for next heartbeat interval
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            self.logger.info(
                f"🛑 Heartbeat lifespan task cancelled for agent '{agent_id}'"
            )
            raise

    async def _process_heartbeat_for_rewiring(
        self, heartbeat_response: dict[str, Any]
    ) -> None:
        """Process heartbeat response for dynamic dependency rewiring."""
        try:
            # Import the DependencyResolutionStep to reuse its rewiring logic
            from ..registry_steps import DependencyResolutionStep

            # Create a temporary step instance to use its rewiring method
            dep_resolution_step = DependencyResolutionStep()
            await dep_resolution_step.process_heartbeat_response_for_rewiring(
                heartbeat_response
            )
        except Exception as e:
            self.logger.error(f"❌ Error processing heartbeat for rewiring: {e}")
            # Don't raise - this should not break the heartbeat loop

    def _build_health_status_from_context(self, context: dict[str, Any]) -> Any:
        """Build health status object from pipeline context."""
        # Get existing health status from context or build from current state
        existing_health_status = context.get("health_status")

        if existing_health_status:
            # Update timestamp to current time for fresh heartbeat
            if hasattr(existing_health_status, "timestamp"):
                from datetime import UTC, datetime

                existing_health_status.timestamp = datetime.now(UTC)
            return existing_health_status

        # Build minimal health status from context if none exists
        agent_id = context.get("agent_id", "unknown-agent")
        agent_config = context.get("agent_config", {})

        # Import here to avoid circular imports
        from datetime import UTC, datetime

        from ..shared.support_types import HealthStatus, HealthStatusType

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=agent_config.get("capabilities", []),
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=agent_config,
        )

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()
