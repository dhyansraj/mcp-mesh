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

from .registry_client import RegistryClient
from .shared.types import HealthStatus, HealthStatusType


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

    def __init__(self, registry_client: RegistryClient):
        self.registry_client = registry_client
        self.logger = logging.getLogger(__name__)
        self._processed_agents: dict[str, bool] = {}
        self._health_tasks: dict[str, asyncio.Task] = {}
        self._last_dependencies_resolved: dict[str, dict[str, Any]] = {}

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
                    self.logger.info(f"Successfully processed agent: {func_name}")
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
            # Skip if already processed
            if func_name in self._processed_agents:
                self.logger.debug(f"Agent {func_name} already processed, skipping")
                return True

            metadata = decorated_func.metadata

            # Build registration request
            registration_data = self._build_registration_data(func_name, metadata)

            self.logger.info(
                f"🎯🎯🎯 ABOUT TO REGISTER {func_name} WITH MESH REGISTRY 🎯🎯🎯"
            )

            # Register with mesh registry
            response = await self._register_with_mesh_registry(registration_data)

            if response and response.get("status") == "success":
                self.logger.info(
                    f"♥♥♥♥♥ CORRECT CODE! Agent {func_name} registered successfully with mesh registry ♥♥♥♥♥"
                )

                # Mark as successfully processed
                self._processed_agents[func_name] = True

                # Set up dependency injection for the function
                await self._setup_dependency_injection(decorated_func, response)
            else:
                self.logger.warning(
                    f"⚠️  Initial registration failed for {func_name}, will retry via heartbeat monitor"
                )
                # Don't mark as processed - will retry in health monitor

            # ALWAYS start health monitoring regardless of registration success
            # This allows agents to work standalone and connect when registry comes online
            health_interval = metadata.get("health_interval", 30)
            self.logger.info(
                f"💓💓💓 Starting heartbeat monitoring for {func_name} with interval {health_interval}s"
            )

            # Create and start the health monitoring task
            # The health monitor will handle registration retries if needed
            task = asyncio.create_task(
                self._health_monitor(
                    func_name, metadata, health_interval, registration_data
                )
            )
            self._health_tasks[func_name] = task

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

        # For MCP stdio agents, create a placeholder HTTP endpoint
        if not agent_endpoint or not agent_endpoint.startswith(("http://", "https://")):
            agent_endpoint = f"http://localhost:0/{agent_name}"

        # Build full registration data
        registration_data = {
            "agent_id": agent_name,
            "metadata": {
                "name": agent_name,
                "agent_type": "mesh_agent",
                "namespace": "default",
                "endpoint": agent_endpoint,
                "capabilities": capabilities,
                "dependencies": metadata.get("dependencies", []),
                "health_interval": metadata.get("health_interval", 30),
                "security_context": metadata.get("security_context"),
                "tags": metadata.get("tags", []),
                "version": metadata.get("version", "1.0.0"),
                "description": metadata.get("description"),
                "timeout": metadata.get("timeout", 30),
                "retry_attempts": metadata.get("retry_attempts", 3),
                "enable_caching": metadata.get("enable_caching", True),
                "fallback_mode": metadata.get("fallback_mode", True),
                "performance_profile": metadata.get("performance_profile", {}),
                "resource_requirements": metadata.get("resource_requirements", {}),
                "metadata": {
                    "function_name": func_name,
                    "decorator_type": "mesh_agent",
                    "registered_at": datetime.now(timezone.utc).isoformat(),
                    "processor_version": "1.0.0",
                },
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
            # Use the new /agents/register_with_metadata endpoint
            response = await self.registry_client.post(
                "/agents/register_with_metadata", json=registration_data
            )

            if response.status == 201:
                return await response.json()
            else:
                error_text = await response.text()
                self.logger.error(
                    f"Registry registration failed: {response.status} - {error_text}"
                )
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
            f"Setting up dependency injection for {decorated_func.function.__name__} "
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
                            f"No healthy provider found for dependency '{dep_name}'"
                        )
                        # Unregister if previously registered
                        await injector.unregister_dependency(dep_name)
                        continue

                    # Create proxy using endpoint from registry
                    try:
                        self.logger.info(
                            f"Creating proxy for '{dep_name}' using endpoint: {dep_info.get('endpoint')}"
                        )

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
                                        ".".join(self._call_chain)
                                        if self._call_chain
                                        else "invoke"
                                    )

                                    # TODO: When HTTP transport is available, make actual HTTP call here
                                    # For now with stdio, we can't make remote calls
                                    raise RuntimeError(
                                        f"Cannot invoke {self._service_name}.{method_name}() - "
                                        f"stdio transport doesn't support HTTP calls to {self._endpoint}"
                                    )

                                def __repr__(self):
                                    if self._call_chain:
                                        return f"<{self._service_name}.{'.'.join(self._call_chain)} proxy>"
                                    return f"<{self._service_name} proxy to {self._endpoint}>"

                            return DynamicServiceProxy()

                        proxy = create_proxy(
                            dep_name,
                            dep_info.get("endpoint"),
                            dep_info.get("agent_id"),
                            dep_info.get("status"),
                        )

                        # Register with injector
                        await injector.register_dependency(dep_name, proxy)
                        self.logger.info(
                            f"Successfully registered proxy for dependency '{dep_name}'"
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
                self._last_dependencies_resolved[func_name] = dependencies_resolved

        except Exception as e:
            self.logger.error(
                f"Failed to setup dependency injection for {decorated_func.function.__name__}: {e}"
            )

        self.logger.debug(
            f"Dependency injection setup complete for {decorated_func.function.__name__}"
        )

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
        self.logger.info(
            f"💓 Health monitor started for {agent_name} (interval: {interval}s)"
        )

        # Check if we need to retry registration
        needs_registration = agent_name not in self._processed_agents

        # Send initial heartbeat immediately (may fail if not registered)
        self.logger.info(f"💓 Sending initial heartbeat for {agent_name}")
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
                if agent_name in mesh_agents:
                    await self._setup_dependency_injection(
                        mesh_agents[agent_name], response
                    )

        while True:
            try:
                await asyncio.sleep(interval)
                self.logger.info(f"💓 Sending heartbeat for {agent_name}")
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
                        if agent_name in mesh_agents:
                            await self._setup_dependency_injection(
                                mesh_agents[agent_name], response
                            )

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
            health_status = HealthStatus(
                agent_name=agent_name,
                status=HealthStatusType.HEALTHY,
                capabilities=metadata.get("capabilities", []),
                timestamp=datetime.now(timezone.utc),
                version=metadata.get("version", "1.0.0"),
                metadata=metadata,
            )

            self.logger.info(f"💗 Sending heartbeat for {agent_name} to registry")

            # Get the full response with dependencies_resolved
            response = await self.registry_client.send_heartbeat_with_response(
                health_status
            )

            if response and response.get("status") == "success":
                self.logger.info(f"💚 Heartbeat sent successfully for {agent_name}")

                # Check if dependencies have changed
                if "dependencies_resolved" in response:
                    current_deps = response.get("dependencies_resolved", {})
                    last_deps = self._last_dependencies_resolved.get(agent_name, {})

                    if current_deps != last_deps:
                        self.logger.info(
                            f"🔄 Dependencies changed for {agent_name}, updating proxies..."
                        )

                        # Get the decorated function to update dependency injection
                        mesh_agents = DecoratorRegistry.get_mesh_agents()
                        if agent_name in mesh_agents:
                            await self._setup_dependency_injection(
                                mesh_agents[agent_name], response
                            )
                        else:
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
        self.logger.info(f"Registered function {func_name} with mesh capabilities")

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
        self.logger.info("Starting decorator processing...")

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
                self.logger.info(
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

            self.logger.info(
                f"Decorator processing complete: {results['total_successful']}/{results['total_processed']} successful"
            )

        except Exception as e:
            self.logger.error(f"Error during decorator processing: {e}")
            results["error"] = str(e)

        return results

    async def cleanup(self) -> None:
        """Clean up resources, especially the registry client."""
        # Cancel all health monitoring tasks
        if (
            hasattr(self, "mesh_agent_processor")
            and self.mesh_agent_processor._health_tasks
        ):
            self.logger.info(
                f"Cancelling {len(self.mesh_agent_processor._health_tasks)} health monitoring tasks"
            )
            for agent_name, task in self.mesh_agent_processor._health_tasks.items():
                if not task.done():
                    task.cancel()
                    self.logger.debug(f"Cancelled health monitoring for {agent_name}")

            # Wait for all tasks to complete cancellation
            await asyncio.gather(
                *self.mesh_agent_processor._health_tasks.values(),
                return_exceptions=True,
            )
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
