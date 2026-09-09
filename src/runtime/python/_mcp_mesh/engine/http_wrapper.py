"""HTTP wrapper for MCP servers to enable distributed communication.

This module provides HTTP transport capabilities for MCP servers,
allowing them to communicate across network boundaries in containerized
and distributed environments.
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

from ..shared.fastmcp_transport import FASTMCP_TRANSPORT_SECURITY_KWARGS
from ..shared.logging_config import configure_logging

# Ensure logging is configured
configure_logging()

logger = logging.getLogger(__name__)


def _parse_session_ttl() -> int:
    """Parse and validate session TTL from environment."""
    raw = os.environ.get("MCP_MESH_SESSION_TTL", "3600")
    try:
        ttl = int(raw)
    except (ValueError, TypeError):
        ttl = 3600
    return max(1, min(ttl, 86400))


SESSION_TTL = _parse_session_ttl()

#: Per-operation Redis budget, seconds. Applied as the connect AND socket
#: timeout on the client and again as an ``asyncio.wait_for`` around each call
#: (issue #1590): the middleware that owns these calls runs on the uvicorn
#: serving loop, so an unbounded Redis operation stalls every concurrent
#: request on this process, ``/health`` and ``/ready`` included. Session
#: affinity is an optimisation — losing it for one request is strictly better
#: than blocking the process.
REDIS_OP_TIMEOUT_SECS = 2.0

#: Re-probe schedule after Redis goes away: 5s, 10s, 20s ... capped at 5min.
#: Without this the first blip latched ``redis_available = False`` forever and
#: silently downgraded the process to the (previously unbounded) in-memory
#: fallback for the rest of its life.
REDIS_REPROBE_BASE_SECS = 5.0
REDIS_REPROBE_MAX_SECS = 300.0

#: Hard cap on the in-memory fallback. Entries also carry the session TTL and
#: are purged on access; this bound is the backstop for a process that is
#: assigning sessions faster than they expire.
MEMORY_STORE_MAX_ENTRIES = 10_000


class SessionStorage:
    """Session storage with Redis backend and in-memory fallback.

    Issue #1590. Three properties this type has to hold, all of which the
    original synchronous implementation broke:

    * **It must never block the serving loop.** Every caller is ASGI
      middleware on the uvicorn loop. The client is therefore
      ``redis.asyncio`` with connect/socket timeouts, and each operation is
      additionally bounded by :data:`REDIS_OP_TIMEOUT_SECS`.
    * **The client must be built on the loop that uses it.** Construction is
      lazy and loop-checked rather than done in ``__init__`` (which runs on
      the transient startup pipeline loop) — an asyncio Redis pool built on
      one loop and awaited on another is the #1565 failure shape.
    * **The fallback must be bounded and temporary.** Memory entries carry
      the session TTL and are purged on access under a hard entry cap, and a
      Redis failure schedules a re-probe with exponential backoff instead of
      latching the downgrade permanently.
    """

    def __init__(self):
        self.redis_client = None
        # key -> (pod_ip, monotonic expiry)
        self.memory_store: dict[str, tuple[str, float]] = {}
        self.redis_available = False
        self._redis_loop = None
        self._redis_failures = 0
        self._next_redis_probe = 0.0
        # One connect at a time per loop. Without it, N concurrent first
        # requests each build a client (the last wins, the rest LEAK sockets)
        # and each failure calls _mark_redis_down, advancing the backoff N
        # times so a one-second blip jumps straight to the 300s cap and
        # defeats the fast-recovery intent. Keyed by loop because an
        # asyncio.Lock is loop-bound; the outer threading.Lock guards the map
        # itself so it is safe to reach from any thread.
        self._connect_locks: dict[int, asyncio.Lock] = {}
        self._connect_locks_guard = threading.Lock()

    def _connect_lock(self, loop) -> asyncio.Lock:
        with self._connect_locks_guard:
            lock = self._connect_locks.get(id(loop))
            if lock is None:
                lock = asyncio.Lock()
                self._connect_locks[id(loop)] = lock
            return lock

    async def _mark_redis_down(self, exc: Exception, what: str) -> None:
        """Latch Redis as unavailable and schedule the next probe.

        Idempotent for a burst: only the failure that actually transitions
        us out of a live/expired-window state advances the backoff. Ten
        concurrent requests failing on the same dead Redis therefore schedule
        ONE 5s probe, not one 300s probe.
        """
        already_down = not self.redis_available and (
            time.monotonic() < self._next_redis_probe
        )
        self.redis_available = False
        client, self.redis_client = self.redis_client, None
        self._redis_loop = None

        if already_down:
            logger.debug(
                "Redis %s failed again while already backing off (%s)", what, exc
            )
        else:
            self._redis_failures += 1
            delay = min(
                REDIS_REPROBE_BASE_SECS * (2 ** (self._redis_failures - 1)),
                REDIS_REPROBE_MAX_SECS,
            )
            self._next_redis_probe = time.monotonic() + delay
            logger.warning(
                # Type AND message: an asyncio.TimeoutError stringifies to "",
                # which would otherwise log "Redis get failed ()".
                "⚠️ Redis %s failed (%s: %s); using in-memory sessions, "
                "next probe in %.0fs",
                what,
                type(exc).__name__,
                exc,
                delay,
            )

        if client is not None:
            await self._close_client(client, owning_loop=None)

    async def _close_client(self, client, *, owning_loop) -> None:
        """Best-effort ``aclose()``, on the client's own loop when needed.

        A redis.asyncio pool holds asyncio primitives bound to the loop that
        created it, so closing it from a different loop is illegal — but
        DROPPING it leaks live sockets, which is worse than the awkwardness
        (issue #1590 review). Fire-and-forget on the owning loop; never let a
        teardown failure reach the request path.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - callers are all async
            running = None

        if owning_loop is None or owning_loop is running:
            try:
                await client.aclose()
            except Exception as e:  # noqa: BLE001 - teardown of a broken client
                logger.debug("Redis client close raised (%s); ignoring", e)
            return

        if not owning_loop.is_running():
            logger.debug("Cannot close the previous Redis client: its loop is gone")
            return
        try:
            # Fire-and-forget: the request path must not wait on a teardown.
            asyncio.run_coroutine_threadsafe(client.aclose(), owning_loop)
        except RuntimeError as e:
            logger.debug("Could not schedule Redis client close (%s)", e)

    def _healthy_on(self, loop) -> bool:
        """True when a live client already exists and belongs to ``loop``."""
        return (
            self.redis_available
            and self.redis_client is not None
            and self._redis_loop is loop
        )

    async def _ensure_redis(self) -> bool:
        """Return True when a live, loop-correct async Redis client is ready.

        Cheap on the hot path: one identity check when the client is healthy,
        one monotonic-clock comparison when it is not and the backoff window
        has not elapsed. The connect itself is single-flight per loop, so a
        burst of concurrent first requests produces ONE client and ONE backoff
        step rather than N of each (issue #1590 review).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - callers are all async
            return False

        # Fast path, lock-free.
        if self._healthy_on(loop):
            return True
        if not self.redis_available and time.monotonic() < self._next_redis_probe:
            return False

        async with self._connect_lock(loop):
            # Re-check under the lock: another coroutine may have connected (or
            # latched a fresh backoff window) while we waited for it.
            if self._healthy_on(loop):
                return True
            if not self.redis_available and time.monotonic() < self._next_redis_probe:
                return False

            if self.redis_client is not None:
                # A live client owned by a DIFFERENT loop (tool-executor
                # worker, heartbeat thread). Its asyncio primitives are bound
                # to that loop, so it has to be rebuilt here — but it must be
                # CLOSED on its own loop, not dropped, or its sockets leak.
                logger.debug("Redis session client rebuilt for a different event loop")
                stale, self.redis_client = self.redis_client, None
                stale_loop, self._redis_loop = self._redis_loop, None
                self.redis_available = False
                await self._close_client(stale, owning_loop=stale_loop)

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            try:
                import redis.asyncio as aioredis

                client = aioredis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_timeout=REDIS_OP_TIMEOUT_SECS,
                    socket_connect_timeout=REDIS_OP_TIMEOUT_SECS,
                )
                await asyncio.wait_for(client.ping(), timeout=REDIS_OP_TIMEOUT_SECS)
            except Exception as e:  # noqa: BLE001 - any failure means "use memory"
                await self._mark_redis_down(e, "connect")
                return False

            self.redis_client = client
            self._redis_loop = loop
            self.redis_available = True
            self._redis_failures = 0
            self._next_redis_probe = 0.0
            logger.info(f"✅ Redis session storage connected: {redis_url}")
            return True

    def _session_key(self, session_id: str, capability: str = None) -> str:
        """Build a session storage key."""
        return (
            f"session:{session_id}:{capability}"
            if capability
            else f"session:{session_id}"
        )

    def _memory_get(self, session_key: str) -> str | None:
        """Read from the fallback, honouring the session TTL."""
        entry = self.memory_store.get(session_key)
        if entry is None:
            return None
        pod_ip, expires_at = entry
        if time.monotonic() >= expires_at:
            self.memory_store.pop(session_key, None)
            return None
        return pod_ip

    def _memory_set(self, session_key: str, pod_ip: str, ttl: int) -> None:
        """Write to the fallback under a TTL and a hard entry cap."""
        now = time.monotonic()
        expired = [k for k, (_, exp) in self.memory_store.items() if now >= exp]
        for key in expired:
            self.memory_store.pop(key, None)

        self.memory_store[session_key] = (pod_ip, now + ttl)

        overflow = len(self.memory_store) - MEMORY_STORE_MAX_ENTRIES
        if overflow > 0:
            # Evict the entries closest to expiry first — they are the ones a
            # subsequent request is least likely to still need.
            doomed = sorted(self.memory_store.items(), key=lambda kv: kv[1][1])
            for key, _ in doomed[:overflow]:
                self.memory_store.pop(key, None)
            logger.warning(
                "In-memory session store hit the %d-entry cap; evicted %d "
                "soonest-to-expire session(s)",
                MEMORY_STORE_MAX_ENTRIES,
                overflow,
            )

    async def get_session_pod(self, session_id: str, capability: str = None) -> str:
        """Get assigned pod for session."""
        session_key = self._session_key(session_id, capability)

        if await self._ensure_redis():
            try:
                assigned_pod = await asyncio.wait_for(
                    self.redis_client.get(session_key),
                    timeout=REDIS_OP_TIMEOUT_SECS,
                )
                if assigned_pod:
                    logger.debug(
                        f"📍 Redis: Found session {session_key} -> {assigned_pod}"
                    )
                    return assigned_pod
                # A Redis MISS still has to consult memory (issue #1590
                # review). Sessions assigned while Redis was down live only in
                # the fallback, so returning None here would let the middleware
                # re-assign an established session to THIS pod and silently
                # move it off the pod holding its state. This path was
                # unreachable before the re-probe existed, because the first
                # failure latched redis_available=False for the process
                # lifetime and Redis was never consulted again.
                remembered = self._memory_get(session_key)
                if remembered is not None:
                    logger.info(
                        f"📍 Recovering session {session_key} -> {remembered} "
                        "from the in-memory fallback into Redis"
                    )
                    await self._write_through(session_key, remembered)
                return remembered
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - degrade, never fail the request
                await self._mark_redis_down(e, "get")

        # Fallback to memory store
        return self._memory_get(session_key)

    async def _write_through(self, session_key: str, pod_ip: str) -> None:
        """Best-effort re-assert of a fallback entry into a recovered Redis.

        Bounded and swallowed: this is opportunistic repair on a read path and
        must never turn a successful lookup into a failed request.
        """
        try:
            await asyncio.wait_for(
                self.redis_client.setex(session_key, SESSION_TTL, pod_ip),
                timeout=REDIS_OP_TIMEOUT_SECS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.debug("Session write-through to Redis failed (%s); ignoring", e)

    async def assign_session_pod(
        self, session_id: str, pod_ip: str, capability: str = None
    ) -> str:
        """Assign pod to session with TTL."""
        session_key = self._session_key(session_id, capability)
        ttl = SESSION_TTL

        if await self._ensure_redis():
            try:
                await asyncio.wait_for(
                    self.redis_client.setex(session_key, ttl, pod_ip),
                    timeout=REDIS_OP_TIMEOUT_SECS,
                )
                logger.info(f"📍 Redis: Assigned session {session_key} -> {pod_ip}")
                return pod_ip
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - degrade, never fail the request
                await self._mark_redis_down(e, "setex")

        # Fallback to memory store
        self._memory_set(session_key, pod_ip, ttl)
        logger.info(f"📍 Memory: Assigned session {session_key} -> {pod_ip}")
        return pod_ip

    async def get_stats(self) -> dict:
        """Get session storage statistics.

        Async since #1590: the Redis client is ``redis.asyncio`` now, so a
        synchronous reader would have handed back un-awaited coroutines.
        """
        stats = {
            "storage_type": "redis" if self.redis_available else "memory",
            "redis_available": self.redis_available,
        }

        if self.redis_available and self.redis_client is not None:
            try:
                session_keys = await asyncio.wait_for(
                    self.redis_client.keys("session:*"),
                    timeout=REDIS_OP_TIMEOUT_SECS,
                )
                stats["total_sessions"] = len(session_keys)
                stats["active_sessions"] = session_keys[:10]  # First 10 for debugging
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - stats must never raise
                stats["total_sessions"] = 0
        else:
            now = time.monotonic()
            live = [k for k, (_, exp) in self.memory_store.items() if now < exp]
            stats["total_sessions"] = len(live)
            stats["active_sessions"] = live[:10]

        return stats


class HttpMcpWrapper:
    """Wraps FastMCP server for mounting into main FastAPI application."""

    def __init__(self, mcp_server: FastMCP):
        self.mcp_server = mcp_server

        # FastMCP app for mounting into main FastAPI app
        self._mcp_app = None
        self._lifespan = None

        # Phase 3: Metadata caching
        self._metadata_cache: dict[str, Any] = {}
        self._cache_timestamp: datetime | None = None
        self._cache_ttl: timedelta = timedelta(minutes=5)  # Cache for 5 minutes

        # Phase 5: Session storage and pod info
        self.session_storage = SessionStorage()
        self.pod_ip = os.getenv("POD_IP", "localhost")

        # Use resolved HTTP port: env var > decorator param > default (same resolution as FastAPI server)
        # This ensures session forwarding uses the same port as the FastAPI server
        self.pod_port = os.getenv("MCP_MESH_HTTP_PORT", "8080")

        # Get FastMCP's lifespan if available (for new FastMCP integration)
        if hasattr(mcp_server, "http_app") and callable(mcp_server.http_app):
            try:
                # Create FastMCP HTTP app with stateless transport
                logger.debug("🔍 Creating FastMCP HTTP app with stateless transport")
                # Disable FastMCP's DNS-rebinding Host/Origin guard (#1312):
                # it defaults to localhost-only allowed_hosts and rejects
                # server-to-server calls whose Host is the k8s Service DNS name
                # with 421 Misdirected Request. Mesh is an internal service
                # mesh, so the browser DNS-rebinding threat model does not apply.
                self._mcp_app = mcp_server.http_app(
                    stateless_http=True,
                    transport="streamable-http",
                    **FASTMCP_TRANSPORT_SECURITY_KWARGS,
                )
                logger.debug(f"✅ Created FastMCP app: {type(self._mcp_app)}")
                if hasattr(self._mcp_app, "lifespan"):
                    self._lifespan = self._mcp_app.lifespan
                    logger.debug("✅ Got FastMCP lifespan for FastAPI app")
            except Exception as e:
                logger.warning(f"Could not create FastMCP stateless app: {e}")
                # Try without stateless_http parameter
                try:
                    logger.debug("🔄 Trying FastMCP HTTP app without stateless_http")
                    # Keep the #1312 Host-guard override on the fallback path too.
                    self._mcp_app = mcp_server.http_app(
                        **FASTMCP_TRANSPORT_SECURITY_KWARGS
                    )
                    if hasattr(self._mcp_app, "lifespan"):
                        self._lifespan = self._mcp_app.lifespan
                        logger.debug("✅ Got FastMCP lifespan (fallback)")
                except Exception as e2:
                    logger.warning(f"FastMCP HTTP app creation failed entirely: {e2}")

    async def setup(self):
        """Set up FastMCP app for integration (no separate wrapper app)."""

        # Using FastMCP library (fastmcp>=3.0.0)
        logger.info(
            "🆕 HTTP Wrapper: Server instance is from FastMCP library (fastmcp)"
        )

        if self._mcp_app is not None:
            # Phase 5: Add session routing middleware to FastMCP app
            self._add_session_routing_middleware()

            logger.debug("🌐 FastMCP app ready for integration with main FastAPI app")
        else:
            logger.warning(
                "❌ FastMCP server doesn't have any supported HTTP app method"
            )
            raise AttributeError("No supported HTTP app method")

    def _get_external_host(self) -> str:
        """Get external hostname for endpoint display."""
        from _mcp_mesh.shared.host_resolver import HostResolver

        return HostResolver.get_external_host()

    def get_endpoint(self, port: int) -> str:
        """Get the full HTTP endpoint URL using the main FastAPI app's port."""
        return f"http://{self._get_external_host()}:{port}"

    # Phase 3: Metadata Caching Methods
    def _is_cache_valid(self) -> bool:
        """Check if metadata cache is still valid."""
        if not self._cache_timestamp:
            return False
        return datetime.now() - self._cache_timestamp < self._cache_ttl

    def _invalidate_cache(self) -> None:
        """Invalidate the metadata cache."""
        self._metadata_cache.clear()
        self._cache_timestamp = None
        logger.debug("🗑️ Metadata cache invalidated")

    def _update_cache(self, metadata: dict[str, Any]) -> None:
        """Update the metadata cache with new data."""
        self._metadata_cache = metadata.copy()
        self._cache_timestamp = datetime.now()
        logger.debug(f"📋 Metadata cache updated with {len(metadata)} entries")

    def get_cached_metadata(self) -> dict[str, Any] | None:
        """Get cached metadata if available and valid."""
        if self._is_cache_valid():
            logger.debug("✅ Returning cached metadata")
            return self._metadata_cache.copy()
        else:
            logger.debug("❌ Cache invalid or expired")
            return None

    def fetch_and_cache_metadata(self, endpoint: str) -> dict[str, Any]:
        """Fetch metadata from remote endpoint and cache it."""
        try:
            import json
            import urllib.error
            import urllib.request

            # Build metadata endpoint URL
            metadata_url = f"{endpoint}/metadata"
            logger.debug(f"🔍 Fetching metadata from: {metadata_url}")

            # Make HTTP request to /metadata endpoint
            req = urllib.request.Request(
                metadata_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "MCP-Mesh-HttpWrapper/1.0",
                },
            )

            with urllib.request.urlopen(req, timeout=10.0) as response:
                response_data = response.read().decode("utf-8")
                metadata = json.loads(response_data)

                # Cache the metadata
                self._update_cache(metadata)
                logger.debug(f"✅ Fetched and cached metadata from {endpoint}")
                return metadata

        except Exception as e:
            logger.warning(f"❌ Failed to fetch metadata from {endpoint}: {e}")
            # Return empty metadata on error
            return {
                "agent_id": "unknown",
                "capabilities": {},
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(e),
            }

    def get_metadata_with_cache(self, endpoint: str) -> dict[str, Any]:
        """Get metadata with caching - try cache first, then fetch."""
        # Try cache first
        cached_metadata = self.get_cached_metadata()
        if cached_metadata:
            return cached_metadata

        # Cache miss or invalid - fetch fresh data
        logger.debug("🔄 Cache miss - fetching fresh metadata")
        return self.fetch_and_cache_metadata(endpoint)

    def get_capability_routing_info(
        self, endpoint: str, capability: str
    ) -> dict[str, Any]:
        """Get routing information for a specific capability."""
        metadata = self.get_metadata_with_cache(endpoint)
        capabilities = metadata.get("capabilities", {})

        if capability in capabilities:
            capability_info = capabilities[capability]
            return {
                "available": True,
                "capability": capability,
                "routing_flags": {
                    "session_required": capability_info.get("session_required", False),
                    "stateful": capability_info.get("stateful", False),
                    "streaming": capability_info.get("streaming", False),
                    "full_mcp_access": capability_info.get("full_mcp_access", False),
                },
                "function_name": capability_info.get("function_name"),
                "description": capability_info.get("description", ""),
                "version": capability_info.get("version", "1.0.0"),
                "agent_id": metadata.get("agent_id"),
                "endpoint": endpoint,
            }
        else:
            return {
                "available": False,
                "capability": capability,
                "error": f"Capability '{capability}' not found",
                "endpoint": endpoint,
            }

    def refresh_metadata_cache(self, endpoint: str) -> dict[str, Any]:
        """Force refresh of metadata cache."""
        self._invalidate_cache()
        return self.fetch_and_cache_metadata(endpoint)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for debugging."""
        return {
            "cache_size": len(self._metadata_cache),
            "cache_timestamp": (
                self._cache_timestamp.isoformat() if self._cache_timestamp else None
            ),
            "cache_ttl_seconds": self._cache_ttl.total_seconds(),
            "cache_valid": self._is_cache_valid(),
            "cache_entries": (
                list(self._metadata_cache.get("capabilities", {}).keys())
                if self._metadata_cache
                else []
            ),
        }

    # Phase 5: Session Routing Methods
    def _add_session_routing_middleware(self):
        """Add session routing middleware to FastMCP app."""
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import Response

        class MCPSessionRoutingMiddleware(BaseHTTPMiddleware):
            """Clean session routing middleware for MCP requests (v0.4.0 style).

            Handles session affinity and basic trace context setup only.
            Function execution tracing is handled by ExecutionTracer in DependencyInjector.
            """

            def __init__(self, app, http_wrapper):
                super().__init__(app)
                self.http_wrapper = http_wrapper
                self.logger = logger

            async def dispatch(self, request: Request, call_next):
                # Read body once for processing
                body = await request.body()
                modified_body = body

                # Extract and set trace context from headers and arguments
                try:
                    from ..tracing.context import TraceContext
                    from ..tracing.trace_context_helper import TraceContextHelper

                    # DEBUG: Log incoming headers for trace propagation debugging
                    trace_id_header = request.headers.get("X-Trace-ID")
                    parent_span_header = request.headers.get("X-Parent-Span")
                    self.logger.info(
                        f"🔍 INCOMING_HEADERS: X-Trace-ID={trace_id_header}, "
                        f"X-Parent-Span={parent_span_header}, path={request.url.path}"
                    )

                    # Extract trace context from both headers AND arguments
                    trace_id = trace_id_header
                    parent_span = parent_span_header

                    # Try extracting from JSON-RPC body arguments as fallback
                    # Also strip trace fields from arguments to avoid Pydantic validation errors
                    if body:
                        try:
                            payload = json.loads(body.decode("utf-8"))
                            if payload.get("method") == "tools/call":
                                arguments = payload.get("params", {}).get(
                                    "arguments", {}
                                )

                                # Extract trace context from arguments (TypeScript uses _trace_id/_parent_span)
                                if not trace_id and arguments.get("_trace_id"):
                                    trace_id = arguments.get("_trace_id")
                                if not parent_span and arguments.get("_parent_span"):
                                    parent_span = arguments.get("_parent_span")

                                # Extract _mesh_headers from arguments
                                mesh_headers_raw = arguments.pop("_mesh_headers", None)
                                if mesh_headers_raw and isinstance(
                                    mesh_headers_raw, dict
                                ):
                                    from ..tracing.context import (
                                        PROPAGATE_HEADERS as _PH,
                                    )
                                    from ..tracing.context import TraceContext as _TC2
                                    from ..tracing.context import (
                                        matches_propagate_header,
                                    )

                                    if _PH:
                                        filtered = {
                                            k.lower(): v
                                            for k, v in mesh_headers_raw.items()
                                            if isinstance(v, str)
                                            and matches_propagate_header(k)
                                        }
                                    else:
                                        filtered = {}

                                    if filtered:
                                        # Merge with HTTP-captured headers (HTTP takes precedence)
                                        existing = _TC2.get_propagated_headers()
                                        if existing:
                                            merged = dict(filtered)
                                            merged.update(
                                                existing
                                            )  # HTTP headers override arg headers
                                            filtered = merged
                                        _TC2.set_propagated_headers(filtered)
                                        self.logger.debug(
                                            f"Set {len(filtered)} propagated headers from _mesh_headers args"
                                        )

                                # Strip trace context fields from arguments before passing to FastMCP
                                if (
                                    "_trace_id" in arguments
                                    or "_parent_span" in arguments
                                    or mesh_headers_raw is not None
                                ):
                                    arguments.pop("_trace_id", None)
                                    arguments.pop("_parent_span", None)
                                    # Update payload with cleaned arguments
                                    modified_body = json.dumps(payload).encode("utf-8")
                                    self.logger.debug(
                                        f"🔗 Stripped trace fields from arguments, "
                                        f"trace_id={trace_id[:8] if trace_id else None}..."
                                    )
                        except Exception as e:
                            self.logger.debug(
                                f"Failed to process body for trace context: {e}"
                            )

                    # Setup trace context if we have a trace_id
                    if trace_id:
                        trace_context = {
                            "trace_id": trace_id,
                            "parent_span": parent_span,
                        }
                        TraceContextHelper.setup_request_trace_context(
                            trace_context, self.logger
                        )

                    # Capture configured propagation headers from incoming request
                    from ..tracing.context import (
                        DISPATCH_HEADERS,
                        PROPAGATE_HEADERS,
                        matches_propagate_header,
                    )
                    from ..tracing.context import TraceContext as _TC

                    # Issue #1570: capture the push-mode dispatch protocol
                    # headers from the RAW inbound request, independently of
                    # the propagate allowlist. They are the dispatch
                    # discriminator, deliberately NOT allowlisted (a nested
                    # outbound call must not look like a job dispatch to every
                    # downstream) — so reading them off the filtered map would
                    # leave push-mode dispatch over HTTP unreachable.
                    dispatch = {
                        name.lower(): value
                        for name, value in request.headers.items()
                        if name.lower() in DISPATCH_HEADERS and value
                    }
                    if dispatch:
                        _TC.set_dispatch_headers(dispatch)
                        self.logger.debug(
                            f"Captured {len(dispatch)} inbound dispatch headers"
                        )

                    if PROPAGATE_HEADERS:
                        captured = {}
                        for header_name, value in request.headers.items():
                            if matches_propagate_header(header_name):
                                captured[header_name.lower()] = value
                        if captured:
                            existing = _TC.get_propagated_headers()
                            if existing:
                                merged = {**existing, **captured}
                            else:
                                merged = captured
                            _TC.set_propagated_headers(merged)
                            self.logger.debug(
                                f"Captured {len(captured)} propagation headers"
                            )
                except Exception as e:
                    # Never fail request due to tracing issues
                    self.logger.warning(f"Failed to set trace context: {e}")
                    pass

                # Create a new request scope with the modified body
                async def receive():
                    return {"type": "http.request", "body": modified_body}

                # Update request with modified receive
                request._receive = receive

                # Extract session ID from request
                session_id = await self.http_wrapper._extract_session_id_from_body(body)

                if session_id:
                    # Check for existing session assignment
                    assigned_pod = (
                        await self.http_wrapper.session_storage.get_session_pod(
                            session_id
                        )
                    )

                    if assigned_pod and assigned_pod != self.http_wrapper.pod_ip:
                        # Forward to assigned pod
                        return await self.http_wrapper._forward_to_external_pod(
                            request, assigned_pod
                        )
                    elif not assigned_pod:
                        # New session - assign to this pod
                        await self.http_wrapper.session_storage.assign_session_pod(
                            session_id, self.http_wrapper.pod_ip
                        )
                        self.logger.info(
                            f"📍 Session {session_id} assigned to {self.http_wrapper.pod_ip}"
                        )
                    # else: assigned to this pod, process locally

                # Process locally with FastMCP
                return await call_next(request)

        # Add the middleware to FastMCP app
        self._mcp_app.add_middleware(MCPSessionRoutingMiddleware, http_wrapper=self)
        logger.info(
            "✅ Clean session routing middleware added to FastMCP app (v0.4.0 style)"
        )

    async def _extract_session_id(self, request) -> str:
        """Extract session ID from request headers or body."""
        # Try header first
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            return session_id

        # Try extracting from JSON-RPC body
        try:
            body = await request.body()
            return await self._extract_session_id_from_body(body)
        except Exception:
            pass

        return None

    async def _extract_session_id_from_body(self, body: bytes) -> str:
        """Extract session ID from already-read request body."""
        try:
            if body:
                payload = json.loads(body.decode("utf-8"))
                if payload.get("method") == "tools/call":
                    arguments = payload.get("params", {}).get("arguments", {})
                    return arguments.get("session_id")
        except Exception:
            pass

        return None

    async def _forward_to_external_pod(self, request, target_pod: str):
        """Forward request to external pod."""
        try:
            # Read request body
            body = await request.body()

            # Prepare headers
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("content-length", None)

            # Forward to target pod
            target_url = f"http://{target_pod}:{self.pod_port}{request.url.path}"
            logger.info(f"🔄 Forwarding session to {target_url}")

            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    params=request.query_params,
                )

                from starlette.responses import Response

                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                )

        except Exception as e:
            logger.error(f"❌ Session forwarding failed: {e}")
            # Return error - don't process locally as it would break session affinity
            from starlette.responses import Response

            return Response(
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {
                            "code": -32603,
                            "message": f"Session forwarding failed: {str(e)}",
                        },
                    }
                ),
                status_code=503,
                headers={"Content-Type": "application/json"},
            )

    async def get_session_stats(self) -> dict:
        """Get current session affinity statistics.

        Async since #1590 — see :meth:`SessionStorage.get_stats`.
        """
        storage_stats = await self.session_storage.get_stats()

        return {
            "pod_ip": self.pod_ip,
            "storage_backend": storage_stats["storage_type"],
            "redis_available": storage_stats["redis_available"],
            "total_sessions": storage_stats["total_sessions"],
            "active_sessions": storage_stats.get("active_sessions", []),
        }
