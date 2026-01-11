"""
Rust-backed heartbeat implementation for API services.

Replaces the Python API heartbeat pipeline with the Rust core runtime.
The Rust core handles:
- Registry communication (HEAD/POST heartbeats)
- Topology change detection
- Event emission

Python handles:
- DI updates when topology changes (route wrapper updates)
- FastAPI app health status
"""

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Lazy import to avoid ImportError if Rust core not built
_rust_core = None


def _get_rust_core():
    """Lazy import of Rust core module."""
    global _rust_core
    if _rust_core is None:
        try:
            import mcp_mesh_core

            _rust_core = mcp_mesh_core
            logger.debug("Rust core module loaded successfully for API heartbeat")
        except ImportError as e:
            logger.warning(f"Rust core not available for API heartbeat: {e}")
            raise
    return _rust_core


def _build_api_agent_spec(context: dict[str, Any], service_id: str = None) -> Any:
    """
    Build AgentSpec from API service context.

    Converts the API service metadata and route wrappers into a Rust AgentSpec.
    For API services:
    - function_name = METHOD:path (e.g., "GET:/api/v1/data")
    - capability = "" (API routes don't provide capabilities, they consume them)
    - dependencies = list of capabilities the route depends on

    Args:
        context: Pipeline context containing display_config, agent_config, etc.
        service_id: Service ID from heartbeat config (passed explicitly)
    """
    core = _get_rust_core()

    # Get service ID - prefer explicit parameter, fallback to context
    if not service_id:
        service_id = context.get("service_id") or context.get(
            "agent_id", "unknown-api-service"
        )
    display_config = context.get("display_config", {})
    agent_config = context.get("agent_config", {})

    # Get registry URL
    from ...shared.config_resolver import get_config_value

    # Default is handled by Rust core
    registry_url = get_config_value(
        "MCP_MESH_REGISTRY_URL",
        override=agent_config.get("registry_url"),
    )

    # Get heartbeat interval
    from ...shared.defaults import MeshDefaults

    heartbeat_interval = int(
        get_config_value(
            "MCP_MESH_HEALTH_INTERVAL",
            override=agent_config.get("health_interval"),
            default=MeshDefaults.HEALTH_INTERVAL,
        )
    )

    # Get HTTP config from display_config
    http_host = display_config.get("display_host", "127.0.0.1")
    http_port = display_config.get("display_port", 8080)
    namespace = agent_config.get("namespace", "default")
    version = agent_config.get("version", "1.0.0")

    # Build tool specs from route wrappers
    from ...engine.decorator_registry import DecoratorRegistry

    tools = []
    route_wrappers = DecoratorRegistry.get_all_route_wrappers()

    for route_id, route_info in route_wrappers.items():
        dependencies = route_info.get("dependencies", [])

        # Only include routes with dependencies (routes without deps don't need registry)
        if not dependencies:
            continue

        # Build dependency specs
        deps = []
        for dep_cap in dependencies:
            dep_spec = core.DependencySpec(
                capability=dep_cap,
                tags=[],
                version=None,
            )
            deps.append(dep_spec)

        # Create ToolSpec for this route
        # For API routes: function_name is the route_id (METHOD:path)
        # capability is empty since routes consume, not provide capabilities
        tool_spec = core.ToolSpec(
            function_name=route_id,  # e.g., "GET:/api/v1/benchmark-services"
            capability="",  # API routes don't provide capabilities
            version="1.0.0",
            description="",
            tags=[],
            dependencies=deps if deps else None,
            input_schema=None,
            llm_filter=None,
            llm_provider=None,
        )
        tools.append(tool_spec)

    # Create AgentSpec
    spec = core.AgentSpec(
        name=service_id,
        registry_url=registry_url,
        version=version,
        description="",
        http_port=http_port,
        http_host=http_host,
        namespace=namespace,
        tools=tools if tools else None,
        llm_agents=None,  # API services don't have LLM agents
        heartbeat_interval=heartbeat_interval,
    )

    logger.info(
        f"Built API AgentSpec: name={service_id}, routes_with_deps={len(tools)}, "
        f"registry={registry_url}"
    )

    return spec


