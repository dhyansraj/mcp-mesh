"""HTTP wrapper for MCP servers to enable distributed communication.

This module provides HTTP transport capabilities for MCP servers,
allowing them to communicate across network boundaries in containerized
and distributed environments.
"""

import asyncio
import json
import logging
import os
import socket
import time
from contextlib import closing
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .logging_config import configure_logging

# Ensure logging is configured
configure_logging()

logger = logging.getLogger(__name__)

# Prometheus metrics
mcp_requests_total = Counter(
    "mcp_requests_total", "Total number of MCP requests", ["method", "status", "agent"]
)

mcp_request_duration_seconds = Histogram(
    "mcp_request_duration_seconds",
    "MCP request latency in seconds",
    ["method", "agent"],
)

mcp_active_connections = Gauge(
    "mcp_active_connections", "Number of active connections", ["agent"]
)

mcp_tools_total = Gauge(
    "mcp_tools_total", "Total number of registered tools", ["agent"]
)

mcp_capabilities_total = Gauge(
    "mcp_capabilities_total", "Total number of capabilities", ["agent"]
)

mcp_dependencies_total = Gauge(
    "mcp_dependencies_total", "Total number of dependencies", ["agent"]
)

http_requests_total = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)


class HttpConfig:
    """Configuration for HTTP wrapper."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 0,
        cors_enabled: bool = True,
        cors_origins: list[str] = None,
    ):
        self.host = host
        self.port = port  # 0 = auto-assign
        self.cors_enabled = cors_enabled
        self.cors_origins = cors_origins or ["*"]


class HttpMcpWrapper:
    """Wraps MCP server with HTTP endpoints for distributed communication."""

    def __init__(self, mcp_server: FastMCP, config: HttpConfig):
        self.mcp_server = mcp_server
        self.config = config
        self.app = FastAPI(
            title=f"MCP Agent: {mcp_server.name}",
            description="HTTP-enabled MCP agent for distributed communication",
        )
        self.actual_port: int | None = None
        self.server: uvicorn.Server | None = None
        self._setup_task: asyncio.Task | None = None

    async def setup(self):
        """Set up HTTP endpoints and middleware."""

        # 1. Add metrics middleware
        @self.app.middleware("http")
        async def track_requests(request: Request, call_next):
            """Track HTTP request metrics."""
            start_time = time.time()

            # Extract endpoint for metrics
            endpoint = request.url.path
            method = request.method

            # Track active connections
            mcp_active_connections.labels(agent=self.mcp_server.name).inc()

            try:
                response = await call_next(request)
                status = response.status_code

                # Track request metrics
                http_requests_total.labels(
                    method=method, endpoint=endpoint, status=status
                ).inc()

                return response
            finally:
                # Track request duration
                duration = time.time() - start_time
                http_request_duration_seconds.labels(
                    method=method, endpoint=endpoint
                ).observe(duration)

                # Decrement active connections
                mcp_active_connections.labels(agent=self.mcp_server.name).dec()

        # 2. Add CORS middleware if enabled
        if self.config.cors_enabled:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=self.config.cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # 3. Mount MCP endpoints
        try:
            from mcp.server.fastapi import create_app

            mcp_app = create_app(self.mcp_server)
            self.app.mount("/mcp", mcp_app)
        except ImportError:
            logger.warning(
                "FastAPI MCP server not available, using fallback implementation"
            )
            self._setup_fallback_mcp_endpoints()

        # 4. Add health endpoints for K8s
        @self.app.get("/health")
        async def health():
            """Basic health check endpoint."""
            return {"status": "healthy", "agent": self.mcp_server.name}

        @self.app.get("/ready")
        async def ready():
            """Readiness check - verify MCP server is initialized."""
            # Check if server has tools registered
            has_tools = (
                hasattr(self.mcp_server, "_tool_manager")
                and len(getattr(self.mcp_server._tool_manager, "_tools", {})) > 0
            )
            return {
                "ready": has_tools,
                "agent": self.mcp_server.name,
                "tools_count": (
                    len(getattr(self.mcp_server._tool_manager, "_tools", {}))
                    if has_tools
                    else 0
                ),
            }

        @self.app.get("/livez")
        async def liveness():
            """Liveness check for K8s."""
            return {"alive": True, "agent": self.mcp_server.name}

        # 5. Add mesh-specific endpoints
        @self.app.get("/mesh/info")
        async def mesh_info():
            """Get mesh agent information."""
            capabilities = self._get_capabilities()
            dependencies = self._get_dependencies()

            # Update metrics gauges
            mcp_capabilities_total.labels(agent=self.mcp_server.name).set(
                len(capabilities)
            )
            mcp_dependencies_total.labels(agent=self.mcp_server.name).set(
                len(dependencies)
            )

            return {
                "agent_id": self.mcp_server.name,
                "capabilities": capabilities,
                "dependencies": dependencies,
                "transport": ["stdio", "http"],
                "http_endpoint": f"http://{self._get_host_ip()}:{self.actual_port}",
            }

        @self.app.get("/mesh/tools")
        async def list_tools():
            """List available tools."""
            tools = {}
            if hasattr(self.mcp_server, "_tool_manager"):
                tool_manager = self.mcp_server._tool_manager
                if hasattr(tool_manager, "_tools"):
                    for name, tool in tool_manager._tools.items():
                        tools[name] = {
                            "description": getattr(tool, "description", ""),
                            "parameters": self._extract_tool_params(tool),
                        }

            # Update tools gauge
            mcp_tools_total.labels(agent=self.mcp_server.name).set(len(tools))

            return {"tools": tools}

        # 6. Add Prometheus metrics endpoint
        @self.app.get("/metrics")
        async def metrics():
            """Prometheus metrics endpoint."""
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    def _setup_fallback_mcp_endpoints(self):
        """Set up fallback MCP endpoints if official server not available."""

        @self.app.post("/mcp")
        async def mcp_handler(request: dict):
            """Fallback MCP protocol handler."""
            start_time = time.time()
            method = request.get("method")
            params = request.get("params", {})
            status = "success"

            try:
                if method == "tools/list":
                    # List available tools
                    tools = []
                    if hasattr(self.mcp_server, "_tool_manager"):
                        for name, tool in self.mcp_server._tool_manager._tools.items():
                            tools.append(
                                {
                                    "name": name,
                                    "description": getattr(tool, "description", ""),
                                    "inputSchema": self._extract_tool_params(tool),
                                }
                            )
                    return {"tools": tools}

                elif method == "tools/call":
                    # Call a tool
                    tool_name = params.get("name")
                    arguments = params.get("arguments", {})

                    if not hasattr(self.mcp_server, "_tool_manager"):
                        raise HTTPException(
                            status_code=500, detail="No tools available"
                        )

                    tools = self.mcp_server._tool_manager._tools
                    if tool_name not in tools:
                        raise HTTPException(
                            status_code=404, detail=f"Tool '{tool_name}' not found"
                        )

                    # Execute tool
                    tool = tools[tool_name]
                    try:
                        # Check if function is async
                        import inspect

                        if inspect.iscoroutinefunction(tool.fn):
                            result = await tool.fn(**arguments)
                        else:
                            result = tool.fn(**arguments)

                        # Convert result to JSON string
                        if isinstance(result, str):
                            result_text = result
                        else:
                            result_text = json.dumps(result)

                        result = {
                            "content": [{"type": "text", "text": result_text}],
                            "isError": False,
                        }
                        return result
                    except Exception as e:
                        status = "error"
                        result = {
                            "content": [{"type": "text", "text": str(e)}],
                            "isError": True,
                        }
                        return result

                else:
                    status = "error"
                    raise HTTPException(
                        status_code=400, detail=f"Unknown method: {method}"
                    )

            except HTTPException:
                status = "error"
                raise
            except Exception as e:
                status = "error"
                logger.error(f"MCP handler error: {e}")
                raise HTTPException(status_code=500, detail=str(e)) from e
            finally:
                # Track MCP metrics
                duration = time.time() - start_time
                mcp_requests_total.labels(
                    method=method or "unknown",
                    status=status,
                    agent=self.mcp_server.name,
                ).inc()
                mcp_request_duration_seconds.labels(
                    method=method or "unknown", agent=self.mcp_server.name
                ).observe(duration)

    async def start(self):
        """Start HTTP server with auto port assignment."""
        # Find available port if not specified
        if self.config.port == 0:
            self.actual_port = self._find_available_port()
        else:
            self.actual_port = self.config.port

        logger.info(
            f"Starting HTTP server for {self.mcp_server.name} on "
            f"{self.config.host}:{self.actual_port}"
        )

        # Configure uvicorn with same log level as MCP_MESH_LOG_LEVEL
        log_level_map = {
            "DEBUG": "debug",
            "INFO": "info",
            "WARNING": "warning",
            "ERROR": "error",
            "CRITICAL": "critical",
        }
        mesh_log_level = os.environ.get("MCP_MESH_LOG_LEVEL", "INFO").upper()
        uvicorn_log_level = log_level_map.get(mesh_log_level, "info").lower()

        config = uvicorn.Config(
            app=self.app,
            host=self.config.host,
            port=self.actual_port,
            log_level=uvicorn_log_level,
            access_log=False,  # Reduce noise
        )
        self.server = uvicorn.Server(config)

        # Start server in background task
        self._setup_task = asyncio.create_task(self._run_server())

        # Give server time to start
        await asyncio.sleep(0.5)

        # Register HTTP endpoint with mesh
        await self._register_http_endpoint()

    async def _run_server(self):
        """Run the HTTP server."""
        try:
            await self.server.serve()
        except Exception as e:
            logger.error(f"HTTP server error: {e}")

    async def stop(self):
        """Stop the HTTP server gracefully."""
        if self.server:
            logger.info(f"Stopping HTTP server for {self.mcp_server.name}")
            self.server.should_exit = True
            if self._setup_task and not self._setup_task.done():
                try:
                    await asyncio.wait_for(self._setup_task, timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        f"HTTP server for {self.mcp_server.name} did not stop in time"
                    )
                    self._setup_task.cancel()

    def _find_available_port(self) -> int:
        """Find an available port to bind to."""
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("", 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return s.getsockname()[1]

    def _get_host_ip(self) -> str:
        """Get the host IP address."""
        # Priority 1: Explicitly set POD_IP (Kubernetes)
        pod_ip = os.environ.get("POD_IP")
        if pod_ip:
            logger.debug(f"Using POD_IP from environment: {pod_ip}")
            return pod_ip

        # Priority 2: Check if running in Kubernetes (even without POD_IP set)
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            logger.warning(
                "Running in Kubernetes but POD_IP not set. Using hostname IP."
            )
            try:
                # In K8s, hostname usually resolves to pod IP
                import socket

                hostname = socket.gethostname()
                pod_ip = socket.gethostbyname(hostname)
                if pod_ip and not pod_ip.startswith("127."):
                    return pod_ip
            except Exception as e:
                logger.debug(f"Failed to resolve hostname to IP: {e}")

        # Priority 3: For Docker or local, try to get external IP
        try:
            # Connect to a public DNS server to find our IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                logger.debug(f"Using detected external IP: {ip}")
                return ip
        except Exception:
            # Fallback to localhost
            logger.debug("Fallback to localhost")
            return "127.0.0.1"

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

    async def _register_http_endpoint(self):
        """Register HTTP endpoint with mesh registry."""
        # This will be called by the processor when it updates registration
        logger.info(
            f"🌐 HTTP endpoint ready: http://{self._get_host_ip()}:{self.actual_port}"
        )

    def get_endpoint(self) -> str:
        """Get the full HTTP endpoint URL."""
        return f"http://{self._get_host_ip()}:{self.actual_port}"
