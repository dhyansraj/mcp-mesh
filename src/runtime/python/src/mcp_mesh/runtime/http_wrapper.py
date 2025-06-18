"""HTTP wrapper for MCP servers to enable distributed communication.

This module provides HTTP transport capabilities for MCP servers,
allowing them to communicate across network boundaries in containerized
and distributed environments.
"""

import asyncio
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

        # Store mcp_server for later use
        self._mcp_app = None
        self._lifespan = None

        # Get FastMCP's lifespan if available (for new FastMCP integration)
        if hasattr(mcp_server, "http_app") and callable(mcp_server.http_app):
            try:
                # Create FastMCP HTTP app with stateless transport
                logger.debug("🔍 Creating FastMCP HTTP app with stateless transport")
                self._mcp_app = mcp_server.http_app(
                    path="/mcp", stateless_http=True, transport="streamable-http"
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
                    self._mcp_app = mcp_server.http_app(path="/mcp")
                    if hasattr(self._mcp_app, "lifespan"):
                        self._lifespan = self._mcp_app.lifespan
                        logger.debug("✅ Got FastMCP lifespan (fallback)")
                except Exception as e2:
                    logger.warning(f"FastMCP HTTP app creation failed entirely: {e2}")

        self.app = FastAPI(
            title=f"MCP Agent: {mcp_server.name}",
            description="HTTP-enabled MCP agent for distributed communication",
            lifespan=self._lifespan,
        )
        self.actual_port: int | None = None
        self.server: uvicorn.Server | None = None
        self._setup_task: asyncio.Task | None = None

    async def setup(self):
        """Set up HTTP endpoints and middleware."""

        # 0. Add request logging middleware
        @self.app.middleware("http")
        async def log_requests(request, call_next):
            logger.debug(f"🌐 HTTP Request: {request.method} {request.url.path}")
            response = await call_next(request)
            logger.debug(f"🌐 HTTP Response: {response.status_code}")
            return response

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
        # Debug the FastMCP server instance first
        logger.debug(f"🔍 DEBUG: FastMCP server type: {type(self.mcp_server)}")
        logger.debug(
            f"🔍 DEBUG: FastMCP server module: {type(self.mcp_server).__module__}"
        )

        # Determine which FastMCP version this server instance is from
        # Check OLD FastMCP first (more specific path)
        if "mcp.server.fastmcp" in type(self.mcp_server).__module__:
            logger.info(
                "🔄 HTTP Wrapper: Server instance is from OLD FastMCP library (mcp.server.fastmcp)"
            )
        elif type(self.mcp_server).__module__.startswith("fastmcp"):
            logger.info(
                "🆕 HTTP Wrapper: Server instance is from NEW FastMCP library (fastmcp)"
            )
        else:
            logger.warning(
                f"❓ HTTP Wrapper: Unknown FastMCP server type: {type(self.mcp_server).__module__}"
            )

        logger.debug(
            f"🔍 DEBUG: FastMCP server dir: {[attr for attr in dir(self.mcp_server) if 'app' in attr.lower()]}"
        )
        logger.debug(f"🔍 DEBUG: Has http_app: {hasattr(self.mcp_server, 'http_app')}")

        # 3.1. Add health endpoints BEFORE mounting FastMCP (to avoid conflicts)
        @self.app.get("/health")
        async def health():
            """Basic health check endpoint."""
            return {"status": "healthy", "agent": self.mcp_server.name}

        # 3.2. Add MCP proxy endpoint to handle session management
        @self.app.post("/mcp")
        async def mcp_proxy(request: Request):
            """Proxy MCP requests with automatic session management."""
            import json

            try:
                # Get request body
                body = await request.body()
                headers = dict(request.headers)

                # Add required headers for FastMCP
                headers["accept"] = "application/json, text/event-stream"
                headers["content-type"] = "application/json"

                logger.debug(
                    "🔄 Proxying MCP request to FastMCP with session management"
                )

                # Forward to FastMCP endpoint - try with base session or create new
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    # Try the created session ID first
                    try:
                        session_id = "70f3698fa9784868b1da8215fc69fdc1"  # From logs
                        url = f"http://127.0.0.1:{self.actual_port}/mcp-server/mcp/{session_id}"
                        async with session.post(
                            url, data=body, headers=headers
                        ) as resp:
                            if resp.status != 400:  # If not "Missing session ID"
                                result = await resp.text()
                                return Response(
                                    content=result, media_type="application/json"
                                )
                    except Exception as e:
                        logger.debug(f"Session proxy attempt failed: {e}")

                # If session approach fails, try direct FastMCP tool calling
                logger.debug("🔄 Falling back to direct FastMCP tool calling")

                # Parse the JSON-RPC request
                import json

                try:
                    rpc_request = json.loads(body.decode())
                    method = rpc_request.get("method")
                    params = rpc_request.get("params", {})
                    request_id = rpc_request.get("id")

                    if method == "tools/list":
                        # Get tools using version-appropriate method
                        if "mcp.server.fastmcp" in type(self.mcp_server).__module__:
                            # OLD FastMCP - use list_tools()
                            tools = await self.mcp_server.list_tools()
                        else:
                            # NEW FastMCP - use get_tools()
                            tools = await self.mcp_server.get_tools()
                        logger.debug(f"🔍 Raw tools from FastMCP: {tools}")
                        logger.debug(f"🔍 Tools type: {type(tools)}")

                        # Handle tools as dictionary (name -> FunctionTool object)
                        tool_list = []
                        if isinstance(tools, dict):
                            for tool_name, tool_obj in tools.items():
                                tool_list.append(
                                    {
                                        "name": tool_name,
                                        "description": getattr(
                                            tool_obj,
                                            "description",
                                            f"Tool: {tool_name}",
                                        ).strip(),
                                    }
                                )
                        else:
                            # Handle other formats
                            for tool in tools:
                                if isinstance(tool, str):
                                    tool_list.append(
                                        {"name": tool, "description": f"Tool: {tool}"}
                                    )
                                else:
                                    tool_list.append(
                                        {
                                            "name": getattr(tool, "name", str(tool)),
                                            "description": getattr(
                                                tool,
                                                "description",
                                                f"Tool: {getattr(tool, 'name', str(tool))}",
                                            ),
                                        }
                                    )

                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"tools": tool_list},
                        }
                        return Response(
                            content=json.dumps(response), media_type="application/json"
                        )

                    elif method == "tools/call":
                        # Call tool directly
                        tool_name = params.get("name")
                        arguments = params.get("arguments", {})

                        logger.debug(
                            f"🎯 Direct tool call: {tool_name} with {arguments}"
                        )

                        try:
                            # Get the tool object using version-appropriate method
                            if "mcp.server.fastmcp" in type(self.mcp_server).__module__:
                                # OLD FastMCP - use call_tool directly
                                logger.debug("🔄 Using OLD FastMCP call_tool method")
                                result = await self.mcp_server.call_tool(
                                    tool_name, arguments
                                )
                                logger.debug(f"🎯 OLD FastMCP result: {result}")

                                # OLD FastMCP returns List[TextContent] directly
                                content = []
                                for item in result:
                                    if hasattr(item, "text"):
                                        content.append(
                                            {"type": "text", "text": item.text}
                                        )
                                    else:
                                        content.append(
                                            {"type": "text", "text": str(item)}
                                        )

                                response = {
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "result": {"content": content},
                                }
                                return Response(
                                    content=json.dumps(response),
                                    media_type="application/json",
                                )

                            else:
                                # NEW FastMCP - use get_tools()
                                tools = await self.mcp_server.get_tools()
                                if tool_name in tools:
                                    tool_obj = tools[tool_name]
                                    logger.debug(f"🔍 Tool object: {tool_obj}")
                                    logger.debug(f"🔍 Tool type: {type(tool_obj)}")

                                    # Check if tool has a callable function
                                    if hasattr(tool_obj, "fn"):
                                        logger.debug(
                                            f"🎯 Found tool function: {tool_obj.fn}"
                                        )
                                        logger.debug(
                                            f"🎯 Function pointer: {tool_obj.fn} at {hex(id(tool_obj.fn))}"
                                        )

                                        # Call the function directly - this should trigger fastmcp_integration!
                                        import inspect

                                        if inspect.iscoroutinefunction(tool_obj.fn):
                                            result = await tool_obj.fn(**arguments)
                                        else:
                                            result = tool_obj.fn(**arguments)

                                        logger.debug(f"🎯 Tool call result: {result}")

                                        # Convert result to proper MCP content format
                                        if isinstance(result, str):
                                            # String results -> text content
                                            content = [{"type": "text", "text": result}]
                                        elif isinstance(result, (dict, list)):
                                            # Structured data -> object content
                                            content = [
                                                {"type": "object", "object": result}
                                            ]
                                        else:
                                            # Other types -> convert to text
                                            content = [
                                                {"type": "text", "text": str(result)}
                                            ]

                                        response = {
                                            "jsonrpc": "2.0",
                                            "id": request_id,
                                            "result": {"content": content},
                                        }
                                        return Response(
                                            content=json.dumps(response),
                                            media_type="application/json",
                                        )
                                    else:
                                        logger.error(
                                            f"Tool {tool_name} has no callable function"
                                        )
                                        error_response = {
                                            "jsonrpc": "2.0",
                                            "id": request_id,
                                            "error": {
                                                "code": -32603,
                                                "message": f"Tool {tool_name} not callable",
                                            },
                                        }
                                        return Response(
                                            content=json.dumps(error_response),
                                            media_type="application/json",
                                        )
                                else:
                                    # Tool not found
                                    error_response = {
                                        "jsonrpc": "2.0",
                                        "id": request_id,
                                        "error": {
                                            "code": -32601,
                                            "message": f"Tool not found: {tool_name}",
                                        },
                                    }
                                    return Response(
                                        content=json.dumps(error_response),
                                        media_type="application/json",
                                    )

                        except Exception as e:
                            logger.error(f"Tool call error: {e}")
                            error_response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32603,
                                    "message": f"Tool call failed: {str(e)}",
                                },
                            }
                            return Response(
                                content=json.dumps(error_response),
                                media_type="application/json",
                            )

                    else:
                        # Unsupported method
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}",
                            },
                        }
                        return Response(
                            content=json.dumps(error_response),
                            media_type="application/json",
                            status_code=404,
                        )

                except json.JSONDecodeError:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                    return Response(
                        content=json.dumps(error_response),
                        media_type="application/json",
                        status_code=400,
                    )

            except Exception as e:
                logger.error(f"MCP proxy error: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                }
                return Response(
                    content=json.dumps(error_response),
                    media_type="application/json",
                    status_code=500,
                )

        try:
            # Use the pre-created FastMCP app with proper lifespan
            if self._mcp_app is not None:
                logger.debug(
                    "🔍 DEBUG: Using pre-created FastMCP app with stateless transport"
                )
                logger.debug(f"🔍 DEBUG: FastMCP app type: {type(self._mcp_app)}")

                # Mount FastMCP app at /mcp-server (following FastMCP docs pattern)
                self.app.mount("/mcp-server", self._mcp_app)
                logger.debug(
                    "🌐 Successfully mounted NEW FastMCP stateless HTTP app at /mcp-server"
                )
                logger.debug("🔍 MCP endpoint will be available at /mcp-server/mcp")

                # Debug: Check what routes the FastMCP app has
                if hasattr(self._mcp_app, "routes"):
                    logger.debug(
                        f"🔍 DEBUG: FastMCP app routes: {[route.path for route in self._mcp_app.routes if hasattr(route, 'path')]}"
                    )

            elif hasattr(self.mcp_server, "streamable_http_app"):
                logger.debug(
                    "🔍 DEBUG: Falling back to OLD FastMCP streamable_http_app"
                )
                logger.debug(
                    f"🔍 DEBUG: streamable_http_app type: {type(self.mcp_server.streamable_http_app)}"
                )

                # Get the streamable HTTP app
                mcp_app = self.mcp_server.streamable_http_app
                logger.debug(f"🔍 DEBUG: Got streamable_http_app: {type(mcp_app)}")

                # Mount it at /mcp
                self.app.mount("/mcp", mcp_app)
                logger.debug(
                    "🌐 Successfully mounted OLD FastMCP streamable_http_app at /mcp - MCP tools will go through FastMCP integration"
                )

            else:
                logger.warning(
                    "❌ FastMCP server doesn't have any supported HTTP app method"
                )
                raise AttributeError("No supported HTTP app method")

        except Exception as e:
            logger.error(f"❌ Failed to mount FastMCP app: {e}")
            import traceback

            logger.debug(f"🔍 DEBUG: Full traceback: {traceback.format_exc()}")
            logger.debug("🔄 Falling back to manual MCP implementation")
            self._setup_fallback_mcp_endpoints()

        # 4. Add additional health endpoints for K8s (health already added above)

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

            # Get tools information
            tools = []
            if hasattr(self.mcp_server, "_tool_manager"):
                for name, tool in self.mcp_server._tool_manager._tools.items():
                    tools.append(
                        {
                            "name": name,
                            "description": getattr(tool, "description", ""),
                        }
                    )

            # Update metrics gauges
            mcp_capabilities_total.labels(agent=self.mcp_server.name).set(
                len(capabilities)
            )
            mcp_dependencies_total.labels(agent=self.mcp_server.name).set(
                len(dependencies)
            )
            mcp_tools_total.labels(agent=self.mcp_server.name).set(len(tools))

            return {
                "agent_id": self.mcp_server.name,
                "capabilities": capabilities,
                "dependencies": dependencies,
                "tools": tools,
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
                    logger.debug("🔍 DEBUG: Checking tools in FastMCP server")
                    logger.debug(
                        f"🔍 DEBUG: Server has _tool_manager: {hasattr(self.mcp_server, '_tool_manager')}"
                    )
                    if hasattr(self.mcp_server, "_tool_manager"):
                        logger.debug(
                            f"🔍 DEBUG: Available tools: {list(self.mcp_server._tool_manager._tools.keys())}"
                        )
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

                        logger.debug(
                            f"🎯 HTTP Wrapper calling function: {tool.fn.__name__} at {hex(id(tool.fn))} | Full function: {tool.fn}"
                        )
                        if inspect.iscoroutinefunction(tool.fn):
                            result = await tool.fn(**arguments)
                        else:
                            result = tool.fn(**arguments)

                        # Convert result to proper MCP content format
                        if isinstance(result, str):
                            # String results -> text content
                            content = [{"type": "text", "text": result}]
                        elif isinstance(result, (dict, list)):
                            # Structured data -> object content
                            content = [{"type": "object", "object": result}]
                        else:
                            # Other types -> convert to text
                            content = [{"type": "text", "text": str(result)}]

                        result = {
                            "content": content,
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
            host=os.environ.get("HOST", self.config.host),
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
                except TimeoutError:
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
        # Priority 1: Auto-detect Kubernetes service DNS name (cleanest for K8s)
        service_name = os.environ.get("SERVICE_NAME")
        namespace = os.environ.get("NAMESPACE")
        if service_name and namespace:
            service_dns = f"{service_name}.{namespace}.svc.cluster.local"
            logger.info(f"🎯 Using Kubernetes service DNS: {service_dns}")
            return service_dns

        # Priority 2: Explicitly set POD_IP (backward compatibility)
        pod_ip = os.environ.get("POD_IP")
        if pod_ip:
            logger.debug(f"Using POD_IP from environment: {pod_ip}")
            return pod_ip

        # Priority 3: Check if running in Kubernetes (even without SERVICE_NAME set)
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            logger.warning(
                "Running in Kubernetes but SERVICE_NAME/NAMESPACE not set. Using hostname IP."
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

        # Priority 4: For Docker or local, try to get external IP
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
