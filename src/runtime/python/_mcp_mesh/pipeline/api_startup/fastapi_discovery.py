import gc
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..shared import PipelineResult, PipelineStatus, PipelineStep


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

            # Discover FastAPI instances
            fastapi_apps = self._discover_fastapi_instances()
            
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

    def _discover_fastapi_instances(self) -> Dict[str, Dict[str, Any]]:
        """
        Discover FastAPI application instances in the Python runtime.
        
        Uses intelligent deduplication to handle standard uvicorn patterns where
        the same app might be imported multiple times (e.g., "module:app" pattern).
        
        Returns:
            Dict mapping app_id -> app_info where app_info contains:
            - 'instance': The FastAPI app instance
            - 'title': App title from FastAPI
            - 'routes': List of route information
            - 'module': Module where app was found
        """
        fastapi_apps = {}
        seen_apps = {}  # For deduplication: title -> app_info
        
        try:
            # Import FastAPI here to avoid dependency if not used
            from fastapi import FastAPI
        except ImportError:
            self.logger.warning("FastAPI not installed - cannot discover FastAPI apps")
            return {}

        # Scan garbage collector for FastAPI instances
        candidate_apps = []
        for obj in gc.get_objects():
            if isinstance(obj, FastAPI):
                candidate_apps.append(obj)

        # Deduplicate apps with identical configurations
        for obj in candidate_apps:
            try:
                title = getattr(obj, "title", "FastAPI App")
                version = getattr(obj, "version", "unknown")
                routes = self._extract_route_info(obj)
                route_count = len(routes)
                
                # Create a signature for deduplication
                app_signature = (title, version, route_count)
                
                # Check if we've seen an identical app
                if app_signature in seen_apps:
                    existing_app = seen_apps[app_signature]
                    # Compare route details to ensure they're truly identical
                    existing_routes = existing_app["routes"]
                    
                    if self._routes_are_identical(routes, existing_routes):
                        self.logger.debug(
                            f"Skipping duplicate FastAPI app: '{title}' (same title, version, and routes)"
                        )
                        continue  # Skip this duplicate
                
                # This is a unique app, add it
                app_id = f"app_{id(obj)}"
                app_info = {
                    "instance": obj,
                    "title": title,
                    "version": version,
                    "routes": routes,
                    "module": self._get_app_module(obj),
                    "object_id": id(obj),
                    "router_routes_count": len(obj.router.routes) if hasattr(obj, 'router') else 0,
                }
                
                fastapi_apps[app_id] = app_info
                seen_apps[app_signature] = app_info
                
                self.logger.debug(
                    f"Found FastAPI app: '{title}' (module: {app_info['module']}) with "
                    f"{len(routes)} routes"
                )
                
            except Exception as e:
                self.logger.warning(f"Error analyzing FastAPI app: {e}")
                continue

        return fastapi_apps

    def _routes_are_identical(self, routes1: List[Dict[str, Any]], routes2: List[Dict[str, Any]]) -> bool:
        """
        Compare two route lists to see if they're identical.
        
        Args:
            routes1: First route list 
            routes2: Second route list
            
        Returns:
            True if routes are identical, False otherwise
        """
        if len(routes1) != len(routes2):
            return False
            
        # Create comparable signatures for each route
        def route_signature(route):
            return (
                tuple(sorted(route.get('methods', []))),  # Sort methods for consistent comparison
                route.get('path', ''),
                route.get('endpoint_name', '')
            )
        
        # Sort routes by signature for consistent comparison
        sig1 = sorted([route_signature(r) for r in routes1])
        sig2 = sorted([route_signature(r) for r in routes2])
        
        return sig1 == sig2

    def _extract_route_info(self, app) -> List[Dict[str, Any]]:
        """
        Extract route information from FastAPI app without modifying it.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            List of route information dictionaries
        """
        routes = []
        
        try:
            for route in app.router.routes:
                if hasattr(route, 'endpoint') and hasattr(route, 'path'):
                    route_info = {
                        "path": route.path,
                        "methods": list(route.methods) if hasattr(route, 'methods') else [],
                        "endpoint": route.endpoint,
                        "endpoint_name": getattr(route.endpoint, '__name__', 'unknown'),
                        "has_mesh_route": hasattr(route.endpoint, '_mesh_route_metadata'),
                    }
                    routes.append(route_info)
                    
        except Exception as e:
            self.logger.warning(f"Error extracting route info: {e}")
            
        return routes

    def _get_app_module(self, app) -> Optional[str]:
        """
        Try to determine which module the FastAPI app belongs to.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            Module name or None if unknown
        """
        try:
            # Try to get module from the app's stack frame when it was created
            # This is best-effort - may not always work
            import inspect
            
            frame = inspect.currentframe()
            while frame:
                frame_globals = frame.f_globals
                for name, obj in frame_globals.items():
                    if obj is app:
                        return frame_globals.get('__name__', 'unknown')
                frame = frame.f_back
                
        except Exception:
            pass
            
        return None

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