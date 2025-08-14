import logging
import uuid
from typing import Any, Dict, Optional

from ...shared.config_resolver import ValidationRule, get_config_value
from ...shared.defaults import MeshDefaults
from ...shared.host_resolver import HostResolver
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class APIServerSetupStep(PipelineStep):
    """
    Minimal API server setup for FastAPI integration.
    
    This step prepares the binding configuration and service registration
    metadata for the user's existing FastAPI application. It does NOT create
    or modify the FastAPI app - it only prepares the configuration needed
    to run the app with uvicorn and register it with the mesh registry.
    
    Our job is ONLY dependency injection - the user owns their FastAPI app.
    """

    def __init__(self):
        super().__init__(
            name="api-server-setup",
            required=True,
            description="Prepare binding config and service registration for existing FastAPI app",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Setup API server configuration."""
        self.logger.debug("Setting up API server configuration...")

        result = PipelineResult(message="API server setup completed")

        try:
            # Verify we have FastAPI apps to work with
            fastapi_apps = context.get("fastapi_apps", {})
            integration_results = context.get("integration_results", {})
            
            if not fastapi_apps:
                result.status = PipelineStatus.FAILED
                result.message = "No FastAPI applications found"
                result.add_error("Cannot setup API server without existing FastAPI app")
                self.logger.error(
                    "❌ No FastAPI applications found. API pipeline requires "
                    "an existing FastAPI app with @mesh.route decorators."
                )
                return result

            # For now, we only support single FastAPI app
            # TODO: Future enhancement could support multiple apps
            if len(fastapi_apps) > 1:
                self.logger.warning(
                    f"⚠️ Multiple FastAPI apps found ({len(fastapi_apps)}), "
                    f"using the first one. Multi-app support coming in future."
                )

            # Get the primary FastAPI app
            primary_app_id = list(fastapi_apps.keys())[0]
            primary_app_info = fastapi_apps[primary_app_id]
            primary_app = primary_app_info["instance"]
            
            self.logger.info(
                f"🎯 Using FastAPI app: '{primary_app_info['title']}' as primary app"
            )

            # Prepare display configuration for registry (NOT binding configuration)
            display_config = self._prepare_display_config()
            
            # Prepare service registration metadata
            service_metadata = self._prepare_service_metadata(
                primary_app_info, integration_results.get(primary_app_id, {}), display_config
            )
            
            # Prepare heartbeat configuration
            heartbeat_config = self._prepare_heartbeat_config(
                primary_app_info, display_config, service_metadata
            )
            
            # Store configuration in context
            result.add_context("primary_fastapi_app", primary_app)
            result.add_context("fastapi_app", primary_app)  # For heartbeat compatibility
            result.add_context("api_display_config", display_config)
            result.add_context("display_config", display_config)  # For heartbeat compatibility
            result.add_context("api_service_metadata", service_metadata)
            result.add_context("service_type", "api")  # Important for registry registration
            result.add_context("heartbeat_config", heartbeat_config)
            
            # Update result message
            integrated_routes = integration_results.get(primary_app_id, {}).get("integrated_count", 0)
            result.message = (
                f"API server config prepared for '{primary_app_info['title']}' "
                f"with {integrated_routes} dependency-injected routes"
            )

            self.logger.info(
                f"✅ API server setup: {primary_app_info['title']} ready "
                f"(registry display: {display_config['display_host']}:{display_config['display_port']})"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"API server setup failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ API server setup failed: {e}")

        return result

    def _prepare_display_config(self) -> Dict[str, Any]:
        """
        Prepare display configuration for service registration.
        
        This is ONLY for registry display purposes since FastAPI services
        are consumers (nobody needs to communicate TO them in mesh network).
        Users configure their actual uvicorn host/port separately.
        """
        # Get external host for display (what others would see this service as)
        external_host = HostResolver.get_external_host()
        
        # Get port for display - users can override via env var
        display_port = get_config_value(
            "MCP_MESH_HTTP_PORT", 
            default=8080,  # FastAPI convention
            rule=ValidationRule.PORT_RULE,
        )
        
        # Also check if user provided host override
        display_host = get_config_value(
            "MCP_MESH_HTTP_HOST",
            default=external_host,
            rule=ValidationRule.STRING_RULE,
        )
        
        display_config = {
            "display_host": display_host,
            "display_port": display_port,
            "external_host": external_host,
        }
        
        self.logger.debug(
            f"📍 Display config: {display_host}:{display_port} "
            f"(for registry display only - user controls actual uvicorn binding)"
        )
        
        return display_config

    def _prepare_service_metadata(
        self, app_info: Dict[str, Any], integration_results: Dict[str, Any], display_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare service registration metadata for mesh registry.
        
        This metadata tells the mesh registry about our API service
        and what capabilities it provides (routes, not MCP tools).
        """
        # Extract route information for registry
        route_capabilities = []
        route_details = integration_results.get("route_details", {})
        
        for route_name, details in route_details.items():
            if details.get("status") == "integrated":
                # Create capability entry for each dependency-injected route
                capability_info = {
                    "name": route_name,
                    "type": "api_route", 
                    "dependencies": details.get("dependencies", []),
                    "dependency_count": details.get("dependency_count", 0),
                }
                route_capabilities.append(capability_info)
        
        # Build service metadata
        service_metadata = {
            "service_name": app_info.get("title", "FastAPI Service"),
            "service_version": app_info.get("version", "1.0.0"),
            "service_type": "api",  # Distinguishes from MCP agents
            "capabilities": route_capabilities,
            "total_routes": len(app_info.get("routes", [])),
            "integrated_routes": integration_results.get("integrated_count", 0),
            "framework": "fastapi",
            "integration_method": "mesh_route_decorators",
            # Display info for registry (NOT actual binding)
            "display_host": display_config["display_host"],
            "display_port": display_config["display_port"],
            "external_host": display_config["external_host"],
        }
        
        self.logger.debug(
            f"📋 Service metadata: {service_metadata['service_name']} "
            f"({len(route_capabilities)} capabilities)"
        )
        
        return service_metadata

    def _prepare_heartbeat_config(
        self, app_info: Dict[str, Any], display_config: Dict[str, Any], service_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Prepare heartbeat configuration for API service.
        
        This configuration will be used to start the heartbeat pipeline
        for periodic service registration and health monitoring.
        """
        # Check if we already have a service ID in the decorator registry
        # If so, and it's in API format, reuse it to avoid ID changes
        service_id = self._get_or_generate_api_service_id(app_info)
        
        # Get heartbeat interval using centralized defaults (consistent with MCP heartbeat)
        from ...shared.defaults import MeshDefaults
        
        heartbeat_interval = get_config_value(
            "MCP_MESH_HEALTH_INTERVAL",
            default=MeshDefaults.HEALTH_INTERVAL,
            rule=ValidationRule.NONZERO_RULE,
        )
        
        # Check if standalone mode (no registry communication)
        standalone_mode = get_config_value(
            "MCP_MESH_STANDALONE",
            default=False,
            rule=ValidationRule.TRUTHY_RULE,
        )
        
        heartbeat_config = {
            "service_id": service_id,
            "interval": heartbeat_interval,
            "standalone_mode": standalone_mode,
            "context": {
                # Context will be populated during heartbeat execution
                # with current pipeline context including fastapi_app, display_config, etc.
            }
        }
        
        # Store the generated service ID back to decorator registry for telemetry
        try:
            from ...engine.decorator_registry import DecoratorRegistry
            
            DecoratorRegistry.update_agent_config({
                "agent_id": service_id,
                "name": app_info.get("title", "api-service")
            })
            
            self.logger.debug(
                f"🔧 Stored API service ID '{service_id}' in decorator registry for telemetry"
            )
        except Exception as e:
            self.logger.warning(
                f"⚠️ Failed to store API service ID in decorator registry: {e}"
            )
        
        self.logger.info(
            f"💓 API heartbeat config created: service_id='{service_id}', "
            f"interval={heartbeat_interval}s, standalone={standalone_mode}"
        )
        
        return heartbeat_config

    def _generate_api_service_id(self, app_info: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate API service ID using same priority logic as MCP agents.
        
        Priority order:
        1. MCP_MESH_API_NAME environment variable 
        2. MCP_MESH_AGENT_NAME environment variable (fallback)
        3. Default to "api-{uuid8}"
        
        Args:
            app_info: FastAPI app information (optional, not used in simplified logic)
            
        Returns:
            Generated service ID with UUID suffix
        """
        import uuid
        
        # Check for API-specific environment variable first
        api_name = get_config_value(
            "MCP_MESH_API_NAME",
            default=None,
            rule=ValidationRule.STRING_RULE,
        )
        
        # Fallback to general agent name env var
        if not api_name:
            api_name = get_config_value(
                "MCP_MESH_AGENT_NAME", 
                default=None,
                rule=ValidationRule.STRING_RULE,
            )
        
        # Clean the service name if provided
        if api_name:
            cleaned_name = api_name.lower().replace(" ", "-").replace("_", "-")
            cleaned_name = "-".join(part for part in cleaned_name.split("-") if part)
        else:
            cleaned_name = ""
        
        # Generate UUID suffix  
        uuid_suffix = str(uuid.uuid4())[:8]
        
        # Apply naming logic
        if not cleaned_name:
            # No name provided: default to "api-{uuid8}"
            service_id = f"api-{uuid_suffix}"
        elif "api" in cleaned_name.lower():
            # Name already contains "api": use "{name}-{uuid8}"
            service_id = f"{cleaned_name}-{uuid_suffix}"
        else:
            # Name doesn't contain "api": use "{name}-api-{uuid8}"
            service_id = f"{cleaned_name}-api-{uuid_suffix}"
        
        self.logger.debug(
            f"Generated API service ID: '{service_id}' from env name: '{api_name}'"
        )
        
        return service_id

    def _get_or_generate_api_service_id(self, app_info: Optional[Dict[str, Any]] = None) -> str:
        """
        Get existing service ID from decorator registry or generate a new one.
        
        Since both the fallback and API pipeline now use identical logic based on 
        environment variables, we can simply reuse any existing API service ID.
        
        Args:
            app_info: FastAPI app information (optional, not used in simplified logic)
            
        Returns:
            Service ID (existing or newly generated)
        """
        try:
            from ...engine.decorator_registry import DecoratorRegistry
            
            # Get current cached config to see if we already have an ID
            current_config = DecoratorRegistry.get_resolved_agent_config()
            existing_id = current_config.get("agent_id", "")
            
            # Check if existing ID looks like an API service ID
            is_api_format = (
                existing_id.startswith("api-") or  # api-{uuid}
                "-api-" in existing_id  # {name}-api-{uuid}
            )
            
            if existing_id and is_api_format:
                # Reuse existing API service ID (fallback and pipeline use same logic now)
                self.logger.info(
                    f"🔄 Reusing existing API service ID: '{existing_id}' (consistent with fallback logic)"
                )
                return existing_id
            else:
                # Generate new ID - will be identical to what fallback would have generated
                new_id = self._generate_api_service_id(app_info)
                self.logger.info(
                    f"🆕 Generated new API service ID: '{new_id}' (no existing API format ID found)"
                )
                return new_id
                
        except Exception as e:
            self.logger.warning(f"⚠️ Error checking existing service ID, generating new one: {e}")
            return self._generate_api_service_id(app_info)

    def _is_http_enabled(self) -> bool:
        """Check if HTTP transport is enabled."""
        return get_config_value(
            "MCP_MESH_HTTP_ENABLED",
            default=True,
            rule=ValidationRule.TRUTHY_RULE,
        )