"""
Rust-backed heartbeat implementation.

Replaces the Python heartbeat loop with the Rust core runtime.
The Rust core handles:
- Registry communication (HEAD/POST heartbeats)
- Topology change detection
- Event emission

Python handles:
- DI updates when topology changes
- LLM tools updates
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
            logger.debug("Rust core module loaded successfully")
        except ImportError as e:
            logger.warning(f"Rust core not available: {e}")
            raise
    return _rust_core


def _build_agent_spec(context: dict[str, Any]) -> Any:
    """
    Build AgentSpec from Python context.

    Converts the Python decorator registry state into a Rust AgentSpec.
    """
    core = _get_rust_core()

    # Get agent config from context
    agent_config = context.get("agent_config", {})
    agent_id = context.get("agent_id", "unknown-agent")

    # Get registry URL
    from ...shared.config_resolver import get_config_value

    registry_url = get_config_value(
        "MCP_MESH_REGISTRY_URL",
        override=agent_config.get("registry_url"),
        default="http://localhost:8000",
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

    # Get HTTP config
    http_host = agent_config.get("http_host", "localhost")
    http_port = agent_config.get("http_port", 0)
    namespace = agent_config.get("namespace", "default")
    version = agent_config.get("version", "1.0.0")
    description = agent_config.get("description", "")

    # Build tool specs from decorator registry
    from ...engine.decorator_registry import DecoratorRegistry

    tools = []
    mesh_tools = DecoratorRegistry.get_mesh_tools()
    mesh_llm_agents = DecoratorRegistry.get_mesh_llm_agents()

    # Import FastMCP schema extractor for input schema extraction
    from ...utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

    # Get FastMCP server info from context (set by fastmcp-server-discovery step)
    # Convert to dict format expected by extract_from_fastmcp_servers
    fastmcp_server_info = context.get("fastmcp_server_info", [])
    fastmcp_servers = {}
    for server_info in fastmcp_server_info:
        server_name = server_info.get("server_name", "unknown")
        fastmcp_servers[server_name] = server_info
    logger.debug(
        f"FastMCP servers for schema extraction: {list(fastmcp_servers.keys())}"
    )

    for tool_name, decorated_func in mesh_tools.items():
        tool_metadata = decorated_func.metadata or {}
        current_function = decorated_func.function

        # Build dependency specs
        deps = []
        for dep_info in tool_metadata.get("dependencies", []):
            dep_spec = core.DependencySpec(
                capability=dep_info.get("capability", ""),
                tags=dep_info.get("tags", []),
                version=dep_info.get("version"),
            )
            deps.append(dep_spec)

        # Extract input schema from FastMCP tool (like heartbeat_preparation.py)
        # This is critical for LLM tool filtering - registry requires inputSchema
        input_schema = tool_metadata.get("input_schema")
        if input_schema is None:
            # Primary method: Extract from FastMCP server tool managers
            input_schema = FastMCPSchemaExtractor.extract_from_fastmcp_servers(
                current_function, fastmcp_servers
            )
            if input_schema:
                logger.debug(
                    f"📋 Extracted inputSchema for {tool_name} from FastMCP servers: {list(input_schema.get('properties', {}).keys())}"
                )
            else:
                # Fallback: Try direct _fastmcp_tool attribute
                input_schema = FastMCPSchemaExtractor.extract_input_schema(
                    current_function
                )
                if input_schema:
                    logger.debug(
                        f"📋 Extracted inputSchema for {tool_name} from _fastmcp_tool: {list(input_schema.get('properties', {}).keys())}"
                    )
                else:
                    logger.warning(f"⚠️ No inputSchema found for {tool_name}")
        input_schema_json = json.dumps(input_schema) if input_schema else None

        # Get LLM filter/provider from mesh_llm_agents by matching function name
        # (The @mesh.llm decorator stores these, not @mesh.tool)
        llm_filter_json = None
        llm_provider_json = None

        func_name = decorated_func.function.__name__
        for llm_agent_id, llm_metadata in mesh_llm_agents.items():
            if llm_metadata.function.__name__ == func_name:
                # Found matching LLM agent - extract filter config
                raw_filter = llm_metadata.config.get("filter")
                filter_mode = llm_metadata.config.get("filter_mode", "all")

                # Normalize filter to array format
                if raw_filter is None:
                    normalized_filter = []
                elif isinstance(raw_filter, list):
                    normalized_filter = raw_filter
                elif isinstance(raw_filter, dict):
                    normalized_filter = [raw_filter]
                elif isinstance(raw_filter, str):
                    normalized_filter = [raw_filter] if raw_filter else []
                else:
                    normalized_filter = []

                if normalized_filter:
                    llm_filter_data = {
                        "filter": normalized_filter,
                        "filter_mode": filter_mode,
                    }
                    llm_filter_json = json.dumps(llm_filter_data)
                    logger.debug(
                        f"🤖 Extracted llm_filter for {func_name}: {len(normalized_filter)} filters, mode={filter_mode}"
                    )

                # Extract llm_provider (v0.6.1: LLM Mesh Delegation)
                provider = llm_metadata.config.get("provider")
                if isinstance(provider, dict):
                    llm_provider_data = {
                        "capability": provider.get("capability", "llm"),
                        "tags": provider.get("tags", []),
                        "version": provider.get("version", ""),
                        "namespace": provider.get("namespace", "default"),
                    }
                    llm_provider_json = json.dumps(llm_provider_data)
                    logger.debug(
                        f"🔌 Extracted llm_provider for {func_name}: {llm_provider_data}"
                    )
                break

        tool_spec = core.ToolSpec(
            function_name=tool_name,
            capability=tool_metadata.get("capability", tool_name),
            version=tool_metadata.get("version", "1.0.0"),
            description=tool_metadata.get("description", ""),
            tags=tool_metadata.get("tags", []),
            dependencies=deps if deps else None,
            input_schema=input_schema_json,
            llm_filter=llm_filter_json,
            llm_provider=llm_provider_json,
        )
        tools.append(tool_spec)
        logger.info(
            f"📤 Tool '{tool_name}': llm_filter={llm_filter_json}, llm_provider={llm_provider_json}"
        )

    # Build LLM agent specs
    llm_agents = []

    for func_id, llm_metadata in mesh_llm_agents.items():
        # LLMAgentMetadata is a dataclass with .config dict
        config = llm_metadata.config if hasattr(llm_metadata, "config") else {}

        provider = config.get("provider", {})
        provider_json = json.dumps(provider) if provider else "{}"

        filter_spec = config.get("filter")
        filter_json = json.dumps(filter_spec) if filter_spec else None

        llm_spec = core.LlmAgentSpec(
            function_id=func_id,
            provider=provider_json,
            filter=filter_json,
            filter_mode=config.get("filter_mode", "all"),
            max_iterations=config.get("max_iterations", 1),
        )
        llm_agents.append(llm_spec)

    # Create AgentSpec
    spec = core.AgentSpec(
        name=agent_id,
        registry_url=registry_url,
        version=version,
        description=description,
        http_port=http_port,
        http_host=http_host,
        namespace=namespace,
        tools=tools if tools else None,
        llm_agents=llm_agents if llm_agents else None,
        heartbeat_interval=heartbeat_interval,
    )

    logger.info(
        f"Built AgentSpec: name={agent_id}, tools={len(tools)}, "
        f"llm_agents={len(llm_agents)}, registry={registry_url}"
    )

    return spec


async def _handle_mesh_event(event: Any, context: dict[str, Any]) -> None:
    """
    Handle a mesh event from the Rust core.

    Dispatches to appropriate handler based on event type.
    """
    event_type = event.event_type

    if event_type == "agent_registered":
        logger.info(f"Agent registered with ID: {event.agent_id}")

    elif event_type == "registration_failed":
        logger.error(f"Agent registration failed: {event.error}")

    elif event_type == "dependency_available":
        await _handle_dependency_change(
            capability=event.capability,
            endpoint=event.endpoint,
            function_name=event.function_name,
            agent_id=event.agent_id,
            available=True,
            context=context,
        )

    elif event_type == "dependency_changed":
        await _handle_dependency_change(
            capability=event.capability,
            endpoint=event.endpoint,
            function_name=event.function_name,
            agent_id=event.agent_id,
            available=True,
            context=context,
        )

    elif event_type == "dependency_unavailable":
        await _handle_dependency_change(
            capability=event.capability,
            endpoint=None,
            function_name=None,
            agent_id=None,
            available=False,
            context=context,
        )

    elif event_type == "llm_tools_updated":
        if event.tools is None:
            logger.warning(
                f"llm_tools_updated event for '{event.function_id}' has no tools data, skipping"
            )
        else:
            await _handle_llm_tools_update(
                function_id=event.function_id,
                tools=event.tools,
                context=context,
            )

    elif event_type == "llm_provider_available":
        if event.provider_info is None:
            logger.warning(
                "llm_provider_available event has no provider_info, skipping"
            )
        else:
            await _handle_llm_provider_update(
                provider_info=event.provider_info,
                context=context,
            )

    elif event_type == "health_check_due":
        # Python can perform health check and report back
        logger.debug("Health check due (not implemented yet)")

    elif event_type == "registry_disconnected":
        logger.warning(f"Registry disconnected: {event.reason}")

    elif event_type == "shutdown":
        logger.info("Rust core shutdown event received")

    else:
        logger.debug(f"Unhandled event type: {event_type}")


async def _handle_dependency_change(
    capability: str,
    endpoint: Optional[str],
    function_name: Optional[str],
    agent_id: Optional[str],
    available: bool,
    context: dict[str, Any],
) -> None:
    """
    Handle dependency availability change.

    Updates the DI system with new/changed/removed dependencies.
    This reuses the existing DependencyResolutionStep logic.
    """
    logger.info(
        f"Dependency change: {capability} -> "
        f"{'available' if available else 'unavailable'} "
        f"at {endpoint}/{function_name}"
    )

    # Import DI components
    from ...engine.decorator_registry import DecoratorRegistry
    from ...engine.dependency_injector import get_global_injector
    from ...engine.unified_mcp_proxy import EnhancedUnifiedMCPProxy

    injector = get_global_injector()

    if not available:
        # Dependency became unavailable - unregister it
        # Find all dependency keys for this capability
        if hasattr(injector, "_dependencies"):
            keys_to_remove = [
                key for key in injector._dependencies.keys() if capability in key
            ]
            for dep_key in keys_to_remove:
                await injector.unregister_dependency(dep_key)
                logger.info(f"Unregistered dependency: {dep_key}")
        return

    # Dependency is available - create proxy and register
    # Map tool names to func_ids
    mesh_tools = DecoratorRegistry.get_mesh_tools()
    tool_name_to_func_id = {}
    for tool_name, decorated_func in mesh_tools.items():
        func = decorated_func.function
        func_id = f"{func.__module__}.{func.__qualname__}"
        tool_name_to_func_id[tool_name] = func_id

    # Find which functions depend on this capability
    for tool_name, decorated_func in mesh_tools.items():
        tool_metadata = decorated_func.metadata or {}
        dependencies = tool_metadata.get("dependencies", [])

        for dep_index, dep_info in enumerate(dependencies):
            if dep_info.get("capability") == capability:
                func_id = tool_name_to_func_id.get(tool_name, tool_name)
                dep_key = f"{func_id}:dep_{dep_index}"

                # Check for self-dependency
                import os

                current_agent_id = None
                try:
                    config = DecoratorRegistry.get_resolved_agent_config()
                    current_agent_id = config.get("agent_id")
                except Exception:
                    current_agent_id = os.getenv("MCP_MESH_AGENT_ID")

                is_self_dependency = (
                    current_agent_id and agent_id and current_agent_id == agent_id
                )

                if is_self_dependency:
                    # Create self-dependency proxy
                    from ...engine.self_dependency_proxy import \
                        SelfDependencyProxy

                    wrapper_func = mesh_tools.get(function_name)
                    if wrapper_func:
                        proxy = SelfDependencyProxy(
                            wrapper_func.function, function_name
                        )
                        logger.debug(f"Created SelfDependencyProxy for {capability}")
                    else:
                        # Fallback to HTTP proxy
                        proxy = EnhancedUnifiedMCPProxy(endpoint, function_name)
                        logger.debug(
                            f"Created EnhancedUnifiedMCPProxy (fallback) for {capability}"
                        )
                else:
                    # Create cross-service proxy
                    kwargs_config = dep_info.get("kwargs", {})
                    proxy = EnhancedUnifiedMCPProxy(
                        endpoint, function_name, kwargs_config=kwargs_config
                    )
                    logger.debug(
                        f"Created EnhancedUnifiedMCPProxy for {capability} -> {endpoint}"
                    )

                await injector.register_dependency(dep_key, proxy)
                logger.info(f"Registered dependency: {dep_key}")


async def _handle_llm_tools_update(
    function_id: str,
    tools: list,
    context: dict[str, Any],
) -> None:
    """
    Handle LLM tools update event.

    Updates the LLM tools registry for the given function via the DI system.
    """
    logger.info(f"LLM tools update for {function_id}: {len(tools)} tools")

    # Import injector
    from ...engine.dependency_injector import get_global_injector

    # Convert tools to the expected format (using "name" for OpenAPI contract)
    tool_list = []
    for tool in tools:
        tool_info = {
            "name": tool.function_name,  # OpenAPI contract uses "name" not "function_name"
            "capability": tool.capability,
            "endpoint": tool.endpoint,
            "agent_id": tool.agent_id,
            "input_schema": (
                json.loads(tool.input_schema) if tool.input_schema else None
            ),
        }
        tool_list.append(tool_info)

    # Update LLM tools via the dependency injector
    injector = get_global_injector()
    llm_tools = {function_id: tool_list}
    injector.update_llm_tools(llm_tools)
    logger.debug(f"Updated {len(tool_list)} LLM tools for {function_id}")


async def _handle_llm_provider_update(
    provider_info: Any,
    context: dict[str, Any],
) -> None:
    """
    Handle LLM provider resolution event.

    Updates the LLM provider for the given function via the DI system.
    """
    function_id = provider_info.function_id
    logger.info(
        f"LLM provider resolved for {function_id}: "
        f"{provider_info.function_name} at {provider_info.endpoint}"
    )

    # Import injector
    from ...engine.dependency_injector import get_global_injector
    from ...engine.unified_mcp_proxy import EnhancedUnifiedMCPProxy

    # Create proxy for the LLM provider
    proxy = EnhancedUnifiedMCPProxy(
        provider_info.endpoint,
        provider_info.function_name,
    )

    # Register as the LLM provider for this function
    injector = get_global_injector()
    provider_key = f"{function_id}:llm_provider"
    await injector.register_dependency(provider_key, proxy)

    # Also store provider metadata for the mesh agent to use (using "name" for OpenAPI contract)
    llm_providers = {
        function_id: {
            "agent_id": provider_info.agent_id,
            "endpoint": provider_info.endpoint,
            "name": provider_info.function_name,  # OpenAPI contract uses "name"
            "model": provider_info.model,
        }
    }
    injector.process_llm_providers(llm_providers)
    logger.debug(f"Registered LLM provider for {function_id}")


async def rust_heartbeat_task(heartbeat_config: dict[str, Any]) -> None:
    """
    Rust-backed heartbeat task that runs in FastAPI lifespan.

    This is a drop-in replacement for heartbeat_lifespan_task.
    Instead of running Python heartbeat loop, it starts the Rust core
    and listens for events.

    Args:
        heartbeat_config: Configuration containing agent_id, interval, context
    """
    agent_id = heartbeat_config["agent_id"]
    context = heartbeat_config["context"]
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    if standalone_mode:
        logger.info(
            f"Rust heartbeat in standalone mode for agent '{agent_id}' "
            "(no registry communication)"
        )
        return

    try:
        core = _get_rust_core()
    except ImportError as e:
        logger.error(
            f"Rust core not available for agent '{agent_id}': {e}. "
            "The mcp_mesh_core module must be built and installed."
        )
        raise RuntimeError(
            f"Rust core (mcp_mesh_core) is required but not available: {e}"
        ) from e

    logger.info(f"Starting Rust-backed heartbeat for agent '{agent_id}'")

    try:
        # Build AgentSpec from context
        spec = _build_agent_spec(context)

        # Start Rust core runtime
        handle = core.start_agent(spec)
        logger.info(f"Rust core started for agent '{agent_id}'")

        # Event loop - process events from Rust core
        while True:
            # Check for Python shutdown signal
            try:
                from ...shared.simple_shutdown import should_stop_heartbeat

                if should_stop_heartbeat():
                    logger.info(
                        f"Stopping Rust heartbeat for agent '{agent_id}' due to shutdown"
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
                    logger.info(f"Rust core shutdown for agent '{agent_id}'")
                    break

                # Handle the event
                await _handle_mesh_event(event, context)

            except Exception as e:
                logger.error(f"Error handling Rust event: {e}")
                # Continue processing events

    except asyncio.CancelledError:
        logger.info(f"Rust heartbeat task cancelled for agent '{agent_id}'")
        raise
    except Exception as e:
        logger.error(f"Rust heartbeat failed for agent '{agent_id}': {e}")
        raise
