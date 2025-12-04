"""HTTP wrapper for MCP servers to enable distributed communication.

This module provides HTTP transport capabilities for MCP servers,
allowing them to communicate across network boundaries in containerized
and distributed environments.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

from ..shared.logging_config import configure_logging

# Ensure logging is configured
configure_logging()

logger = logging.getLogger(__name__)


class SessionStorage:
    """Session storage with Redis backend and in-memory fallback."""

    def __init__(self):
        self.redis_client = None
        self.memory_store = {}  # Fallback storage
        self.redis_available = False
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis client with graceful fallback."""
        try:
            import redis

            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            self.redis_client = redis.from_url(redis_url, decode_responses=True)

            # Test connection
            self.redis_client.ping()
            self.redis_available = True
            logger.info(f"✅ Redis session storage connected: {redis_url}")

        except Exception as e:
            logger.warning(f"⚠️ Redis unavailable, using in-memory sessions: {e}")
            self.redis_available = False

    async def get_session_pod(self, session_id: str, capability: str = None) -> str:
        """Get assigned pod for session."""
        # Use capability-specific key if provided, otherwise simple session key
        session_key = (
            f"session:{session_id}:{capability}"
            if capability
            else f"session:{session_id}"
        )

        if self.redis_available:
            try:
                assigned_pod = self.redis_client.get(session_key)
                if assigned_pod:
                    logger.debug(
                        f"📍 Redis: Found session {session_key} -> {assigned_pod}"
                    )
                    return assigned_pod
            except Exception as e:
                logger.warning(f"Redis get failed, falling back to memory: {e}")
                self.redis_available = False

        # Fallback to memory store
        return self.memory_store.get(session_key)

    async def assign_session_pod(
        self, session_id: str, pod_ip: str, capability: str = None
    ) -> str:
        """Assign pod to session with TTL."""
        # Use capability-specific key if provided, otherwise simple session key
        session_key = (
            f"session:{session_id}:{capability}"
            if capability
            else f"session:{session_id}"
        )
        ttl = 3600  # 1 hour TTL

        if self.redis_available:
            try:
                self.redis_client.setex(session_key, ttl, pod_ip)
                logger.info(f"📍 Redis: Assigned session {session_key} -> {pod_ip}")
                return pod_ip
            except Exception as e:
                logger.warning(f"Redis set failed, falling back to memory: {e}")
                self.redis_available = False

        # Fallback to memory store
        self.memory_store[session_key] = pod_ip
        logger.info(f"📍 Memory: Assigned session {session_key} -> {pod_ip}")
        return pod_ip

    def get_stats(self) -> dict:
        """Get session storage statistics."""
        stats = {
            "storage_type": "redis" if self.redis_available else "memory",
            "redis_available": self.redis_available,
        }

        if self.redis_available:
            try:
                session_keys = self.redis_client.keys("session:*")
                stats["total_sessions"] = len(session_keys)
                stats["active_sessions"] = session_keys[:10]  # First 10 for debugging
            except Exception:
                stats["total_sessions"] = 0
        else:
            stats["total_sessions"] = len(self.memory_store)
            stats["active_sessions"] = list(self.memory_store.keys())[:10]

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
                self._mcp_app = mcp_server.http_app(
                    stateless_http=True, transport="streamable-http"
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
                    self._mcp_app = mcp_server.http_app()
                    if hasattr(self._mcp_app, "lifespan"):
                        self._lifespan = self._mcp_app.lifespan
                        logger.debug("✅ Got FastMCP lifespan (fallback)")
                except Exception as e2:
                    logger.warning(f"FastMCP HTTP app creation failed entirely: {e2}")

    async def setup(self):
        """Set up FastMCP app for integration (no separate wrapper app)."""

        # Using FastMCP library (fastmcp>=2.8.0)
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

    def _get_capabilities(self) -> list[str]:
        """Extract capabilities from registered tools."""
        capabilities = set()

        # Look for mesh metadata on tools
        if hasattr(self.mcp_server, "_tool_manager"):
            for _, tool in self.mcp_server._tool_manager._tools.items():
                # Check for mesh metadata
                if hasattr(tool.fn, "_mesh_agent_metadata"):
                    metadata = tool.fn._mesh_agent_metadata
                    if "capability" in metadata:
                        capabilities.add(metadata["capability"])

        return list(capabilities)

    def _get_dependencies(self) -> list[str]:
        """Extract dependencies from registered tools."""
        dependencies = set()

        # Look for mesh metadata on tools
        if hasattr(self.mcp_server, "_tool_manager"):
            for _, tool in self.mcp_server._tool_manager._tools.items():
                # Check for mesh dependencies
                if hasattr(tool.fn, "_mesh_agent_dependencies"):
                    deps = tool.fn._mesh_agent_dependencies
                    dependencies.update(deps)

        return list(dependencies)

    def _extract_tool_params(self, tool: Any) -> dict:
        """Extract parameter schema from tool."""
        # This is a simplified version - real implementation would
        # introspect function signature and type hints
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

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
                # Extract and set trace context from headers for distributed tracing
                try:
                    from ..tracing.trace_context_helper import TraceContextHelper

                    # DEBUG: Log incoming headers for trace propagation debugging
                    trace_id_header = request.headers.get("X-Trace-ID")
                    parent_span_header = request.headers.get("X-Parent-Span")
                    self.logger.info(
                        f"🔍 INCOMING_HEADERS: X-Trace-ID={trace_id_header}, "
                        f"X-Parent-Span={parent_span_header}, path={request.url.path}"
                    )

                    # Use helper class for trace context extraction and setup
                    trace_context = (
                        await TraceContextHelper.extract_trace_context_from_request(
                            request
                        )
                    )
                    TraceContextHelper.setup_request_trace_context(
                        trace_context, self.logger
                    )
                except Exception as e:
                    # Never fail request due to tracing issues
                    self.logger.warning(f"Failed to set trace context: {e}")
                    pass

                # Extract session ID from request
                session_id = await self.http_wrapper._extract_session_id(request)

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

    def get_session_stats(self) -> dict:
        """Get current session affinity statistics."""
        storage_stats = self.session_storage.get_stats()

        return {
            "pod_ip": self.pod_ip,
            "storage_backend": storage_stats["storage_type"],
            "redis_available": storage_stats["redis_available"],
            "total_sessions": storage_stats["total_sessions"],
            "active_sessions": storage_stats.get("active_sessions", []),
        }
