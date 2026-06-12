"""
Mesh decorators implementation - dual decorator architecture.

Provides @mesh.tool and @mesh.agent decorators with clean separation of concerns.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

# Import from _mcp_mesh for registry and runtime integration
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.strict_di import StrictDIError
from _mcp_mesh.shared.config_resolver import ValidationRule, get_config_value
from _mcp_mesh.shared.simple_shutdown import start_blocking_loop_with_shutdown_support

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Global reference to the runtime processor, set by mcp_mesh runtime
_runtime_processor: Any | None = None

# Shared agent ID for all functions in the same process
_SHARED_AGENT_ID: str | None = None

# Sentinel placeholder used by @mesh.a2a_consumer to mark tags that should
# be substituted with the surrounding @mesh.agent name once it is known.
# See _resolve_pending_consumer_self_tags below.
_MESH_CONSUMER_SELF_SENTINEL = "__MESH_CONSUMER_SELF__"

# Budget for waiting on ``uvicorn.Server.started`` after the immediate
# server thread launches: MCP_MESH_SERVER_STARTUP_TIMEOUT (default 30s),
# shared with the heartbeat's first-registration deferral. See
# ``_mcp_mesh.shared.port_binding.get_server_startup_timeout`` — sized for
# slow-but-healthy ASGI lifespans (model loading etc.), so a healthy slow
# startup is not misclassified as wedged.


class ImmediateServerStartupError(RuntimeError):
    """The immediate uvicorn server bound its socket but can never serve.

    Raised (and deliberately NOT swallowed by ``_start_uvicorn_immediately``'s
    catch-all) when the server thread dies before ``server.started`` flips —
    e.g. ``uvicorn.Config.load()`` failing on bad TLS cert/key paths after
    the socket was already bound. A bound socket that can never serve is not
    something the mesh can adapt around: registering it would advertise an
    endpoint that refuses every connection, and the orchestrator fallback
    server path does not carry the agent's TLS configuration. Failing the
    decorator application loudly is the only honest outcome.
    """


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
            # Hijack the FastMCP/user lifespan so its body runs on the user
            # loop (worker-0 of the tool_executor pool). Tools and lifespan
            # then share the same asyncio loop, so loop-bound resources
            # (asyncpg pools, redis clients, aiohttp sessions) created in
            # lifespan startup are safely usable from tool bodies. The
            # framework loop (uvicorn) stays free to service /health,
            # /ready, /livez. See issue #1061.
            #
            # Both wrap sites (this one and the lifespan_factory composers)
            # call the same wrap_lifespan_for_user_loop helper — the
            # hijack logic lives in exactly one place.
            from _mcp_mesh.pipeline.mcp_startup.lifespan_factory import (
                wrap_lifespan_for_user_loop,
            )

            user_loop_lifespan = wrap_lifespan_for_user_loop(fastmcp_lifespan)
            app = FastAPI(
                title="MCP Mesh Agent (Starting)", lifespan=user_loop_lifespan
            )
            logger.debug(
                "📦 IMMEDIATE UVICORN: Created FastAPI app with user-loop-dispatched FastMCP lifespan"
            )
        else:
            app = FastAPI(title="MCP Mesh Agent (Starting)")
            logger.debug("📦 IMMEDIATE UVICORN: Created minimal FastAPI app")

        # Add middleware to strip trace arguments from tool calls BEFORE app starts
        # This must be done unconditionally because meshctl --trace sends trace args
        # regardless of agent's tracing configuration
        try:
            import json as json_module

            class TraceArgumentStripperMiddleware:
                """Pure ASGI middleware to strip trace and mesh arguments from tool calls.

                This middleware ALWAYS runs to strip _trace_id, _parent_span, and
                _mesh_headers from MCP tool arguments, preventing Pydantic validation
                errors. Also captures _mesh_headers into propagated headers context.

                Buffers all body chunks before parsing to handle chunked transfers
                (uvicorn splits large payloads >~64KB across multiple receive calls).
                """

                def __init__(self, app):
                    self.app = app

                async def __call__(self, scope, receive, send):
                    if scope["type"] != "http":
                        await self.app(scope, receive, send)
                        return

                    # Read entire body upfront before calling the inner app
                    body_chunks = []
                    while True:
                        message = await receive()
                        body = message.get("body", b"")
                        if body:
                            body_chunks.append(body)
                        if message.get("type") == "http.disconnect":
                            break
                        if not message.get("more_body", False):
                            break

                    full_body = b"".join(body_chunks)
                    modified_body = full_body

                    # Try to strip trace arguments from the complete body
                    if full_body:
                        try:
                            payload = json_module.loads(full_body.decode("utf-8"))
                            if (
                                isinstance(payload, dict)
                                and payload.get("method") == "tools/call"
                            ):
                                arguments = payload.get("params", {}).get(
                                    "arguments", {}
                                )
                                if isinstance(arguments, dict):
                                    changed = False

                                    # Strip trace context fields from arguments
                                    if (
                                        "_trace_id" in arguments
                                        or "_parent_span" in arguments
                                    ):
                                        arguments.pop("_trace_id", None)
                                        arguments.pop("_parent_span", None)
                                        changed = True

                                    # Strip and capture _mesh_headers from arguments
                                    mesh_headers = arguments.pop("_mesh_headers", None)
                                    if mesh_headers is not None:
                                        changed = True
                                        if isinstance(mesh_headers, dict):
                                            try:
                                                from _mcp_mesh.tracing.context import (
                                                    PROPAGATE_HEADERS,
                                                    TraceContext,
                                                )

                                                if PROPAGATE_HEADERS:
                                                    from _mcp_mesh.tracing.context import (
                                                        matches_propagate_header,
                                                    )

                                                    filtered = {
                                                        k.lower(): v
                                                        for k, v in mesh_headers.items()
                                                        if isinstance(v, str)
                                                        and matches_propagate_header(k)
                                                    }
                                                    if filtered:
                                                        # Merge with HTTP-captured headers (HTTP takes precedence)
                                                        existing = (
                                                            TraceContext.get_propagated_headers()
                                                        )
                                                        if existing:
                                                            merged = dict(filtered)
                                                            merged.update(existing)
                                                            filtered = merged
                                                        TraceContext.set_propagated_headers(
                                                            filtered
                                                        )
                                            except Exception:
                                                pass

                                    if changed:
                                        modified_body = json_module.dumps(
                                            payload
                                        ).encode("utf-8")
                                        logger.debug(
                                            "[TRACE] Stripped trace/mesh fields from arguments"
                                        )
                        except Exception as e:
                            logger.debug(
                                f"[TRACE] Failed to process body for stripping: {e}"
                            )

                    # Create a simple receive that returns the (modified) body once,
                    # then delegates back to original receive for lifecycle events
                    body_sent = False

                    async def modified_receive():
                        nonlocal body_sent
                        if not body_sent:
                            body_sent = True
                            return {
                                "type": "http.request",
                                "body": modified_body,
                                "more_body": False,
                            }
                        # After body is delivered, delegate to original receive
                        # for disconnect and other lifecycle events — do NOT
                        # return disconnect immediately as that breaks ASGI
                        return await receive()

                    await self.app(scope, modified_receive, send)

            app.add_middleware(TraceArgumentStripperMiddleware)
            logger.debug(
                "📦 IMMEDIATE UVICORN: Added trace argument stripper middleware"
            )
        except Exception as e:
            logger.warning(
                f"⚠️ IMMEDIATE UVICORN: Failed to add trace argument stripper middleware: {e}"
            )

        # Add trace context middleware for header propagation (always-on)
        # Handles trace context setup, propagated header capture, and _mesh_headers processing
        try:
            # Use pure ASGI middleware for proper SSE header injection (Issue #310)
            class TraceContextMiddleware:
                """Pure ASGI middleware for trace context and header injection.

                This middleware:
                1. Extracts trace context from incoming request headers AND arguments
                2. Captures configured propagation headers from HTTP headers
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
                        from _mcp_mesh.tracing.context import (
                            PROPAGATE_HEADERS,
                            TraceContext,
                        )
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
                                incoming_parent_span if incoming_parent_span else None
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

                        # Capture configured propagation headers from HTTP headers (always-on, prefix matching)
                        if PROPAGATE_HEADERS:
                            from _mcp_mesh.tracing.context import (
                                matches_propagate_header as _mph,
                            )

                            captured = {}
                            # Iterate all request headers and filter by prefix match
                            for raw_header in headers_list:
                                # headers_list is list of (name, value) tuples as bytes
                                header_name = (
                                    raw_header[0].decode("latin-1")
                                    if isinstance(raw_header[0], bytes)
                                    else raw_header[0]
                                )
                                header_value = (
                                    raw_header[1].decode("latin-1")
                                    if isinstance(raw_header[1], bytes)
                                    else raw_header[1]
                                )
                                if _mph(header_name):
                                    captured[header_name.lower()] = header_value
                            if captured:
                                TraceContext.set_propagated_headers(captured)
                                logger.debug(
                                    f"[TRACE] Captured {len(captured)} propagated headers"
                                )
                    except Exception as e:
                        logger.warning(f"Failed to set trace context: {e}")

                    # Create receive wrapper to extract trace context from arguments
                    # Note: Argument stripping is handled by TraceArgumentStripperMiddleware
                    import json as json_module

                    async def receive_with_trace_extraction():
                        message = await receive()
                        if message["type"] == "http.request":
                            body = message.get("body", b"")
                            if body:
                                try:
                                    payload = json_module.loads(body.decode("utf-8"))
                                    if payload.get("method") == "tools/call":
                                        arguments = payload.get("params", {}).get(
                                            "arguments", {}
                                        )

                                        # Extract trace context from arguments if not in headers
                                        nonlocal trace_id, span_id, parent_span
                                        if not trace_id and arguments.get("_trace_id"):
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
                                                    trace_id = current_trace.trace_id
                                                    span_id = current_trace.span_id
                                                    parent_span = (
                                                        current_trace.parent_span
                                                    )
                                                logger.debug(
                                                    f"[TRACE] Extracted trace context from arguments: trace_id={arg_trace_id}"
                                                )
                                            except Exception:
                                                pass
                                except Exception as e:
                                    logger.debug(
                                        f"[TRACE] Failed to process body for extraction: {e}"
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
                        scope, receive_with_trace_extraction, send_with_trace_headers
                    )

            app.add_middleware(TraceContextMiddleware)
            logger.debug(
                "📦 IMMEDIATE UVICORN: Added trace context middleware for header propagation"
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

        # Resolve TLS config from Rust core
        from _mcp_mesh.shared.tls_config import get_tls_config

        tls = get_tls_config()

        ssl_kwargs = {}
        if tls["enabled"]:
            if not tls.get("cert_path") or not tls.get("key_path"):
                raise RuntimeError(
                    "TLS enabled but MCP_MESH_TLS_CERT or MCP_MESH_TLS_KEY is not set"
                )
            import ssl

            ssl_kwargs["ssl_certfile"] = tls["cert_path"]
            ssl_kwargs["ssl_keyfile"] = tls["key_path"]
            if tls.get("ca_path"):
                ssl_kwargs["ssl_ca_certs"] = tls["ca_path"]
                ssl_kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED
            logger.info(f"IMMEDIATE UVICORN: TLS enabled (mode={tls['mode']})")

        # Port handling (issue #1194):
        # - http_port=0 explicitly means auto-assign (OS picks a free port)
        # - http_port>0 means use that specific port, falling back to an
        #   OS-assigned port (with a prominent warning) if it is taken.
        #
        # The socket is bound HERE — synchronously, before uvicorn starts —
        # and handed to uvicorn as a pre-bound socket. This makes bind
        # failures impossible to swallow (previously uvicorn's bind error
        # died inside the server thread and the agent registered a port it
        # never bound — a phantom endpoint). The port recorded below is
        # read back from the bound socket, so registration always carries
        # the ACTUAL port.
        from _mcp_mesh.shared.port_binding import bind_server_socket_with_fallback

        bound_socket, port = bind_server_socket_with_fallback(http_host, http_port)
        if http_port == 0:
            logger.info(f"🎯 IMMEDIATE UVICORN: Auto-assigned port {port} for agent")
        elif port != http_port:
            # bind_server_socket_with_fallback already logged the prominent
            # conflict warning; this line ties it to the agent lifecycle log.
            logger.warning(
                f"⚠️ IMMEDIATE UVICORN: configured port {http_port} unavailable - "
                f"serving and registering on auto-assigned port {port} instead"
            )

        logger.debug(
            f"🚀 IMMEDIATE UVICORN: Starting uvicorn server on {http_host}:{port}"
        )

        # Build the uvicorn Server explicitly so we can hand it the
        # pre-bound socket (issue #1194). Serving on a socket we already
        # own means the registered port is, by construction, the bound
        # port. The Server object is also registered with the shutdown
        # coordinator so SIGTERM/SIGINT flip ``server.should_exit`` and
        # uvicorn runs its graceful shutdown (FastAPI lifespan exit phase).
        uvicorn_config = uvicorn.Config(
            app,
            host=http_host,
            port=port,
            log_level="info",
            timeout_graceful_shutdown=30,  # Allow time for registry cleanup
            access_log=False,  # Reduce noise
            ws="websockets-sansio",  # Use modern websockets API (avoids deprecation warnings)
            **ssl_kwargs,
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)

        from _mcp_mesh.shared.simple_shutdown import register_uvicorn_server

        register_uvicorn_server(uvicorn_server)

        # Start uvicorn server in background thread (NON-daemon to keep process alive)
        def run_server():
            """Run uvicorn server on the pre-bound socket in a background thread."""
            try:
                logger.debug(
                    f"🌟 IMMEDIATE UVICORN: Starting server on {http_host}:{port}"
                )
                uvicorn_server.run(sockets=[bound_socket])
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

        # Store the bound-server record IMMEDIATELY with status "starting",
        # then upgrade it to "running" once uvicorn proves serving. Two
        # constraints meet here (issue #1194 + PR #1197 review):
        #
        # * The debounced startup pipeline (~1s after the last decorator)
        #   races this thread's ASGI lifespan startup. If the record were
        #   stored only after ``server.started`` flips, any lifespan slower
        #   than the debounce delay would make ServerDiscoveryStep find
        #   nothing and the pipeline would pre-bind a SECOND server on a
        #   different port (duplicate server, registered port != the port
        #   the agent's real app ends up on).
        # * A bound socket is not a serving socket: uvicorn can still fail
        #   AFTER the bind (e.g. ``Config.load()`` raising on unreadable TLS
        #   cert/key paths) inside the server thread.
        #
        # The hard invariant stays bind-level — ``port`` is read back from
        # the socket this process bound, so the record can never advertise a
        # port nobody owns. Proven-serving is enforced as a *liveness
        # deferral* at registration time instead: the heartbeat defers its
        # first registration on ``server.started`` (bounded by the same
        # budget; see startup_orchestrator._setup_heartbeat_background).
        server_info = {
            "app": app,
            "server": uvicorn_server,
            "config": uvicorn_config,
            "host": http_host,
            "port": port,
            "thread": thread,  # Server thread (non-daemon)
            "type": "immediate_uvicorn_running",
            "status": "starting",  # bound, serving not yet proven
        }

        # Import here to avoid circular imports
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.shared.port_binding import get_server_startup_timeout

        DecoratorRegistry.store_immediate_uvicorn_server(server_info)

        logger.debug(
            "🔄 IMMEDIATE UVICORN: Server reference stored in DecoratorRegistry"
        )

        startup_timeout = get_server_startup_timeout()
        startup_deadline = time.monotonic() + startup_timeout
        while not uvicorn_server.started and thread.is_alive():
            if time.monotonic() >= startup_deadline:
                break
            time.sleep(0.05)

        if uvicorn_server.started:
            # Upgrade in place — server discovery holds a reference to this
            # same dict, so the status change is visible everywhere.
            server_info["status"] = "running"
            logger.debug(
                f"✅ IMMEDIATE UVICORN: Uvicorn server running on {http_host}:{port} (non-daemon thread)"
            )
        elif not thread.is_alive():
            # The server thread died before serving (run_server already
            # logged the underlying exception + traceback). Remove the
            # record so nothing reuses or registers it, release the bound
            # socket — this process can never serve on it — and fail the
            # decorator application loudly. Thread death surfaces within
            # ~50ms here, well before the debounced pipeline (~1s) reads
            # the registry.
            DecoratorRegistry.clear_immediate_uvicorn_server()
            try:
                bound_socket.close()
            except OSError:
                pass
            logger.error(
                f"❌ IMMEDIATE UVICORN: server thread died before serving "
                f"on {http_host}:{port} — the agent cannot serve; failing "
                f"loudly (see the server error logged above)"
            )
            raise ImmediateServerStartupError(
                f"immediate uvicorn server thread died before serving on "
                f"{http_host}:{port} — see the server error logged above"
            )
        else:
            # Budget expired with the thread ALIVE and the socket bound: the
            # port is genuinely held by this process, so keep the record
            # (status stays "starting") — the pipeline reuses THIS server
            # instead of starting a duplicate, and registration carries the
            # bound port. The heartbeat's own bounded deferral has the same
            # budget, so registration may proceed before serving is proven;
            # if uvicorn ultimately fails to serve, the thread dies and the
            # process exits — a too-early registration is transient at
            # worst, never a phantom bind. Note this also defers dependency
            # resolution for consumers of this agent until registration —
            # acceptable and arguably correct (don't advertise until
            # serving); the settling-window grace (issue #1193) layers on
            # top of this without being pre-empted here.
            logger.warning(
                f"⚠️ IMMEDIATE UVICORN: server has not reported started within "
                f"{startup_timeout:.0f}s on {http_host}:{port} (slow ASGI "
                f"lifespan startup?). The port IS bound by this process, so "
                f"the server record is kept and startup continues; raise "
                f"MCP_MESH_SERVER_STARTUP_TIMEOUT if your startup is "
                f"legitimately slower."
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

    except ImmediateServerStartupError:
        # Bound-but-can-never-serve is the loud-failure case: the pipeline
        # fallback cannot honor this agent's TLS configuration, so quietly
        # falling through would trade a dead endpoint for a wrong one.
        raise
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

    Resolution order (first match wins):
    1. MCP_MESH_AGENT_ID env var — explicit full-id override (production K8s
       sets this to the pod name so the same id survives restarts and lines
       up with the pod's logs / metrics). This is the value used everywhere
       (heartbeat registration, claim worker, JobController instance_id),
       so a single env var pins identity across all subsystems.
    2. Synthetic ``{prefix}-{8chars}`` where prefix precedence is
       MCP_MESH_AGENT_NAME env var > agent_name parameter > "agent" and
       8chars is the first 8 characters of a fresh UUID.

    Args:
        agent_name: Optional name from @mesh.agent decorator

    Returns:
        Shared agent ID for this process
    """
    global _SHARED_AGENT_ID

    if _SHARED_AGENT_ID is None:
        # Step 1: explicit full-id override.
        explicit = get_config_value(
            "MCP_MESH_AGENT_ID",
            default=None,
            rule=ValidationRule.STRING_RULE,
        )
        if explicit:
            _SHARED_AGENT_ID = explicit
            return _SHARED_AGENT_ID

        # Step 2: synthetic prefix-uuid form.
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


def _is_tool_isolation_enabled() -> bool:
    """Whether to dispatch async tool execution to the dedicated worker loop.

    Default ON. Set MCP_MESH_TOOL_ISOLATION=false to disable (legacy behavior).
    """
    return get_config_value(
        "MCP_MESH_TOOL_ISOLATION",
        override=None,
        default=True,
        rule=ValidationRule.TRUTHY_RULE,
    )


def _wrap_with_isolation(final_func: Callable, func_name: str) -> Callable:
    """Wrap an async tool function so its body runs on the mesh worker loop.

    Only async functions are wrapped — sync tools are already dispatched off
    the main loop by FastMCP via ``anyio.to_thread.run_sync``.

    Stream wrappers are also skipped: they call
    ``ctx.report_progress(...)`` whose underlying transport is bound to the
    main loop. Dispatching the wrapper to a worker loop would cause the
    progress notifications to deadlock on the main-loop session, so we
    leave streaming tools to FastMCP's normal in-loop dispatch
    (issue #645 bug). Streaming tools don't typically do blocking syscalls
    inside the generator — they're shipping LLM tokens.

    The isolation wrapper is applied as the OUTERMOST layer so FastMCP sees
    a coroutine function and awaits it on the main loop, while the actual
    user work executes on the worker thread. The decorator chain
    (``__wrapped__`` and ``_mesh_original_func``) is preserved via
    ``functools.wraps`` and explicit attribute copy so
    ``signature_analyzer._get_original_func`` keeps finding the user function.
    """
    if not asyncio.iscoroutinefunction(final_func):
        return final_func

    meta = getattr(final_func, "_mesh_tool_metadata", None)
    if isinstance(meta, dict) and meta.get("stream_type") == "text":
        logger.debug(
            f"🧵 ISOLATION: Skipping stream tool '{func_name}' "
            f"(progress notifications must run on the main loop)"
        )
        return final_func

    @wraps(final_func)
    async def isolated(*args, **kwargs):
        # Local import to keep the decorator import-time cost minimal and to
        # avoid any circular import surprises.
        from _mcp_mesh.shared.tool_executor import dispatch

        future = dispatch(final_func, args, kwargs)
        return await asyncio.wrap_future(future)

    # functools.wraps sets __wrapped__ = final_func, which preserves the
    # signature_analyzer chain (it walks __wrapped__ then checks
    # _mesh_original_func). Mirror _mesh_original_func explicitly so callers
    # that read it directly off the outermost wrapper still find the user
    # function, not the DI wrapper.
    if hasattr(final_func, "_mesh_original_func"):
        isolated._mesh_original_func = final_func._mesh_original_func
    else:
        isolated._mesh_original_func = final_func

    # Preserve mesh metadata attributes that FastMCP / pipeline code reads
    # from the outermost wrapper.
    for attr in (
        "_mesh_tool_metadata",
        "_mesh_injected_deps",
        "_mesh_dependencies",
        "_mesh_positions",
        "_mesh_update_dependency",
        "_mesh_function_id",
    ):
        if hasattr(final_func, attr):
            try:
                setattr(isolated, attr, getattr(final_func, attr))
            except AttributeError:
                pass

    # Preserve the trimmed signature (DI wrapper hides injectable params from
    # FastMCP). functools.wraps does NOT copy __signature__ by default.
    if hasattr(final_func, "__signature__"):
        try:
            isolated.__signature__ = final_func.__signature__
        except AttributeError:
            pass

    isolated._mesh_isolation_wrapped = True
    logger.debug(
        f"🧵 ISOLATION: Wrapped async tool '{func_name}' for worker-loop execution"
    )
    return isolated


def tool(
    capability: str | None = None,
    *,
    tags: list[str] | None = None,
    version: str = "1.0.0",
    dependencies: list[dict[str, Any]] | list[str] | None = None,
    description: str | None = None,
    output_schema_strict: bool = True,
    task: bool = False,
    retry_on: tuple[type[BaseException], ...] | None = None,
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
        dependencies: Optional list of dependencies (default: []). Each entry
            is either a capability string or a dict with keys:
              - capability (required, str)
              - tags (optional, list[str | list[str]])
              - version (optional, str)
              - expected_type (optional, type | dict): Python type (Pydantic
                model, dataclass, TypedDict, primitive, etc.) or pre-built
                JSON Schema dict describing the expected response shape.
                Issue #547 Phase 1D.
              - match_mode (optional, "subset" | "strict"): Schema check mode
                when expected_type is set. Defaults to "subset" if
                expected_type is provided. Issue #547 Phase 1D.
        description: Optional description (default: function docstring)
        output_schema_strict: Whether a BLOCK verdict from the schema normalizer
            should refuse agent startup for this specific tool (default: True).
            Set to False as a per-tool escape hatch when the producer's output
            schema cannot be canonicalized but the tool should still register.
            Wins even when the cluster-wide MCP_MESH_SCHEMA_STRICT=true env var
            promotes WARN→BLOCK. Issue #547 Phase 4.
        task: When True, mark this tool as long-running (Phase 1 MeshJob
            substrate). Producers advertise ``task=True`` in their tool
            metadata so consumers know to invoke the tool via job semantics
            (submit + wait/poll) rather than as a regular synchronous
            ``tools/call``. The actual job-context binding happens at
            inbound call time via the tool wrapper (next dispatch). A
            ``task=True`` tool MUST be ``async def`` — long-running tools
            need an event loop to drive ``MeshJob.update_progress()``,
            cancellation, and outbound polling. See ``MESHJOB_DESIGN.org``
            "Producer-side flow".
        retry_on: Optional tuple of exception classes that mark a handler
            raise as transient/retry-eligible (issue #879). When the handler
            raises ``e`` and ``isinstance(e, retry_on)`` matches, the SDK
            calls ``controller.release_lease(reason)`` instead of
            ``controller.fail(...)`` — the registry resets
            ``owner_instance_id`` (release does NOT increment
            ``attempt_count``; the claim that picked the row up already
            counted this attempt) and a peer replica re-claims the row
            within ~5s via the HEAD-heartbeat path. If the row's existing
            ``attempt_count`` is already past ``max_retries``, the registry
            marks the row terminal=failed with
            ``error="exhausted (release): <reason>"``. Default
            (``None``/``()``) preserves the previous behaviour: every
            handler raise maps to ``job.fail()`` and burns no retry
            budget. Only meaningful for ``task=True`` tools — ignored
            otherwise.

            Note: while ``retry_on`` accepts any ``BaseException`` subclass,
            do NOT include ``asyncio.CancelledError``, ``KeyboardInterrupt``,
            or ``SystemExit``. Retrying on these defeats cooperative
            cancellation/shutdown — a CancelledError propagated from an
            outer scope (deadline, peer cancel) would silently re-claim the
            row instead of honouring the cancel. Stick to ``Exception``
            subclasses representing transient I/O / availability faults
            (``OSError``, ``ConnectionError``, custom transient types).
        **kwargs: Additional metadata

    Returns:
        Function with dependency injection wrapper if dependencies are specified,
        otherwise the original function with metadata attached
    """

    def decorator(target: T) -> T:
        # Validate optional capability
        if capability is not None and not isinstance(capability, str):
            raise ValueError("capability must be a string")

        if not isinstance(output_schema_strict, bool):
            raise ValueError("output_schema_strict must be a boolean")

        if not isinstance(task, bool):
            raise ValueError("task must be a boolean")

        # task=True is async-only: long-running tools need an event loop
        # to drive MeshJob.update_progress / cancellation / outbound polling.
        # Fail loudly at decoration time so the developer sees the problem
        # immediately rather than at first invocation.
        if task and not asyncio.iscoroutinefunction(target):
            raise ValueError(
                f"@mesh.tool(task=True) requires an async def function; "
                f"'{getattr(target, '__name__', '?')}' is sync. "
                "Mark the function async or remove task=True."
            )

        # Validate retry_on (issue #879): must be a tuple of exception
        # classes. We deliberately reject lists so the dispatch wrapper
        # can pass it straight to ``isinstance`` without a runtime cast.
        # Empty tuple is allowed and equivalent to None (no retry-eligible
        # exceptions).
        validated_retry_on: tuple[type[BaseException], ...] = ()
        if retry_on is not None:
            if not isinstance(retry_on, tuple):
                raise ValueError(
                    "retry_on must be a tuple of exception classes "
                    "(e.g., (OSError, ConnectionError))"
                )
            for exc_cls in retry_on:
                if not (isinstance(exc_cls, type) and issubclass(exc_cls, BaseException)):
                    raise ValueError(
                        f"retry_on entries must be exception classes; "
                        f"got {exc_cls!r}"
                    )
                if issubclass(exc_cls, (KeyboardInterrupt, SystemExit)) or issubclass(exc_cls, asyncio.CancelledError):
                    raise ValueError(
                        f"retry_on must not include control-flow exceptions "
                        f"(KeyboardInterrupt, SystemExit, asyncio.CancelledError); "
                        f"got {exc_cls!r}"
                    )
            validated_retry_on = retry_on

        # retry_on is only meaningful for task=True tools — without the job
        # dispatch wrapper, raised exceptions propagate normally and there is
        # nothing to retry. Fail loud at decoration time rather than silently
        # ignore the kwarg.
        if retry_on is not None and not task:
            raise ValueError(
                "retry_on is only valid with task=True; remove retry_on or "
                "set task=True"
            )

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
                    # Tags can be strings or arrays of strings (OR alternatives)
                    # e.g., ["required", ["python", "typescript"]] = required AND (python OR typescript)
                    dep_tags = dep.get("tags", [])
                    if not isinstance(dep_tags, list):
                        raise ValueError("dependency tags must be a list")
                    for tag in dep_tags:
                        if isinstance(tag, str):
                            continue  # Simple tag - OK
                        elif isinstance(tag, list):
                            # OR alternative - validate inner tags are all strings
                            for inner_tag in tag:
                                if not isinstance(inner_tag, str):
                                    raise ValueError(
                                        "OR alternative tags must be strings"
                                    )
                        else:
                            raise ValueError(
                                "tags must be strings or arrays of strings (OR alternatives)"
                            )

                    dep_version = dep.get("version")
                    if dep_version is not None and not isinstance(dep_version, str):
                        raise ValueError("dependency version must be a string")

                    # Issue #547 Phase 1D: optional consumer-side schema declaration.
                    # expected_type may be a Python type (Pydantic model, dataclass,
                    # TypedDict, primitive, etc.) OR a pre-built JSON Schema dict.
                    # match_mode is "subset" (default opt-in) or "strict".
                    expected_type = dep.get("expected_type")
                    match_mode = dep.get("match_mode")

                    if match_mode is not None and match_mode not in ("subset", "strict"):
                        raise ValueError(
                            "dependency match_mode must be 'subset' or 'strict'"
                        )

                    dependency_dict = {
                        "capability": dep["capability"],
                        "tags": dep_tags,
                    }
                    if dep_version is not None:
                        dependency_dict["version"] = dep_version

                    if expected_type is not None:
                        # Default match_mode to "subset" (most permissive opt-in)
                        # when caller provides expected_type without match_mode.
                        if match_mode is None:
                            match_mode = "subset"
                        if isinstance(expected_type, dict):
                            # Caller supplied a pre-built JSON Schema; pass through.
                            dependency_dict["expected_schema_raw"] = expected_type
                        else:
                            # Defer Rust-normalizer call to the heartbeat pipeline
                            # (decorator runs at import time; keep it cheap).
                            from _mcp_mesh.utils.fastmcp_schema_extractor import (
                                FastMCPSchemaExtractor,
                            )

                            schema = FastMCPSchemaExtractor.extract_type_schema(
                                expected_type
                            )
                            if schema is not None:
                                dependency_dict["expected_schema_raw"] = schema
                            # else: extraction failed; warning already logged.
                    elif match_mode is not None:
                        logger.warning(
                            f"dependency '{dep['capability']}': match_mode set "
                            "but no expected_type; schema check will be skipped"
                        )

                    if match_mode is not None:
                        dependency_dict["match_mode"] = match_mode

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
            # Issue #547 Phase 4: per-tool override for the schema verdict policy.
            "output_schema_strict": output_schema_strict,
            # Phase 1 MeshJob substrate: producers advertise task=True so
            # consumers know to invoke via job semantics (submit + wait)
            # rather than a synchronous tools/call. The inbound tool
            # wrapper (next dispatch) reads this flag to decide whether
            # to bind a JobController via run_as_job before invocation.
            "task": task,
            # Issue #879: per-tool exception whitelist for the fast retry
            # path. The job_dispatch / claim_dispatcher wrappers compare
            # raised exceptions against this tuple via ``isinstance`` and
            # call ``controller.release_lease(reason)`` instead of
            # ``controller.fail(...)`` for matches — the registry then
            # resets owner_instance_id and a peer replica re-claims within
            # ~5s. Empty tuple = previous behaviour (every raise → fail).
            "retry_on": validated_retry_on,
            **kwargs,
        }

        # Issue #645 Phase 1: detect Stream[str] return annotation and stamp
        # metadata so the heartbeat pipeline propagates it as a kwargs field
        # (heartbeat_preparation.py:198-214 → rust_heartbeat.py:395-398) and
        # the runtime wrapper switches on streaming behavior. Re-raise with a
        # clear message when the user asks for Stream[T] for T != str.
        from _mcp_mesh.engine.stream_introspection import detect_stream_type

        try:
            stream_type = detect_stream_type(target)
        except ValueError as e:
            raise ValueError(
                f"@mesh.tool '{getattr(target, '__name__', '?')}': {e}"
            ) from None
        if stream_type is not None:
            metadata["stream_type"] = stream_type

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

            # Apply tool-execution isolation: for async tools, dispatch the
            # actual coroutine onto a dedicated worker event loop so a user's
            # blocking syscall (e.g. time.sleep inside an async def tool)
            # cannot freeze uvicorn's main loop and stall /health probes.
            # Sync tools are left alone — FastMCP already runs them via
            # anyio.to_thread.run_sync (off the main loop).
            isolation_enabled = _is_tool_isolation_enabled()
            logger.debug(
                f"🧵 ISOLATION: enabled={isolation_enabled} for '{target.__name__}' "
                f"(async={asyncio.iscoroutinefunction(wrapped)})"
            )
            if isolation_enabled and asyncio.iscoroutinefunction(wrapped):
                wrapped = _wrap_with_isolation(wrapped, target.__name__)

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

        except ValueError:
            # ValueError is reserved for contract violations the user MUST
            # see at decoration time — currently the multi-``MeshJob``
            # rejection from ``analyze_mesh_job_signature`` (per
            # MESHJOB_DDDI_CONTRACT.md), ``StrictDIError`` (the
            # MCP_MESH_STRICT_DI promotion of DI ambiguity/skip warnings,
            # a ValueError subclass) and any future signature-shape
            # rejection. Graceful-degradation would silently advertise a
            # broken tool and surface a confusing AttributeError on first
            # invocation; that is exactly the failure mode this branch is
            # supposed to prevent.
            #
            # Remove the entry registered above before propagating —
            # otherwise the registry keeps a half-registered tool (original
            # function, no wrapper) whenever the raise does NOT kill the
            # process (decoration inside a user try block, REPL/notebook).
            DecoratorRegistry.unregister_mesh_tool(target.__name__)
            raise
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
    heartbeat_interval: int = 5,
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
        heartbeat_interval: Heartbeat interval in seconds (default: 5)
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
        MCP_MESH_HEALTH_INTERVAL: Override heartbeat_interval parameter (integer, ≥1)
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

        if not isinstance(heartbeat_interval, int):
            raise ValueError("heartbeat_interval must be an integer")
        if heartbeat_interval < 1:
            raise ValueError("heartbeat_interval must be at least 1 second")

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

        final_heartbeat_interval = get_config_value(
            "MCP_MESH_HEALTH_INTERVAL",
            override=heartbeat_interval,
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
            "heartbeat_interval": final_heartbeat_interval,
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

        # Resolve any @mesh.a2a_consumer self-tag sentinels now that we
        # know the agent name. The convention puts @mesh.agent at the
        # bottom of the file, so consumer decorators (above) ran first
        # and stamped a placeholder; substitute it in-place here.
        _resolve_pending_consumer_self_tags(name)

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

            # Prepare TLS credentials before starting HTTP server.
            # This fetches from Vault (if configured) and writes secure temp files.
            try:
                from _mcp_mesh.shared.tls_config import prepare_tls

                prepare_tls(agent_id)
            except Exception as e:
                logger.warning(f"TLS preparation failed: {e}")

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
                    # Tags can be strings or arrays of strings (OR alternatives)
                    # e.g., ["required", ["python", "typescript"]] = required AND (python OR typescript)
                    dep_tags = dep.get("tags", [])
                    if not isinstance(dep_tags, list):
                        raise ValueError("dependency tags must be a list")
                    for tag in dep_tags:
                        if isinstance(tag, str):
                            continue  # Simple tag - OK
                        elif isinstance(tag, list):
                            # OR alternative - validate inner tags are all strings
                            for inner_tag in tag:
                                if not isinstance(inner_tag, str):
                                    raise ValueError(
                                        "OR alternative tags must be strings"
                                    )
                        else:
                            raise ValueError(
                                "tags must be strings or arrays of strings (OR alternatives)"
                            )

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

            # Streaming routes: build the SSE endpoint at DECORATION time so
            # FastAPI registers the correct streaming endpoint at @app.post()
            # time (issue #1206). The route-integration pipeline step runs
            # debounced AFTER uvicorn may already be serving — with only the
            # post-registration endpoint swap, a request arriving in that
            # window (or HELD across it by the #1193 settling-window grace)
            # completed inside the plain DI wrapper, whose raw async-generator
            # return value FastAPI cannot serialize → 500. Registering the
            # SSE endpoint from the start removes the window entirely; the
            # integration step detects ``_mesh_is_sse_endpoint`` and only
            # registers the inner wrapper for heartbeat dependency updates.
            try:
                from _mcp_mesh.engine.stream_introspection import (
                    detect_stream_type,
                )

                is_stream_route = detect_stream_type(target) == "text"
            except Exception as e:
                logger.debug(
                    f"Stream-route detection skipped for {target.__name__}: {e}"
                )
                is_stream_route = False

            if is_stream_route:
                try:
                    from _mcp_mesh.pipeline.api_startup.route_integration import (
                        _build_sse_endpoint,
                    )

                    sse_endpoint = _build_sse_endpoint(wrapped, target)
                    logger.debug(
                        f"📡 Built SSE endpoint for streaming route "
                        f"'{target.__name__}' at decoration time"
                    )
                    _trigger_debounced_processing()
                    return sse_endpoint
                except Exception as e:
                    # Graceful degradation: fall back to the pre-#1206 flow
                    # (annotation strip below + integration-time SSE swap).
                    logger.warning(
                        f"Decoration-time SSE endpoint build failed for route "
                        f"'{target.__name__}' ({e}); falling back to the "
                        f"integration-time endpoint swap — the pre-#1206 "
                        f"startup race window applies to this route (a "
                        f"request arriving before route integration runs may "
                        f"hit the plain DI wrapper and fail with a 500)"
                    )

                # FastAPI inspects the endpoint's return annotation (via
                # get_type_hints following __wrapped__) to build a Pydantic
                # response_field. An AsyncIterator[str] / Stream[str] return
                # is not a valid Pydantic field and crashes registration. The
                # route integration step later detects the stream annotation
                # on the underlying _mesh_original_func and installs an
                # SSE-emitting endpoint, so the wrapper itself does not need
                # to expose the streaming return type to FastAPI.
                try:
                    import inspect as _inspect

                    from _mcp_mesh.engine.dependency_injector import (
                        _MESH_PROGRESS_CTX_PARAM,
                    )

                    wrapper_anns = dict(getattr(wrapped, "__annotations__", {}) or {})
                    wrapper_anns.pop("return", None)
                    # The streaming wrapper's signature carries an internal
                    # parameter (``_MESH_PROGRESS_CTX_PARAM``) typed as
                    # ``Optional[Context]`` so FastMCP's tool path can
                    # auto-fill the progress channel. FastAPI/Pydantic do not
                    # tolerate field names with a leading underscore when
                    # building the route's body model — and the SSE wrapper
                    # handles streaming through its own pipe (not via
                    # FastMCP's Context), so the synthesized param has no
                    # business being visible here. Strip it from both the
                    # annotations dict and the explicit signature.
                    wrapper_anns.pop(_MESH_PROGRESS_CTX_PARAM, None)
                    wrapped.__annotations__ = wrapper_anns
                    if hasattr(wrapped, "__wrapped__"):
                        try:
                            del wrapped.__wrapped__
                        except AttributeError:
                            pass
                    explicit_sig = wrapped.__dict__.get("__signature__")
                    if explicit_sig is not None:
                        cleaned_params = [
                            p
                            for n, p in explicit_sig.parameters.items()
                            if n != _MESH_PROGRESS_CTX_PARAM
                        ]
                        wrapped.__signature__ = explicit_sig.replace(
                            parameters=cleaned_params,
                            return_annotation=_inspect.Signature.empty,
                        )
                except Exception as e:
                    logger.debug(
                        f"Stream-route annotation strip skipped for "
                        f"{target.__name__}: {e}"
                    )

            # Return the wrapped function - FastAPI will register this wrapper when it runs
            logger.debug(
                f"✅ Returning injection wrapper for route '{target.__name__}'"
            )
            logger.debug(f"🔹 Returning WRAPPER: {wrapped} at {hex(id(wrapped))}")

            # Trigger debounced processing before returning
            _trigger_debounced_processing()
            return wrapped

        except StrictDIError:
            # MCP_MESH_STRICT_DI promotes DI ambiguity/skip warnings to
            # decoration-time errors; swallowing them here for graceful
            # degradation would defeat the opt-in entirely. Remove the
            # entry registered above before propagating so the registry
            # does not keep a half-registered route when the raise does
            # not kill the process.
            DecoratorRegistry.unregister_custom_decorator(
                "mesh_route", target.__name__
            )
            raise
        except Exception as e:
            # Log but don't fail - graceful degradation
            logger.error(
                f"Route dependency injection setup failed for {target.__name__}: {e}"
            )

            # Fallback: return original function and trigger processing
            _trigger_debounced_processing()
            return target

    return decorator


def _derive_a2a_skill_id_from_path(path: str) -> str:
    """Derive a default skill_id from an A2A path's last segment.

    ``/agents/report-generator`` → ``report-generator``. Falls back to
    ``"default"`` for degenerate inputs (just ``/`` or empty after strip).
    Issue #903 / A2A_SURFACE_DESIGN.org > "API Surface (Python v1)".
    """
    last = path.rstrip("/").rsplit("/", 1)[-1].strip()
    return last or "default"


def _derive_a2a_skill_name_from_id(skill_id: str) -> str:
    """Derive a TitleCase skill name from a skill_id.

    ``report-generator`` → ``Report Generator``. Splits on ``-`` and ``_``.
    """
    parts = [p for p in skill_id.replace("_", "-").split("-") if p]
    return " ".join(p.capitalize() for p in parts) if parts else skill_id


def a2a(
    *,
    path: str,
    description: str | None = None,
    dependencies: list[str] | list[dict[str, Any]] | None = None,
    skill_id: str | None = None,
    skill_name: str | None = None,
    input_modes: list[str] | None = None,
    output_modes: list[str] | None = None,
    tags: list[str] | None = None,
    auth: str | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """A2A (Agent-to-Agent) surface decorator (issue #903 Phase 1B).

    Exposes a function as an A2A v1.0 protocol surface. Each decorated
    function becomes one agent card with one skill, mounted at
    ``GET {path}/.well-known/agent.json`` (discovery) and
    ``POST {path}`` (JSON-RPC tasks/* entry point). The function body is
    user-controlled and may declare DDDI dependencies (typically a single
    underlying ``@mesh.tool`` capability).

    Phase 1: discovery + agent-card generation only. ``tasks/*`` JSON-RPC
    methods return ``Method not implemented``. Phase 2 wires actual task
    routing.

    Args:
        path: REQUIRED URL path suffix for this surface (must start with
            ``/``), e.g. ``/agents/report-generator``. The registry
            concatenates ``MCP_MESH_PUBLIC_URL_PREFIX`` with this path
            to compute the public FQDN.
        description: Free-form skill description shown on the agent card.
            Defaults to the function's docstring when not set.
        dependencies: Optional list of mesh capabilities to inject (same
            shape as ``@mesh.tool`` deps). For v1, typically a single
            capability — multi-skill grouping is v2 (see design doc
            "LLM-backed multi-skill cards" section).
        skill_id: A2A skill identifier (kebab-case canonical). When unset,
            derived from the path's last segment.
        skill_name: Human-readable skill name. When unset, derived from
            ``skill_id`` (TitleCase).
        input_modes: A2A inputModes for this skill (default
            ``["application/json"]``).
        output_modes: A2A outputModes for this skill (default
            ``["application/json"]``).
        tags: Skill tags surfaced on the agent card.
        auth: Authentication scheme. v1 accepts ``"bearer"`` or ``None``
            (no auth). Anything else raises ``ValueError`` — broader auth
            schemes (SPIRE/mTLS/OAuth) land in v2.
        **kwargs: Additional metadata stamped onto the surface registration.

    Returns:
        The decorated function with ``_mesh_a2a_metadata`` attached and
        DI wiring applied (mirrors ``@mesh.route``).

    Example:
        @mesh.a2a(
            path="/agents/report-generator",
            description="Generate a long-form report",
            dependencies=["generate_report"],
            auth="bearer",
        )
        async def report_generator_a2a(
            payload: dict,
            generate_report: McpMeshTool = None,
        ):
            return await generate_report(**payload)
    """

    def decorator(target: T) -> T:
        # Validate path (REQUIRED, must start with /)
        if not isinstance(path, str) or not path:
            raise ValueError("path is required for @mesh.a2a and must be a non-empty string")
        if not path.startswith("/"):
            raise ValueError(
                f"@mesh.a2a path must start with '/' (got {path!r})"
            )

        # Validate auth — v1 scope only allows "bearer" or None.
        if auth is not None:
            if not isinstance(auth, str):
                raise ValueError("auth must be a string or None")
            if auth != "bearer":
                raise ValueError(
                    f"@mesh.a2a auth={auth!r} is not supported in v1; "
                    "only 'bearer' or None are valid. Broader auth schemes "
                    "(SPIRE/mTLS/OAuth) are v2 scope."
                )

        if description is not None and not isinstance(description, str):
            raise ValueError("description must be a string or None")

        if skill_id is not None and not isinstance(skill_id, str):
            raise ValueError("skill_id must be a string or None")

        if skill_name is not None and not isinstance(skill_name, str):
            raise ValueError("skill_name must be a string or None")

        # Validate input/output modes
        for field_name, value in (("input_modes", input_modes), ("output_modes", output_modes)):
            if value is not None:
                if not isinstance(value, list):
                    raise ValueError(f"{field_name} must be a list of strings")
                for entry in value:
                    if not isinstance(entry, str):
                        raise ValueError(f"all {field_name} entries must be strings")

        # Validate tags
        if tags is not None:
            if not isinstance(tags, list):
                raise ValueError("tags must be a list of strings")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ValueError("all tags must be strings")

        # Validate and process dependencies (mirrors @mesh.route shape).
        if dependencies is not None:
            if not isinstance(dependencies, list):
                raise ValueError("dependencies must be a list")

            validated_dependencies = []
            for dep in dependencies:
                if isinstance(dep, str):
                    validated_dependencies.append({"capability": dep, "tags": []})
                elif isinstance(dep, dict):
                    if "capability" not in dep:
                        raise ValueError("dependency must have 'capability' field")
                    if not isinstance(dep["capability"], str):
                        raise ValueError("dependency capability must be a string")
                    # Mirror @mesh.tool's tag validation — tags is a list
                    # whose elements are either strings (AND-tags) or
                    # nested lists of strings (OR-groups). Without this
                    # check, malformed shapes (ints, nested ints, dicts)
                    # would silently propagate to the registry and only
                    # surface as confusing resolver mismatches at
                    # capability-binding time.
                    dep_tags = dep.get("tags", [])
                    if not isinstance(dep_tags, list):
                        raise ValueError("dependency tags must be a list")
                    for tag in dep_tags:
                        if isinstance(tag, str):
                            continue
                        elif isinstance(tag, list):
                            for inner_tag in tag:
                                if not isinstance(inner_tag, str):
                                    raise ValueError(
                                        "OR alternative tags must be strings"
                                    )
                        else:
                            raise ValueError(
                                "tags must be strings or arrays of strings (OR alternatives)"
                            )
                    dep_version = dep.get("version")
                    if dep_version is not None and not isinstance(dep_version, str):
                        raise ValueError("dependency version must be a string")
                    dep_dict = {
                        "capability": dep["capability"],
                        "tags": dep_tags,
                    }
                    if dep_version is not None:
                        dep_dict["version"] = dep_version
                    validated_dependencies.append(dep_dict)
                else:
                    raise ValueError("dependencies must be strings or dictionaries")
        else:
            validated_dependencies = []

        if len(validated_dependencies) > 1:
            # v1 emits a single agent card per surface with one skill. Multi-
            # dep is permitted (the user's function can fan out internally)
            # but multi-skill grouping is reserved for v2 (see design doc).
            logger.warning(
                f"@mesh.a2a({path}) declares {len(validated_dependencies)} "
                "dependencies; v1 emits one agent card per surface with one "
                "skill. Multi-skill grouping in a single card is v2 scope."
            )

        # Derive defaults for skill_id and skill_name when not provided.
        final_skill_id = skill_id if skill_id else _derive_a2a_skill_id_from_path(path)
        final_skill_name = (
            skill_name if skill_name else _derive_a2a_skill_name_from_id(final_skill_id)
        )

        final_input_modes = (
            list(input_modes) if input_modes is not None else ["application/json"]
        )
        final_output_modes = (
            list(output_modes) if output_modes is not None else ["application/json"]
        )
        final_tags = list(tags) if tags is not None else []

        final_description = description
        if final_description is None:
            doc = getattr(target, "__doc__", None)
            if doc:
                final_description = doc.strip().split("\n")[0]

        # Build A2A surface metadata. Stamped onto the function so the
        # pipeline (heartbeat preparation + FastAPI route mount step) can
        # discover it.
        metadata = {
            "path": path,
            "skill_id": final_skill_id,
            "skill_name": final_skill_name,
            "description": final_description,
            "input_modes": final_input_modes,
            "output_modes": final_output_modes,
            "tags": final_tags,
            "auth": auth,
            "dependencies": validated_dependencies,
            **kwargs,
        }

        target._mesh_a2a_metadata = metadata

        # Register with DecoratorRegistry under a custom decorator type so
        # the pipeline can discover @mesh.a2a-decorated functions.
        DecoratorRegistry.register_custom_decorator("mesh_a2a", target, metadata)

        try:
            _add_tracing_middleware_immediately()
        except Exception as e:
            logger.debug(f"Failed to add immediate tracing middleware for a2a: {e}")

        logger.debug(
            f"🌐 A2A surface registered: path={path}, skill_id={final_skill_id}, "
            f"deps={len(validated_dependencies)}, auth={auth!r}"
        )

        # Wrap with DI injector when there are dependencies (mirrors @mesh.route).
        try:
            from _mcp_mesh.engine.dependency_injector import get_global_injector

            dependency_names = [dep["capability"] for dep in validated_dependencies]
            injector = get_global_injector()
            wrapped = injector.create_injection_wrapper(target, dependency_names)

            # Preserve metadata on wrapper so the route-mount step finds it
            # regardless of which reference it has.
            wrapped._mesh_a2a_metadata = metadata
            target._mesh_injection_wrapper = wrapped
            wrapped._mesh_is_injection_wrapper = True

            _trigger_debounced_processing()
            return wrapped
        except StrictDIError:
            # MCP_MESH_STRICT_DI promotes DI ambiguity/skip warnings to
            # decoration-time errors; swallowing them here for graceful
            # degradation would defeat the opt-in entirely. Remove the
            # entry registered above before propagating so the registry
            # does not keep a half-registered A2A surface when the raise
            # does not kill the process.
            DecoratorRegistry.unregister_custom_decorator("mesh_a2a", target.__name__)
            raise
        except Exception as e:
            logger.error(
                f"A2A dependency injection setup failed for {target.__name__}: {e}"
            )
            _trigger_debounced_processing()
            return target

    return decorator


def a2a_consumer(
    *,
    capability: str,
    a2a_url: str,
    a2a_skill_id: str | None = None,
    tags: list[str] | None = None,
    auth: Any | None = None,
    version: str = "1.0.0",
    description: str | None = None,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    poll_interval_max: float = 2.0,
    **kwargs: Any,
) -> Callable[[T], T]:
    """Bridge an external A2A v1.0 endpoint into a mesh capability (issue #908).

    Wraps a user function as a regular ``@mesh.tool`` capability whose
    body issues a synchronous ``tasks/send`` against an external A2A
    backend. The decorator:

    - Constructs a single ``A2AClient`` per decorator application (cached
      in a closure, reused across calls).
    - Injects the client as the ``_a2a`` keyword argument when the user
      function declares it.
    - Registers the capability with the surrounding ``@mesh.agent``'s
      name automatically appended as a tag, so multiple consumer agents
      bridging the same logical capability are distinguishable for mesh
      capability+tag failover.

    A consumer is NOT an A2A producer — registration goes through the
    standard ``@mesh.tool`` path, not the ``api_startup`` / a2a-surface
    pipeline.

    Args:
        capability: REQUIRED mesh capability name to register. Downstream
            mesh tools depend on this string the same way they depend on
            any other ``@mesh.tool`` capability.
        a2a_url: REQUIRED full URL of the A2A endpoint (e.g.
            ``http://host:port/agents/<skill>``).
        a2a_skill_id: A2A skill identifier on the upstream side. Defaults
            to ``capability`` when omitted. Recorded on the client for
            future per-skill-discovery use; not yet sent on the wire
            (Phase 1 only uses the URL itself).
        tags: Extra mesh tags for the capability. The consumer agent's
            name is automatically appended (or substituted in lazily
            when no ``@mesh.agent`` is registered yet at decoration
            time).
        auth: ``A2ABearer`` instance for outbound bearer auth, or
            ``None`` for unauthenticated calls.
        version: Capability version (default ``"1.0.0"``).
        description: Capability description; defaults to the function's
            docstring.
        timeout: Default timeout (seconds) for ``A2AClient.send`` calls
            issued by this decorator. Per-call ``send(..., timeout=...)``
            overrides the default.
        poll_interval: Initial backoff (seconds) between ``tasks/get``
            polls while a task is non-terminal. Must be > 0. Default
            ``0.5``.
        poll_interval_max: Cap (seconds) on the exponential poll backoff.
            Must be > 0. Default ``2.0``.
        **kwargs: Additional metadata stamped onto the underlying
            ``@mesh.tool`` registration (passed through unchanged).

    Returns:
        The user function wrapped as a ``@mesh.tool``-style capability
        with the ``A2AClient`` bound for ``_a2a`` injection.

    Example:
        @app.tool()
        @mesh.a2a_consumer(
            capability="current-date",
            a2a_url="http://localhost:9090/agents/date",
            a2a_skill_id="get-date",
            tags=["a2a-bridge"],
        )
        async def current_date(_a2a: mesh.A2AClient = None) -> dict:
            response = await _a2a.send(
                message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
            )
            return json.loads(response.artifact_text)
    """
    # Implementation lives in a private submodule (``_a2a_consumer``)
    # so the public name ``mesh.a2a_consumer`` belongs to THIS decorator
    # function. Importing from a public ``a2a_consumer`` submodule would
    # set ``mesh.a2a_consumer`` to the module object as a Python import
    # side effect, shadowing the decorator on subsequent attribute
    # lookups in the same process.
    from ._a2a_consumer import A2ABearer, A2AClient

    if not isinstance(capability, str) or not capability:
        raise ValueError(
            "@mesh.a2a_consumer: 'capability' is required and must be a non-empty string"
        )
    if not isinstance(a2a_url, str) or not a2a_url:
        raise ValueError(
            "@mesh.a2a_consumer: 'a2a_url' is required and must be a non-empty string"
        )
    if a2a_skill_id is not None and not isinstance(a2a_skill_id, str):
        raise ValueError("@mesh.a2a_consumer: 'a2a_skill_id' must be a string or None")
    if auth is not None and not isinstance(auth, A2ABearer):
        raise ValueError(
            "@mesh.a2a_consumer: 'auth' must be a mesh.A2ABearer instance or None"
        )
    if tags is not None:
        if not isinstance(tags, list):
            raise ValueError("@mesh.a2a_consumer: 'tags' must be a list of strings")
        for t in tags:
            if not isinstance(t, str):
                raise ValueError("@mesh.a2a_consumer: all tags must be strings")
            if t == _MESH_CONSUMER_SELF_SENTINEL:
                raise ValueError(
                    f"@mesh.a2a_consumer: tag {_MESH_CONSUMER_SELF_SENTINEL!r} is reserved "
                    "for the framework's consumer-name auto-injection sentinel; do not supply it explicitly"
                )
    if not isinstance(version, str):
        raise ValueError("@mesh.a2a_consumer: 'version' must be a string")
    if description is not None and not isinstance(description, str):
        raise ValueError("@mesh.a2a_consumer: 'description' must be a string or None")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("@mesh.a2a_consumer: 'timeout' must be a positive number")
    if not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
        raise ValueError(
            "@mesh.a2a_consumer: 'poll_interval' must be a positive number"
        )
    if not isinstance(poll_interval_max, (int, float)) or poll_interval_max <= 0:
        raise ValueError(
            "@mesh.a2a_consumer: 'poll_interval_max' must be a positive number"
        )

    final_skill_id = a2a_skill_id if a2a_skill_id else capability
    user_tags = list(tags) if tags is not None else []

    def decorator(target: T) -> T:
        # Coupled with the marker-propagation try/except at the bottom of this
        # decorator — that block copies _mesh_a2a_consumer_metadata onto the DI
        # wrapper returned by tool() so this guard catches re-decoration.
        if hasattr(target, "_mesh_a2a_consumer_metadata"):
            raise RuntimeError(
                f"@mesh.a2a_consumer({capability!r}): function {target.__name__!r} is already "
                "decorated with @mesh.a2a_consumer; stacking the decorator orphans the inner "
                "A2AClient. Apply @mesh.a2a_consumer exactly once per function."
            )

        # Deferred resolution of the surrounding @mesh.agent name. The
        # convention is that @mesh.agent is the LAST decorator in the
        # file (its auto_run blocks the importing thread), so this
        # consumer typically runs BEFORE the agent is registered. We
        # stamp a sentinel here and let the @mesh.agent decorator
        # substitute the real name once it knows it (see
        # _resolve_pending_consumer_self_tags below).
        merged_tags = list(user_tags)
        if _MESH_CONSUMER_SELF_SENTINEL not in merged_tags:
            merged_tags.append(_MESH_CONSUMER_SELF_SENTINEL)

        client = A2AClient(
            url=a2a_url,
            skill_id=final_skill_id,
            auth=auth,
            timeout_default=float(timeout),
            poll_interval=float(poll_interval),
            poll_interval_max=float(poll_interval_max),
        )

        # Detect whether the user function declares the ``_a2a`` parameter.
        # We require the literal name (NOT a prefix match) — anything
        # broader would be too magical and surprise users who name
        # parameters starting with ``_a``.
        import inspect as _inspect

        try:
            sig = _inspect.signature(target)
            wants_a2a = "_a2a" in sig.parameters
        except (TypeError, ValueError):
            wants_a2a = False

        if asyncio.iscoroutinefunction(target):

            @wraps(target)
            async def bridge(*args: Any, **call_kwargs: Any) -> Any:
                if wants_a2a and "_a2a" not in call_kwargs:
                    call_kwargs["_a2a"] = client
                return await target(*args, **call_kwargs)

        else:

            @wraps(target)
            def bridge(*args: Any, **call_kwargs: Any) -> Any:
                if wants_a2a and "_a2a" not in call_kwargs:
                    call_kwargs["_a2a"] = client
                return target(*args, **call_kwargs)

        # Hide the user's ``_a2a`` parameter from the inner @mesh.tool
        # signature analyzer — we bind it ourselves in ``bridge`` and the
        # DI single-parameter heuristic would otherwise log a noisy
        # "consider typing as McpMeshTool" warning AND attempt to inject
        # a remote-capability proxy into the slot. The user-facing
        # signature for FastMCP / the agent card stays clean too.
        if wants_a2a:
            user_sig = _inspect.signature(target)
            cleaned_params = [
                p for name, p in user_sig.parameters.items() if name != "_a2a"
            ]
            bridge.__signature__ = user_sig.replace(parameters=cleaned_params)

        # Stamp marker so debugging / introspection can see this is a
        # consumer-side bridge (parallels ``_mesh_a2a_metadata`` on the
        # producer side). ``consumer_name`` starts as the sentinel and
        # is rewritten in-place by ``_resolve_pending_consumer_self_tags``
        # when @mesh.agent runs.
        bridge._mesh_a2a_consumer_metadata = {
            "capability": capability,
            "a2a_url": a2a_url,
            "a2a_skill_id": final_skill_id,
            "tags": list(merged_tags),
            "auth": "bearer" if isinstance(auth, A2ABearer) else None,
            "consumer_name": _MESH_CONSUMER_SELF_SENTINEL,
        }
        bridge._mesh_a2a_consumer_client = client
        bridge._mesh_a2a_consumer_pending_self_tag = True

        # Route through the standard @mesh.tool registration path. This
        # is the only registration the consumer needs — heartbeat
        # publishes capability + tags via the regular mcp_startup
        # pipeline; no a2a_startup involvement.
        wrapped = tool(
            capability=capability,
            tags=merged_tags,
            version=version,
            description=description,
            **kwargs,
        )(bridge)

        # ``tool()`` returns the DI wrapper; copy the consumer markers
        # across so post-substitution can find them via the registry's
        # stored function reference too.
        # Propagate the consumer markers onto the DI wrapper returned by tool() —
        # the registry stores the wrapper, not bridge, AND the double-decoration
        # guard at the top of this decorator depends on these attributes being
        # observable via hasattr(target, ...).
        try:
            wrapped._mesh_a2a_consumer_metadata = bridge._mesh_a2a_consumer_metadata
            wrapped._mesh_a2a_consumer_client = bridge._mesh_a2a_consumer_client
            wrapped._mesh_a2a_consumer_pending_self_tag = True
        except (AttributeError, TypeError):
            pass

        return wrapped

    return decorator


def _resolve_pending_consumer_self_tags(agent_name: str) -> None:
    """Substitute the deferred consumer-name sentinel with the real
    @mesh.agent name across all registered tools and bridge functions.

    Called from the @mesh.agent decorator once the agent name is known.
    Walks both the function-level ``_mesh_tool_metadata`` (and
    ``_mesh_a2a_consumer_metadata``) AND the registry's stored copy,
    because ``DecoratorRegistry.register_mesh_tool`` snapshots metadata
    via ``.copy()`` at decoration time.

    Multi-``@mesh.agent`` diagnostic: if a second @mesh.agent runs in the
    same process after a first has already resolved all consumer self-tags,
    no pending tools remain and the substitution is a silent no-op. The
    first @mesh.agent's name "wins" and binds to all consumer tools. Emit
    a clear WARNING so users notice the implicit binding rather than
    debugging by archaeology.
    """
    if not agent_name:
        return

    def _swap(tag_list: list[str]) -> None:
        for i, t in enumerate(tag_list):
            if t == _MESH_CONSUMER_SELF_SENTINEL:
                tag_list[i] = agent_name

    registry_tools = DecoratorRegistry.get_mesh_tools()
    pending: list[Any] = []
    already_resolved = False
    for decorated in registry_tools.values():
        fn = decorated.function
        if getattr(fn, "_mesh_a2a_consumer_pending_self_tag", False):
            pending.append(decorated)
            continue
        # Use the explicit self-resolved marker rather than inferring from
        # consumer_name, so a future explicit ``consumer_name=`` kwarg on
        # @mesh.a2a_consumer (escape hatch for users who don't want the
        # auto self-tag) doesn't false-fire the multi-agent warning.
        if getattr(fn, "_mesh_a2a_consumer_self_resolved", False):
            already_resolved = True

    if not pending:
        if already_resolved:
            logger.warning(
                "@mesh.agent(%r): consumer-name self-tag substitution found 0 pending "
                "tools, but one or more @mesh.a2a_consumer tools have already been "
                "resolved by a prior @mesh.agent in this process. The first @mesh.agent "
                "wins and binds its name to all consumer tools. If multiple @mesh.agent "
                "declarations are intentional, document which one owns each consumer "
                "explicitly via consumer-name tags.",
                agent_name,
            )
        return

    for decorated in pending:
        fn = decorated.function

        fn_meta = getattr(fn, "_mesh_tool_metadata", None)
        if isinstance(fn_meta, dict):
            tags = fn_meta.get("tags")
            if isinstance(tags, list):
                _swap(tags)

        consumer_meta = getattr(fn, "_mesh_a2a_consumer_metadata", None)
        if isinstance(consumer_meta, dict):
            tags = consumer_meta.get("tags")
            if isinstance(tags, list):
                _swap(tags)
            if consumer_meta.get("consumer_name") == _MESH_CONSUMER_SELF_SENTINEL:
                consumer_meta["consumer_name"] = agent_name

        registry_tags = decorated.metadata.get("tags") if isinstance(decorated.metadata, dict) else None
        if isinstance(registry_tags, list):
            _swap(registry_tags)

        try:
            fn._mesh_a2a_consumer_pending_self_tag = False
            # Mark explicitly so future code can distinguish self-resolved
            # (sentinel-substituted by this @mesh.agent) from explicit
            # ``consumer_name=`` kwargs on @mesh.a2a_consumer.
            fn._mesh_a2a_consumer_self_resolved = True
        except (AttributeError, TypeError):
            pass


def _a2a_mount(*args: Any, **kwargs: Any):
    """Attribute alias for ``mesh.a2a.mount`` (see ``mesh.a2a.mount``).

    The implementation lives in ``mesh.a2a`` to keep the FastAPI import
    out of ``mesh.decorators`` (which is loaded eagerly by ``import mesh``
    and shouldn't pull FastAPI for users that only need ``@mesh.tool``).

    Imports via ``importlib`` rather than ``from . import a2a`` because
    the ``mesh`` package's ``__getattr__`` shadows ``a2a`` with the
    decorator function — a plain ``from`` import would resolve
    ``a2a`` to ``_a2a_mount`` itself and recurse.
    """
    import importlib

    a2a_module = importlib.import_module("mesh.a2a")
    return a2a_module.mount(*args, **kwargs)


# Expose ``mount`` as an attribute of the ``a2a`` decorator so users can
# write ``@mesh.a2a.mount(app, path=...)`` while still keeping
# ``@mesh.a2a(path=...)`` callable as a plain decorator.
a2a.mount = _a2a_mount  # type: ignore[attr-defined]


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
    provider: dict[str, Any],
    model: str | None = None,
    max_iterations: int = 10,
    system_prompt: str | None = None,
    system_prompt_file: str | None = None,
    response_model: type | None = None,
    context_param: str | None = None,
    parallel_tool_calls: bool = False,
    output_mode: str | None = None,
    **kwargs: Any,
) -> Callable[[T], T]:
    """
    LLM agent decorator with automatic agentic loop.

    Mesh-delegated only: every @mesh.llm consumer must point ``provider`` at a
    @mesh.llm_provider registered in the mesh. Direct LiteLLM mode was removed
    in v2 — there is one path, and it goes through a provider agent.

    The MeshLlmAgent proxy handles the complete agentic loop:
    - Tool filtering based on filter parameter
    - Provider resolution via mesh DI (capability + tags + version)
    - Tool execution via MCP proxies
    - Response parsing to Pydantic models

    Configuration Hierarchy (ENV > Decorator):
        - MESH_LLM_MODEL: Override the optional consumer-side model override
        - MESH_LLM_MAX_ITERATIONS: Override max iterations

    Usage:
        from pydantic import BaseModel
        import mesh

        class ChatResponse(BaseModel):
            answer: str
            confidence: float

        @mesh.llm(
            filter={"capability": "document", "tags": ["pdf"]},
            provider={"capability": "llm", "tags": ["claude"]},
        )
        @mesh.tool(capability="chat")
        async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            llm.set_system_prompt("You are a helpful assistant.")
            return await llm(message)

    Args:
        filter: Tool filter (string, dict, or list of mixed)
        filter_mode: Filter mode ("all", "best_match", "*")
        provider: REQUIRED. Provider filter dict for mesh delegation.
                  Format: {"capability": "llm", "tags": ["claude"], "version": ">=1.0.0"}
        model: Optional model override forwarded to the provider — lets a single
               consumer pin to a specific model (e.g., haiku) when the provider
               otherwise defaults to a different one (e.g., sonnet). May be
               overridden by MESH_LLM_MODEL.
        max_iterations: Max agentic loop iterations (can be overridden by MESH_LLM_MAX_ITERATIONS)
        system_prompt: Default system prompt (literal string or ``file://`` template)
        system_prompt_file: Path to Jinja2 template file (deprecated — use system_prompt="file://...")
        response_model: Schema the LLM is required to emit and validate against. When
                        set, it drives the provider structured-output schema and response
                        validation independently of the function's return annotation.
                        When omitted, falls back to the return annotation (current
                        behavior). The return annotation continues to drive the tool
                        ``outputSchema`` regardless.
        context_param: Function parameter name to auto-extract template context from
        parallel_tool_calls: Encourage the LLM to emit independent tool_calls in parallel
        output_mode: Optional structured-output mode forwarded to the provider.
                     One of "strict" (vendor-native schema enforcement, e.g.
                     response_format / responseSchema), "hint" (schema embedded
                     in the prompt instead of native enforcement), or "text" (no
                     schema enforcement). When omitted (None), the provider
                     auto-selects per vendor and schema (current behavior).
        **kwargs: Additional model parameters forwarded to the provider as defaults
                  (e.g., temperature=0.7, max_tokens=2048)

    Returns:
        Decorated function with MeshLlmAgent injection

    Raises:
        TypeError: If ``provider`` is not a dict
        ValueError: If no MeshLlmAgent parameter found
        UserWarning: If multiple MeshLlmAgent parameters or non-Pydantic return type
    """
    import inspect
    import warnings

    # Up-front validation: provider must be a dict (mesh delegation only).
    # Catch the legacy direct-mode signature (provider="claude") before we
    # walk the function body so the failure mode is clear and immediate.
    # Distinguish explicit None from the legacy string form so the error
    # message points at the right migration step.
    if provider is None:
        raise TypeError(
            "@mesh.llm: 'provider' is required (mesh-delegated only since v2). "
            "Pass provider={'capability': 'llm', 'tags': ['+claude']}. "
            "See docs/01-getting-started/06-llm-integration.md."
        )
    if not isinstance(provider, dict):
        raise TypeError(
            f"@mesh.llm: 'provider' must be a dict for mesh delegation "
            f"(got {type(provider).__name__}). Direct LLM mode was removed in v2.\n"
            f"  Use: @mesh.llm(provider={{'capability': 'llm', 'tags': ['+claude']}}, ...)\n"
            f"  Migrate from: @mesh.llm(provider='claude', model='...', api_key='...')"
        )

    # The explicit ``output_mode`` param is authoritative over any value passed
    # through ``**kwargs`` (kept for back-compat with the pre-promotion path).
    # Take the explicit param when set, else fall back to the kwargs value so a
    # single source feeds the LLMConfig without double-passing.
    if output_mode is None:
        output_mode = kwargs.pop("output_mode", None)
    else:
        kwargs.pop("output_mode", None)
    if output_mode is not None and output_mode not in ("strict", "hint", "text"):
        raise ValueError(
            f"@mesh.llm: 'output_mode' must be 'strict', 'hint', or 'text', "
            f"got {output_mode!r}."
        )

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

        # Mesh delegation: provider is the filter dict; never overridden by env.
        resolved_provider = provider

        # Resolve optional consumer-side model override with env var override
        resolved_model = get_config_value(
            "MESH_LLM_MODEL",
            override=model,
            default=None,
            rule=ValidationRule.STRING_RULE,
        )

        # Warn about missing configuration parameters
        if not system_prompt and not system_prompt_file:
            logger.warning(
                f"⚠️ @mesh.llm: No 'system_prompt' specified for function '{func.__name__}'. "
                f"Using default: 'You are a helpful assistant.' "
                f"Consider adding a custom system_prompt for better results."
            )

        # Use default system prompt if not provided
        effective_system_prompt = (
            system_prompt if system_prompt else "You are a helpful assistant."
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
            "model": resolved_model,
            "max_iterations": get_config_value(
                "MESH_LLM_MAX_ITERATIONS",
                override=max_iterations,
                default=10,
                rule=ValidationRule.NONZERO_RULE,
            ),
            "system_prompt": effective_system_prompt,
            "system_prompt_file": system_prompt_file,
            # Phase 1: Template metadata
            "is_template": is_template,
            "template_path": template_path,
            "context_param": context_param,
            "parallel_tool_calls": parallel_tool_calls,
            "output_mode": output_mode,
        }
        resolved_config.update(kwargs)

        # Step 2: Extract output type from return annotation
        sig = inspect.signature(func)
        return_annotation = sig.return_annotation

        # Issue #645 Phase 1: detect Stream[str] up front. When the function
        # is a streaming tool, the LLM-output type is implicitly str (the
        # element type) and the Pydantic-model warning below would be a false
        # alarm — skip it. ValueError for Stream[non-str] is re-raised with
        # decorator context.
        from _mcp_mesh.engine.stream_introspection import detect_stream_type

        try:
            llm_stream_type = detect_stream_type(func)
        except ValueError as e:
            raise ValueError(
                f"@mesh.llm '{func.__name__}': {e}"
            ) from None

        # Issue #1085: response_model takes precedence as the LLM-emitted/validated
        # schema. When omitted, fall back to the return annotation (back-compat).
        # The return annotation independently drives the tool outputSchema at
        # heartbeat time, so that path is unaffected by this choice.
        output_type = response_model
        if (
            output_type is None
            and return_annotation
            and return_annotation != inspect.Signature.empty
        ):
            output_type = return_annotation

        if output_type is not None:
            # Warn if the resolved LLM-output type is not a Pydantic model — but
            # skip the warning for streaming tools where the return annotation is
            # intentionally Stream[str].
            if llm_stream_type is None:
                try:
                    from pydantic import BaseModel

                    if not (
                        inspect.isclass(output_type) and issubclass(output_type, BaseModel)
                    ):
                        warnings.warn(
                            f"@mesh.llm tool '{func.__name__}': the resolved LLM response schema {output_type} "
                            f"is not a Pydantic BaseModel subclass (it comes from response_model= when set, "
                            f"otherwise the function return annotation). LLM structured-output validation may fail at runtime.",
                            UserWarning,
                            stacklevel=2,
                        )
                except ImportError:
                    pass  # Pydantic not available, skip validation

        # Stream[str] is a string-typed contract — chunks of str that accumulate
        # to a str final result. The chunked-vs-buffered distinction is encoded
        # separately via stream_type metadata, so the LLM-output type collapses
        # to str. Without this, MeshLlmAgent.stream() would reject the agent
        # because output_type would be AsyncIterator[str].
        if llm_stream_type == "text":
            output_type = str

        # Auto-discriminate stream vs buffered LLM provider variants via the
        # ``ai.mcpmesh.stream`` tag — consumer half of the contract with
        # ``@mesh.llm_provider``, which stamps the tag on its streaming variant
        # only. Stream consumers require the tag; buffered consumers exclude
        # it, so the registry resolver picks the right variant deterministically
        # via the existing +/- tag-operator semantics. If the user explicitly
        # set a discrimination tag (any operator form), don't override.
        provider_tags = list(resolved_provider.get("tags") or [])
        has_stream_tag = any(
            t in ("ai.mcpmesh.stream", "+ai.mcpmesh.stream", "-ai.mcpmesh.stream")
            for t in provider_tags
        )
        if not has_stream_tag:
            if llm_stream_type == "text":
                provider_tags.append("ai.mcpmesh.stream")
            else:
                provider_tags.append("-ai.mcpmesh.stream")
            resolved_provider = {**resolved_provider, "tags": provider_tags}
            resolved_config["provider"] = resolved_provider

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

        # Issue #645 Phase 1: when the LLM tool is declared as Stream[str],
        # propagate the marker onto the @mesh.tool metadata so heartbeat picks
        # it up. The detection at the @mesh.tool layer above sees the original
        # function annotation; this branch makes @mesh.llm-only usage work too
        # (no @mesh.tool decorator on top, no metadata entry yet).
        if llm_stream_type is not None:
            tool_meta = getattr(existing_wrapper, "_mesh_tool_metadata", None)
            if tool_meta is not None:
                tool_meta["stream_type"] = llm_stream_type

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

            # Override signature to hide LLM parameter from FastMCP schema.
            # Start from the existing wrapper's signature (not raw ``func``):
            # for streaming tools, ``@mesh.tool`` already appended the
            # synthesized progress-context keyword so FastMCP can auto-fill
            # ``Context`` for progress notifications. Reading from ``func``
            # here would drop that param and silently disable streaming
            # (issue #645 bug 3).
            try:
                _sig = (
                    inspect.signature(existing_wrapper)
                    if hasattr(existing_wrapper, "__signature__")
                    else inspect.signature(func)
                )
                _clean = [p for n, p in _sig.parameters.items() if n != param_name]
                combined_injection_wrapper.__signature__ = _sig.replace(
                    parameters=_clean
                )
            except Exception:
                pass

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

            # Override signature to hide LLM parameter from FastMCP schema
            try:
                _sig = inspect.signature(func)
                _clean = [p for n, p in _sig.parameters.items() if n != param_name]
                llm_injection_wrapper.__signature__ = _sig.replace(parameters=_clean)
            except Exception:
                pass

            # Update DecoratorRegistry with the wrapper
            DecoratorRegistry.update_mesh_llm_function(
                function_id, llm_injection_wrapper
            )

            # Return the new wrapper
            return llm_injection_wrapper

    return decorator
