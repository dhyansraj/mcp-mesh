"""
Rust-backed heartbeat implementation for A2A services (issue #903 Phase 1B).

Sibling of ``api_heartbeat/rust_api_heartbeat.py`` (which handles
``@mesh.route`` services). Both delegate registry communication to the
Rust core; the difference is the AgentSpec shape:

  * API services: ``agent_type="api"``, no ``surfaces`` field.
  * A2A services: ``agent_type="a2a"`` + ``surfaces=<json>`` array.

The dependency-change handler reuses the dependency-injector path
(mirrors ``mcp_heartbeat/rust_heartbeat.py``) because ``@mesh.a2a``
wires DI via ``injector.create_injection_wrapper`` — i.e., A2A
handlers live in the global injector's function registry, NOT in the
``DecoratorRegistry.get_all_route_wrappers()`` mapping that
``rust_api_heartbeat`` walks.
"""

import asyncio
import json
import logging
import re
from typing import Any, Optional

# Matches the registry/SDK convention of "{base}-{8-hex-chars}" at the end
# of a service_id. Used to strip the suffix and recover the base name.
_A2A_SERVICE_ID_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$")

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
            logger.debug("Rust core module loaded successfully for A2A heartbeat")
        except ImportError as e:
            logger.warning(f"Rust core not available for A2A heartbeat: {e}")
            raise
    return _rust_core


def _build_a2a_agent_spec(context: dict[str, Any], service_id: Optional[str] = None) -> Any:
    """
    Build AgentSpec from A2A service context.

    Emits ``agent_type="a2a"`` and serializes the surfaces array onto
    the Rust AgentSpec's ``surfaces`` field (JSON string). Same shape
    as the mcp-startup rust_heartbeat path uses for ``@mesh.agent`` +
    ``@mesh.a2a`` agents — guarantees the registry's
    ``MeshAgentRegistration.surfaces`` JSONB column lands a consistent
    shape regardless of which entry-point the agent uses.

    Args:
        context: Pipeline context (with ``a2a_surfaces``, ``display_config``,
                 ``agent_config``).
        service_id: Service ID from heartbeat config (passed explicitly).
    """
    core = _get_rust_core()

    if not service_id:
        service_id = context.get("service_id") or context.get(
            "agent_id", "unknown-a2a-service"
        )
    display_config = context.get("display_config", {})
    # Prefer pipeline-context override (test seams), fall back to the
    # DecoratorRegistry's resolved config so the FastAPI app title +
    # any update_agent_config(...) writes from a2a_server_setup.py
    # land in the heartbeat. Without this fallback, base_name strips
    # the service_id suffix and produces names like "a2a" instead of
    # the actual app title.
    agent_config = context.get("agent_config")
    if not agent_config:
        from ...engine.decorator_registry import DecoratorRegistry

        agent_config = DecoratorRegistry.get_resolved_agent_config() or {}

    from ...shared.config_resolver import get_config_value
    from ...shared.defaults import MeshDefaults

    registry_url = get_config_value(
        "MCP_MESH_REGISTRY_URL",
        override=agent_config.get("registry_url"),
    )

    heartbeat_interval = int(
        get_config_value(
            "MCP_MESH_HEALTH_INTERVAL",
            override=agent_config.get("health_interval"),
            default=MeshDefaults.HEALTH_INTERVAL,
        )
    )

    http_host = display_config.get("display_host", "127.0.0.1")
    http_port = display_config.get("display_port", 8080)
    namespace = agent_config.get("namespace", "default")
    version = agent_config.get("version", "1.0.0")

    # Build tool specs for A2A surfaces. Each surface's underlying handler
    # may declare cross-agent dependencies (e.g., ``date_service``); we
    # surface those so the Rust core resolves them and the injector wires
    # the proxies on dependency_available events. The function_name is the
    # surface's skill_id so the registry can correlate updates.
    from ...engine.decorator_registry import DecoratorRegistry

    tools = []
    a2a_decorators = DecoratorRegistry.get_all_by_type("mesh_a2a")
    for func_id, decorated in a2a_decorators.items():
        meta = decorated.metadata or {}
        deps_meta = meta.get("dependencies") or []

        deps = []
        for dep in deps_meta:
            cap = dep.get("capability") if isinstance(dep, dict) else dep
            if not cap:
                continue
            dep_tags = dep.get("tags", []) if isinstance(dep, dict) else []
            dep_version = dep.get("version") if isinstance(dep, dict) else None
            dep_spec = core.DependencySpec(
                capability=cap,
                tags=json.dumps(dep_tags),
                version=dep_version,
            )
            deps.append(dep_spec)

        if not deps:
            continue

        skill_id = meta.get("skill_id", func_id)
        tool_spec = core.ToolSpec(
            function_name=skill_id,
            capability="",  # A2A surfaces consume capabilities, not provide them
            version="1.0.0",
            description=meta.get("description") or "",
            tags=meta.get("tags") or [],
            dependencies=deps if deps else None,
            input_schema=None,
            llm_filter=None,
            llm_provider=None,
        )
        tools.append(tool_spec)

    # Derive base name from service_id (strip the "-{uuid8}" suffix if present).
    base_name = agent_config.get("name")
    if not base_name:
        stripped = _A2A_SERVICE_ID_SUFFIX_RE.sub("", service_id)
        base_name = stripped if stripped != service_id else service_id

    # Surfaces JSON is the centerpiece — the registry consumes it to
    # populate the ``MeshAgentRegistration.surfaces`` JSONB column and
    # stamp FQDNs onto each surface's public_url before responding.
    a2a_surfaces = context.get("a2a_surfaces")
    if not a2a_surfaces:
        try:
            from ...engine.a2a_surfaces import collect_a2a_surfaces

            a2a_surfaces = collect_a2a_surfaces()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"Could not collect a2a surfaces: {e}")
            a2a_surfaces = []

    surfaces_json = json.dumps(a2a_surfaces) if a2a_surfaces else None

    spec_kwargs: dict[str, Any] = dict(
        name=base_name,
        registry_url=registry_url,
        version=version,
        description="",
        http_port=http_port,
        http_host=http_host,
        namespace=namespace,
        agent_type="a2a",
        tools=tools if tools else None,
        llm_agents=None,
        heartbeat_interval=heartbeat_interval,
        agent_id=service_id,
        # Issue #972: this pipeline only fires for agents bootstrapped via
        # the A2A surface path (no @mesh.agent / @mesh.tool decorators), so
        # producer is true iff we have at least one surface to publish.
        # Consumer is always false here — consumer-side bridges live on
        # @mesh.tool wrappers that ship through the mcp_heartbeat path.
        a2a_producer=bool(a2a_surfaces),
        a2a_consumer=False,
    )
    if surfaces_json is not None:
        spec_kwargs["surfaces"] = surfaces_json

    spec = core.AgentSpec(**spec_kwargs)

    logger.info(
        f"Built A2A AgentSpec: name={base_name}, agent_id={service_id}, "
        f"agent_type=a2a, surfaces={len(a2a_surfaces)}, "
        f"tools_with_deps={len(tools)}, registry={registry_url}"
    )

    return spec