async def _handle_api_mesh_event(event: Any, context: dict[str, Any]) -> None:
    """
    Handle a mesh event from the Rust core for API services.

    Dispatches to appropriate handler based on event type.
    """
    event_type = event.event_type

    if event_type == "agent_registered":
        logger.info(f"API service registered with ID: {event.agent_id}")

    elif event_type == "registration_failed":
        logger.error(f"API service registration failed: {event.error}")

    elif event_type == "dependency_available":
        await _handle_api_dependency_change(
            capability=event.capability,
            endpoint=event.endpoint,
            function_name=event.function_name,
            agent_id=event.agent_id,
            available=True,
            context=context,
        )

    elif event_type == "dependency_changed":
        await _handle_api_dependency_change(
            capability=event.capability,
            endpoint=event.endpoint,
            function_name=event.function_name,
            agent_id=event.agent_id,
            available=True,
            context=context,
        )

    elif event_type == "dependency_unavailable":
        await _handle_api_dependency_change(
            capability=event.capability,
            endpoint=None,
            function_name=None,
            agent_id=None,
            available=False,
            context=context,
        )

    elif event_type == "llm_tools_updated":
        # API services typically don't use LLM tools, but handle gracefully
        logger.debug(f"LLM tools update for API service (ignored): {event.function_id}")

    elif event_type == "health_check_due":
        logger.debug("Health check due for API service (not implemented yet)")

    elif event_type == "registry_disconnected":
        logger.warning(f"Registry disconnected for API service: {event.reason}")

    elif event_type == "shutdown":
        logger.info("Rust core shutdown event received for API service")

    else:
        logger.debug(f"Unhandled event type for API service: {event_type}")


async def _handle_api_dependency_change(
    capability: str,
    endpoint: Optional[str],
    function_name: Optional[str],
    agent_id: Optional[str],
    available: bool,
    context: dict[str, Any],
) -> None:
    """
    Handle dependency availability change for API services.

    Updates route wrappers with new/changed/removed dependencies.
    API services use route wrappers which have direct _mesh_update_dependency methods.
    """
    logger.info(
        f"API dependency change: {capability} -> "
        f"{'available' if available else 'unavailable'} "
        f"at {endpoint}/{function_name}"
    )

    from ...engine.decorator_registry import DecoratorRegistry
    from ...engine.unified_mcp_proxy import EnhancedUnifiedMCPProxy

    route_wrappers = DecoratorRegistry.get_all_route_wrappers()

    if not available:
        # Dependency became unavailable - clear it from all route wrappers
        for route_id, route_info in route_wrappers.items():
            dependencies = route_info.get("dependencies", [])
            wrapper = route_info.get("wrapper")

            if not wrapper or not hasattr(wrapper, "_mesh_update_dependency"):
                continue

            # Find which dependency index(es) match this capability
            for dep_index, dep_cap in enumerate(dependencies):
                if dep_cap == capability:
                    # Set to None to indicate unavailable
                    wrapper._mesh_update_dependency(dep_index, None)
                    logger.info(
                        f"Cleared dependency '{capability}' at index {dep_index} "
                        f"for route '{route_id}'"
                    )
        return

    # Dependency is available - update all route wrappers that need it
    for route_id, route_info in route_wrappers.items():
        dependencies = route_info.get("dependencies", [])
        wrapper = route_info.get("wrapper")

        if not wrapper or not hasattr(wrapper, "_mesh_update_dependency"):
            continue

        # Find which dependency index(es) match this capability
        for dep_index, dep_cap in enumerate(dependencies):
            if dep_cap == capability:
                # Check for self-dependency (rare for API services but handle it)
                current_service_id = context.get("service_id") or context.get(
                    "agent_id"
                )
                if not current_service_id:
                    # Use config resolver for consistent env var handling
                    current_service_id = get_config_value("MCP_MESH_AGENT_ID")

                is_self_dependency = (
                    current_service_id and agent_id and current_service_id == agent_id
                )

                if is_self_dependency:
                    # Self-dependency for API services - use SelfDependencyProxy
                    from ...engine.self_dependency_proxy import SelfDependencyProxy

                    # For API services, try to find the function in mesh tools
                    mesh_tools = DecoratorRegistry.get_mesh_tools()
                    wrapper_func = mesh_tools.get(function_name)

                    if wrapper_func:
                        proxy = SelfDependencyProxy(
                            wrapper_func.function, function_name
                        )
                        logger.debug(
                            f"Created SelfDependencyProxy for API route '{route_id}' "
                            f"dependency '{capability}'"
                        )
                    else:
                        # Fallback to HTTP proxy
                        proxy = EnhancedUnifiedMCPProxy(endpoint, function_name)
                        logger.debug(
                            f"Created EnhancedUnifiedMCPProxy (fallback) for API route "
                            f"'{route_id}' dependency '{capability}'"
                        )
                else:
                    # Cross-service dependency - create HTTP proxy
                    proxy = EnhancedUnifiedMCPProxy(endpoint, function_name)
                    logger.debug(
                        f"Created EnhancedUnifiedMCPProxy for API route '{route_id}' "
                        f"dependency '{capability}' -> {endpoint}"
                    )

                # Update the route wrapper
                wrapper._mesh_update_dependency(dep_index, proxy)
                logger.info(
                    f"Updated dependency '{capability}' at index {dep_index} "
                    f"for route '{route_id}' -> {endpoint}/{function_name}"
                )


