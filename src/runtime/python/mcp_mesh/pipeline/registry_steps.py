"""
Registry communication steps for MCP Mesh pipeline.

Handles communication with the mesh registry service, including
heartbeat sending and dependency resolution.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from ..generated.mcp_mesh_registry_client.api_client import ApiClient
from ..generated.mcp_mesh_registry_client.configuration import Configuration
from ..shared.registry_client_wrapper import RegistryClientWrapper
from .pipeline import PipelineResult, PipelineStatus
from .steps import PipelineStep

logger = logging.getLogger(__name__)


class RegistryConnectionStep(PipelineStep):
    """
    Establishes connection to the mesh registry.

    Creates and configures the registry client for subsequent
    communication steps.
    """

    def __init__(self):
        super().__init__(
            name="registry-connection",
            required=True,
            description="Connect to mesh registry service",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Establish registry connection."""
        self.logger.debug("Establishing registry connection...")

        result = PipelineResult(message="Registry connection established")

        try:
            # Get registry URL
            registry_url = self._get_registry_url()

            # Create registry client configuration
            config = Configuration(host=registry_url)
            registry_client = ApiClient(config)

            # Create wrapper for type-safe operations
            registry_wrapper = RegistryClientWrapper(registry_client)

            # Store in context
            result.add_context("registry_url", registry_url)
            result.add_context("registry_client", registry_client)
            result.add_context("registry_wrapper", registry_wrapper)

            result.message = f"Connected to registry at {registry_url}"
            self.logger.info(f"🔗 Registry connection established: {registry_url}")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Registry connection failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Registry connection failed: {e}")

        return result

    def _get_registry_url(self) -> str:
        """Get registry URL from environment."""
        return os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8000")