async def _handle_a2a_mesh_event(event: Any, context: dict[str, Any]) -> None:
    """
    Handle a mesh event from the Rust core for A2A services.

    Dispatches to the dependency-injector path because ``@mesh.a2a``
    wires DI via ``injector.create_injection_wrapper`` (functions live
    in the global injector's function registry).
    """
    event_type = event.event_type

    if event_type == "agent_registered":
        logger.info(f"A2A service registered with ID: {event.agent_id}")

    elif event_type == "registration_failed":
        logger.error(f"A2A service registration failed: {event.error}")

    elif event_type == "dependency_available":
        await _handle_a2a_dependency_change(
            capability=event.capability,
            endpoint=event.endpoint,
            function_name=event.function_name,
            agent_id=event.agent_id,
            available=True,
            context=context,
            producer_kwargs=getattr(event, "kwargs", None),
        )

    elif event_type == "dependency_changed":
        await _handle_a2a_dependency_change(
            capability=event.capability,
            endpoint=event.endpoint,
            function_name=event.function_name,
            agent_id=event.agent_id,
            available=True,
            context=context,
            producer_kwargs=getattr(event, "kwargs", None),
        )

    elif event_type == "dependency_unavailable":
        await _handle_a2a_dependency_change(
            capability=event.capability,
            endpoint=None,
            function_name=None,
            agent_id=None,
            available=False,
            context=context,
            producer_kwargs=None,
        )

    elif event_type == "llm_tools_updated":
        logger.debug(
            f"LLM tools update for A2A service (ignored): {event.function_id}"
        )

    elif event_type == "health_check_due":
        logger.debug("Health check due for A2A service (not implemented yet)")

    elif event_type == "registry_disconnected":
        logger.warning(f"Registry disconnected for A2A service: {event.reason}")

    elif event_type == "shutdown":
        logger.info("Rust core shutdown event received for A2A service")

    else:
        logger.debug(f"Unhandled event type for A2A service: {event_type}")


