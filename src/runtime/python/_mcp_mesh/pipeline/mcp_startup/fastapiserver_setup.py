import asyncio
import logging
import os
import socket
import time
from datetime import UTC, datetime
from typing import Any, Optional

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

            # Check for existing server from ServerDiscoveryStep
            existing_server = context.get("existing_server")
            existing_fastapi_app = context.get("existing_fastapi_app")
            server_reuse = context.get("server_reuse", False)

            # Check if HTTP transport is enabled
            if not self._is_http_enabled():
                result.status = PipelineStatus.SKIPPED
                result.message = "HTTP transport disabled"
                self.logger.info("⚠️ HTTP transport disabled via MCP_MESH_HTTP_ENABLED")
                return result

            # Resolve binding and advertisement configuration
            binding_config = self._resolve_binding_config(agent_config)
            advertisement_config = self._resolve_advertisement_config(agent_config)

            # Handle existing server case - mount FastMCP with proper lifespan integration
            if server_reuse and existing_server:
                self.logger.debug(
                    "🔄 SERVER REUSE: Found existing server, will mount FastMCP with proper lifespan integration"
                )
                return await self._handle_existing_server(
                    context,
                    result,
                    existing_server,
                    existing_fastapi_app,
                    fastmcp_servers,
                    agent_config,
                    binding_config,
                    advertisement_config,
                )

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
            # Store context for shutdown coordination
            self._current_context = context
            fastapi_app = self._create_fastapi_app(
                agent_config, fastmcp_servers, heartbeat_config, mcp_wrappers
            )

            # Add K8s health endpoints
            await self._add_k8s_endpoints(
                fastapi_app, agent_config, mcp_wrappers, context
            )

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

            # Store context for graceful shutdown access
            self._store_context_for_shutdown(context)

            # Store agent_id for metadata endpoint access
            agent_id = context.get("agent_id")
            if agent_id:
                self._current_context = self._current_context or {}
                self._current_context["agent_id"] = agent_id

            # Store mcp_wrappers for session stats access
            self._current_context = self._current_context or {}
            self._current_context["mcp_wrappers"] = mcp_wrappers

            # Store results in context (app prepared, but server not started yet)
            result.add_context("fastapi_app", fastapi_app)
            result.add_context("mcp_wrappers", mcp_wrappers)
            result.add_context("fastapi_binding_config", binding_config)
            result.add_context("fastapi_advertisement_config", advertisement_config)

            # Set shutdown context for signal handlers with FastAPI app
            try:
                from mesh.decorators import set_shutdown_context

                shutdown_context = {
                    "fastapi_app": fastapi_app,
                    "registry_url": context.get("registry_url"),
                    "agent_id": context.get("agent_id"),
                    "registry_wrapper": context.get("registry_wrapper"),
                }
                set_shutdown_context(shutdown_context)
                self.logger.debug("🔧 Shutdown context set for signal handlers")
            except Exception as e:
                self.logger.warning(f"⚠️ Failed to set shutdown context: {e}")

            # Pass through server reuse information to orchestrator
            result.add_context("server_reused", server_reuse)
            result.add_context("existing_server", existing_server)

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

            from fastapi import FastAPI, Response

            agent_name = agent_config.get("name", "mcp-mesh-agent")
            agent_description = agent_config.get(
                "description", "MCP Mesh Agent with FastAPI integration"
            )

            # Simplified lifespan - heartbeat now handled by daemon thread
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

            if len(fastmcp_servers) == 1:
                # Single FastMCP server - simple lifespan with graceful shutdown
                self.logger.debug("Creating simple lifespan for single FastMCP server")
                fastmcp_lifespan = get_fastmcp_lifespan()

                if fastmcp_lifespan:

                    @asynccontextmanager
                    async def simple_fastmcp_lifespan(main_app):
                        """Simple lifespan for single FastMCP server."""
                        fastmcp_ctx = None
                        try:
                            fastmcp_ctx = fastmcp_lifespan(main_app)
                            await fastmcp_ctx.__aenter__()
                            self.logger.debug("Started FastMCP lifespan")
                        except Exception as e:
                            self.logger.error(f"Failed to start FastMCP lifespan: {e}")

                        try:
                            yield
                        finally:
                            # Graceful shutdown - unregister from registry
                            await self._graceful_shutdown(main_app)

                            # Clean up FastMCP lifespan
                            if fastmcp_ctx:
                                try:
                                    await fastmcp_ctx.__aexit__(None, None, None)
                                    self.logger.debug("FastMCP lifespan stopped")
                                except Exception as e:
                                    self.logger.warning(
                                        f"Error closing FastMCP lifespan: {e}"
                                    )

                    primary_lifespan = simple_fastmcp_lifespan
                else:
                    primary_lifespan = None

            elif len(fastmcp_servers) > 1:
                # Multiple FastMCP servers - combine lifespans
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

                if fastmcp_lifespans:

                    @asynccontextmanager
                    async def multiple_fastmcp_lifespan(main_app):
                        """Combined lifespan for multiple FastMCP servers."""
                        lifespan_contexts = []
                        for lifespan in fastmcp_lifespans:
                            try:
                                ctx = lifespan(main_app)
                                await ctx.__aenter__()
                                lifespan_contexts.append(ctx)
                            except Exception as e:
                                self.logger.error(
                                    f"Failed to start FastMCP lifespan: {e}"
                                )

                        try:
                            yield
                        finally:
                            # Registry cleanup using simple shutdown
                            context = getattr(self, "_current_context", {})
                            registry_url = context.get(
                                "registry_url", "http://localhost:8001"
                            )
                            agent_id = context.get("agent_id", "unknown")

                            try:
                                from ...shared.simple_shutdown import (
                                    _simple_shutdown_coordinator,
                                )

                                _simple_shutdown_coordinator.set_shutdown_context(
                                    registry_url, agent_id
                                )
                                await _simple_shutdown_coordinator.perform_registry_cleanup()
                            except Exception as e:
                                self.logger.error(f"❌ Registry cleanup error: {e}")

                            # Clean up all lifespans in reverse order
                            for ctx in reversed(lifespan_contexts):
                                try:
                                    await ctx.__aexit__(None, None, None)
                                except Exception as e:
                                    self.logger.warning(
                                        f"Error closing FastMCP lifespan: {e}"
                                    )

                    primary_lifespan = multiple_fastmcp_lifespan

            # Add minimal graceful shutdown lifespan if no FastMCP lifespans found
            if primary_lifespan is None:
                self.logger.debug(
                    "Creating minimal lifespan for graceful shutdown only"
                )

                @asynccontextmanager
                async def graceful_shutdown_only_lifespan(main_app):
                    """Minimal lifespan for graceful shutdown only."""
                    try:
                        yield
                    finally:
                        # Registry cleanup using simple shutdown
                        context = getattr(self, "_current_context", {})
                        registry_url = context.get(
                            "registry_url", "http://localhost:8001"
                        )
                        agent_id = context.get("agent_id", "unknown")

                        try:
                            from ...shared.simple_shutdown import (
                                _simple_shutdown_coordinator,
                            )

                            _simple_shutdown_coordinator.set_shutdown_context(
                                registry_url, agent_id
                            )
                            await _simple_shutdown_coordinator.perform_registry_cleanup()
                        except Exception as e:
                            self.logger.error(f"❌ Registry cleanup error: {e}")

                primary_lifespan = graceful_shutdown_only_lifespan

            app = FastAPI(
                title=f"MCP Mesh Agent: {agent_name}",
                description=agent_description,
                version=agent_config.get("version", "1.0.0"),
                docs_url="/docs",  # Enable OpenAPI docs
                redoc_url="/redoc",
                lifespan=primary_lifespan,
            )

            # Registry cleanup is now integrated directly into the lifespan above

            # Store app reference for global shutdown coordination
            app.state.shutdown_step = self

            self.logger.debug(
                f"Created FastAPI app for agent '{agent_name}' with lifespan: {primary_lifespan is not None}"
            )
            return app

        except ImportError as e:
            raise Exception(f"FastAPI not available: {e}")

    # Note: Trace context middleware for distributed tracing is added in
    # mesh/decorators.py BEFORE the FastAPI app starts. This ensures the middleware
    # is properly registered since middleware cannot be added after the app starts.

    async def _add_k8s_endpoints(
        self,
        app: Any,
        agent_config: dict[str, Any],
        mcp_wrappers: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """
        Set up health check result updates for K8s endpoints.

        Note: The /health endpoint is already registered by immediate uvicorn.
        We just need to update the result it returns via DecoratorRegistry.
        """
        from fastapi import Response

        agent_name = agent_config.get("name", "mcp-mesh-agent")
        health_check_fn = agent_config.get("health_check")
        health_check_ttl = agent_config.get("health_check_ttl", 15)

        # Create a background task to update health check results periodically
        async def update_health_result():
            """Update health check result in DecoratorRegistry."""
            if health_check_fn:
                # Use health check cache if configured
                from ...engine.decorator_registry import DecoratorRegistry
                from ...shared.health_check_cache import get_health_status_with_cache

                health_status = await get_health_status_with_cache(
                    agent_id=agent_name,
                    health_check_fn=health_check_fn,
                    agent_config=agent_config,
                    startup_context=context,
                    ttl=health_check_ttl,
                )

                result = {
                    "status": health_status.status.value,
                    "agent": agent_name,
                    "checks": health_status.checks,
                    "errors": health_status.errors,
                    "timestamp": health_status.timestamp.isoformat(),
                }
            else:
                # No health check configured - return default healthy status
                result = {
                    "status": "healthy",
                    "agent": agent_name,
                    "timestamp": self._get_timestamp(),
                }

            # Store result for /health endpoint to use
            from ...engine.decorator_registry import DecoratorRegistry

            DecoratorRegistry.store_health_check_result(result)

        # Run once immediately to populate initial result
        # We're already in an async context (called from execute()), so just await it

        await update_health_result()

        # Note: /health endpoint is already registered by immediate uvicorn
        # It will call DecoratorRegistry.get_health_check_result() to get this data

        @app.get("/ready")
        @app.head("/ready")
        async def ready(response: Response):
            """
            Readiness check for Kubernetes.

            Returns 200 when the service is ready to serve traffic.
            Returns 503 when unhealthy - K8s will remove pod from service endpoints.
            """
            # Get health check result if available
            from ...engine.decorator_registry import DecoratorRegistry

            custom_health = DecoratorRegistry.get_health_check_result()

            if custom_health:
                status = custom_health.get("status", "starting")
                if status == "healthy":
                    response.status_code = 200
                    return {
                        "ready": True,
                        "agent": agent_name,
                        "status": status,
                        "mcp_wrappers": len(mcp_wrappers),
                        "timestamp": self._get_timestamp(),
                    }
                else:
                    # Not ready to serve traffic
                    response.status_code = 503
                    return {
                        "ready": False,
                        "agent": agent_name,
                        "status": status,
                        "reason": f"Service is {status}",
                        "errors": custom_health.get("errors", []),
                    }
            else:
                # No custom health check - assume ready
                response.status_code = 200
                return {
                    "ready": True,
                    "agent": agent_name,
                    "mcp_wrappers": len(mcp_wrappers),
                    "timestamp": self._get_timestamp(),
                }

        @app.get("/livez")
        @app.head("/livez")
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

        # Add metadata endpoint for capability routing information
        @app.get("/metadata")
        async def get_routing_metadata():
            """Get routing metadata for all capabilities on this agent."""
            from datetime import datetime

            from ...engine.decorator_registry import DecoratorRegistry

            capabilities_metadata = {}

            # Get all registered mesh tools from existing DecoratorRegistry
            try:
                registered_tools = DecoratorRegistry.get_mesh_tools()

                for func_name, decorated_func in registered_tools.items():
                    metadata = decorated_func.metadata
                    capability_name = metadata.get("capability", func_name)
                    capabilities_metadata[capability_name] = {
                        "function_name": func_name,
                        "capability": capability_name,
                        "version": metadata.get("version", "1.0.0"),
                        "tags": metadata.get("tags", []),
                        "description": metadata.get("description", ""),
                        # Extract routing flags from **kwargs (already supported)
                        "session_required": metadata.get("session_required", False),
                        "stateful": metadata.get("stateful", False),
                        "streaming": metadata.get("streaming", False),
                        "full_mcp_access": metadata.get("full_mcp_access", False),
                        # Include any custom metadata from **kwargs
                        "custom_metadata": {
                            k: v
                            for k, v in metadata.items()
                            if k
                            not in [
                                "capability",
                                "function_name",
                                "version",
                                "tags",
                                "description",
                                "dependencies",
                            ]
                        },
                    }
            except Exception as e:
                self.logger.warning(f"Failed to get mesh tools metadata: {e}")
                capabilities_metadata = {}

            # Get agent ID from stored context (set during startup)
            stored_context = getattr(self, "_current_context", {})
            agent_id = stored_context.get("agent_id")

            # Fallback to agent config name if agent_id not available
            if not agent_id:
                current_agent_config = agent_config or {}
                agent_id = current_agent_config.get("name", "unknown")

            # Phase 5: Add session affinity statistics
            session_affinity_stats = {}
            try:
                mcp_wrappers = stored_context.get("mcp_wrappers", {})
                if mcp_wrappers:
                    # Get session stats from first wrapper (they should all be similar)
                    first_wrapper = next(iter(mcp_wrappers.values()))
                    if first_wrapper and hasattr(
                        first_wrapper.get("wrapper"), "get_session_stats"
                    ):
                        session_affinity_stats = first_wrapper[
                            "wrapper"
                        ].get_session_stats()
            except Exception as e:
                self.logger.debug(f"Failed to get session stats: {e}")
                session_affinity_stats = {"error": "session stats unavailable"}

            metadata_response = {
                "agent_id": agent_id,
                "capabilities": capabilities_metadata,
                "timestamp": datetime.now().isoformat(),
                "status": "healthy",
            }

            # Add session affinity stats if available
            if session_affinity_stats:
                metadata_response["session_affinity"] = session_affinity_stats

            return metadata_response

        self.logger.debug(
            "Added K8s health endpoints: /health, /ready, /livez, /metrics, /metadata"
        )

    def _integrate_mcp_wrapper(
        self, app: Any, mcp_wrapper: Any, server_key: str
    ) -> None:
        """Integrate HttpMcpWrapper FastMCP app into the main FastAPI app."""
        try:
            # The HttpMcpWrapper provides a FastMCP app for direct mounting
            fastmcp_app = mcp_wrapper._mcp_app

            if fastmcp_app is not None:
                # Phase 5: Session routing now handled by HttpMcpWrapper middleware
                # No need to add FastAPI-level middleware

                # Mount the FastMCP app at root since it already provides /mcp routes
                # FastMCP creates routes like /mcp/, so mounting at root gives us the correct paths
                app.mount("", fastmcp_app)
                self.logger.debug(
                    f"Mounted FastMCP app with HttpMcpWrapper session routing from '{server_key}'"
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

    async def _graceful_shutdown(self, main_app: Any) -> None:
        """
        Perform graceful shutdown by unregistering agent from registry.

        Args:
            main_app: FastAPI application instance (unused but required by lifespan signature)
        """
        try:
            # Get pipeline context from the step execution context
            # Note: We need to access the context from where this was called
            context = getattr(self, "_current_context", {})

            # Get registry configuration
            registry_url = context.get("registry_url")
            agent_id = context.get("agent_id")

            if not registry_url or not agent_id:
                self.logger.warning(
                    f"🚨 Cannot perform graceful shutdown: missing registry_url={registry_url} or agent_id={agent_id}"
                )
                return

            # Get or create registry client wrapper
            registry_wrapper = context.get("registry_wrapper")
            if not registry_wrapper:
                # Create new registry client for shutdown
                from ...generated.mcp_mesh_registry_client.api_client import ApiClient
                from ...generated.mcp_mesh_registry_client.configuration import (
                    Configuration,
                )
                from ...shared.registry_client_wrapper import RegistryClientWrapper
                from ..registry_connection import RegistryConnectionStep

                config = Configuration(host=registry_url)
                api_client = ApiClient(configuration=config)
                registry_wrapper = RegistryClientWrapper(api_client)
                self.logger.debug(
                    f"🔧 Created registry client for graceful shutdown: {registry_url}"
                )

            # Perform graceful unregistration
            success = await registry_wrapper.unregister_agent(agent_id)
            if success:
                self.logger.info(
                    f"🏁 Graceful shutdown completed for agent '{agent_id}'"
                )
            else:
                self.logger.warning(
                    f"⚠️ Graceful shutdown failed for agent '{agent_id}' - continuing shutdown"
                )

        except Exception as e:
            # Don't fail the shutdown process due to unregistration errors
            self.logger.error(f"❌ Graceful shutdown error: {e} - continuing shutdown")

    def _store_context_for_shutdown(self, context: dict[str, Any]) -> None:
        """Store context for access during shutdown."""
        # Store essential shutdown information
        self._current_context = {
            "registry_url": context.get("registry_url"),
            "agent_id": context.get("agent_id"),
            "registry_wrapper": context.get("registry_wrapper"),
        }

    async def _handle_existing_server(
        self,
        context: dict[str, Any],
        result: Any,
        existing_server: dict[str, Any],
        existing_fastapi_app: dict[str, Any],
        fastmcp_servers: dict[str, Any],
        agent_config: dict[str, Any],
        binding_config: dict[str, Any],
        advertisement_config: dict[str, Any],
    ) -> Any:
        """
        Handle mounting FastMCP on existing uvicorn server.

        This is used when ServerDiscoveryStep finds an existing uvicorn server
        (e.g., started immediately in @mesh.agent decorator) and we need to
        mount FastMCP endpoints on it instead of starting a new server.
        """
        try:
            self.logger.debug("🔄 SERVER REUSE: Mounting FastMCP on existing server")

            # Get the existing minimal FastAPI app that's already running
            existing_app = None
            if existing_fastapi_app and "app" in existing_fastapi_app:
                existing_app = existing_fastapi_app["app"]
            elif existing_fastapi_app and "instance" in existing_fastapi_app:
                existing_app = existing_fastapi_app["instance"]
            elif existing_server and "app" in existing_server:
                existing_app = existing_server["app"]
            else:
                # As fallback, try to get the app from DecoratorRegistry
                from ...engine.decorator_registry import DecoratorRegistry

                server_info = DecoratorRegistry.get_immediate_uvicorn_server()
                if server_info and "app" in server_info:
                    existing_app = server_info["app"]

            if not existing_app:
                raise ValueError("No existing FastAPI app found for server reuse")

            self.logger.debug(
                f"🔄 SERVER REUSE: Using existing FastAPI app '{existing_app.title}' for FastMCP mounting"
            )

            # Check if FastMCP lifespan is already integrated with the FastAPI app
            from ...engine.decorator_registry import DecoratorRegistry

            fastmcp_lifespan = DecoratorRegistry.get_fastmcp_lifespan()
            fastmcp_http_app = DecoratorRegistry.get_fastmcp_http_app()

            mcp_wrappers = {}
            if fastmcp_servers:
                if fastmcp_lifespan and fastmcp_http_app:
                    self.logger.debug(
                        "✅ SERVER REUSE: FastMCP lifespan already integrated, mounting same HTTP app"
                    )

                    # Note: Trace context middleware is added in decorators.py BEFORE the app starts
                    # We cannot add middleware after the application has started

                    # FastMCP lifespan is already integrated, mount the same HTTP app that was used for lifespan
                    for server_key, server_instance in fastmcp_servers.items():
                        try:
                            # Mount the same FastMCP HTTP app that was used for lifespan integration
                            # This ensures the session manager is shared between lifespan and routes
                            existing_app.mount("", fastmcp_http_app)
                            self.logger.debug(
                                f"🔌 SERVER REUSE: Mounted FastMCP server '{server_key}' using stored HTTP app (lifespan already integrated)"
                            )

                            mcp_wrappers[server_key] = {
                                "fastmcp_app": fastmcp_http_app,
                                "server_instance": server_instance,
                                "lifespan_integrated": True,
                            }

                        except Exception as e:
                            self.logger.error(
                                f"❌ SERVER REUSE: Failed to mount FastMCP server '{server_key}': {e}"
                            )
                            result.add_error(
                                f"Failed to mount server '{server_key}': {e}"
                            )
                else:
                    self.logger.debug(
                        "🔄 SERVER REUSE: No FastMCP lifespan integrated, using HttpMcpWrapper"
                    )

                    # No lifespan integration, use HttpMcpWrapper (fallback method)
                    for server_key, server_instance in fastmcp_servers.items():
                        try:
                            # Create HttpMcpWrapper for proper FastMCP app creation and session routing
                            from ...engine.http_wrapper import HttpMcpWrapper

                            mcp_wrapper = HttpMcpWrapper(server_instance)
                            await mcp_wrapper.setup()

                            # Mount using the wrapper's properly configured FastMCP app
                            if mcp_wrapper._mcp_app:
                                # Mount at root since FastMCP creates its own /mcp routes internally
                                existing_app.mount("", mcp_wrapper._mcp_app)
                                self.logger.debug(
                                    f"🔌 SERVER REUSE: Mounted FastMCP server '{server_key}' via HttpMcpWrapper at root (provides /mcp routes)"
                                )

                            mcp_wrappers[server_key] = {
                                "wrapper": mcp_wrapper,
                                "server_instance": server_instance,
                                "lifespan_integrated": False,
                            }
                        except Exception as e:
                            self.logger.error(
                                f"❌ SERVER REUSE: Failed to create HttpMcpWrapper for server '{server_key}': {e}"
                            )
                            result.add_error(
                                f"Failed to wrap server '{server_key}': {e}"
                            )

                # Add K8s health endpoints to existing app (if not already present)
                await self._add_k8s_endpoints(
                    existing_app, agent_config, mcp_wrappers, context
                )

                # FastMCP servers are already mounted directly - no additional integration needed
                self.logger.debug(
                    "🔌 SERVER REUSE: All FastMCP servers mounted successfully"
                )

            # Store context for graceful shutdown access
            self._store_context_for_shutdown(context)

            # Store agent_id for metadata endpoint access
            agent_id = context.get("agent_id")
            if agent_id:
                self._current_context = self._current_context or {}
                self._current_context["agent_id"] = agent_id

            # Store mcp_wrappers for session stats access
            self._current_context = self._current_context or {}
            self._current_context["mcp_wrappers"] = mcp_wrappers

            # FastMCP is now mounted directly - no server replacement needed
            self.logger.debug(
                "🔄 SERVER REUSE: FastMCP routes mounted to existing app successfully"
            )

            # Store results in context (existing app updated, server reused)
            result.add_context("fastapi_app", existing_app)
            result.add_context("mcp_wrappers", mcp_wrappers)
            result.add_context("fastapi_binding_config", binding_config)
            result.add_context("fastapi_advertisement_config", advertisement_config)
            result.add_context(
                "server_reused", True
            )  # Flag to skip uvicorn.run() in orchestrator

            bind_host = binding_config["bind_host"]
            bind_port = binding_config["bind_port"]
            external_host = advertisement_config["external_host"]
            external_endpoint = (
                advertisement_config.get("external_endpoint")
                or f"http://{external_host}:{bind_port}"
            )

            result.message = f"FastAPI app mounted on existing server {bind_host}:{bind_port} (external: {external_endpoint})"
            self.logger.debug(
                f"✅ SERVER REUSE: FastMCP mounted on existing server with {len(mcp_wrappers)} MCP wrappers"
            )

        except Exception as e:
            self.logger.error(
                f"❌ SERVER REUSE: Failed to mount on existing server: {e}"
            )
            result.status = (
                result.PipelineStatus.FAILED
                if hasattr(result, "PipelineStatus")
                else "failed"
            )
            result.message = f"Server reuse failed: {e}"
            result.add_error(str(e))

        return result
