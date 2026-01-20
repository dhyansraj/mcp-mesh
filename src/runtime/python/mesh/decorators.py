"""
Mesh decorators implementation - dual decorator architecture.

Provides @mesh.tool and @mesh.agent decorators with clean separation of concerns.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

# Import from _mcp_mesh for registry and runtime integration
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.shared.config_resolver import ValidationRule, get_config_value
from _mcp_mesh.shared.simple_shutdown import start_blocking_loop_with_shutdown_support

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global reference to the runtime processor, set by mcp_mesh runtime
_runtime_processor: Any | None = None

# Shared agent ID for all functions in the same process
_SHARED_AGENT_ID: str | None = None


def _start_uvicorn_immediately(http_host: str, http_port: int):
    """
    Start basic uvicorn server immediately to prevent Python interpreter shutdown.

    This prevents the DNS threading conflicts by ensuring uvicorn takes control
    before the script ends and Python enters shutdown state.
    """
    logger.debug(
        f"🎯 IMMEDIATE UVICORN: _start_uvicorn_immediately() called with host={http_host}, port={http_port}"
    )

    try:
        import asyncio
        import threading
        import time

        import uvicorn
        from fastapi import FastAPI, Response

        logger.debug(
            "📦 IMMEDIATE UVICORN: Successfully imported uvicorn, FastAPI, threading, asyncio"
        )

        # Get stored FastMCP lifespan if available
        fastmcp_lifespan = None
        try:
            from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

            fastmcp_lifespan = DecoratorRegistry.get_fastmcp_lifespan()
            if fastmcp_lifespan:
                logger.debug(
                    "✅ IMMEDIATE UVICORN: Found stored FastMCP lifespan, will integrate with FastAPI"
                )
            else:
                logger.debug(
                    "🔍 IMMEDIATE UVICORN: No FastMCP lifespan found, creating basic FastAPI app"
                )
        except Exception as e:
            logger.warning(f"⚠️ IMMEDIATE UVICORN: Failed to get FastMCP lifespan: {e}")

        # Create FastAPI app with FastMCP lifespan if available
        if fastmcp_lifespan:
            app = FastAPI(title="MCP Mesh Agent (Starting)", lifespan=fastmcp_lifespan)
            logger.debug(
                "📦 IMMEDIATE UVICORN: Created FastAPI app with FastMCP lifespan integration"
            )
        else:
            app = FastAPI(title="MCP Mesh Agent (Starting)")
            logger.debug("📦 IMMEDIATE UVICORN: Created minimal FastAPI app")

        # Add trace context middleware for distributed tracing BEFORE app starts
        # This must be done before uvicorn.run() since middleware can't be added after start
        try:
            import os

            tracing_enabled = os.getenv(
                "MCP_MESH_DISTRIBUTED_TRACING_ENABLED", "false"
            ).lower() in ("true", "1", "yes")
            if tracing_enabled:
                # Use pure ASGI middleware for proper SSE header injection (Issue #310)
                class TraceContextMiddleware:
                    """Pure ASGI middleware for trace context and header injection.

                    This middleware:
                    1. Extracts trace context from incoming request headers AND arguments
                    2. Strips trace fields (_trace_id, _parent_span) from arguments to avoid validation errors
                    3. Sets up trace context for the request lifecycle
                    4. Injects trace headers into the response (works with SSE)
                    """

                    def __init__(self, app):
                        self.app = app

                    async def __call__(self, scope, receive, send):
                        if scope["type"] != "http":
                            await self.app(scope, receive, send)
                            return

                        path = scope.get("path", "")
                        logger.debug(f"[TRACE] Processing request {path}")

                        # Extract and set trace context from request headers
                        trace_id = None
                        span_id = None
                        parent_span = None

                        try:
                            from _mcp_mesh.tracing.context import TraceContext
                            from _mcp_mesh.tracing.trace_context_helper import (
                                TraceContextHelper,
                                get_header_case_insensitive,
                            )

                            # Extract trace headers from request (case-insensitive)
                            headers_list = scope.get("headers", [])
                            incoming_trace_id = get_header_case_insensitive(
                                headers_list, "x-trace-id"
                            )
                            incoming_parent_span = get_header_case_insensitive(
                                headers_list, "x-parent-span"
                            )

                            # Setup trace context from headers
                            trace_context = {
                                "trace_id": (
                                    incoming_trace_id if incoming_trace_id else None
                                ),
                                "parent_span": (
                                    incoming_parent_span
                                    if incoming_parent_span
                                    else None
                                ),
                            }
                            TraceContextHelper.setup_request_trace_context(
                                trace_context, logger
                            )

                            # Get trace IDs to inject into response
                            current_trace = TraceContext.get_current()
                            if current_trace:
                                trace_id = current_trace.trace_id
                                span_id = current_trace.span_id
                                parent_span = current_trace.parent_span
                        except Exception as e:
                            logger.warning(f"Failed to set trace context: {e}")

                        # Create body-modifying receive wrapper to strip trace fields from arguments
                        # This handles the case where trace context is passed in JSON-RPC arguments
                        import json as json_module

                        async def receive_with_trace_stripping():
                            message = await receive()
                            if message["type"] == "http.request":
                                body = message.get("body", b"")
                                if body:
                                    try:
                                        payload = json_module.loads(
                                            body.decode("utf-8")
                                        )
                                        if payload.get("method") == "tools/call":
                                            arguments = payload.get("params", {}).get(
                                                "arguments", {}
                                            )

                                            # Extract trace context from arguments if not in headers
                                            nonlocal trace_id, span_id, parent_span
                                            if not trace_id and arguments.get(
                                                "_trace_id"
                                            ):
                                                try:
                                                    from _mcp_mesh.tracing.context import (
                                                        TraceContext,
                                                    )
                                                    from _mcp_mesh.tracing.trace_context_helper import (
                                                        TraceContextHelper,
                                                    )

                                                    arg_trace_id = arguments.get(
                                                        "_trace_id"
                                                    )
                                                    arg_parent_span = arguments.get(
                                                        "_parent_span"
                                                    )
                                                    trace_context = {
                                                        "trace_id": arg_trace_id,
                                                        "parent_span": arg_parent_span,
                                                    }
                                                    TraceContextHelper.setup_request_trace_context(
                                                        trace_context, logger
                                                    )
                                                    current_trace = (
                                                        TraceContext.get_current()
                                                    )
                                                    if current_trace:
                                                        trace_id = (
                                                            current_trace.trace_id
                                                        )
                                                        span_id = current_trace.span_id
                                                        parent_span = (
                                                            current_trace.parent_span
                                                        )
                                                except Exception:
                                                    pass

                                            # Strip trace context fields from arguments
                                            if (
                                                "_trace_id" in arguments
                                                or "_parent_span" in arguments
                                            ):
                                                arguments.pop("_trace_id", None)
                                                arguments.pop("_parent_span", None)
                                                modified_body = json_module.dumps(
                                                    payload
                                                ).encode("utf-8")
                                                logger.debug(
                                                    "[TRACE] Stripped trace fields from arguments"
                                                )
                                                return {
                                                    **message,
                                                    "body": modified_body,
                                                }
                                    except Exception as e:
                                        logger.debug(
                                            f"[TRACE] Failed to process body: {e}"
                                        )
                            return message

                        # Wrap send to inject headers before response starts
                        async def send_with_trace_headers(message):
                            if message["type"] == "http.response.start" and trace_id:
                                # Add trace headers to the response
                                headers = list(message.get("headers", []))
                                headers.append((b"x-trace-id", trace_id.encode()))
                                if span_id:
                                    headers.append((b"x-span-id", span_id.encode()))
                                if parent_span:
                                    headers.append(
                                        (b"x-parent-span-id", parent_span.encode())
                                    )
                                message = {**message, "headers": headers}
                            await send(message)

                        await self.app(
                            scope, receive_with_trace_stripping, send_with_trace_headers
                        )

                app.add_middleware(TraceContextMiddleware)
                logger.debug(
                    "📦 IMMEDIATE UVICORN: Added trace context middleware for distributed tracing"
                )
        except Exception as e:
            logger.warning(
                f"⚠️ IMMEDIATE UVICORN: Failed to add trace context middleware: {e}"
            )

        # Add K8s health endpoints using health_check_manager
        from _mcp_mesh.shared.health_check_manager import (
            build_health_response,
            build_livez_response,
            build_ready_response,
        )

        @app.get("/health")
        @app.head("/health")
        async def health(response: Response):
            """Health check endpoint that supports custom health checks."""
            data, status_code = build_health_response(agent_name="mcp-mesh-agent")
            response.status_code = status_code
            return data

        @app.get("/ready")
        @app.head("/ready")
        async def ready(response: Response):
            """Kubernetes readiness probe - service ready to serve traffic."""
            data, status_code = build_ready_response(agent_name="mcp-mesh-agent")
            response.status_code = status_code
            return data

        @app.get("/livez")
        @app.head("/livez")
        async def livez():
            """Kubernetes liveness probe - always returns 200 if app is running."""
            return build_livez_response(agent_name="mcp-mesh-agent")

        @app.get("/immediate-status")
        def immediate_status():
            return {
                "immediate_uvicorn": True,
                "message": "This server was started immediately in decorator",
            }

        logger.debug("📦 IMMEDIATE UVICORN: Added status endpoints")

        # Port handling:
        # - http_port=0 explicitly means auto-assign (let uvicorn choose)
        # - http_port>0 means use that specific port
        # Note: The default is 8080 only if http_port was never specified,
        # which is handled upstream in the @mesh.agent decorator
        port = http_port

        logger.debug(
            f"🚀 IMMEDIATE UVICORN: Starting uvicorn server on {http_host}:{port}"
        )

        # Use uvicorn.run() for proper signal handling (enables FastAPI lifespan shutdown)
        logger.debug(
            "⚡ IMMEDIATE UVICORN: Starting server with uvicorn.run() for proper signal handling"
        )

        # Start uvicorn server in background thread (NON-daemon to keep process alive)
        def run_server():
            """Run uvicorn server in background thread with proper signal handling."""
            try:
                logger.debug(
                    f"🌟 IMMEDIATE UVICORN: Starting server on {http_host}:{port}"
                )
                # Use uvicorn.run() instead of Server().run() for proper signal handling
                uvicorn.run(
                    app,
                    host=http_host,
                    port=port,
                    log_level="info",
                    timeout_graceful_shutdown=30,  # Allow time for registry cleanup
                    access_log=False,  # Reduce noise
                    ws="websockets-sansio",  # Use modern websockets API (avoids deprecation warnings)
                )
            except Exception as e:
                logger.error(f"❌ IMMEDIATE UVICORN: Server failed: {e}")
                import traceback

                logger.error(f"Server traceback: {traceback.format_exc()}")

        # Start server in non-daemon thread so it can handle signals properly
        thread = threading.Thread(target=run_server, daemon=False)
        thread.start()

        logger.debug(
            "🔒 IMMEDIATE UVICORN: Server thread started (daemon=False) - can handle signals"
        )

        # Store server reference in DecoratorRegistry BEFORE starting (critical timing)
        server_info = {
            "app": app,
            "server": None,  # No server object with uvicorn.run()
            "config": None,  # No config object needed
            "host": http_host,
            "port": port,
            "thread": thread,  # Server thread (non-daemon)
            "type": "immediate_uvicorn_running",
            "status": "running",  # Server is now running in background thread
        }

        # Import here to avoid circular imports
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        DecoratorRegistry.store_immediate_uvicorn_server(server_info)

        logger.debug(
            "🔄 IMMEDIATE UVICORN: Server reference stored in DecoratorRegistry BEFORE pipeline starts"
        )

        # Give server a moment to start
        time.sleep(1)

        # Detect actual port if port=0 (auto-assign)
        actual_port = port
        if port == 0:
            import socket

            # Try to detect actual port by scanning for listening sockets
            try:
                import subprocess

                # Use lsof to find the port bound by this process
                result = subprocess.run(
                    ["lsof", "-i", "-P", "-n", f"-p{os.getpid()}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.split("\n"):
                    if "LISTEN" in line and "python" in line.lower():
                        # Parse port from line like "python  1234  user  5u  IPv4 ... TCP *:54321 (LISTEN)"
                        parts = line.split()
                        for part in parts:
                            if ":" in part and "(LISTEN)" not in part:
                                try:
                                    port_str = part.split(":")[-1]
                                    detected_port = int(port_str)
                                    if detected_port > 0:
                                        actual_port = detected_port
                                        logger.info(
                                            f"🎯 IMMEDIATE UVICORN: Detected auto-assigned port {actual_port}"
                                        )
                                        # Update server_info with actual port
                                        server_info["port"] = actual_port
                                        server_info["requested_port"] = (
                                            0  # Remember original request
                                        )
                                        break
                                except (ValueError, IndexError):
                                    pass
                        if actual_port > 0:
                            break
            except Exception as e:
                logger.warning(
                    f"⚠️ IMMEDIATE UVICORN: Could not detect auto-assigned port: {e}"
                )

        logger.debug(
            f"✅ IMMEDIATE UVICORN: Uvicorn server running on {http_host}:{actual_port} (daemon thread)"
        )

        # Set up registry context for shutdown cleanup (use defaults initially)
        import os

        from _mcp_mesh.shared.simple_shutdown import _simple_shutdown_coordinator

        registry_url = os.getenv("MCP_MESH_REGISTRY_URL", "http://localhost:8000")
        agent_id = "unknown"  # Will be updated by pipeline when available
        _simple_shutdown_coordinator.set_shutdown_context(registry_url, agent_id)

        # CRITICAL FIX: Keep main thread alive to prevent shutdown state
        # This matches the working test setup pattern that prevents DNS resolution failures
        # Uses simple shutdown with signal handlers for clean registry cleanup
        start_blocking_loop_with_shutdown_support(thread)

    except Exception as e:
        logger.error(
            f"❌ IMMEDIATE UVICORN: Failed to start immediate uvicorn server: {e}"
        )
        # Don't fail decorator application - pipeline can still try to start normally


def _trigger_debounced_processing():
    """
    Trigger debounced processing when a decorator is applied.

    This connects to the pipeline's debounce coordinator to ensure
    all decorators are captured before processing begins.
    """
    try:
        from _mcp_mesh.pipeline.mcp_startup import get_debounce_coordinator

        coordinator = get_debounce_coordinator()
        coordinator.trigger_processing()
        logger.debug("⚡ Triggered debounced processing")

    except ImportError:
        # Pipeline orchestrator not available - graceful degradation
        logger.debug(
            "⚠️ Pipeline orchestrator not available, skipping debounced processing"
        )
    except Exception as e:
        # Don't fail decorator application due to processing errors
        logger.debug(f"⚠️ Failed to trigger debounced processing: {e}")


def _get_or_create_agent_id(agent_name: str | None = None) -> str:
    """
    Get or create a shared agent ID for all functions in this process.

    Format: {prefix}-{8chars} where:
    - prefix precedence: MCP_MESH_AGENT_NAME env var > agent_name parameter > "agent"
    - 8chars is first 8 characters of a UUID

    Args:
        agent_name: Optional name from @mesh.agent decorator

    Returns:
        Shared agent ID for this process
    """
    global _SHARED_AGENT_ID

    if _SHARED_AGENT_ID is None:
        # Precedence: env var > agent_name > default "agent"
        prefix = get_config_value(
            "MCP_MESH_AGENT_NAME",
            override=agent_name,
            default="agent",
            rule=ValidationRule.STRING_RULE,
        )

        uuid_suffix = str(uuid.uuid4())[:8]
        _SHARED_AGENT_ID = f"{prefix}-{uuid_suffix}"

    return _SHARED_AGENT_ID


def _enhance_mesh_decorators(processor):
    """Called by mcp_mesh runtime to enhance decorators with runtime capabilities."""
    global _runtime_processor
    _runtime_processor = processor


def _clear_shared_agent_id():
    """Clear the shared agent ID (useful for testing)."""
    global _SHARED_AGENT_ID
    _SHARED_AGENT_ID = None


def tool(
    capability: str | None = None,
    *,
    tags: list[str] | None = None,
    version: str = "1.0.0",
    dependencies: list[dict[str, Any]] | list[str] | None = None,
    description: str | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    Tool-level decorator for individual MCP functions/capabilities.

    Handles individual tool registration, capabilities, and dependencies.

    IMPORTANT: For optimal compatibility with FastMCP, use this decorator order:

    @mesh.tool(capability="example", dependencies=[...])
    @server.tool()
    def my_function():
        pass

    While both orders currently work, the above order is recommended for future compatibility.

    Args:
        capability: Optional capability name this tool provides (default: None)
        tags: Optional list of tags for discovery (default: [])
        version: Tool version (default: "1.0.0")
        dependencies: Optional list of dependencies (default: [])
        description: Optional description (default: function docstring)
        **kwargs: Additional metadata

    Returns:
        Function with dependency injection wrapper if dependencies are specified,
        otherwise the original function with metadata attached
    """

    def decorator(target: T) -> T:
        # Validate optional capability
        if capability is not None and not isinstance(capability, str):
            raise ValueError("capability must be a string")

        # Validate optional parameters
        if tags is not None:
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ValueError("all tags must be strings")

        if not isinstance(version, str):
            raise ValueError("version must be a string")

        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string")

        # Validate and process dependencies
        if dependencies is not None:
            if not isinstance(dependencies, list):
                raise ValueError("dependencies must be a list")

            validated_dependencies = []
            for dep in dependencies:
                if isinstance(dep, str):
                    # Simple string dependency
                    validated_dependencies.append(
                        {
                            "capability": dep,
                            "tags": [],
                        }
                    )
                elif isinstance(dep, dict):
                    # Complex dependency with metadata
                    if "capability" not in dep:
                        raise ValueError("dependency must have 'capability' field")
                    if not isinstance(dep["capability"], str):
                        raise ValueError("dependency capability must be a string")

                    # Validate optional dependency fields
                    dep_tags = dep.get("tags", [])
                    if not isinstance(dep_tags, list):
                        raise ValueError("dependency tags must be a list")
                    for tag in dep_tags:
                        if not isinstance(tag, str):
                            raise ValueError("all dependency tags must be strings")

                    dep_version = dep.get("version")
                    if dep_version is not None and not isinstance(dep_version, str):
                        raise ValueError("dependency version must be a string")

                    dependency_dict = {
                        "capability": dep["capability"],
                        "tags": dep_tags,
                    }
                    if dep_version is not None:
                        dependency_dict["version"] = dep_version
                    validated_dependencies.append(dependency_dict)
                else:
                    raise ValueError("dependencies must be strings or dictionaries")
        else:
            validated_dependencies = []

        # Build tool metadata
        metadata = {
            "capability": capability,
            "tags": tags or [],
            "version": version,
            "dependencies": validated_dependencies,
            "description": description or getattr(target, "__doc__", None),
            **kwargs,
        }

        # Store metadata on function
        target._mesh_tool_metadata = metadata

        # Register with DecoratorRegistry for processor discovery (will be updated with wrapper if needed)
        DecoratorRegistry.register_mesh_tool(target, metadata)

        # Always create dependency injection wrapper for consistent execution logging
        # This ensures ALL @mesh.tool functions get execution logging, even without dependencies
        logger.debug(
            f"🔍 Function '{target.__name__}' has {len(validated_dependencies)} validated dependencies: {validated_dependencies}"
        )

        try:
            # Import here to avoid circular imports
            from _mcp_mesh.engine.dependency_injector import get_global_injector

            # Extract dependency names for injector (empty list for functions without dependencies)
            dependency_names = [dep["capability"] for dep in validated_dependencies]

            # Log the original function pointer
            logger.debug(f"🔸 ORIGINAL function pointer: {target} at {hex(id(target))}")

            injector = get_global_injector()
            wrapped = injector.create_injection_wrapper(target, dependency_names)

            # Log the wrapper function pointer
            logger.debug(
                f"🔹 WRAPPER function pointer: {wrapped} at {hex(id(wrapped))}"
            )

            # Preserve metadata on wrapper
            wrapped._mesh_tool_metadata = metadata

            # Store the wrapper on the original function for reference
            target._mesh_injection_wrapper = wrapped

            # CRITICAL: Update DecoratorRegistry to use the wrapper instead of the original
            DecoratorRegistry.update_mesh_tool_function(target.__name__, wrapped)
            logger.debug(
                f"🔄 Updated DecoratorRegistry to use wrapper for '{target.__name__}'"
            )

            # If runtime processor is available, register with it
            if _runtime_processor is not None:
                try:
                    _runtime_processor.register_function(wrapped, metadata)
                except Exception as e:
                    logger.error(
                        f"Runtime registration failed for {target.__name__}: {e}"
                    )

            # Return the wrapped function - FastMCP will cache this wrapper when it runs
            logger.debug(f"✅ Returning injection wrapper for '{target.__name__}'")
            logger.debug(f"🔹 Returning WRAPPER: {wrapped} at {hex(id(wrapped))}")

            # Trigger debounced processing before returning
            _trigger_debounced_processing()
            return wrapped

        except Exception as e:
            # Log but don't fail - graceful degradation
            logger.error(
                f"Dependency injection setup failed for {target.__name__}: {e}"
            )

            # Fallback: register with runtime if available
            if _runtime_processor is not None:
                try:
                    _runtime_processor.register_function(target, metadata)
                except Exception as e:
                    logger.error(
                        f"Runtime registration failed for {target.__name__}: {e}"
                    )

            # Trigger debounced processing before returning
            _trigger_debounced_processing()
            return target

    return decorator