class HeartbeatSendStep(PipelineStep):
    """
    Sends heartbeat to the mesh registry.

    Performs the actual registry communication using the prepared
    heartbeat data from previous steps.
    """

    def __init__(self, required: bool = True):
        super().__init__(
            name="heartbeat-send",
            required=required,
            description="Send heartbeat to mesh registry",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Send heartbeat to registry or print JSON in debug mode."""
        result = PipelineResult(message="Heartbeat processed successfully")

        try:
            # Get required context
            health_status = context.get("health_status")
            agent_id = context.get("agent_id", "unknown-agent")
            registration_data = context.get("registration_data")

            if not health_status:
                raise ValueError("Health status not available in context")

            # Build the complete heartbeat payload for debug logging
            heartbeat_payload = self._build_heartbeat_payload(
                agent_id, health_status, registration_data, context
            )

            # Debug: Log heartbeat payload that would be sent
            import json
            json_output = json.dumps(heartbeat_payload, indent=2, default=str)
            self.logger.debug(f"🔍 Heartbeat message to send:\n{json_output}")

            # Send actual HTTP request to registry
            registry_wrapper = context.get("registry_wrapper")

            if not registry_wrapper:
                # If no registry wrapper, just log the payload and mark as successful
                self.logger.info(f"⚠️ No registry connection - would send heartbeat for agent '{agent_id}'")
                result.add_context("heartbeat_response", {"status": "no_registry", "logged": True})
                result.add_context("dependencies_resolved", {})
                result.message = f"Heartbeat logged for agent '{agent_id}' (no registry)"
                return result

            self.logger.info(f"💓 Sending heartbeat for agent '{agent_id}'...")

            response = (
                await registry_wrapper.send_heartbeat_with_dependency_resolution(
                    health_status
                )
            )

            if response:
                # Store response data
                result.add_context("heartbeat_response", response)
                result.add_context(
                    "dependencies_resolved",
                    response.get("dependencies_resolved", {}),
                )

                result.message = (
                    f"Heartbeat sent successfully for agent '{agent_id}'"
                )
                self.logger.info(f"💚 Heartbeat successful for agent '{agent_id}'")

                # Log dependency resolution info
                deps_resolved = response.get("dependencies_resolved", {})
                if deps_resolved:
                    self.logger.info(
                        f"🔗 Dependencies resolved: {len(deps_resolved)} items"
                    )

            else:
                result.status = PipelineStatus.FAILED
                result.message = "Heartbeat failed - no response from registry"
                self.logger.error("💔 Heartbeat failed - no response")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Heartbeat processing failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Heartbeat processing failed: {e}")

        return result

    def _build_heartbeat_payload(
        self,
        agent_id: str,
        health_status: Any,
        registration_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the complete heartbeat payload for display."""
        # Convert health_status to dict if it's a model object
        if hasattr(health_status, "__dict__"):
            health_dict = {
                "agent_name": getattr(health_status, "agent_name", agent_id),
                "status": (
                    getattr(health_status, "status", "healthy").value
                    if hasattr(getattr(health_status, "status", "healthy"), "value")
                    else str(getattr(health_status, "status", "healthy"))
                ),
                "capabilities": getattr(health_status, "capabilities", []),
                "timestamp": (
                    getattr(health_status, "timestamp", "").isoformat()
                    if hasattr(getattr(health_status, "timestamp", ""), "isoformat")
                    else str(getattr(health_status, "timestamp", ""))
                ),
                "version": getattr(health_status, "version", "1.0.0"),
                "metadata": getattr(health_status, "metadata", {}),
            }
        else:
            health_dict = health_status

        # Get additional context
        tools_list = context.get("tools_list", [])
        agent_config = context.get("agent_config", {})

        # Build comprehensive payload
        payload = {
            "agent_id": agent_id,
            "health_status": health_dict,
            "tools": tools_list,
            "agent_config": agent_config,
            "registration_data": registration_data or {},
            "debug_info": {
                "tool_count": len(tools_list),
                "pipeline_context_keys": list(context.keys()),
                "mode": "debug_print",
            },
        }

        return payload


class DependencyResolutionStep(PipelineStep):
    """
    Processes dependency resolution from registry response.

    Takes the dependencies_resolved data from the heartbeat response
    and prepares it for dependency injection (simplified for now).
    """

    def __init__(self):
        super().__init__(
            name="dependency-resolution",
            required=False,  # Optional - can work without dependencies
            description="Process dependency resolution from registry",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Process dependency resolution."""
        self.logger.debug("Processing dependency resolution...")

        result = PipelineResult(message="Dependency resolution processed")

        try:
            # Get heartbeat response and registry wrapper
            heartbeat_response = context.get("heartbeat_response", {})
            registry_wrapper = context.get("registry_wrapper")

            if not heartbeat_response or not registry_wrapper:
                result.status = PipelineStatus.SUCCESS
                result.message = "No heartbeat response or registry wrapper - completed successfully"
                self.logger.info("ℹ️ No heartbeat response to process - this is normal")
                return result

            # Use existing parse_tool_dependencies method from registry wrapper
            dependencies_resolved = registry_wrapper.parse_tool_dependencies(heartbeat_response)

            if not dependencies_resolved:
                result.status = PipelineStatus.SUCCESS
                result.message = "No dependencies to resolve - completed successfully"
                self.logger.info("ℹ️ No dependencies to resolve - this is normal")
                return result

            # Process each resolved dependency using existing method
            processed_deps = {}
            for function_name, dependency_list in dependencies_resolved.items():
                if isinstance(dependency_list, list):
                    for dep_resolution in dependency_list:
                        if isinstance(dep_resolution, dict) and "capability" in dep_resolution:
                            capability = dep_resolution["capability"]
                            processed_deps[capability] = self._process_dependency(capability, dep_resolution)
                            self.logger.debug(
                                f"Processed dependency '{capability}' for function '{function_name}': "
                                f"{dep_resolution.get('endpoint', 'no-endpoint')}"
                            )

            # Store processed dependencies
            result.add_context("processed_dependencies", processed_deps)
            result.add_context("dependency_count", len(processed_deps))

            # Register dependencies with the global injector
            await self._register_dependencies_with_injector(processed_deps)

            result.message = f"Processed {len(processed_deps)} dependencies"
            self.logger.info(
                f"🔗 Dependency resolution completed: {len(processed_deps)} dependencies"
            )

            # Log dependency details
            for dep_name, dep_data in processed_deps.items():
                status = dep_data.get("status", "unknown")
                self.logger.debug(f"  - {dep_name}: {status}")

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Dependency resolution failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Dependency resolution failed: {e}")

        return result

    def _process_dependency(
        self, dep_name: str, dep_info: dict[str, Any]
    ) -> dict[str, Any]:
        """Process a single dependency."""
        # Simplified processing - just collect info for now
        # TODO: SIMPLIFICATION - Real proxy creation would happen here

        return {
            "name": dep_name,
            "status": dep_info.get("status", "unknown"),
            "agent_id": dep_info.get("agent_id"),
            "endpoint": dep_info.get("endpoint"),
            "function_name": dep_info.get("function_name"),
            "processed_at": "simplified_mode",  # TODO: Remove after simplification
        }

    async def _register_dependencies_with_injector(self, processed_deps: dict[str, Any]) -> None:
        """Register processed dependencies with the global dependency injector."""
        try:
            # Import here to avoid circular imports
            from ..engine.dependency_injector import get_global_injector
            from ..engine.sync_http_client import SyncHttpClient
            
            injector = get_global_injector()
            
            for capability, dep_data in processed_deps.items():
                if dep_data.get("status") == "available":
                    endpoint = dep_data.get("endpoint")
                    function_name = dep_data.get("function_name")
                    agent_id = dep_data.get("agent_id")
                    
                    if endpoint and function_name:
                        # Create HTTP client for the dependency  
                        http_client = SyncHttpClient(
                            base_url=endpoint
                        )
                        
                        # Create callable wrapper that knows which function to call
                        def create_callable_proxy(client, func_name):
                            def proxy_call():
                                try:
                                    result = client.call_tool(func_name, {})
                                    # Extract text from MCP result format
                                    if isinstance(result, dict) and "content" in result:
                                        content = result["content"]
                                        if content and isinstance(content[0], dict) and "text" in content[0]:
                                            return content[0]["text"]
                                    return str(result)
                                except Exception as e:
                                    self.logger.error(f"Failed to call {func_name}: {e}")
                                    raise
                            return proxy_call
                        
                        proxy = create_callable_proxy(http_client, function_name)
                        
                        # Register with injector
                        await injector.register_dependency(capability, proxy)
                        
                        self.logger.info(
                            f"🔌 Registered dependency '{capability}' -> {endpoint}/{function_name}"
                        )
                    else:
                        self.logger.warning(
                            f"⚠️ Cannot register dependency '{capability}': missing endpoint or function_name"
                        )
                else:
                    self.logger.warning(
                        f"⚠️ Skipping dependency '{capability}': status = {dep_data.get('status')}"
                    )
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to register dependencies with injector: {e}")
            # Don't raise - this is not critical for pipeline to continue
