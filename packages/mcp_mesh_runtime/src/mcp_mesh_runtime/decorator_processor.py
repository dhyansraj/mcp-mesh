"""
DecoratorProcessor - Processes decorator metadata and registers with mesh registry.

This module reads decorator metadata from DecoratorRegistry (in mcp_mesh package)
and performs the actual registration with the mesh registry service. It handles
the heavy lifting of transforming decorator metadata into proper service registrations.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from mcp_mesh import DecoratedFunction, DecoratorRegistry

from .shared.registry_client import RegistryClient


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
                    self._processed_agents[func_name] = True
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

            # Register with mesh registry
            response = await self._register_with_mesh_registry(registration_data)

            if response and response.get("status") == "success":
                self.logger.info(
                    f"Agent {func_name} registered successfully with mesh registry"
                )

                # Set up dependency injection for the function
                await self._setup_dependency_injection(decorated_func)

                return True
            else:
                self.logger.error(f"Failed to register agent {func_name}: {response}")
                return False

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
        self, decorated_func: DecoratedFunction
    ) -> None:
        """
        Set up dependency injection for the decorated function.

        This is where the actual dependency injection magic happens.
        The function will be enhanced to automatically receive dependencies
        when they become available in the mesh.

        Args:
            decorated_func: DecoratedFunction to enhance
        """
        # For now, we'll add the dependency injection setup hook
        # This is where we would integrate with the existing dependency injection system

        metadata = decorated_func.metadata
        dependencies = metadata.get("dependencies", [])

        if dependencies:
            self.logger.info(
                f"Setting up dependency injection for {decorated_func.function.__name__} "
                f"with dependencies: {dependencies}"
            )

            # Add a marker to the function indicating it's been processed
            decorated_func.function._mesh_processor_enhanced = True
            decorated_func.function._mesh_processor_dependencies = dependencies

            # TODO: Integrate with existing dependency injection system
            # This would involve:
            # 1. Setting up parameter injection hooks
            # 2. Monitoring registry for dependency availability
            # 3. Updating function signatures dynamically
            # 4. Handling dependency lifecycle (add/remove)

        self.logger.debug(
            f"Dependency injection setup complete for {decorated_func.function.__name__}"
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

    def _get_registry_url_from_env(self) -> str:
        """Get registry URL from environment variables."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8080")

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
