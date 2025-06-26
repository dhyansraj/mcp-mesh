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

            # Check if we're in debug mode
            debug_mode = os.getenv("MCP_MESH_DEBUG_MODE", "true").lower() == "true"

            if debug_mode:
                # Debug mode: print JSON and mark as successful
                self.logger.debug(
                    "Debug mode: printing heartbeat JSON instead of sending HTTP"
                )

                # Build the complete heartbeat payload
                heartbeat_payload = self._build_heartbeat_payload(
                    agent_id, health_status, registration_data, context
                )

                # Print the JSON message
                json_output = json.dumps(heartbeat_payload, indent=2, default=str)
                print(f"DEBUG: heartbeat message to send {json_output}")

                # Store mock response data
                result.add_context(
                    "heartbeat_response", {"status": "debug_mode", "printed": True}
                )
                result.add_context("dependencies_resolved", {})

                result.message = f"Debug: heartbeat JSON printed for agent '{agent_id}'"
                self.logger.info(
                    f"🎯 Debug mode: heartbeat JSON printed for agent '{agent_id}'"
                )

            else:
                # Production mode: send actual HTTP request
                registry_wrapper = context.get("registry_wrapper")

                if not registry_wrapper:
                    raise ValueError("Registry wrapper not available in context")

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
            dependencies_resolved = context.get("dependencies_resolved", {})
            mesh_tools = context.get("mesh_tools", {})

            if not dependencies_resolved:
                result.status = PipelineStatus.SKIPPED
                result.message = "No dependencies to resolve"
                self.logger.debug("ℹ️ No dependencies to resolve")
                return result

            # Process each resolved dependency
            processed_deps = {}
            for dep_name, dep_info in dependencies_resolved.items():
                processed_deps[dep_name] = self._process_dependency(dep_name, dep_info)

            # Store processed dependencies
            result.add_context("processed_dependencies", processed_deps)
            result.add_context("dependency_count", len(processed_deps))

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
