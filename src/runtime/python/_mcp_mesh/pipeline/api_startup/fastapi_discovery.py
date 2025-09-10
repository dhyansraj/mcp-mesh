import logging
from typing import Any, Dict, List

from ..shared import PipelineResult, PipelineStatus, PipelineStep
from ...shared.server_discovery import ServerDiscoveryUtil


class FastAPIAppDiscoveryStep(PipelineStep):
    """
    Discovers existing FastAPI application instances in the user's code.
    
    This step scans the Python runtime to find FastAPI applications that
    have been instantiated by the user, without modifying them in any way.
    
    The goal is minimal intervention - we only discover what exists,
    we don't create or modify anything.
    """

    def __init__(self):
        super().__init__(
            name="fastapi-discovery",
            required=True,
            description="Discover existing FastAPI application instances",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Discover FastAPI applications."""
        self.logger.debug("Discovering FastAPI applications...")

        result = PipelineResult(message="FastAPI discovery completed")

        try:
            # Get route decorators from context (from RouteCollectionStep)
            mesh_routes = context.get("mesh_routes", {})
            
            if not mesh_routes:
                result.status = PipelineStatus.SKIPPED
                result.message = "No @mesh.route decorators found"
                self.logger.info("⚠️ No @mesh.route decorators found to process")
                return result

            # Discover FastAPI instances using shared utility
            fastapi_apps = ServerDiscoveryUtil.discover_fastapi_instances()
            
            if not fastapi_apps:
                # This is not necessarily an error - user might be using FastAPI differently
                result.status = PipelineStatus.FAILED
                result.message = "No FastAPI applications found"
                result.add_error("No FastAPI applications discovered in runtime")
                self.logger.error(
                    "❌ No FastAPI applications found. @mesh.route decorators require "
                    "an existing FastAPI app instance. Please create a FastAPI app before "
                    "using @mesh.route decorators."
                )
                return result

            # Analyze which routes belong to which apps
            route_mapping = self._map_routes_to_apps(fastapi_apps, mesh_routes)
            
            # Store discovery results in context
            result.add_context("fastapi_apps", fastapi_apps)
            result.add_context("route_mapping", route_mapping)
            result.add_context("discovered_app_count", len(fastapi_apps))
            
            # Update result message
            route_count = sum(len(routes) for routes in route_mapping.values())
            result.message = (
                f"Discovered {len(fastapi_apps)} FastAPI app(s) with "
                f"{route_count} @mesh.route decorated handlers"
            )

            self.logger.info(
                f"📦 FastAPI Discovery: {len(fastapi_apps)} app(s), "
                f"{route_count} @mesh.route handlers, {len(mesh_routes)} total routes"
            )

            # Log details for debugging
            for app_id, app_info in fastapi_apps.items():
                app_title = app_info.get("title", "Unknown")
                routes_in_app = len(route_mapping.get(app_id, {}))
                self.logger.debug(
                    f"  App '{app_title}' ({app_id}): {routes_in_app} @mesh.route handlers"
                )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"FastAPI discovery failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ FastAPI discovery failed: {e}")

        return result


    def _map_routes_to_apps(
        self, 
        fastapi_apps: Dict[str, Dict[str, Any]], 
        mesh_routes: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Map @mesh.route decorated functions to their FastAPI applications.
        
        Args:
            fastapi_apps: Discovered FastAPI applications
            mesh_routes: @mesh.route decorated functions from DecoratorRegistry
            
        Returns:
            Dict mapping app_id -> {route_name -> route_info} for routes that have @mesh.route
        """
        route_mapping = {}
        
        for app_id, app_info in fastapi_apps.items():
            app_routes = {}
            
            for route_info in app_info["routes"]:
                endpoint_name = route_info["endpoint_name"]
                
                # Check if this route handler has @mesh.route decorator
                if endpoint_name in mesh_routes:
                    mesh_route_data = mesh_routes[endpoint_name]
                    
                    # Combine FastAPI route info with @mesh.route metadata
                    combined_info = {
                        **route_info,  # FastAPI route info
                        "mesh_metadata": mesh_route_data.metadata,  # @mesh.route metadata
                        "dependencies": mesh_route_data.metadata.get("dependencies", []),
                        "mesh_decorator": mesh_route_data,  # Full DecoratedFunction object
                    }
                    
                    app_routes[endpoint_name] = combined_info
                    
                    self.logger.debug(
                        f"Mapped route '{endpoint_name}' to app '{app_info['title']}' "
                        f"with {len(combined_info['dependencies'])} dependencies"
                    )
            
            if app_routes:
                route_mapping[app_id] = app_routes
                
        return route_mapping