async def _handle_a2a_dependency_change(
    capability: str,
    endpoint: Optional[str],
    function_name: Optional[str],
    agent_id: Optional[str],
    available: bool,
    context: dict[str, Any],
    producer_kwargs: Optional[str] = None,
) -> None:
    """
    Handle dependency availability change for A2A services.

    Walks ``DecoratorRegistry.get_all_by_type("mesh_a2a")`` and updates
    each surface's underlying injection wrapper via
    ``_mesh_update_dependency``. ``producer_kwargs`` is the producer's
    @mesh.tool kwargs (JSON string) so the proxy honours producer-side
    streaming/timeout config.
    """
    logger.info(
        f"A2A dependency change: {capability} -> "
        f"{'available' if available else 'unavailable'} "
        f"at {endpoint}/{function_name}"
    )

    from ...engine.decorator_registry import DecoratorRegistry
    from ...engine.unified_mcp_proxy import EnhancedUnifiedMCPProxy

    parsed_producer_kwargs: dict = {}
    if producer_kwargs:
        try:
            parsed = json.loads(producer_kwargs)
        except (TypeError, ValueError) as e:
            logger.warning(
                f"Could not parse producer kwargs for {capability}: {e}; "
                f"falling back to empty config"
            )
        else:
            if isinstance(parsed, dict):
                parsed_producer_kwargs = parsed
            elif parsed is not None:
                logger.warning(
                    f"Producer kwargs for {capability} parsed to "
                    f"{type(parsed).__name__}, expected dict; "
                    "falling back to empty config"
                )

    a2a_decorators = DecoratorRegistry.get_all_by_type("mesh_a2a")

    for func_id, decorated in a2a_decorators.items():
        meta = decorated.metadata or {}
        deps_meta = meta.get("dependencies") or []
        # Locate the active wrapper. The decorator stamps
        # ``_mesh_injection_wrapper`` on the original target after wrapping.
        target = decorated.function
        wrapper = getattr(target, "_mesh_injection_wrapper", None) or target

        if not hasattr(wrapper, "_mesh_update_dependency"):
            continue

        for dep_index, dep in enumerate(deps_meta):
            dep_cap = dep.get("capability") if isinstance(dep, dict) else dep
            if dep_cap != capability:
                continue

            if not available:
                wrapper._mesh_update_dependency(dep_index, None)
                logger.info(
                    f"Cleared dependency '{capability}' at index {dep_index} "
                    f"for A2A surface '{func_id}'"
                )
                continue

            current_service_id = context.get("service_id") or context.get("agent_id")
            if not current_service_id:
                from ...shared.config_resolver import get_config_value

                current_service_id = get_config_value("MCP_MESH_AGENT_ID")

            is_self_dependency = (
                current_service_id and agent_id and current_service_id == agent_id
            )

            if is_self_dependency:
                from ...engine.self_dependency_proxy import SelfDependencyProxy

                mesh_tools = DecoratorRegistry.get_mesh_tools()
                wrapper_func = mesh_tools.get(function_name)

                if wrapper_func:
                    proxy = SelfDependencyProxy(
                        wrapper_func.function, function_name
                    )
                    logger.debug(
                        f"Created SelfDependencyProxy for A2A surface '{func_id}' "
                        f"dependency '{capability}'"
                    )
                else:
                    proxy = EnhancedUnifiedMCPProxy(
                        endpoint,
                        function_name,
                        kwargs_config=dict(parsed_producer_kwargs),
                    )
                    logger.debug(
                        f"Created EnhancedUnifiedMCPProxy (fallback) for A2A "
                        f"surface '{func_id}' dependency '{capability}'"
                    )
            else:
                proxy = EnhancedUnifiedMCPProxy(
                    endpoint,
                    function_name,
                    kwargs_config=dict(parsed_producer_kwargs),
                )
                logger.debug(
                    f"Created EnhancedUnifiedMCPProxy for A2A surface '{func_id}' "
                    f"dependency '{capability}' -> {endpoint}"
                )

            wrapper._mesh_update_dependency(dep_index, proxy)
            logger.info(
                f"Updated dependency '{capability}' at index {dep_index} "
                f"for A2A surface '{func_id}' -> {endpoint}/{function_name}"
            )


