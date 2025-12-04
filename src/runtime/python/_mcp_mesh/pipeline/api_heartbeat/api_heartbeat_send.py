"""
API heartbeat send step for API heartbeat pipeline.

Sends service health status and registration data to the registry
for FastAPI applications using @mesh.route decorators.
"""

import logging
from typing import Any

from ...engine.decorator_registry import DecoratorRegistry
from ..shared.base_step import PipelineStep
from ..shared.pipeline_types import PipelineResult

logger = logging.getLogger(__name__)


class APIHeartbeatSendStep(PipelineStep):
    """
    Send API service heartbeat to registry.

    Communicates service health status and registration information
    to the registry for monitoring and discovery purposes.
    """

    def __init__(self, required: bool = True):
        super().__init__(
            name="api-heartbeat-send",
            required=required,
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Send API service heartbeat to registry.

        Args:
            context: Pipeline context containing registry_wrapper, health_status, service_id

        Returns:
            PipelineResult with heartbeat_response in context
        """
        self.logger.debug("Sending API service heartbeat to registry")

        try:
            # Get required components from context
            registry_wrapper = context.get("registry_wrapper")
            health_status = context.get("health_status")
            service_id = context.get("service_id") or context.get("agent_id", "unknown")

            if not registry_wrapper:
                error_msg = "No registry wrapper available for heartbeat"
                self.logger.error(f"❌ {error_msg}")

                from ..shared.pipeline_types import PipelineStatus

                result = PipelineResult(
                    status=PipelineStatus.FAILED, message=error_msg, context=context
                )
                result.add_error(error_msg)
                return result

            if not health_status:
                error_msg = "No health status available for heartbeat"
                self.logger.error(f"❌ {error_msg}")

                from ..shared.pipeline_types import PipelineStatus

                result = PipelineResult(
                    status=PipelineStatus.FAILED, message=error_msg, context=context
                )
                result.add_error(error_msg)
                return result

            # Prepare heartbeat data for API service
            heartbeat_data = self._prepare_api_heartbeat_data(
                health_status, service_id, context
            )

            self.logger.debug(f"📡 Sending heartbeat for API service '{service_id}'")

            # Send heartbeat to registry using the same format as test_api_service.json
            # Import json at the beginning
            import json

            import aiohttp

            try:
                # For API services, send directly to registry using the format that works
                # Get registry URL
                registry_url = context.get("registry_url", "http://localhost:8000")

                # Build the API service payload using actual dependencies from @mesh.route decorators
                display_config = context.get("display_config", {})

                # Build per-route tool entries using METHOD:path as unique identifiers
                # This allows dependency resolution to map back to specific route wrappers
                route_wrappers = DecoratorRegistry.get_all_route_wrappers()
                tools_list = []

                for route_id, route_info in route_wrappers.items():
                    dependencies = route_info.get("dependencies", [])
                    if dependencies:  # Only include routes with dependencies
                        tools_list.append(
                            {
                                "function_name": route_id,  # e.g., "GET:/api/v1/benchmark-services"
                                "dependencies": [
                                    {"capability": dep, "tags": []}
                                    for dep in dependencies
                                ],
                            }
                        )

                # Fallback to old behavior if no route wrappers registered yet
                if not tools_list:
                    all_route_dependencies = self._extract_all_route_dependencies(
                        context
                    )
                    if all_route_dependencies:
                        tools_list.append(
                            {
                                "function_name": "api_endpoint_handler",
                                "dependencies": all_route_dependencies,
                            }
                        )

                self.logger.debug(
                    f"Route wrappers registered: {list(route_wrappers.keys())}"
                )

                api_service_payload = {
                    "agent_id": service_id,
                    "agent_type": "api",
                    "tools": tools_list,
                    "http_host": display_config.get("display_host", "127.0.0.1"),
                    "http_port": display_config.get("display_port", 8080),
                }

                self.logger.debug(
                    f"Sending API service payload to {registry_url}/heartbeat"
                )

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{registry_url}/heartbeat",
                            headers={"Content-Type": "application/json"},
                            data=json.dumps(api_service_payload),
                        ) as response:
                            self.logger.debug(
                                f'{registry_url} "POST /heartbeat HTTP/1.1" {response.status}'
                            )
                            if response.status == 200:
                                heartbeat_response = await response.json()
                            else:
                                response_text = await response.text()
                                self.logger.error(
                                    f"❌ Registry error {response.status}: {response_text}"
                                )
                                raise Exception(
                                    f"Registry returned {response.status}: {response_text}"
                                )

                except Exception as http_error:
                    self.logger.error(f"❌ HTTP request failed: {http_error}")
                    raise http_error

                if heartbeat_response:
                    self.logger.info(
                        f"💚 API heartbeat successful for service '{service_id}'"
                    )

                    return PipelineResult(
                        message=f"API heartbeat sent for service {service_id}",
                        context={
                            "heartbeat_response": heartbeat_response,
                            "heartbeat_success": True,
                            "heartbeat_data": heartbeat_data,
                        },
                    )
                else:
                    error_msg = f"Registry heartbeat failed for service {service_id}"
                    self.logger.warning(f"⚠️ {error_msg}")

                    from ..shared.pipeline_types import PipelineStatus

                    result = PipelineResult(
                        status=PipelineStatus.FAILED, message=error_msg, context=context
                    )
                    result.add_error(error_msg)
                    return result

            except Exception as e:
                error_msg = f"Registry communication failed: {e}"
                self.logger.error(f"❌ {error_msg}")

                from ..shared.pipeline_types import PipelineStatus

                result = PipelineResult(
                    status=PipelineStatus.FAILED, message=error_msg, context=context
                )
                result.add_error(str(e))
                return result

        except Exception as e:
            error_msg = f"API heartbeat send failed: {e}"
            self.logger.error(f"❌ {error_msg}")

            from ..shared.pipeline_types import PipelineStatus

            result = PipelineResult(
                status=PipelineStatus.FAILED, message=error_msg, context=context
            )
            result.add_error(str(e))
            return result

    def _prepare_api_heartbeat_data(
        self, health_status: Any, service_id: str, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Prepare heartbeat data specific to API services."""
        try:
            # Extract FastAPI-specific information
            app_title = context.get("app_title", "Unknown API")
            app_version = context.get("app_version", "1.0.0")
            routes_total = context.get("routes_total", 0)
            routes_with_mesh = context.get("routes_with_mesh", 0)

            # Get display configuration
            display_config = context.get("display_config", {})
            host = display_config.get("host", "0.0.0.0")
            port = display_config.get("port", 8080)

            heartbeat_data = {
                "service_id": service_id,
                "service_type": "api",
                "app_title": app_title,
                "app_version": app_version,
                "host": host,
                "port": port,
                "routes": {
                    "total": routes_total,
                    "with_mesh": routes_with_mesh,
                },
                "health_status": (
                    health_status
                    if isinstance(health_status, dict)
                    else {
                        "status": (
                            health_status.status.value
                            if hasattr(health_status, "status")
                            and hasattr(health_status.status, "value")
                            else str(getattr(health_status, "status", "healthy"))
                        ),
                        "timestamp": (
                            health_status.timestamp.isoformat()
                            if hasattr(health_status, "timestamp")
                            and hasattr(health_status.timestamp, "isoformat")
                            else str(getattr(health_status, "timestamp", ""))
                        ),
                        "version": getattr(health_status, "version", "1.0.0"),
                        "metadata": getattr(health_status, "metadata", {}),
                    }
                ),
            }

            return heartbeat_data

        except Exception as e:
            self.logger.warning(f"⚠️ Could not prepare heartbeat data: {e}")
            return {
                "service_id": service_id,
                "service_type": "api",
                "error": f"Failed to prepare heartbeat data: {e}",
            }

    def _extract_all_route_dependencies(
        self, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Extract all unique dependencies from @mesh.route decorators in the FastAPI app.

        This method looks at the actual route dependencies that were discovered during
        the API startup pipeline and extracts them for registry registration.

        Args:
            context: Pipeline context containing FastAPI app and route information

        Returns:
            List of unique dependency objects in the format expected by registry
        """
        try:
            # Try to get dependencies from startup context (preferred method)
            api_service_metadata = context.get("api_service_metadata", {})
            route_capabilities = api_service_metadata.get("capabilities", [])

            self.logger.debug(
                f"api_service_metadata keys: {list(api_service_metadata.keys())}"
            )

            # Extract dependencies from route capabilities
            all_dependencies = []
            seen_capabilities = set()

            for route_capability in route_capabilities:
                route_deps = route_capability.get("dependencies", [])
                for dep in route_deps:
                    # dep should already be a string (capability name)
                    if isinstance(dep, str) and dep not in seen_capabilities:
                        seen_capabilities.add(dep)
                        # Convert to object format for registry
                        all_dependencies.append(
                            {
                                "capability": dep,
                                "tags": [],  # No tags info available at this level
                            }
                        )

            # If we found dependencies from startup context, use them
            if all_dependencies:
                self.logger.debug(
                    f"Extracted {len(all_dependencies)} unique dependencies from API startup: "
                    f"{[dep['capability'] for dep in all_dependencies]}"
                )
                return all_dependencies

            # Fallback: try to extract directly from FastAPI app routes
            fastapi_app = context.get("fastapi_app")
            if fastapi_app:
                return self._extract_dependencies_from_routes(fastapi_app)

            # Final fallback: empty dependencies
            self.logger.warning(
                "⚠️ No route dependencies found in context or FastAPI app"
            )
            return []

        except Exception as e:
            self.logger.error(f"❌ Failed to extract route dependencies: {e}")
            return []

    def _extract_dependencies_from_routes(
        self, fastapi_app: Any
    ) -> list[dict[str, Any]]:
        """
        Fallback method to extract dependencies directly from FastAPI route metadata.

        Args:
            fastapi_app: FastAPI application instance

        Returns:
            List of unique dependency objects
        """
        try:
            all_dependencies = []
            seen_capabilities = set()

            routes = getattr(fastapi_app, "routes", [])
            for route in routes:
                endpoint = getattr(route, "endpoint", None)
                if endpoint and hasattr(endpoint, "_mesh_route_metadata"):
                    metadata = endpoint._mesh_route_metadata
                    route_deps = metadata.get("dependencies", [])

                    for dep in route_deps:
                        if isinstance(dep, dict):
                            capability = dep.get("capability")
                            if capability and capability not in seen_capabilities:
                                seen_capabilities.add(capability)
                                all_dependencies.append(
                                    {
                                        "capability": capability,
                                        "tags": dep.get("tags", []),
                                    }
                                )
                        elif isinstance(dep, str) and dep not in seen_capabilities:
                            seen_capabilities.add(dep)
                            all_dependencies.append({"capability": dep, "tags": []})

            self.logger.debug(
                f"Extracted {len(all_dependencies)} unique dependencies from FastAPI routes: "
                f"{[dep['capability'] for dep in all_dependencies]}"
            )
            return all_dependencies

        except Exception as e:
            self.logger.error(f"❌ Failed to extract dependencies from routes: {e}")
            return []
