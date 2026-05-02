import functools
import inspect
import json
import logging
from typing import Any

from ...engine.decorator_registry import DecoratorRegistry
from ...engine.dependency_injector import get_global_injector
from ...engine.stream_introspection import detect_stream_type
from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _resolve_user_function(handler: Any) -> Any:
    """Return the user-authored function underneath a possibly wrapped handler.

    The dependency-injector wrapper stores the originally-decorated function on
    ``_mesh_original_func``. Falls back to ``handler`` when no wrapping is in
    play (handlers without dependencies that bypass wrapping).
    """
    return getattr(handler, "_mesh_original_func", handler)


def _frame_chunk_as_sse(chunk: str) -> str:
    """Format a single chunk as SSE ``data:`` lines per spec.

    Each line of the chunk becomes its own ``data:`` line; the record is
    terminated by a blank line. Empty chunks still emit a ``data:`` line so
    consumers see a heartbeat-style event.
    """
    lines = chunk.splitlines() or [""]
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _build_sse_endpoint(wrapped_handler: Any, user_func: Any) -> Any:
    """Wrap a streaming route handler so FastAPI emits Server-Sent Events.

    The user's function declares ``-> mesh.Stream[str]`` and yields chunks.
    The dependency-injector wrapper (P1) accumulates those chunks into a
    single string for MCP consumers. For HTTP consumers we need the chunks
    individually, so we sidestep the accumulation and call the user's
    underlying generator directly with dependencies injected.

    Behavior:
    - Successful completion emits ``data: [DONE]\\n\\n`` terminator.
    - Exceptions surface as ``event: error`` SSE events with a JSON payload
      ``{"error": <msg>, "type": <exc class>}``.
    - Multi-line chunks emit one ``data:`` line per line per spec.
    - ``__signature__`` is the user function's clean signature so FastAPI's
      parameter binding extracts path/query/body params correctly.
    """
    from fastapi.responses import StreamingResponse

    from ...engine.dependency_injector import _prepare_injection_kwargs

    injector = get_global_injector()
    mesh_positions = list(getattr(wrapped_handler, "_mesh_positions", []) or [])
    dependencies = list(getattr(wrapped_handler, "_mesh_dependencies", []) or [])
    injected_deps = getattr(
        wrapped_handler, "_mesh_injected_deps", [None] * len(dependencies)
    )

    @functools.wraps(user_func)
    async def sse_endpoint(*args, **kwargs):
        if mesh_positions:
            final_kwargs, _ = _prepare_injection_kwargs(
                user_func,
                kwargs,
                mesh_positions,
                dependencies,
                injected_deps,
                injector.get_dependency,
                logger,
            )
        else:
            final_kwargs = kwargs

        if inspect.isasyncgenfunction(user_func):
            gen = user_func(*args, **final_kwargs)
        else:
            produced = user_func(*args, **final_kwargs)
            if inspect.iscoroutine(produced):
                produced = await produced
            gen = produced

        if not hasattr(gen, "__aiter__"):
            raise TypeError(
                f"Stream route '{user_func.__name__}' did not return an async "
                f"iterator (got {type(gen).__name__})."
            )

        async def event_stream():
            try:
                try:
                    async for chunk in gen:
                        if not isinstance(chunk, str):
                            raise TypeError(
                                f"Stream route '{user_func.__name__}' yielded "
                                f"non-str chunk of type {type(chunk).__name__}; "
                                f"v1 supports str only."
                            )
                        yield _frame_chunk_as_sse(chunk)
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    err_payload = json.dumps(
                        {"error": str(e), "type": type(e).__name__}
                    )
                    yield f"event: error\ndata: {err_payload}\n\n"
            finally:
                # Run on normal completion, error, GeneratorExit (client
                # disconnect), and CancelledError. Idempotent — aclose() on an
                # exhausted generator is a no-op.
                aclose = getattr(gen, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception as close_err:
                        logger.debug(
                            "SSE route '%s': aclose() during teardown failed: %s",
                            user_func.__name__,
                            close_err,
                        )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    user_sig = inspect.signature(user_func)
    # Strip the streaming return annotation so FastAPI does not try to build a
    # Pydantic response_field for AsyncIterator[str]. The SSE endpoint always
    # returns a StreamingResponse, which FastAPI passes through.
    #
    # Also strip McpMeshTool-typed params: FastAPI's body inference sees a
    # second non-trivial param (alongside the user's body model) and switches
    # to embed-mode, expecting ``{"body": {...}}`` instead of ``{...}``. Mesh
    # deps are framework-injected — never bound from the request — so they
    # must not influence FastAPI's parameter binding.
    from _mcp_mesh.engine.signature_analyzer import get_mesh_agent_parameter_names

    try:
        mesh_param_names = set(get_mesh_agent_parameter_names(user_func))
    except Exception:
        mesh_param_names = set()
    public_params = [
        p for n, p in user_sig.parameters.items() if n not in mesh_param_names
    ]
    sse_endpoint.__signature__ = user_sig.replace(
        parameters=public_params,
        return_annotation=inspect.Signature.empty,
    )
    user_anns = dict(getattr(user_func, "__annotations__", {}) or {})
    user_anns.pop("return", None)
    for name in mesh_param_names:
        user_anns.pop(name, None)
    sse_endpoint.__annotations__ = user_anns
    # functools.wraps set __wrapped__ -> async-generator user_func; FastAPI
    # follows that chain when probing is_coroutine_callable, and an async-gen
    # function reports False, dispatching us through the threadpool path which
    # tries to JSON-encode our StreamingResponse. Drop the link so FastAPI sees
    # this endpoint as the coroutine function it actually is.
    if hasattr(sse_endpoint, "__wrapped__"):
        try:
            del sse_endpoint.__wrapped__
        except AttributeError:
            pass
    sse_endpoint._mesh_route_metadata = getattr(
        wrapped_handler, "_mesh_route_metadata", None
    ) or getattr(user_func, "_mesh_route_metadata", {})
    sse_endpoint._mesh_is_sse_endpoint = True
    sse_endpoint._mesh_original_func = user_func
    sse_endpoint._mesh_inner_wrapper = wrapped_handler
    return sse_endpoint


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

        user_func = _resolve_user_function(original_handler)
        try:
            stream_type = detect_stream_type(user_func)
        except ValueError as e:
            self.logger.warning(
                f"Route '{endpoint_name}' has invalid stream annotation: {e}"
            )
            stream_type = None
        is_stream_route = stream_type == "text"

        # Skip if no dependencies and not a streaming route
        if not dependency_names and not is_stream_route:
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
        elif dependency_names:
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
        else:
            # Streaming route with no mesh dependencies — SSE wrapping only.
            wrapped_handler = original_handler

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

        if is_stream_route:
            wrapped_handler = _build_sse_endpoint(wrapped_handler, user_func)
            self.logger.info(
                f"📡 Route {methods} {path} -> {endpoint_name}() registered with SSE streaming"
            )

        # Find and replace the route handler in FastAPI
        route_replaced = self._replace_route_handler(
            app, path, methods, original_handler, wrapped_handler
        )

        if route_replaced:
            self.logger.debug(
                f"Route '{endpoint_name}' integrated with {len(dependency_names)} dependencies"
                + (" (SSE)" if is_stream_route else "")
            )
            return {
                "status": "integrated",
                "dependency_count": len(dependency_names),
                "dependencies": dependency_names,
                "original_handler": original_handler,
                "wrapped_handler": wrapped_handler,
                "sse": is_stream_route,
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

                        # FastAPI dispatches via a per-route ASGI handler closure
                        # (route.app) that captured the original Dependant and
                        # response_field at registration time. Updating
                        # route.endpoint alone is not enough — we must rebuild
                        # the dependant AND the request_response closure so
                        # invocation actually targets the wrapper. Critical for
                        # SSE wrapping where the wrapper returns a
                        # StreamingResponse; without rebuild, FastAPI keeps
                        # calling the original async-generator function and tries
                        # to JSON-encode the result. Harmless for plain DI
                        # wrapping where the closure already targeted the wrapper.
                        try:
                            from fastapi.dependencies.utils import (
                                _should_embed_body_fields,
                                get_body_field,
                                get_dependant,
                                get_flat_dependant,
                            )
                            from fastapi.routing import request_response

                            route.dependant = get_dependant(
                                path=route.path_format, call=wrapped_handler
                            )
                            # APIRoute.__init__ caches a flattened dependant,
                            # the embed-body-fields decision, and the body
                            # field model based on the original endpoint.
                            # When the original endpoint mixed a Pydantic
                            # body model with framework-only params (e.g.
                            # McpMeshTool, FastMCP Context), FastAPI baked
                            # in embed-mode body parsing — request parser
                            # then expects ``{"body": {...}}`` envelopes.
                            # Since the SSE wrapper now exposes ONLY the
                            # user-facing params, refresh the cached
                            # decision from the rebuilt dependant. Issue
                            # #645 bug 5.
                            route._flat_dependant = get_flat_dependant(
                                route.dependant
                            )
                            route._embed_body_fields = _should_embed_body_fields(
                                route._flat_dependant.body_params
                            )
                            try:
                                route.body_field = get_body_field(
                                    flat_dependant=route._flat_dependant,
                                    name=route.unique_id,
                                    embed_body_fields=route._embed_body_fields,
                                )
                            except TypeError:
                                # Older FastAPI signature without embed_body_fields kwarg
                                route.body_field = get_body_field(
                                    dependant=route._flat_dependant,
                                    name=route.unique_id,
                                )
                            route.app = request_response(route.get_route_handler())
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to rebuild route handler for {path}: {e}"
                            )

                        return True

            # If we get here, we didn't find the route
            self.logger.warning(
                f"Could not find route {methods} {path} to replace handler"
            )
            return False

        except Exception as e:
            self.logger.error(f"❌ Error replacing route handler: {e}")
            return False