async def rust_api_heartbeat_task(heartbeat_config: dict[str, Any]) -> None:
    """
    Rust-backed heartbeat task for API services that runs in FastAPI lifespan.

    This is a drop-in replacement for api_heartbeat_lifespan_task.
    Instead of running Python heartbeat pipeline, it starts the Rust core
    and listens for events.

    Args:
        heartbeat_config: Configuration containing service_id, interval, context
    """
    service_id = heartbeat_config.get("service_id", "unknown-api-service")
    context = heartbeat_config.get("context", {})
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    if standalone_mode:
        logger.info(
            f"Rust API heartbeat in standalone mode for service '{service_id}' "
            "(no registry communication)"
        )
        return

    try:
        core = _get_rust_core()
    except ImportError as e:
        logger.error(
            f"Rust core not available for API service '{service_id}': {e}. "
            "The mcp_mesh_core module must be built and installed."
        )
        raise RuntimeError(
            f"Rust core (mcp_mesh_core) is required but not available: {e}"
        ) from e

    logger.info(f"Starting Rust-backed heartbeat for API service '{service_id}'")

    try:
        # Build AgentSpec from API service context, passing service_id explicitly
        spec = _build_api_agent_spec(context, service_id=service_id)

        # Start Rust core runtime
        handle = core.start_agent(spec)
        logger.info(f"Rust core started for API service '{service_id}'")

        # Event loop - process events from Rust core
        while True:
            # Check for Python shutdown signal
            try:
                from ...shared.simple_shutdown import should_stop_heartbeat

                if should_stop_heartbeat():
                    logger.info(
                        f"Stopping Rust API heartbeat for service '{service_id}' due to shutdown"
                    )
                    handle.shutdown()
                    break
            except ImportError:
                pass

            try:
                # Wait for next event from Rust core with timeout
                # Timeout allows periodic shutdown checks
                try:
                    event = await asyncio.wait_for(handle.next_event(), timeout=1.0)
                except TimeoutError:
                    # No event in 1 second, loop back to check shutdown signal
                    continue

                if event.event_type == "shutdown":
                    logger.info(f"Rust core shutdown for API service '{service_id}'")
                    break

                # Handle the event
                await _handle_api_mesh_event(event, context)

            except Exception as e:
                logger.error(f"Error handling Rust event for API service: {e}")
                # Continue processing events

    except asyncio.CancelledError:
        logger.info(f"Rust API heartbeat task cancelled for service '{service_id}'")
        raise
    except Exception as e:
        logger.error(f"Rust API heartbeat failed for service '{service_id}': {e}")
        raise
