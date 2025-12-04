import logging
from typing import Any

from ...engine.decorator_registry import DecoratorRegistry
from ...engine.dependency_injector import get_global_injector
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class RouteIntegrationStep(PipelineStep):
    """
    Integrates dependency injection into FastAPI route handlers.

    This step takes the discovered FastAPI apps and @mesh.route decorated handlers,
    then applies dependency injection by replacing the route.endpoint with a
    dependency injection wrapper.

    Uses the existing dependency injection engine from MCP tools - route handlers
    are just functions, so the same injection logic applies perfectly.
    """

    def __init__(self):
        super().__init__(
            name="route-integration",
            required=True,
            description="Apply dependency injection to @mesh.route decorated handlers",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Apply dependency injection to route handlers."""
        self.logger.debug("Applying dependency injection to route handlers...")

        result = PipelineResult(message="Route integration completed")

        try:
            # Get discovery results from context
            fastapi_apps = context.get("fastapi_apps", {})
            route_mapping = context.get("route_mapping", {})

            if not fastapi_apps:
                result.status = PipelineStatus.SKIPPED
                result.message = "No FastAPI applications found"
                self.logger.warning("⚠️ No FastAPI applications to integrate")
                return result

            if not route_mapping:
                result.status = PipelineStatus.SKIPPED
                result.message = "No @mesh.route handlers found"
                self.logger.warning("⚠️ No @mesh.route handlers to integrate")
                return result

            # Apply dependency injection to each app's routes
            integration_results = {}
            total_integrated = 0

            for app_id, app_info in fastapi_apps.items():
                if app_id not in route_mapping:
                    continue

                app_results = self._integrate_app_routes(
                    app_info, route_mapping[app_id]
                )
                integration_results[app_id] = app_results
                total_integrated += app_results["integrated_count"]

                self.logger.debug(
                    f"Integrated {app_results['integrated_count']} routes in "
                    f"'{app_info['title']}'"
                )

            # Store integration results in context
            result.add_context("integration_results", integration_results)
            result.add_context("total_integrated_routes", total_integrated)

            # Update result message
            result.message = f"Integrated {total_integrated} route handlers with dependency injection"

            self.logger.info(
                f"✅ Route Integration: {total_integrated} handlers now have dependency injection"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Route integration failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ Route integration failed: {e}")

        return result

    def _integrate_app_routes(
        self, app_info: dict[str, Any], route_mapping: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Apply dependency injection to routes in a single FastAPI app.

        Args:
            app_info: FastAPI app information from discovery
            route_mapping: Route mapping for this specific app

        Returns:
            Integration results for this app
        """
        app = app_info["instance"]
        app_title = app_info["title"]
        injector = get_global_injector()

        integration_results = {
            "app_title": app_title,
            "integrated_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "route_details": {},
        }

        # Process each @mesh.route decorated handler
        for route_name, route_info in route_mapping.items():
            try:
                result_detail = self._integrate_single_route(app, route_info, injector)
                integration_results["route_details"][route_name] = result_detail

                if result_detail["status"] == "integrated":
                    integration_results["integrated_count"] += 1
                elif result_detail["status"] == "skipped":
                    integration_results["skipped_count"] += 1
                else:
                    integration_results["error_count"] += 1

            except Exception as e:
                self.logger.error(f"❌ Failed to integrate route '{route_name}': {e}")
                integration_results["error_count"] += 1
                integration_results["route_details"][route_name] = {
                    "status": "error",
                    "error": str(e),
                }

        return integration_results

    def _integrate_single_route(
        self, app, route_info: dict[str, Any], injector
    ) -> dict[str, Any]:
        """
        Apply dependency injection to a single route handler.

        Args:
            app: FastAPI application instance
            route_info: Route information including dependencies
            injector: Dependency injector instance

        Returns:
            Integration result details
        """
        endpoint_name = route_info["endpoint_name"]
        original_handler = route_info["endpoint"]
        dependencies = route_info["dependencies"]
        path = route_info["path"]
        methods = route_info["methods"]

        # Extract dependency names for injector
        dependency_names = [dep["capability"] for dep in dependencies]

        self.logger.debug(
            f"Integrating route {methods} {path} -> {endpoint_name}() "
            f"with dependencies: {dependency_names}"
        )

        # Skip if no dependencies
        if not dependency_names:
            self.logger.debug(f"Route '{endpoint_name}' has no dependencies, skipping")
            return {
                "status": "skipped",
                "reason": "no_dependencies",
                "dependency_count": 0,
            }

        # Check if function already has an injection wrapper (from @mesh.route decorator)
        # The function might be the wrapper itself (if decorator order is correct)
        is_already_wrapper = getattr(
            original_handler, "_mesh_is_injection_wrapper", False
        )
        existing_wrapper = getattr(original_handler, "_mesh_injection_wrapper", None)

        if is_already_wrapper:
            self.logger.debug(
                f"Function '{endpoint_name}' is already an injection wrapper from @mesh.route decorator"
            )
            wrapped_handler = original_handler  # Use the function as-is
        elif existing_wrapper:
            self.logger.debug(
                f"Route '{endpoint_name}' already has injection wrapper from @mesh.route decorator, using existing wrapper"
            )
            wrapped_handler = existing_wrapper
        else:
            # Create dependency injection wrapper using existing engine
            self.logger.debug(
                f"Creating new injection wrapper for route '{endpoint_name}'"
            )
            try:
                wrapped_handler = injector.create_injection_wrapper(
                    original_handler, dependency_names
                )

                # Preserve original handler metadata on wrapper
                wrapped_handler._mesh_route_metadata = getattr(
                    original_handler, "_mesh_route_metadata", {}
                )
                wrapped_handler._original_handler = original_handler
                wrapped_handler._mesh_dependencies = dependency_names
            except Exception as e:
                self.logger.error(
                    f"Failed to create injection wrapper for {endpoint_name}: {e}"
                )
                return {
                    "status": "failed",
                    "reason": f"wrapper_creation_failed: {e}",
                    "dependency_count": len(dependency_names),
                }

        # CRITICAL FIX: Check if there are multiple wrapper instances for this function
        # If so, use the one that actually receives dependency updates
        from ...engine.dependency_injector import get_global_injector

        injector = get_global_injector()

        # Find all functions that depend on the first dependency of this route
        if dependency_names:
            first_dep = dependency_names[
                0
            ]  # Use first dependency to find all instances
            affected_functions = injector._dependency_mapping.get(first_dep, set())

            # Check if there are multiple instances and if so, prefer the one that's NOT __main__
            if len(affected_functions) > 1:
                non_main_functions = [
                    f for f in affected_functions if not f.startswith("__main__.")
                ]
                if non_main_functions:
                    # Found a non-main instance, try to get that wrapper instead
                    preferred_func_id = non_main_functions[0]  # Take first non-main
                    preferred_wrapper = injector._function_registry.get(
                        preferred_func_id
                    )
                    if preferred_wrapper:
                        wrapped_handler = preferred_wrapper

        # Register the route wrapper in DecoratorRegistry for path-based dependency resolution
        # This creates a mapping from METHOD:path -> wrapper function
        for method in methods:
            DecoratorRegistry.register_route_wrapper(
                method=method,
                path=path,
                wrapper=wrapped_handler,
                dependencies=dependency_names,
            )

        # Find and replace the route handler in FastAPI
        route_replaced = self._replace_route_handler(
            app, path, methods, original_handler, wrapped_handler
        )

        if route_replaced:
            self.logger.debug(
                f"Route '{endpoint_name}' integrated with {len(dependency_names)} dependencies"
            )
            return {
                "status": "integrated",
                "dependency_count": len(dependency_names),
                "dependencies": dependency_names,
                "original_handler": original_handler,
                "wrapped_handler": wrapped_handler,
            }
        else:
            self.logger.warning(
                f"⚠️ Failed to find route to replace for '{endpoint_name}'"
            )
            return {"status": "error", "error": "route_not_found_for_replacement"}

    def _replace_route_handler(
        self, app, path: str, methods: list, original_handler, wrapped_handler
    ) -> bool:
        """
        Replace the route handler in FastAPI's router.

        Args:
            app: FastAPI application instance
            path: Route path to find
            methods: HTTP methods for the route
            original_handler: Original handler function
            wrapped_handler: New wrapped handler function

        Returns:
            True if replacement was successful, False otherwise
        """
        try:
            # Find the matching route in FastAPI's router
            for route in app.router.routes:
                if (
                    hasattr(route, "endpoint")
                    and hasattr(route, "path")
                    and hasattr(route, "methods")
                ):

                    # Match by path and endpoint function
                    if route.path == path and route.endpoint is original_handler:

                        # Replace the endpoint with our wrapped version
                        route.endpoint = wrapped_handler

                        return True

            # If we get here, we didn't find the route
            self.logger.warning(
                f"Could not find route {methods} {path} to replace handler"
            )
            return False

        except Exception as e:
            self.logger.error(f"❌ Error replacing route handler: {e}")
            return False
