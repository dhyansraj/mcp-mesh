#!/usr/bin/env python3
"""
Test Mesh Processor - Decorator Infrastructure

This mimics MCP Mesh's decorator-driven server startup architecture.
Step 3.2a: Basic decorator registration with debug logging.
"""

import logging
import inspect
import sys
import threading
import time
import os
from typing import Any, Callable

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestMeshProcessor:
    """Mimics MCP Mesh's decorator-driven architecture."""

    def __init__(self):
        self.decorated_functions = []
        self.fastmcp_instance = None
        self.fastapi_app = None
        self.mcp_http_app = None
        self.server_started = False
        self.server_thread = None
        logger.debug("🔧 TestMeshProcessor initialized")

    def discover_fastmcp_instance(self, module) -> Any:
        """Discover FastMCP instance in the given module."""
        logger.debug(f"🔍 Searching for FastMCP instance in module: {module.__name__}")

        # Look for FastMCP instances in module globals
        for name, obj in module.__dict__.items():
            logger.debug(f"  🔎 Checking attribute '{name}': {type(obj)}")

            # Check if it's a FastMCP instance
            if hasattr(obj, '__class__') and 'FastMCP' in str(type(obj)):
                logger.info(f"✅ Found FastMCP instance: '{name}' = {obj}")
                logger.debug(f"📋 FastMCP instance details:")
                logger.debug(f"  - Type: {type(obj)}")
                logger.debug(f"  - Name: {getattr(obj, 'name', 'unknown')}")

                # Check if it has tools registered
                if hasattr(obj, '_tools'):
                    tool_count = len(obj._tools) if obj._tools else 0
                    logger.debug(f"  - Registered tools: {tool_count}")
                    if obj._tools:
                        for tool_name in obj._tools.keys():
                            logger.debug(f"    🔧 Tool: {tool_name}")

                return obj

        logger.warning(f"❌ No FastMCP instance found in module: {module.__name__}")
        return None

    def create_fastapi_app(self) -> Any:
        """Create FastAPI app with proper lifespan integration from FastMCP."""
        if not self.fastmcp_instance:
            logger.error("❌ Cannot create FastAPI app - no FastMCP instance available")
            return None

        try:
            logger.debug("🏗️ Creating FastAPI app with FastMCP lifespan integration...")

            # Get the FastMCP HTTP app with stateless transport (like MCP Mesh)
            logger.debug("🔄 Getting FastMCP HTTP app with stateless transport...")
            try:
                # Try stateless HTTP first (like MCP Mesh does)
                self.mcp_http_app = self.fastmcp_instance.http_app(
                    stateless_http=True, transport="streamable-http"
                )
                logger.debug(f"✅ FastMCP HTTP app created with stateless transport: {type(self.mcp_http_app)}")
            except Exception as e:
                logger.warning(f"⚠️ Stateless HTTP failed ({e}), trying fallback...")
                # Fallback to regular HTTP app
                self.mcp_http_app = self.fastmcp_instance.http_app()
                logger.debug(f"✅ FastMCP HTTP app created (fallback): {type(self.mcp_http_app)}")

            # Import FastAPI
            from fastapi import FastAPI

            # Create FastAPI app with FastMCP lifespan (CRITICAL for proper operation)
            logger.debug("🔄 Creating FastAPI app with FastMCP lifespan...")
            self.fastapi_app = FastAPI(
                title="Test Client Mesh",
                description="Test client with MCP Mesh-like architecture",
                version="1.0.0",
                lifespan=self.mcp_http_app.lifespan  # This is REQUIRED!
            )
            logger.info("✅ FastAPI app created successfully with lifespan integration")

            # Add health check endpoint
            @self.fastapi_app.get("/health")
            async def health():
                return {"status": "healthy", "service": "test-client-mesh"}

            logger.debug("➕ Added health check endpoint")
            logger.debug(f"📋 FastAPI app details:")
            logger.debug(f"  - Title: {self.fastapi_app.title}")
            logger.debug(f"  - Lifespan: {self.fastapi_app.router.lifespan_context is not None}")

            return self.fastapi_app

        except Exception as e:
            logger.error(f"❌ Failed to create FastAPI app: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def mount_fastmcp_on_fastapi(self) -> bool:
        """Mount discovered FastMCP instance on FastAPI app."""
        if not self.fastapi_app:
            logger.error("❌ Cannot mount FastMCP - no FastAPI app available")
            return False

        if not self.mcp_http_app:
            logger.error("❌ Cannot mount FastMCP - no FastMCP HTTP app available")
            return False

        try:
            logger.debug("🔌 Mounting FastMCP on FastAPI app...")

            # Mount FastMCP directly at root - FastMCP handles its own /mcp routing
            # (Same pattern as vanilla FastMCP)
            logger.debug("🔄 Mounting FastMCP HTTP app at root...")
            self.fastapi_app.mount("", self.mcp_http_app)
            logger.info("✅ FastMCP mounted successfully at root")

            logger.debug("📋 FastAPI mounting details:")
            logger.debug(f"  - FastMCP app type: {type(self.mcp_http_app)}")
            logger.debug(f"  - FastAPI routes count: {len(self.fastapi_app.routes)}")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to mount FastMCP on FastAPI: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def start_uvicorn_server(self) -> bool:
        """Start uvicorn server in background thread and keep script alive."""
        if not self.fastapi_app:
            logger.error("❌ Cannot start server - no FastAPI app available")
            return False

        if self.server_started:
            logger.debug("🔄 Server already started, skipping...")
            return True

        try:
            logger.debug("🚀 Starting uvicorn server in background thread...")

            # Get port from environment or use default
            port = int(os.getenv("PORT", "8080"))
            host = "0.0.0.0"

            logger.debug(f"🔄 Server will start on {host}:{port}")

            # Define server function to run in background thread
            def run_server():
                try:
                    import uvicorn
                    logger.info(f"🌟 Starting uvicorn server on {host}:{port}")

                    # Create uvicorn config
                    config = uvicorn.Config(
                        app=self.fastapi_app,
                        host=host,
                        port=port,
                        log_level="info",
                        access_log=True
                    )

                    # Create and run server
                    server = uvicorn.Server(config)
                    server.run()

                except Exception as e:
                    logger.error(f"❌ Server thread failed: {e}")
                    import traceback
                    logger.error(f"Server traceback: {traceback.format_exc()}")

            # Start server in background thread
            self.server_thread = threading.Thread(target=run_server, daemon=True)
            self.server_thread.start()
            self.server_started = True

            # Give server a moment to start
            time.sleep(1)

            logger.info(f"✅ Server started successfully in background thread")
            logger.info(f"📍 MCP endpoint: http://localhost:{port}/mcp")
            logger.info(f"🏥 Health endpoint: http://localhost:{port}/health")

            # Keep script alive (mimics MCP Mesh behavior)
            self._keep_script_alive()

            return True

        except Exception as e:
            logger.error(f"❌ Failed to start server: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def register_decorated_functions_with_fastmcp(self) -> bool:
        """Register all accumulated decorated functions with the discovered FastMCP instance."""
        if not self.fastmcp_instance:
            logger.error("❌ Cannot register functions - no FastMCP instance available")
            return False

        if not self.decorated_functions:
            logger.warning("⚠️ No decorated functions to register")
            return True

        try:
            logger.debug(f"🔧 Registering {len(self.decorated_functions)} decorated functions with FastMCP instance...")

            for func in self.decorated_functions:
                logger.debug(f"  📝 Registering function: {func.__name__}")

                # Register the function with FastMCP using the @app.tool() decorator
                # This mimics what @app.tool() does internally
                self.fastmcp_instance.tool()(func)
                logger.debug(f"  ✅ Function '{func.__name__}' registered with FastMCP")

            logger.info(f"✅ Successfully registered {len(self.decorated_functions)} functions with FastMCP")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to register decorated functions with FastMCP: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _start_heartbeat_process(self):
        """Start background heartbeat process that mimics MCP Mesh registry heartbeat."""
        logger.info("💓 Starting heartbeat process to mimic MCP Mesh registry calls...")

        def heartbeat_worker():
            """Background heartbeat worker that calls registry every 5 seconds."""
            import time
            import socket

            # Get the host IP (like MCP Mesh does for registry calls)
            try:
                # Connect to a remote address to get local IP
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.connect(("8.8.8.8", 80))
                    host_ip = s.getsockname()[0]
            except Exception:
                host_ip = "127.0.0.1"

            registry_url = f"http://{host_ip}:8000/heartbeat"
            heartbeat_count = 0

            logger.info(f"💓 Heartbeat worker started - calling {registry_url} every 5 seconds")

            while True:
                try:
                    heartbeat_count += 1
                    start_time = time.time()

                    # Make HEAD call to registry heartbeat endpoint (ignore response)
                    try:
                        import httpx
                        with httpx.Client(timeout=2.0) as client:
                            response = client.head(registry_url)
                            duration = round((time.time() - start_time) * 1000, 1)
                            logger.info(f"💓 Heartbeat #{heartbeat_count} -> {registry_url} ({duration}ms) [status: {response.status_code}]")
                    except Exception as e:
                        duration = round((time.time() - start_time) * 1000, 1)
                        logger.info(f"💓 Heartbeat #{heartbeat_count} -> {registry_url} ({duration}ms) [failed: {e}]")

                    # Sleep for 5 seconds
                    time.sleep(5)

                except KeyboardInterrupt:
                    logger.info("💓 Heartbeat worker interrupted")
                    break
                except Exception as e:
                    logger.error(f"❌ Heartbeat worker error: {e}")
                    time.sleep(5)  # Continue despite errors

        # Start heartbeat in daemon thread (so it doesn't prevent shutdown)
        import threading
        self.heartbeat_thread = threading.Thread(target=heartbeat_worker, daemon=True)
        self.heartbeat_thread.start()
        logger.info("✅ Heartbeat process started in background")

    def _keep_script_alive(self):
        """Keep the script alive so server continues running."""
        logger.info("🔄 Keeping script alive (mimics MCP Mesh behavior)...")
        logger.info("🛑 Press Ctrl+C to stop the server")

        # Start heartbeat process to mimic MCP Mesh
        self._start_heartbeat_process()

        # Simple approach: block on thread join with timeout
        try:
            while True:
                if self.server_thread and self.server_thread.is_alive():
                    # Check every second if server thread is still alive
                    self.server_thread.join(timeout=1)
                else:
                    logger.warning("⚠️ Server thread died, exiting...")
                    break
        except KeyboardInterrupt:
            logger.info("🛑 Keyboard interrupt received, shutting down...")
        except Exception as e:
            logger.error(f"❌ Error in keep_script_alive: {e}")

        logger.info("🏁 Script shutting down...")

    def tool(self) -> Callable:
        """Test mesh tool decorator - mimics @mesh.tool()"""
        def decorator(func: Callable) -> Callable:
            logger.debug(f"🎯 @test_mesh.tool() decorator called for function: {func.__name__}")

            # Register the decorated function
            self.decorated_functions.append(func)
            logger.debug(f"📝 Registered function '{func.__name__}' - total decorated: {len(self.decorated_functions)}")

            # Get the module where the function was defined
            module = inspect.getmodule(func)
            module_name = module.__name__ if module else "unknown"
            logger.debug(f"📍 Function '{func.__name__}' defined in module: {module_name}")

            # Log caller frame info for debugging
            frame = inspect.currentframe()
            if frame and frame.f_back:
                caller_filename = frame.f_back.f_code.co_filename
                caller_lineno = frame.f_back.f_lineno
                logger.debug(f"📞 Decorator called from: {caller_filename}:{caller_lineno}")

            # Step 3.2b: Discover FastMCP instance (if we haven't already)
            if self.fastmcp_instance is None and module:
                logger.debug(f"🔍 First time decorating in module '{module_name}' - discovering FastMCP instance")
                self.fastmcp_instance = self.discover_fastmcp_instance(module)

                if self.fastmcp_instance:
                    logger.info(f"🎯 FastMCP instance discovered and cached!")

                    # Step 3.2b2: Register accumulated decorated functions with FastMCP
                    logger.debug("🔧 Registering decorated functions with FastMCP...")
                    if self.register_decorated_functions_with_fastmcp():
                        logger.info("🎯 Decorated functions registered with FastMCP!")
                    else:
                        logger.error("❌ Failed to register decorated functions")
                        return func

                    # Step 3.2c: Create FastAPI app with lifespan integration
                    logger.debug("🏗️ Creating FastAPI app with lifespan integration...")
                    if self.create_fastapi_app():
                        logger.info("🎯 FastAPI app created successfully!")

                        # Step 3.2d: Mount FastMCP on FastAPI
                        logger.debug("🔌 Mounting FastMCP on FastAPI...")
                        if self.mount_fastmcp_on_fastapi():
                            logger.info("🎯 FastMCP mounted successfully!")

                            # Step 3.2e: Start uvicorn server in background
                            logger.debug("🚀 Starting uvicorn server...")
                            if self.start_uvicorn_server():
                                logger.info("🎯 Server started successfully!")
                                # This will block here keeping script alive!
                            else:
                                logger.error("❌ Failed to start server")
                                return func

                        else:
                            logger.error("❌ Failed to mount FastMCP")
                            return func

                    else:
                        logger.error("❌ Failed to create FastAPI app")
                        return func

                else:
                    logger.error(f"❌ Could not find FastMCP instance in module '{module_name}'")

            else:
                # FastMCP instance already discovered, just register this new function
                if self.fastmcp_instance:
                    logger.debug(f"🔧 FastMCP instance already exists, registering function '{func.__name__}' directly")
                    try:
                        self.fastmcp_instance.tool()(func)
                        logger.debug(f"✅ Function '{func.__name__}' registered with existing FastMCP instance")
                    except Exception as e:
                        logger.error(f"❌ Failed to register function '{func.__name__}' with FastMCP: {e}")

            # Server startup already triggered during first decoration (if needed)
            logger.debug(f"🔄 Function '{func.__name__}' decorated (server startup handled during first decoration)")

            return func  # Return original function unchanged for now

        return decorator

# Create global instance (mimics MCP Mesh pattern)
test_mesh = TestMeshProcessor()

logger.info("🏁 test_mesh_processor.py loaded - TestMeshProcessor ready")