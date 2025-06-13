"""
DecoratorProcessor - Processes decorator metadata and registers with mesh registry.

This module reads decorator metadata from DecoratorRegistry (in mcp_mesh package)
and performs the actual registration with the mesh registry service. It handles
the heavy lifting of transforming decorator metadata into proper service registrations.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from mcp_mesh import DecoratedFunction, DecoratorRegistry

from .logging_config import configure_logging
from .registry_client import RegistryClient
from .shared.types import HealthStatus, HealthStatusType

# Ensure logging is configured
configure_logging()


class DecoratorProcessorError(Exception):
    """Base exception for decorator processor errors."""

    pass


class RegistrationError(DecoratorProcessorError):
    """Raised when agent registration fails."""

    pass


class MeshAgentProcessor:
    """
    Specialized processor for @mesh_agent decorated functions.

    Handles the transformation of decorator metadata into proper agent
    registrations with the mesh registry service.
    """

    def __init__(self, registry_client: RegistryClient) -> None:
        self.registry_client: RegistryClient = registry_client
        self.logger: logging.Logger = logging.getLogger(__name__)
        self._processed_agents: dict[str, bool] = {}
        self._health_tasks: dict[str, asyncio.Task[None]] = {}
        self._last_dependencies_resolved: dict[str, dict[str, Any]] = {}
        self._http_wrappers: dict[str, Any] = {}  # Store HTTP wrappers per server
        self._mcp_servers: dict[str, Any] = {}  # Cache MCP servers
        self._server_http_config: dict[str, dict[str, Any]] = (
            {}
        )  # Track HTTP config per server
        self._agent_metadata: dict[str, dict[str, Any]] = (
            {}
        )  # Store agent metadata for updates

    async def process_agents(
        self, agents: dict[str, DecoratedFunction]
    ) -> dict[str, bool]:
        """
        Process all @mesh_agent decorated functions.

        Args:
            agents: Dictionary of function_name -> DecoratedFunction

        Returns:
            Dictionary of function_name -> success_status
        """
        results = {}

        for func_name, decorated_func in agents.items():
            try:
                success = await self.process_single_agent(func_name, decorated_func)
                results[func_name] = success

                if success:
                    # Don't mark as processed here - let process_single_agent handle it
                    agent_name = decorated_func.metadata.get("agent_name", func_name)
                    self.logger.debug(
                        f"Successfully processed multi-tool agent: {agent_name}"
                    )
                else:
                    self.logger.warning(f"Failed to process agent: {func_name}")

            except Exception as e:
                self.logger.error(f"Error processing agent {func_name}: {e}")
                results[func_name] = False

        return results

    async def process_single_agent(
        self, func_name: str, decorated_func: DecoratedFunction
    ) -> bool:
        """
        Process a single @mesh_agent decorated function.

        Args:
            func_name: Name of the function
            decorated_func: DecoratedFunction with metadata

        Returns:
            True if processing succeeded, False otherwise
        """
        try:
            metadata = decorated_func.metadata
            agent_name = metadata.get("agent_name", func_name)

            # Skip if already processed
            if agent_name in self._processed_agents:
                self.logger.debug(f"Agent {agent_name} already processed, skipping")
                return True

            # Build registration request
            registration_data: dict[str, Any] = self._build_registration_data(
                func_name, metadata
            )

            self.logger.debug(
                f"🎯🎯🎯 ABOUT TO REGISTER {func_name} WITH MESH REGISTRY 🎯🎯🎯"
            )

            # Store the metadata BEFORE processing (needed for HTTP wrapper updates)
            # Use agent_name as key for consistency with heartbeat
            stored_metadata = metadata.copy()
            stored_metadata["function_name"] = (
                func_name  # Store function name for later reference
            )
            self._agent_metadata[agent_name] = stored_metadata

            # Register with mesh registry
            response = await self._register_with_mesh_registry(registration_data)

            if response and response.get("status") == "success":
                self.logger.info(
                    f"🎉 Agent {agent_name} registered successfully with mesh registry"
                )

                # Mark as successfully processed
                self._processed_agents[agent_name] = True

                # Set up dependency injection for the function
                await self._setup_dependency_injection(decorated_func, response)

                # Check if HTTP wrapper should be enabled
                http_enabled: bool = self._should_enable_http(metadata)
                self.logger.debug(
                    f"🔍 Checking HTTP for {func_name}: enable_http={metadata.get('enable_http')}, should_enable={http_enabled}"
                )
                if http_enabled:
                    self.logger.debug(
                        f"🌐 HTTP wrapper should be enabled for {func_name}"
                    )
                    await self._setup_http_wrapper(func_name, decorated_func)
                else:
                    self.logger.debug(
                        f"📡 HTTP wrapper not enabled for {func_name} (enable_http={metadata.get('enable_http', False)})"
                    )
            else:
                self.logger.warning(
                    f"⚠️  Initial registration failed for {func_name}, will retry via heartbeat monitor"
                )
                # Don't mark as processed - will retry in health monitor

            # ALWAYS start health monitoring regardless of registration success
            # This allows agents to work standalone and connect when registry comes online
            health_interval = metadata.get("health_interval", 30)
            self.logger.debug(
                f"💓💓💓 Starting heartbeat monitoring for {func_name} with interval {health_interval}s"
            )

            # Create and start the health monitoring task
            # The health monitor will handle registration retries if needed
            # Use the agent_id from registration_data to ensure consistency
            agent_id = registration_data["agent_id"]
            task = asyncio.create_task(
                self._health_monitor(
                    agent_id, metadata, health_interval, registration_data
                )
            )
            self._health_tasks[agent_name] = task

            # Return True even if registration failed - agent can work standalone
            return True

        except Exception as e:
            self.logger.error(f"Error processing agent {func_name}: {e}")
            return False

    def _build_registration_data(
        self, func_name: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Transform decorator metadata into registration format.

        Args:
            func_name: Name of the function
            metadata: Decorator metadata

        Returns:
            Registration data for mesh registry
        """
        # Build capabilities list
        capabilities = []
        if metadata.get("capabilities"):
            for cap_name in metadata["capabilities"]:
                capability = {
                    "name": cap_name,
                    "version": metadata.get("version", "1.0.0"),
                    "description": metadata.get(
                        "description", f"Capability: {cap_name}"
                    ),
                    "tags": metadata.get("tags", []),
                    "parameters": {},  # Will be populated from function signature
                    "performance_metrics": metadata.get("performance_profile", {}),
                    "security_level": "standard",  # Default security level
                    "resource_requirements": metadata.get("resource_requirements", {}),
                    "metadata": {
                        "function_name": func_name,
                        "decorator_type": "mesh_agent",
                    },
                }
                capabilities.append(capability)

        # Determine agent name and endpoint
        agent_name = metadata.get("agent_name", func_name)
        agent_endpoint = metadata.get("endpoint")

        # For MCP stdio agents, don't set an HTTP endpoint yet
        # It will be updated when the HTTP wrapper is created
        if not agent_endpoint or not agent_endpoint.startswith(("http://", "https://")):
            agent_endpoint = f"stdio://{agent_name}"

        # Build full registration data
        registration_data = {
            "agent_id": agent_name,
            "metadata": {
                "name": agent_name,
                "agent_type": "mcp_agent",  # Correct enum value per OpenAPI spec
                "namespace": "default",
                "endpoint": agent_endpoint,
                "capabilities": capabilities,
                "dependencies": metadata.get("dependencies", []),
                "health_interval": metadata.get("health_interval", 30),
                "security_context": metadata.get("security_context"),
                "tags": metadata.get("tags", []),
                "version": metadata.get("version", "1.0.0"),
                "description": metadata.get("description"),
                "timeout_threshold": metadata.get(
                    "timeout", 30
                ),  # Map to correct field name
                "eviction_threshold": metadata.get("eviction_threshold", 120),
                # Remove invalid fields: retry_attempts, enable_caching, fallback_mode,
                # performance_profile, resource_requirements, nested metadata
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return registration_data

    async def _register_with_mesh_registry(
        self, registration_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Register agent with the mesh registry service.

        Args:
            registration_data: Registration data

        Returns:
            Registry response or None if failed
        """
        try:
            # Use the properly formatted registration method instead of generic post
            agent_id = registration_data["agent_id"]
            metadata = registration_data["metadata"]

            # Create proper registration payload for REST API (following OpenAPI schema)
            registration_payload = {
                "agent_id": agent_id,
                "metadata": {
                    "name": metadata["name"],
                    "agent_type": "mcp_agent",  # Required: Type of agent
                    "namespace": "default",  # Required: Agent namespace
                    "endpoint": metadata["endpoint"],
                    "capabilities": metadata["capabilities"],
                    "dependencies": metadata.get("dependencies", []),
                    "health_interval": metadata.get("health_interval", 30),
                    "security_context": metadata.get("security_context"),
                    "tags": metadata.get("tags", []),
                    "version": metadata.get("version", "1.0.0"),
                    "description": metadata.get("description"),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Call the registration endpoint directly
            response = await self.registry_client.post(
                "/agents/register", registration_payload
            )

            if (
                response
                and hasattr(response, "status_code")
                and response.status_code == 201
            ):
                response_data = (
                    await response.json() if hasattr(response, "json") else {}
                )
                return {
                    "status": "success",
                    "agent_id": agent_id,
                    "response": response_data,
                }
            else:
                self.logger.error("Registry registration failed")
                return None

        except Exception as e:
            self.logger.error(f"Error registering with mesh registry: {e}")
            return None

    async def _setup_dependency_injection(
        self,
        decorated_func: DecoratedFunction,
        registry_response: dict[str, Any] | None = None,
    ) -> None:
        """
        Set up dependency injection for the decorated function.

        This is where the actual dependency injection magic happens.
        The function will be enhanced to automatically receive dependencies
        when they become available in the mesh.

        Args:
            decorated_func: DecoratedFunction to enhance
            registry_response: Optional registry response containing dependencies_resolved
        """
        metadata = decorated_func.metadata
        dependencies = metadata.get("dependencies", [])

        if not dependencies:
            self.logger.debug(f"No dependencies for {decorated_func.function.__name__}")
            return

        self.logger.info(
            f"🔧 Setting up dependency injection for {decorated_func.function.__name__} "
            f"with dependencies: {dependencies}"
        )

        # Get the dependency injector
        try:
            from .dependency_injector import get_global_injector

            injector = get_global_injector()

            # Process dependencies_resolved from registry response
            if registry_response and "dependencies_resolved" in registry_response:
                dependencies_resolved = registry_response.get(
                    "dependencies_resolved", {}
                )

                for dep_name in dependencies:
                    dep_info = dependencies_resolved.get(dep_name)

                    if dep_info is None:
                        self.logger.warning(
                            f"⚠️  No healthy provider found for dependency '{dep_name}'"
                        )
                        # Unregister if previously registered
                        await injector.unregister_dependency(dep_name)
                        continue

                    # Create proxy using endpoint from registry
                    try:
                        endpoint = dep_info.get("endpoint", "")
                        self.logger.debug(
                            f"Creating proxy for '{dep_name}' using endpoint: {endpoint}"
                        )

                        # Check if this is an HTTP endpoint
                        if endpoint.startswith("http://") or endpoint.startswith(
                            "https://"
                        ):
                            # Create HTTP-based proxy
                            proxy = await self._create_http_proxy(dep_name, dep_info)
                        else:
                            # Create stdio-based proxy (existing code)
                            proxy = self._create_stdio_proxy(dep_name, dep_info)

                        # Register with injector
                        await injector.register_dependency(dep_name, proxy)
                        self.logger.info(
                            f"🔗 Successfully registered proxy for dependency '{dep_name}'"
                        )

                    except Exception as e:
                        self.logger.error(
                            f"Failed to create proxy for dependency '{dep_name}': {e}"
                        )
                        await injector.unregister_dependency(dep_name)

            # Add markers to the function
            decorated_func.function._mesh_processor_enhanced = True
            decorated_func.function._mesh_processor_dependencies = dependencies

            # Store the resolved dependencies for comparison in heartbeat
            if registry_response and "dependencies_resolved" in registry_response:
                func_name = decorated_func.function.__name__
                agent_name = metadata.get("agent_name", func_name)
                self._last_dependencies_resolved[agent_name] = dependencies_resolved

        except Exception as e:
            self.logger.error(
                f"Failed to setup dependency injection for {decorated_func.function.__name__}: {e}"
            )

    def _create_stdio_proxy(self, dep_name: str, dep_info: dict[str, Any]):
        """Create a stdio-based proxy (existing implementation)."""

        # Create a dynamic proxy using a factory function to capture variables properly
        def create_proxy(service_name, endpoint, agent_id, status):
            class DynamicServiceProxy:
                def __init__(self):
                    self._service_name = service_name
                    self._endpoint = endpoint
                    self._agent_id = agent_id
                    self._status = status
                    self._call_chain = []

                def __getattr__(self, name: str) -> Any:
                    """Intercept attribute access and return self for chaining."""
                    # Clone the proxy with extended call chain
                    new_proxy = DynamicServiceProxy()
                    new_proxy._call_chain = self._call_chain + [name]
                    return new_proxy

                def __call__(self, *args, **kwargs):
                    """Execute the remote call when proxy is invoked."""
                    method_name = (
                        ".".join(self._call_chain) if self._call_chain else "invoke"
                    )

                    # TODO: When HTTP transport is available, make actual HTTP call here
                    # For now with stdio, we can't make remote calls
                    raise RuntimeError(
                        f"Cannot invoke {self._service_name}.{method_name}() - "
                        f"stdio transport doesn't support HTTP calls to {self._endpoint}"
                    )

                def __repr__(self):
                    if self._call_chain:
                        return (
                            f"<{self._service_name}.{'.'.join(self._call_chain)} proxy>"
                        )
                    return f"<{self._service_name} proxy to {self._endpoint}>"

            return DynamicServiceProxy()

        return create_proxy(
            dep_name,
            dep_info.get("endpoint"),
            dep_info.get("agent_id"),
            dep_info.get("status"),
        )

    async def _create_http_proxy(self, dep_name: str, dep_info: dict[str, Any]):
        """Create an HTTP-based proxy that can make remote calls."""
        endpoint = dep_info.get("endpoint")
        agent_id = dep_info.get("agent_id")

        # For stdio-based agents, we can't make real HTTP calls
        # but we still create a proxy that indicates the dependency is available
        if not endpoint.startswith("http"):
            # Use the stdio proxy instead
            return self._create_stdio_proxy(dep_name, dep_info)

        # Import here to avoid circular imports
        from .sync_http_client import SyncHttpClient

        # Capture the logger for use in the proxy
        logger = self.logger

        class HttpServiceProxy:
            def __init__(self):
                self._service_name = dep_name
                self._endpoint = endpoint
                self._agent_id = agent_id
                self._call_chain = []
                self._client = SyncHttpClient(endpoint)
                self._logger = logger

            def __getattr__(self, name: str) -> Any:
                """Intercept attribute access and return self for chaining."""
                # Clone the proxy with extended call chain
                new_proxy = HttpServiceProxy()
                new_proxy._service_name = self._service_name
                new_proxy._endpoint = self._endpoint
                new_proxy._agent_id = self._agent_id
                new_proxy._call_chain = self._call_chain + [name]
                new_proxy._client = self._client  # Share the same client
                new_proxy._logger = self._logger
                return new_proxy

            def __call__(self, *args, **kwargs):
                """Execute the remote call via HTTP synchronously."""
                # Build the tool name from the call chain
                # For flat function style, the tool name is the full chain
                tool_name = "_".join([self._service_name] + self._call_chain)

                try:
                    # Make the synchronous HTTP call
                    result = self._client.call_tool(tool_name, kwargs or {})
                    return result
                except Exception as e:
                    self._logger.error(
                        f"HTTP call failed for {tool_name}: {e}",
                        extra={
                            "endpoint": self._endpoint,
                            "agent_id": self._agent_id,
                            "error": str(e),
                        },
                    )
                    # Re-raise to let the caller handle it
                    raise

            def __repr__(self):
                if self._call_chain:
                    return f"<{self._service_name}.{'.'.join(self._call_chain)} HTTP proxy>"
                return f"<{self._service_name} HTTP proxy to {self._endpoint}>"

            def __del__(self):
                """Clean up the HTTP client."""
                if hasattr(self, "_client"):
                    self._client.close()

        return HttpServiceProxy()

    async def _health_monitor(
        self,
        agent_name: str,
        metadata: dict[str, Any],
        interval: int,
        registration_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Background task for periodic health monitoring.

        Args:
            agent_name: Name of the agent
            metadata: Agent metadata
            interval: Health check interval in seconds
        """
        self.logger.debug(
            f"💓 Health monitor started for {agent_name} (interval: {interval}s)"
        )

        # Check if we need to retry registration
        needs_registration = agent_name not in self._processed_agents

        # Send initial heartbeat immediately (may fail if not registered)
        self.logger.debug(f"💓 Sending initial heartbeat for {agent_name}")
        heartbeat_success = await self._send_heartbeat(agent_name, metadata)

        # If heartbeat failed and we need registration, try to register
        if not heartbeat_success and needs_registration and registration_data:
            self.logger.info(
                f"🔄 Attempting to register {agent_name} via health monitor"
            )
            response = await self._register_with_mesh_registry(registration_data)
            if response and response.get("status") == "success":
                self.logger.info(f"✅ Successfully registered {agent_name} on retry!")
                self._processed_agents[agent_name] = True
                needs_registration = False

                # Set up dependency injection for late registration
                mesh_agents = DecoratorRegistry.get_mesh_agents()
                # Find the function by checking agent_name in metadata
                for func_name, decorated_func in mesh_agents.items():
                    if (
                        decorated_func.metadata.get("agent_name", func_name)
                        == agent_name
                    ):
                        await self._setup_dependency_injection(decorated_func, response)
                        break

        while True:
            try:
                await asyncio.sleep(interval)
                self.logger.debug(f"💓 Sending heartbeat for {agent_name}")
                heartbeat_success = await self._send_heartbeat(agent_name, metadata)

                # If not registered yet and heartbeat failed, retry registration
                if (
                    agent_name not in self._processed_agents
                    and not heartbeat_success
                    and registration_data
                ):
                    self.logger.info(
                        f"🔄 Registry appears to be back online, retrying registration for {agent_name}"
                    )
                    response = await self._register_with_mesh_registry(
                        registration_data
                    )
                    if response and response.get("status") == "success":
                        self.logger.info(
                            f"✅ Successfully registered {agent_name} after registry came back online!"
                        )
                        self._processed_agents[agent_name] = True

                        # Get the decorated function to set up dependency injection
                        mesh_agents = DecoratorRegistry.get_mesh_agents()
                        # Find the function by checking agent_name in metadata
                        for func_name, decorated_func in mesh_agents.items():
                            if (
                                decorated_func.metadata.get("agent_name", func_name)
                                == agent_name
                            ):
                                await self._setup_dependency_injection(
                                    decorated_func, response
                                )
                                break

            except asyncio.CancelledError:
                self.logger.info(f"Health monitor cancelled for {agent_name}")
                break
            except Exception as e:
                self.logger.error(f"Error in health monitor for {agent_name}: {e}")
                # Continue monitoring even on errors

    async def _send_heartbeat(self, agent_name: str, metadata: dict[str, Any]) -> bool:
        """Send a heartbeat to the registry and handle dependency updates.

        Returns:
            True if heartbeat was sent successfully, False otherwise
        """
        try:
            # Use the latest metadata which may have been updated with HTTP endpoint
            current_metadata = self._agent_metadata.get(agent_name, metadata)

            health_status = HealthStatus(
                agent_name=agent_name,
                status=HealthStatusType.HEALTHY,
                capabilities=current_metadata.get("capabilities", []),
                timestamp=datetime.now(timezone.utc),
                version=current_metadata.get("version", "1.0.0"),
                metadata=current_metadata,
            )

            self.logger.debug(f"💗 Sending heartbeat for {agent_name} to registry")
            self.logger.debug(
                f"   Endpoint in metadata: {current_metadata.get('endpoint', 'NOT SET')}"
            )
            self.logger.debug(
                f"   Transport in metadata: {current_metadata.get('transport', 'NOT SET')}"
            )

            # Get the full response with dependencies_resolved
            response = await self.registry_client.send_heartbeat_with_response(
                health_status
            )

            if response and response.get("status") == "success":
                self.logger.debug(f"💚 Heartbeat sent successfully for {agent_name}")

                # Check if dependencies have changed
                if "dependencies_resolved" in response:
                    current_deps = response.get("dependencies_resolved", {})
                    last_deps = self._last_dependencies_resolved.get(agent_name, {})

                    if current_deps != last_deps:
                        self.logger.debug(
                            f"🔄 Dependencies changed for {agent_name}, updating proxies..."
                        )

                        # Get the decorated function to update dependency injection
                        mesh_agents = DecoratorRegistry.get_mesh_agents()
                        # Find the function by checking agent_name in metadata
                        found = False
                        for func_name, decorated_func in mesh_agents.items():
                            if (
                                decorated_func.metadata.get("agent_name", func_name)
                                == agent_name
                            ):
                                await self._setup_dependency_injection(
                                    decorated_func, response
                                )
                                found = True
                                break
                        if not found:
                            self.logger.warning(
                                f"Could not find decorated function for {agent_name}"
                            )

                return True
            else:
                self.logger.error(f"💔 Failed to send heartbeat for {agent_name}")
                return False
        except Exception as e:
            self.logger.error(f"💔 Error sending heartbeat for {agent_name}: {e}")
            return False

    def _should_enable_http(self, metadata: dict[str, Any]) -> bool:
        """Determine if HTTP wrapper should be enabled."""
        # Explicit enable
        if metadata.get("enable_http"):
            return True

        # Auto-detect container environment
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            return True

        return os.environ.get("MCP_MESH_HTTP_ENABLED", "").lower() == "true"

    async def _setup_http_wrapper(
        self, func_name: str, decorated_func: DecoratedFunction
    ):
        """Set up HTTP wrapper for the function."""
        try:
            from .http_wrapper import HttpConfig, HttpMcpWrapper

            self.logger.debug(f"🔍 Looking for MCP server for function {func_name}")

            # Get or create MCP server for this function
            mcp_server = self._get_mcp_server_for_function(func_name, decorated_func)
            if not mcp_server:
                self.logger.warning(
                    f"❌ Could not get MCP server for {func_name}, skipping HTTP wrapper"
                )
                return

            self.logger.debug(
                f"✅ Found MCP server '{mcp_server.name}' for function {func_name}"
            )

            server_name = mcp_server.name
            metadata = decorated_func.metadata
            agent_name = metadata.get("agent_name", func_name)

            # Check if we already have an HTTP wrapper for this server
            if server_name in self._http_wrappers:
                # Reuse existing wrapper
                wrapper = self._http_wrappers[server_name]
                http_endpoint = wrapper.get_endpoint()
                self.logger.debug(
                    f"♻️  Reusing existing HTTP wrapper for server '{server_name}' at {http_endpoint}"
                )
                self.logger.debug(
                    f"📍 Function {func_name} is accessible via existing HTTP endpoint:"
                )
                self.logger.debug(
                    f'   Call function: curl -X POST {http_endpoint}/mcp -H \'Content-Type: application/json\' -d \'{{"method": "tools/call", "params": {{"name": "{func_name}", "arguments": {{}}}}}}\''
                )

                # Update registration with HTTP endpoint for this function
                await self._update_registration_with_http(agent_name, http_endpoint)
                return

            # First HTTP-enabled function for this server - create new wrapper
            self.logger.debug(
                f"🆕 Creating new HTTP wrapper for server '{server_name}'"
            )

            # Create HTTP wrapper config
            config = HttpConfig(
                host=metadata.get("http_host", "0.0.0.0"),
                port=metadata.get("http_port", 0),  # 0 = auto-assign
            )

            # Create and start HTTP wrapper
            wrapper = HttpMcpWrapper(mcp_server, config)
            await wrapper.setup()
            await wrapper.start()

            # Store wrapper for lifecycle management (by server name, not function name)
            self._http_wrappers[server_name] = wrapper

            # Update registration with HTTP endpoint for all functions in this server
            http_endpoint = wrapper.get_endpoint()
            await self._update_all_server_functions_with_http(
                server_name, http_endpoint
            )

            self.logger.debug(
                f"🌐 HTTP wrapper started for server '{server_name}' at {http_endpoint}"
            )
            self.logger.debug(
                f"📍 All functions in server '{server_name}' are now accessible via HTTP:"
            )
            self.logger.debug(f"   Health check: curl {http_endpoint}/health")
            self.logger.debug(f"   Mesh info: curl {http_endpoint}/mesh/info")
            self.logger.debug(
                f"   List tools: curl -X POST {http_endpoint}/mcp -H 'Content-Type: application/json' -d '{{\"method\": \"tools/list\"}}'"
            )
            self.logger.debug(
                f'   Call {func_name}: curl -X POST {http_endpoint}/mcp -H \'Content-Type: application/json\' -d \'{{"method": "tools/call", "params": {{"name": "{func_name}", "arguments": {{}}}}}}\''
            )

        except Exception as e:
            self.logger.error(f"Failed to set up HTTP wrapper for {func_name}: {e}")

    def _get_mcp_server_for_function(
        self, func_name: str, decorated_func: DecoratedFunction
    ):
        """Get or create the MCP server instance for a function."""
        # Check if we already have a server for this function
        if func_name in self._mcp_servers:
            return self._mcp_servers[func_name]

        # Try to get from fastmcp integration tracking
        from .fastmcp_integration import get_server_for_function

        server = get_server_for_function(func_name)
        if server:
            self._mcp_servers[func_name] = server
            return server

        # Try to find the MCP server from the function
        # This assumes the function has been decorated with @server.tool()
        func = decorated_func.function

        # Look for FastMCP server in function attributes or module
        import inspect

        # Check if function has a reference to its server
        if hasattr(func, "_mcp_server"):
            self._mcp_servers[func_name] = func._mcp_server
            return func._mcp_server

        # Try to find server in the module
        module = inspect.getmodule(func)
        if module:
            for _name, obj in inspect.getmembers(module):
                if hasattr(obj, "__class__") and obj.__class__.__name__ == "FastMCP":
                    # Found a FastMCP server in the module
                    self._mcp_servers[func_name] = obj
                    return obj

        # If we can't find an existing server, we can't create HTTP wrapper
        self.logger.warning(f"Could not find MCP server for function {func_name}")
        return None

    async def _update_registration_with_http(self, agent_name: str, http_endpoint: str):
        """Update agent registration with HTTP endpoint information."""
        try:
            # The registry doesn't have a PUT endpoint for updates
            # Instead, we need to re-register with the new HTTP endpoint
            # or let the next heartbeat include the updated endpoint

            # Update the stored registration data for this agent
            if agent_name in self._agent_metadata:
                self._agent_metadata[agent_name]["endpoint"] = http_endpoint
                self._agent_metadata[agent_name]["transport"] = ["stdio", "http"]

                # The next heartbeat will automatically include the updated endpoint
                self.logger.debug(
                    f"✅ Updated local registration data for {agent_name} with HTTP endpoint {http_endpoint}"
                )
                self.logger.debug(
                    "📍 HTTP endpoint will be propagated to registry on next heartbeat"
                )

                # Send an immediate heartbeat to update the registry
                self.logger.debug(
                    "💗 Sending immediate heartbeat to update registry with HTTP endpoint"
                )
                await self._send_heartbeat(agent_name, self._agent_metadata[agent_name])
            else:
                self.logger.warning(
                    f"Agent {agent_name} not found in metadata, cannot update HTTP endpoint"
                )
                self.logger.warning(
                    f"Available agents in metadata: {list(self._agent_metadata.keys())}"
                )

        except Exception as e:
            self.logger.error(f"Error updating registration with HTTP endpoint: {e}")

    async def _update_all_server_functions_with_http(
        self, server_name: str, http_endpoint: str
    ):
        """Update all functions from a server with the HTTP endpoint."""
        try:
            # Find all functions that belong to this server
            updated_count = 0
            for agent_name, metadata in self._agent_metadata.items():
                # Get the actual function name from the metadata
                func_name = metadata.get("function_name", agent_name)

                # Check if this function belongs to the server
                # We can check by seeing if they share the same MCP server instance
                if func_name in self._mcp_servers:
                    func_server = self._mcp_servers[func_name]
                    if hasattr(func_server, "name") and func_server.name == server_name:
                        # Update this function's metadata
                        metadata["endpoint"] = http_endpoint
                        metadata["transport"] = ["stdio", "http"]
                        updated_count += 1

                        self.logger.debug(
                            f"✅ Updated {agent_name} (function: {func_name}) with HTTP endpoint {http_endpoint}"
                        )

                        # Send immediate heartbeat for this agent
                        await self._send_heartbeat(agent_name, metadata)

            if updated_count > 0:
                self.logger.debug(
                    f"📍 Updated {updated_count} functions from server '{server_name}' with HTTP endpoint"
                )
            else:
                self.logger.warning(
                    f"No functions found for server '{server_name}' to update with HTTP endpoint"
                )
                self.logger.warning(
                    f"Current _agent_metadata: {list(self._agent_metadata.keys())}"
                )
                self.logger.warning(
                    f"Current _mcp_servers: {list(self._mcp_servers.keys())}"
                )

                # Let's also check if we can find functions by looking at all metadata
                for func_name, _metadata in self._agent_metadata.items():
                    self.logger.warning(
                        f"  Function {func_name}: has server? {func_name in self._mcp_servers}"
                    )

        except Exception as e:
            self.logger.error(
                f"Error updating server functions with HTTP endpoint: {e}"
            )


class DecoratorProcessor:
    """
    Main processor that coordinates all decorator processing.

    This class reads from DecoratorRegistry and delegates to specialized
    processors for each decorator type.
    """

    def __init__(self, registry_url: str | None = None):
        self.registry_url = registry_url or self._get_registry_url_from_env()
        self.registry_client = RegistryClient(self.registry_url)
        self.logger = logging.getLogger(__name__)

        # Specialized processors
        self.mesh_agent_processor = MeshAgentProcessor(self.registry_client)

        # Track processing state
        self._processing_complete = False
        self._last_processed_count = 0
        self._background_task = None

    def _get_registry_url_from_env(self) -> str:
        """Get registry URL from environment variables."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8000")

    def start(self) -> None:
        """Start the decorator processor (background processing)."""
        # Start background task to process decorators
        if self._background_task is None:
            # Get or create event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop, create one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Schedule the background task
            self._background_task = loop.create_task(self._background_processing())

    def register_function(self, func: Any, metadata: dict[str, Any]) -> None:
        """Register a function with its metadata for processing."""
        # Store function registration for later processing
        func_name = func.__name__
        self.logger.debug(f"Registered function {func_name} with mesh capabilities")

        # Try to process immediately if possible
        try:
            # Check if we have an event loop running
            loop = asyncio.get_running_loop()
            # Schedule immediate processing
            loop.create_task(self._process_single_registration())
        except RuntimeError:
            # No event loop running - will be processed by background task when started
            pass

    async def _process_single_registration(self) -> None:
        """Process a single registration immediately."""
        try:
            await self.process_all_decorators()
        except Exception as e:
            self.logger.error(f"Error in immediate processing: {e}")

    async def _background_processing(self) -> None:
        """Background task to periodically process decorators."""
        while True:
            try:
                await self.process_all_decorators()
                await asyncio.sleep(30)  # Process every 30 seconds
            except Exception as e:
                self.logger.error(f"Error in background processing: {e}")
                await asyncio.sleep(5)  # Retry after 5 seconds on error

    async def process_all_decorators(self) -> dict[str, Any]:
        """
        Process all decorators in DecoratorRegistry.

        Returns:
            Processing results summary
        """
        self.logger.debug("Starting decorator processing...")

        results = {
            "mesh_agents": {},
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "registry_url": self.registry_url,
            "total_processed": 0,
            "total_successful": 0,
            "total_failed": 0,
        }

        try:
            # Process @mesh_agent decorators
            mesh_agents = DecoratorRegistry.get_mesh_agents()
            if mesh_agents:
                self.logger.debug(
                    f"Processing {len(mesh_agents)} @mesh_agent decorators"
                )
                agent_results = await self.mesh_agent_processor.process_agents(
                    mesh_agents
                )
                results["mesh_agents"] = agent_results

                # Update counters
                results["total_processed"] += len(agent_results)
                results["total_successful"] += sum(
                    1 for success in agent_results.values() if success
                )
                results["total_failed"] += sum(
                    1 for success in agent_results.values() if not success
                )

            # TODO: Add processing for other decorator types when implemented
            # results["mesh_tools"] = await self.mesh_tool_processor.process_tools(...)
            # results["mesh_resources"] = await self.mesh_resource_processor.process_resources(...)

            self._processing_complete = True
            self._last_processed_count = results["total_processed"]

            self.logger.debug(
                f"Decorator processing complete: {results['total_successful']}/{results['total_processed']} successful"
            )

        except Exception as e:
            self.logger.error(f"Error during decorator processing: {e}")
            results["error"] = str(e)

        return results

    async def cleanup(self) -> None:
        """Clean up resources, especially the registry client."""
        # Stop all HTTP wrappers
        if (
            hasattr(self, "mesh_agent_processor")
            and self.mesh_agent_processor._http_wrappers
        ):
            self.logger.debug(
                f"Stopping {len(self.mesh_agent_processor._http_wrappers)} HTTP wrappers"
            )
            for (
                server_name,
                wrapper,
            ) in self.mesh_agent_processor._http_wrappers.items():
                try:
                    await wrapper.stop()
                    self.logger.debug(
                        f"Stopped HTTP wrapper for server '{server_name}'"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error stopping HTTP wrapper for server '{server_name}': {e}"
                    )
            self.mesh_agent_processor._http_wrappers.clear()

        # Cancel all health monitoring tasks
        if (
            hasattr(self, "mesh_agent_processor")
            and self.mesh_agent_processor._health_tasks
        ):
            self.logger.debug(
                f"Cancelling {len(self.mesh_agent_processor._health_tasks)} health monitoring tasks"
            )
            for agent_name, task in self.mesh_agent_processor._health_tasks.items():
                if not task.done():
                    task.cancel()
                    self.logger.debug(f"Cancelled health monitoring for {agent_name}")

            # Wait for all tasks to complete cancellation with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *self.mesh_agent_processor._health_tasks.values(),
                        return_exceptions=True,
                    ),
                    timeout=5.0,  # 5 second timeout for cleanup
                )
            except asyncio.TimeoutError:
                self.logger.warning("Some health monitoring tasks did not stop in time")
            finally:
                self.mesh_agent_processor._health_tasks.clear()

        if self.registry_client:
            try:
                await self.registry_client.close()
                self.logger.debug("Registry client closed successfully")
            except Exception as e:
                self.logger.error(f"Error closing registry client: {e}")

    async def process_new_decorators(self) -> dict[str, Any]:
        """
        Process only new decorators since last processing.

        This is useful for incremental processing when new decorators
        are added at runtime.

        Returns:
            Processing results for new decorators only
        """
        # For now, just process all decorators
        # TODO: Implement incremental processing
        return await self.process_all_decorators()

    def get_processing_stats(self) -> dict[str, Any]:
        """Get current processing statistics."""
        decorator_stats = DecoratorRegistry.get_stats()

        return {
            "registry_stats": decorator_stats,
            "processing_complete": self._processing_complete,
            "last_processed_count": self._last_processed_count,
            "registry_url": self.registry_url,
            "mesh_agent_processor_stats": {
                "processed_agents": len(self.mesh_agent_processor._processed_agents)
            },
        }


# Convenience functions for external use
async def process_mesh_agents(registry_url: str | None = None) -> dict[str, Any]:
    """
    Convenience function to process all @mesh_agent decorators.

    Args:
        registry_url: Optional registry URL (defaults to environment)

    Returns:
        Processing results
    """
    processor = DecoratorProcessor(registry_url)
    return await processor.process_all_decorators()


def create_decorator_processor(
    registry_url: str | None = None,
) -> DecoratorProcessor:
    """
    Factory function to create a DecoratorProcessor.

    Args:
        registry_url: Optional registry URL (defaults to environment)

    Returns:
        Configured DecoratorProcessor instance
    """
    return DecoratorProcessor(registry_url)