def agent(
    name: str | None = None,
    *,
    version: str = "1.0.0",
    description: str | None = None,
    http_host: str | None = None,
    http_port: int = 0,
    enable_http: bool = True,
    namespace: str = "default",
    health_interval: int = 5,  # Will be overridden by centralized defaults
    health_check: Callable[[], Awaitable[Any]] | None = None,
    health_check_ttl: int = 15,
    auto_run: bool = True,  # Changed to True by default!
    auto_run_interval: int = 10,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    Agent-level decorator for agent-wide configuration and metadata.

    This handles agent-level concerns like deployment, infrastructure,
    and overall agent metadata. Applied to classes or main functions.

    Args:
        name: Required agent name (mandatory!)
        version: Agent version (default: "1.0.0")
        description: Optional agent description
        http_host: HTTP server host (default: "0.0.0.0")
            Environment variable: MCP_MESH_HTTP_HOST (takes precedence)
        http_port: HTTP server port (default: 0, means auto-assign)
            Environment variable: MCP_MESH_HTTP_PORT (takes precedence)
        enable_http: Enable HTTP endpoints (default: True)
            Environment variable: MCP_MESH_HTTP_ENABLED (takes precedence)
        namespace: Agent namespace (default: "default")
            Environment variable: MCP_MESH_NAMESPACE (takes precedence)
        health_interval: Health check interval in seconds (default: 30)
            Environment variable: MCP_MESH_HEALTH_INTERVAL (takes precedence)
        health_check: Optional async function that returns HealthStatus
            Called before heartbeat and on /health endpoint with TTL caching
        health_check_ttl: Cache TTL for health check results in seconds (default: 15)
            Reduces expensive health check calls by caching results
        auto_run: Automatically start service and keep process alive (default: True)
            Environment variable: MCP_MESH_AUTO_RUN (takes precedence)
        auto_run_interval: Keep-alive heartbeat interval in seconds (default: 10)
            Environment variable: MCP_MESH_AUTO_RUN_INTERVAL (takes precedence)
        **kwargs: Additional agent metadata

    Environment Variables:
        MCP_MESH_HTTP_HOST: Override http_host parameter (string)
        MCP_MESH_HTTP_PORT: Override http_port parameter (integer, 0-65535)
        MCP_MESH_HTTP_ENABLED: Override enable_http parameter (boolean: true/false)
        MCP_MESH_NAMESPACE: Override namespace parameter (string)
        MCP_MESH_HEALTH_INTERVAL: Override health_interval parameter (integer, ≥1)
        MCP_MESH_AUTO_RUN: Override auto_run parameter (boolean: true/false)
        MCP_MESH_AUTO_RUN_INTERVAL: Override auto_run_interval parameter (integer, ≥1)

    Auto-Run Feature:
        When auto_run=True, the decorator automatically starts the service and keeps
        the process alive. This eliminates the need for manual while True loops.

        Example:
            @mesh.agent(name="my-service", auto_run=True)
            class MyAgent:
                pass

            @mesh.tool(capability="greeting")
            def hello():
                return "Hello!"

            # Script automatically stays alive - no while loop needed!

    Returns:
        The original class/function with agent metadata attached
    """

    def decorator(target: T) -> T:
        # Validate required name
        if name is None:
            raise ValueError("name is required for @mesh.agent")
        if not isinstance(name, str):
            raise ValueError("name must be a string")

        # Validate decorator parameters first
        if not isinstance(version, str):
            raise ValueError("version must be a string")

        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string")

        if http_host is not None and not isinstance(http_host, str):
            raise ValueError("http_host must be a string or None")

        if not isinstance(http_port, int):
            raise ValueError("http_port must be an integer")
        if not (0 <= http_port <= 65535):
            raise ValueError("http_port must be between 0 and 65535")

        if not isinstance(enable_http, bool):
            raise ValueError("enable_http must be a boolean")

        if not isinstance(namespace, str):
            raise ValueError("namespace must be a string")

        if not isinstance(health_interval, int):
            raise ValueError("health_interval must be an integer")
        if health_interval < 1:
            raise ValueError("health_interval must be at least 1 second")

        if not isinstance(auto_run, bool):
            raise ValueError("auto_run must be a boolean")

        if not isinstance(auto_run_interval, int):
            raise ValueError("auto_run_interval must be an integer")
        if auto_run_interval < 1:
            raise ValueError("auto_run_interval must be at least 1 second")

        if health_check is not None and not callable(health_check):
            raise ValueError("health_check must be a callable (async function)")

        if not isinstance(health_check_ttl, int):
            raise ValueError("health_check_ttl must be an integer")
        if health_check_ttl < 1:
            raise ValueError("health_check_ttl must be at least 1 second")

        # Separate binding host (for uvicorn server) from external host (for registry)
        from _mcp_mesh.shared.host_resolver import HostResolver

        # HOST variable for uvicorn binding (documented in environment-variables.md)
        binding_host = get_config_value(
            "HOST",
            default="0.0.0.0",
            rule=ValidationRule.STRING_RULE,
        )

        # External hostname for registry advertisement (MCP_MESH_HTTP_HOST)
        external_host = HostResolver.get_external_host()

        final_http_port = get_config_value(
            "MCP_MESH_HTTP_PORT",
            override=http_port,
            default=0,
            rule=ValidationRule.PORT_RULE,
        )

        final_enable_http = get_config_value(
            "MCP_MESH_HTTP_ENABLED",
            override=enable_http,
            default=True,
            rule=ValidationRule.TRUTHY_RULE,
        )

        final_namespace = get_config_value(
            "MCP_MESH_NAMESPACE",
            override=namespace,
            default="default",
            rule=ValidationRule.STRING_RULE,
        )

        # Import centralized defaults
        from _mcp_mesh.shared.defaults import MeshDefaults

        final_health_interval = get_config_value(
            "MCP_MESH_HEALTH_INTERVAL",
            override=health_interval,
            default=MeshDefaults.HEALTH_INTERVAL,
            rule=ValidationRule.NONZERO_RULE,
        )

        final_auto_run = get_config_value(
            "MCP_MESH_AUTO_RUN",
            override=auto_run,
            default=MeshDefaults.AUTO_RUN,
            rule=ValidationRule.TRUTHY_RULE,
        )

        final_auto_run_interval = get_config_value(
            "MCP_MESH_AUTO_RUN_INTERVAL",
            override=auto_run_interval,
            default=MeshDefaults.AUTO_RUN_INTERVAL,
            rule=ValidationRule.NONZERO_RULE,
        )

        # Generate agent ID using shared function
        agent_id = _get_or_create_agent_id(name)

        # Build agent metadata
        metadata = {
            "name": name,
            "version": version,
            "description": description,
            "http_host": external_host,
            "http_port": final_http_port,
            "enable_http": final_enable_http,
            "namespace": final_namespace,
            "health_interval": final_health_interval,
            "health_check": health_check,
            "health_check_ttl": health_check_ttl,
            "auto_run": final_auto_run,
            "auto_run_interval": final_auto_run_interval,
            "agent_id": agent_id,
            **kwargs,
        }

        # Store metadata on target (class or function)
        target._mesh_agent_metadata = metadata

        # Register with DecoratorRegistry for processor discovery
        DecoratorRegistry.register_mesh_agent(target, metadata)

        # Trigger debounced processing
        _trigger_debounced_processing()

        # If runtime processor is available, register with it
        if _runtime_processor is not None:
            try:
                _runtime_processor.register_function(target, metadata)
            except Exception as e:
                logger.error(f"Runtime registration failed for agent {name}: {e}")

        # Auto-run functionality: start uvicorn immediately to prevent Python shutdown state
        if final_auto_run:
            logger.debug(
                f"🚀 AGENT DECORATOR: Auto-run enabled for agent '{name}' - starting uvicorn immediately to prevent shutdown state"
            )

            # Create FastMCP lifespan before starting uvicorn for proper integration
            fastmcp_lifespan = None
            try:
                # Try to create FastMCP server and extract lifespan
                logger.debug(
                    "🔍 AGENT DECORATOR: Creating FastMCP server for lifespan extraction"
                )

                # Look for FastMCP app in current module
                import sys

                current_module = sys.modules.get(target.__module__)
                if current_module:
                    # Look for 'app' attribute (standard FastMCP pattern)
                    if hasattr(current_module, "app"):
                        fastmcp_server = current_module.app
                        logger.debug(
                            f"🔍 AGENT DECORATOR: Found FastMCP server: {type(fastmcp_server)}"
                        )

                        # Create FastMCP HTTP app with stateless transport to get lifespan
                        if hasattr(fastmcp_server, "http_app") and callable(
                            fastmcp_server.http_app
                        ):
                            try:
                                fastmcp_http_app = fastmcp_server.http_app(
                                    stateless_http=True, transport="streamable-http"
                                )
                                if hasattr(fastmcp_http_app, "lifespan"):
                                    fastmcp_lifespan = fastmcp_http_app.lifespan
                                    logger.debug(
                                        "✅ AGENT DECORATOR: Extracted FastMCP lifespan for FastAPI integration"
                                    )

                                    # Store both lifespan and HTTP app in DecoratorRegistry for uvicorn and pipeline to use
                                    DecoratorRegistry.store_fastmcp_lifespan(
                                        fastmcp_lifespan
                                    )
                                    DecoratorRegistry.store_fastmcp_http_app(
                                        fastmcp_http_app
                                    )
                                    logger.debug(
                                        "✅ AGENT DECORATOR: Stored FastMCP HTTP app for proper mounting"
                                    )
                                else:
                                    logger.warning(
                                        "⚠️ AGENT DECORATOR: FastMCP HTTP app has no lifespan attribute"
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"⚠️ AGENT DECORATOR: Failed to create FastMCP HTTP app: {e}"
                                )
                        else:
                            logger.warning(
                                "⚠️ AGENT DECORATOR: FastMCP server has no http_app method"
                            )
                    else:
                        logger.debug(
                            "🔍 AGENT DECORATOR: No FastMCP 'app' found in current module - will handle in pipeline"
                        )
                else:
                    logger.warning(
                        "⚠️ AGENT DECORATOR: Could not access current module for FastMCP discovery"
                    )

            except Exception as e:
                logger.warning(
                    f"⚠️ AGENT DECORATOR: FastMCP lifespan creation failed: {e}"
                )

            logger.debug(
                f"🎯 AGENT DECORATOR: About to call _start_uvicorn_immediately({binding_host}, {final_http_port})"
            )
            # Start basic uvicorn server immediately to prevent interpreter shutdown
            _start_uvicorn_immediately(binding_host, final_http_port)
            logger.debug(
                "✅ AGENT DECORATOR: _start_uvicorn_immediately() call completed"
            )

        return target

    return decorator


def route(
    *,
    dependencies: list[dict[str, Any]] | list[str] | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    FastAPI route handler decorator for dependency injection.

    Enables automatic dependency injection of MCP agents into FastAPI route handlers,
    eliminating the need for manual MCP client management in backend services.

    Args:
        dependencies: Optional list of agent capabilities to inject (default: [])
        **kwargs: Additional metadata for the route

    Returns:
        The original route handler function with dependency injection enabled

    Example:
        @app.post("/upload")
        @mesh.route(dependencies=["pdf-extractor", "user-service"])
        async def upload_resume(
            request: Request,
            file: UploadFile = File(...),
            pdf_tool: mesh.McpMeshTool = None,    # Injected by MCP Mesh
            user_service: mesh.McpMeshTool = None  # Injected by MCP Mesh
        ):
            result = await pdf_tool.extract_text_from_pdf(file)
            await user_service.update_profile(user_data, result)
            return {"success": True}
    """

    def decorator(target: T) -> T:
        # Validate and process dependencies (reuse logic from tool decorator)
        if dependencies is not None:
            if not isinstance(dependencies, list):
                raise ValueError("dependencies must be a list")

            validated_dependencies = []
            for dep in dependencies:
                if isinstance(dep, str):
                    # Simple string dependency
                    validated_dependencies.append(
                        {
                            "capability": dep,
                            "tags": [],
                        }
                    )
                elif isinstance(dep, dict):
                    # Complex dependency with metadata
                    if "capability" not in dep:
                        raise ValueError("dependency must have 'capability' field")
                    if not isinstance(dep["capability"], str):
                        raise ValueError("dependency capability must be a string")

                    # Validate optional dependency fields
                    dep_tags = dep.get("tags", [])
                    if not isinstance(dep_tags, list):
                        raise ValueError("dependency tags must be a list")
                    for tag in dep_tags:
                        if not isinstance(tag, str):
                            raise ValueError("all dependency tags must be strings")

                    dep_version = dep.get("version")
                    if dep_version is not None and not isinstance(dep_version, str):
                        raise ValueError("dependency version must be a string")

                    dependency_dict = {
                        "capability": dep["capability"],
                        "tags": dep_tags,
                    }
                    if dep_version is not None:
                        dependency_dict["version"] = dep_version
                    validated_dependencies.append(dependency_dict)
                else:
                    raise ValueError("dependencies must be strings or dictionaries")
        else:
            validated_dependencies = []

        # Build route metadata
        metadata = {
            "dependencies": validated_dependencies,
            "description": getattr(target, "__doc__", None),
            **kwargs,
        }

        # Store metadata on function
        target._mesh_route_metadata = metadata

        # Register with DecoratorRegistry using custom decorator type
        DecoratorRegistry.register_custom_decorator("mesh_route", target, metadata)

        # Try to add tracing middleware to any FastAPI apps we can find immediately
        # This ensures middleware is added before the app starts
        try:
            _add_tracing_middleware_immediately()
        except Exception as e:
            # Don't fail decorator application due to middleware issues
            logger.debug(f"Failed to add immediate tracing middleware: {e}")

        logger.debug(
            f"🔍 Route '{target.__name__}' registered with {len(validated_dependencies)} dependencies"
        )

        try:
            # Import here to avoid circular imports
            from _mcp_mesh.engine.dependency_injector import get_global_injector

            # Extract dependency names for injector
            dependency_names = [dep["capability"] for dep in validated_dependencies]

            # Log the original function pointer
            logger.debug(
                f"🔸 ORIGINAL route function pointer: {target} at {hex(id(target))}"
            )

            injector = get_global_injector()
            wrapped = injector.create_injection_wrapper(target, dependency_names)

            # Log the wrapper function pointer
            logger.debug(
                f"🔹 WRAPPER route function pointer: {wrapped} at {hex(id(wrapped))}"
            )

            # Preserve metadata on wrapper
            wrapped._mesh_route_metadata = metadata

            # Store the wrapper on the original function for reference
            target._mesh_injection_wrapper = wrapped

            # Also store a flag on the wrapper itself so route integration can detect it
            wrapped._mesh_is_injection_wrapper = True

            # Return the wrapped function - FastAPI will register this wrapper when it runs
            logger.debug(
                f"✅ Returning injection wrapper for route '{target.__name__}'"
            )
            logger.debug(f"🔹 Returning WRAPPER: {wrapped} at {hex(id(wrapped))}")

            # Trigger debounced processing before returning
            _trigger_debounced_processing()
            return wrapped

        except Exception as e:
            # Log but don't fail - graceful degradation
            logger.error(
                f"Route dependency injection setup failed for {target.__name__}: {e}"
            )

            # Fallback: return original function and trigger processing
            _trigger_debounced_processing()
            return target

    return decorator


def _add_tracing_middleware_immediately():
    """
    Request tracing middleware injection using monkey-patch approach.

    This sets up automatic middleware injection for both existing and future
    FastAPI apps, eliminating timing issues with app startup/lifespan.
    """
    try:
        from _mcp_mesh.shared.fastapi_middleware_manager import (
            get_fastapi_middleware_manager,
        )

        manager = get_fastapi_middleware_manager()
        success = manager.request_middleware_injection()

        if success:
            logger.debug(
                "🔍 TRACING: Middleware injection setup completed (monkey-patch + discovery)"
            )
        else:
            logger.debug("🔍 TRACING: Middleware injection setup failed")

    except Exception as e:
        # Never fail decorator application
        logger.debug(f"🔍 TRACING: Middleware injection setup failed: {e}")


# Middleware injection is now handled by FastAPIMiddlewareManager
# in _mcp_mesh.shared.fastapi_middleware_manager


# Graceful shutdown functions have been moved to _mcp_mesh.shared.graceful_shutdown_manager
# This maintains backward compatibility for existing pipeline code


def set_shutdown_context(context: dict[str, Any]):
    """Set context for graceful shutdown (called from pipeline)."""
    # Delegate to the shared graceful shutdown manager
    set_global_shutdown_context(context)


def _get_llm_agent_for_injection(
    wrapper: Any, param_name: str, kwargs: dict, func_name: str
) -> Any:
    """
    Get the appropriate LLM agent for injection based on template mode.

    Handles both template-based (per-call context) and non-template (cached) modes.

    Args:
        wrapper: The wrapper function with _mesh_llm_* attributes
        param_name: Name of the LLM parameter to inject
        kwargs: Current call kwargs (may contain context value)
        func_name: Function name for logging

    Returns:
        MeshLlmAgent instance (either per-call with context or cached)
    """
    config = getattr(wrapper, "_mesh_llm_config", {})
    is_template = config.get("is_template", False)
    context_param_name = config.get("context_param")
    create_context_agent = getattr(wrapper, "_mesh_create_context_agent", None)

    if is_template and context_param_name and create_context_agent:
        # Template mode: create per-call agent with context
        context_value = kwargs.get(context_param_name)
        if context_value is not None:
            logger.debug(f"🎯 Created per-call LLM agent with context for {func_name}")
            return create_context_agent(context_value)

    # Non-template mode or no context provided: use cached agent
    return wrapper._mesh_llm_agent


def llm(
    filter: dict[str, Any] | list[dict[str, Any] | str] | str | None = None,
    *,
    filter_mode: str = "all",
    provider: str | dict[str, Any] = "claude",
    model: str | None = None,
    api_key: str | None = None,
    max_iterations: int = 10,
    system_prompt: str | None = None,
    system_prompt_file: str | None = None,
    context_param: str | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    LLM agent decorator with automatic agentic loop.

    This decorator enables LLM agents to automatically access mesh tools via
    dependency injection. The MeshLlmAgent proxy handles the complete agentic loop:
    - Tool filtering based on filter parameter
    - LLM API calls (Claude, OpenAI, etc. via LiteLLM)
    - Tool execution via MCP proxies
    - Response parsing to Pydantic models

    Configuration Hierarchy (ENV > Decorator):
        - MESH_LLM_PROVIDER: Override provider
        - MESH_LLM_MODEL: Override model
        - ANTHROPIC_API_KEY: Claude API key
        - OPENAI_API_KEY: OpenAI API key
        - MESH_LLM_MAX_ITERATIONS: Override max iterations

    Usage:
        from pydantic import BaseModel
        import mesh

        class ChatResponse(BaseModel):
            answer: str
            confidence: float

        @mesh.llm(
            filter={"capability": "document", "tags": ["pdf"]},
            provider="claude",
            model="claude-3-5-sonnet-20241022"
        )
        @mesh.tool(capability="chat")
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            llm.set_system_prompt("You are a helpful assistant.")
            return llm(message)

    Args:
        filter: Tool filter (string, dict, or list of mixed)
        filter_mode: Filter mode ("all", "best_match", "*")
        provider: LLM provider (string like "claude" for direct LiteLLM, or dict for mesh delegation)
                  Mesh delegation format: {"capability": "llm", "tags": ["claude"], "version": ">=1.0.0"}
                  When dict: Uses mesh DI to resolve provider agent instead of calling LiteLLM directly
        model: Model name (can be overridden by MESH_LLM_MODEL) - only used with string provider
        api_key: API key (can be overridden by provider-specific env vars) - only used with string provider
        max_iterations: Max agentic loop iterations (can be overridden by MESH_LLM_MAX_ITERATIONS)
        system_prompt: Default system prompt
        system_prompt_file: Path to Jinja2 template file
        **kwargs: Additional configuration

    Returns:
        Decorated function with MeshLlmAgent injection

    Raises:
        ValueError: If no MeshLlmAgent parameter found
        UserWarning: If multiple MeshLlmAgent parameters or non-Pydantic return type
    """
    import inspect
    import warnings

    def decorator(func: T) -> T:
        # Step 1: Resolve configuration with hierarchy (ENV > decorator params)
        # Phase 1: Detect file:// prefix for template files
        is_template = False
        template_path = None

        if system_prompt:
            # Check for file:// prefix
            if system_prompt.startswith("file://"):
                is_template = True
                template_path = system_prompt[7:]  # Strip "file://" prefix
            # Auto-detect .jinja2 or .j2 extension without file:// prefix
            elif system_prompt.endswith(".jinja2") or system_prompt.endswith(".j2"):
                is_template = True
                template_path = system_prompt

        # Backward compatibility: system_prompt_file (deprecated)
        if system_prompt_file:
            logger.warning(
                f"⚠️ @mesh.llm: 'system_prompt_file' parameter is deprecated. "
                f"Use 'system_prompt=\"file://{system_prompt_file}\"' instead."
            )
            if not is_template:  # Only use if system_prompt didn't specify a template
                is_template = True
                template_path = system_prompt_file

        # Validate context_param usage
        if context_param and not is_template:
            logger.warning(
                f"⚠️ @mesh.llm: 'context_param' specified for function '{func.__name__}' "
                f"but system_prompt is not a template (no file:// prefix or .jinja2/.j2 extension). "
                f"Context parameter will be ignored."
            )

        # Handle provider config: dict (mesh delegation) or string (direct LiteLLM)
        # If provider is dict, don't allow env var override (explicit mesh delegation)
        if isinstance(provider, dict):
            resolved_provider = provider
        else:
            resolved_provider = get_config_value(
                "MESH_LLM_PROVIDER",
                override=provider,
                default="claude",
                rule=ValidationRule.STRING_RULE,
            )

        resolved_config = {
            "filter": filter,
            "filter_mode": get_config_value(
                "MESH_LLM_FILTER_MODE",
                override=filter_mode,
                default="all",
                rule=ValidationRule.STRING_RULE,
            ),
            "provider": resolved_provider,
            "model": get_config_value(
                "MESH_LLM_MODEL",
                override=model,
                default=None,
                rule=ValidationRule.STRING_RULE,
            ),
            "api_key": api_key,  # Will be resolved from provider-specific env vars later
            "max_iterations": get_config_value(
                "MESH_LLM_MAX_ITERATIONS",
                override=max_iterations,
                default=10,
                rule=ValidationRule.NONZERO_RULE,
            ),
            "system_prompt": system_prompt,
            "system_prompt_file": system_prompt_file,
            # Phase 1: Template metadata
            "is_template": is_template,
            "template_path": template_path,
            "context_param": context_param,
        }
        resolved_config.update(kwargs)

        # Step 2: Extract output type from return annotation
        sig = inspect.signature(func)
        return_annotation = sig.return_annotation

        output_type = None
        if return_annotation and return_annotation != inspect.Signature.empty:
            output_type = return_annotation

            # Warn if not a Pydantic model
            try:
                from pydantic import BaseModel

                if not (
                    inspect.isclass(output_type) and issubclass(output_type, BaseModel)
                ):
                    warnings.warn(
                        f"Function '{func.__name__}' decorated with @mesh.llm should return a Pydantic BaseModel subclass, "
                        f"got {output_type}. This may cause validation errors at runtime.",
                        UserWarning,
                        stacklevel=2,
                    )
            except ImportError:
                pass  # Pydantic not available, skip validation

        # Step 3: Find MeshLlmAgent parameter
        from mesh.types import MeshLlmAgent

        llm_params = []
        for param_name, param in sig.parameters.items():
            if param.annotation == MeshLlmAgent or (
                hasattr(param.annotation, "__origin__")
                and param.annotation.__origin__ == MeshLlmAgent
            ):
                llm_params.append(param_name)

        if not llm_params:
            raise ValueError(
                f"Function '{func.__name__}' decorated with @mesh.llm must have at least one parameter "
                f"of type 'mesh.MeshLlmAgent'. Example: def {func.__name__}(..., llm: mesh.MeshLlmAgent = None)"
            )

        if len(llm_params) > 1:
            warnings.warn(
                f"Function '{func.__name__}' has multiple MeshLlmAgent parameters: {llm_params}. "
                f"Only the first parameter '{llm_params[0]}' will be injected. "
                f"Additional parameters will be ignored.",
                UserWarning,
                stacklevel=2,
            )

        param_name = llm_params[0]

        # Step 4: Generate unique function ID
        function_id = f"{func.__name__}_{uuid.uuid4().hex[:8]}"

        # Step 5: Register with DecoratorRegistry
        DecoratorRegistry.register_mesh_llm(
            func=func,
            config=resolved_config,
            output_type=output_type,
            param_name=param_name,
            function_id=function_id,
        )

        logger.debug(
            f"@mesh.llm registered: {func.__name__} "
            f"(provider={resolved_config['provider']}, param={param_name}, filter={filter})"
        )

        # Step 6: Enhance existing wrapper from @mesh.tool (if present)
        # or create new wrapper
        #
        # This approach:
        # - Reuses the wrapper created by @mesh.tool (if present)
        # - Avoids creating multiple wrapper layers
        # - Ensures FastMCP caches the SAME wrapper instance we update later
        # - Combines both DI injection and LLM injection in the same wrapper

        # Check if there's an existing wrapper from @mesh.tool
        mesh_tools = DecoratorRegistry.get_mesh_tools()
        existing_wrapper = None

        if func.__name__ in mesh_tools:
            existing_wrapper = mesh_tools[func.__name__].function
            logger.info(
                f"🔗 Found existing @mesh.tool wrapper for '{func.__name__}' at {hex(id(existing_wrapper))} - enhancing it"
            )

        # Trigger debounced processing
        _trigger_debounced_processing()

        if existing_wrapper:
            # ENHANCE the existing wrapper with LLM attributes
            logger.info(
                f"✨ Enhancing existing wrapper with LLM injection for '{func.__name__}'"
            )

            # Store the original wrapped function if not already stored
            if not hasattr(existing_wrapper, "__wrapped__"):
                existing_wrapper.__wrapped__ = func

            # Store the original call behavior to preserve DI injection
            original_call = existing_wrapper

            # Create enhanced wrapper that does BOTH DI injection and LLM injection
            @wraps(func)
            def combined_injection_wrapper(*args, **kwargs):
                """Wrapper that injects both MeshLlmAgent and DI parameters."""
                # Inject LLM parameter if not provided or if it's None
                if param_name not in kwargs or kwargs.get(param_name) is None:
                    kwargs[param_name] = _get_llm_agent_for_injection(
                        combined_injection_wrapper, param_name, kwargs, func.__name__
                    )
                # Then call the original wrapper (which handles DI injection)
                return original_call(*args, **kwargs)

            # Add LLM metadata attributes to combined wrapper
            combined_injection_wrapper._mesh_llm_agent = (
                None  # Will be updated during heartbeat
            )
            combined_injection_wrapper._mesh_llm_param_name = param_name
            combined_injection_wrapper._mesh_llm_function_id = function_id
            combined_injection_wrapper._mesh_llm_config = resolved_config
            combined_injection_wrapper._mesh_llm_output_type = output_type
            combined_injection_wrapper.__wrapped__ = func

            # Create update method for heartbeat that updates the COMBINED wrapper
            def update_llm_agent(agent):
                combined_injection_wrapper._mesh_llm_agent = agent
                logger.info(
                    f"🔄 Updated MeshLlmAgent on combined wrapper for {func.__name__} (function_id={function_id})"
                )

            combined_injection_wrapper._mesh_update_llm_agent = update_llm_agent

            # Copy any other mesh attributes from existing wrapper
            for attr in dir(existing_wrapper):
                if attr.startswith("_mesh_") and not hasattr(
                    combined_injection_wrapper, attr
                ):
                    try:
                        setattr(
                            combined_injection_wrapper,
                            attr,
                            getattr(existing_wrapper, attr),
                        )
                    except AttributeError:
                        pass  # Some attributes might not be settable

            # Update DecoratorRegistry with the combined wrapper
            DecoratorRegistry.update_mesh_llm_function(
                function_id, combined_injection_wrapper
            )
            DecoratorRegistry.update_mesh_tool_function(
                func.__name__, combined_injection_wrapper
            )

            logger.info(
                f"✅ Enhanced wrapper for '{func.__name__}' with combined DI + LLM injection at {hex(id(combined_injection_wrapper))}"
            )

            # Return the enhanced wrapper
            return combined_injection_wrapper

        else:
            # FALLBACK: Create new wrapper if no existing @mesh.tool wrapper found
            logger.info(
                f"📝 No existing wrapper found for '{func.__name__}' - creating new LLM wrapper"
            )

            @wraps(func)
            def llm_injection_wrapper(*args, **kwargs):
                """Wrapper that injects MeshLlmAgent parameter."""
                # Inject llm parameter if not provided or if it's None
                if param_name not in kwargs or kwargs.get(param_name) is None:
                    kwargs[param_name] = _get_llm_agent_for_injection(
                        llm_injection_wrapper, param_name, kwargs, func.__name__
                    )
                return func(*args, **kwargs)

            # Create update method for heartbeat - updates the wrapper, not func
            def update_llm_agent(agent):
                llm_injection_wrapper._mesh_llm_agent = agent
                logger.info(
                    f"🔄 Updated MeshLlmAgent for {func.__name__} (function_id={function_id})"
                )

            # Copy all metadata attributes to the wrapper
            llm_injection_wrapper._mesh_llm_agent = None
            llm_injection_wrapper._mesh_llm_param_name = param_name
            llm_injection_wrapper._mesh_llm_function_id = function_id
            llm_injection_wrapper._mesh_llm_config = resolved_config
            llm_injection_wrapper._mesh_llm_output_type = output_type
            llm_injection_wrapper._mesh_update_llm_agent = update_llm_agent

            # Update DecoratorRegistry with the wrapper
            DecoratorRegistry.update_mesh_llm_function(
                function_id, llm_injection_wrapper
            )

            # Return the new wrapper
            return llm_injection_wrapper

    return decorator