async def rust_a2a_heartbeat_task(heartbeat_config: dict[str, Any]) -> None:
    """
    Rust-backed heartbeat task for A2A services that runs in FastAPI lifespan.

    Drop-in replacement for ``a2a_heartbeat_lifespan_task``. Mirrors
    ``rust_api_heartbeat_task`` for the A2A flow.

    Args:
        heartbeat_config: Configuration containing service_id, interval,
                         and context (with ``a2a_surfaces``).
    """
    service_id = heartbeat_config.get("service_id", "unknown-a2a-service")
    context = heartbeat_config.get("context", {})
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    if standalone_mode:
        logger.info(
            f"Rust A2A heartbeat in standalone mode for service '{service_id}' "
            "(no registry communication)"
        )
        return

    try:
        core = _get_rust_core()
    except ImportError as e:
        logger.error(
            f"Rust core not available for A2A service '{service_id}': {e}. "
            "The mcp_mesh_core module must be built and installed."
        )
        raise RuntimeError(
            f"Rust core (mcp_mesh_core) is required but not available: {e}"
        ) from e

    logger.info(f"Starting Rust-backed heartbeat for A2A service '{service_id}'")

    handle = None
    try:
        spec = _build_a2a_agent_spec(context, service_id=service_id)

        handle = core.start_agent(spec)
        logger.info(f"Rust core started for A2A service '{service_id}'")

        # Track this handle in the process-wide registry so atexit can drain
        # it before Py_Finalize. Closes the pyo3-async-runtimes
        # Python::attach race during abnormal exits. See issue #877.
        try:
            from ...shared.simple_shutdown import register_rust_agent_handle

            register_rust_agent_handle(handle)
        except Exception as e:  # pragma: no cover - never block startup
            logger.debug(f"Could not register handle for atexit drain: {e}")

        # Track consecutive failures from ``handle.next_event()`` /
        # ``_handle_a2a_mesh_event`` so a persistently-failing event
        # source doesn't tight-loop on logger.error. Backoff is
        # exponential per attempt and capped; on too many in a row we
        # surface the failure to the caller instead of swallowing it
        # forever.
        consecutive_failures = 0
        MAX_CONSECUTIVE = 10

        while True:
            try:
                from ...shared.simple_shutdown import should_stop_heartbeat

                if should_stop_heartbeat():
                    logger.info(
                        f"Stopping Rust A2A heartbeat for service '{service_id}' due to shutdown"
                    )
                    handle.shutdown()
                    break
            except ImportError:
                pass

            try:
                # Pull the next event. The 1s liveness timeout lives INSIDE the
                # Rust future (issue #1256): a `None` return is a timeout tick
                # that lets us re-check the shutdown signal. We must NOT wrap
                # this in asyncio.wait_for — an external cancellation could drop
                # a dequeued event in the recv→deliver window, permanently
                # stalling a dependency edge.
                event = await handle.next_event()
                if event is None:
                    # Liveness tick, no event; loop back to check shutdown.
                    continue

                if event.event_type == "shutdown":
                    logger.info(f"Rust core shutdown for A2A service '{service_id}'")
                    break

                await _handle_a2a_mesh_event(event, context)
                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                logger.error(
                    f"Error handling Rust event for A2A service "
                    f"({consecutive_failures}/{MAX_CONSECUTIVE}): {e}"
                )
                if consecutive_failures >= MAX_CONSECUTIVE:
                    logger.error(
                        f"Rust A2A event loop exiting after {MAX_CONSECUTIVE} "
                        f"consecutive failures for service '{service_id}'"
                    )
                    raise
                # Exponential backoff capped at 5s so we don't burn CPU
                # while still recovering quickly from transient blips.
                backoff = min(0.5 * (2 ** (consecutive_failures - 1)), 5.0)
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise

    except asyncio.CancelledError:
        logger.info(f"Rust A2A heartbeat task cancelled for service '{service_id}'")
        raise
    except Exception as e:
        logger.error(f"Rust A2A heartbeat failed for service '{service_id}': {e}")
        raise
    finally:
        if handle is not None:
            try:
                handle.shutdown()
                try:
                    await asyncio.sleep(0.2)
                except (asyncio.CancelledError, RuntimeError):
                    import time

                    time.sleep(0.2)
                logger.debug(
                    f"Rust core shutdown complete for A2A service '{service_id}'"
                )
                try:
                    from ...shared.simple_shutdown import (
                        unregister_rust_agent_handle,
                    )

                    unregister_rust_agent_handle(handle)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Error during Rust core shutdown for A2A service: {e}")
