"""
Simplified orchestrator for MCP Mesh using pipeline architecture.

This replaces the complex scattered initialization with a clean,
explicit pipeline execution that can be easily tested and debugged.
"""

import asyncio
import logging
import os
import sys
from typing import Any, Optional

from .startup_pipeline import StartupPipeline

logger = logging.getLogger(__name__)


class DebounceCoordinator:
    """
    Coordinates decorator processing with debouncing to ensure single heartbeat.

    When decorators are applied, each one triggers a processing request.
    This coordinator delays execution by a configurable amount and cancels
    previous pending tasks, ensuring only the final state (with all decorators)
    gets processed.

    Uses threading.Timer for synchronous debouncing that works without asyncio.
    """

    def __init__(self, delay_seconds: float = 1.0):
        """
        Initialize the debounce coordinator.

        Args:
            delay_seconds: How long to wait after last decorator before processing
        """
        import threading

        self.delay_seconds = delay_seconds
        self._pending_timer: Optional[threading.Timer] = None
        self._orchestrator: Optional[MeshOrchestrator] = None
        self._lock = threading.Lock()
        self.logger = logging.getLogger(f"{__name__}.DebounceCoordinator")

    def set_orchestrator(self, orchestrator: "MeshOrchestrator") -> None:
        """Set the orchestrator to use for processing."""
        self._orchestrator = orchestrator

    def trigger_processing(self) -> None:
        """
        Trigger debounced processing.

        Cancels any pending processing and schedules a new one after delay.
        This is called by each decorator when applied.
        Uses threading.Timer for synchronous debouncing.
        """
        import threading

        with self._lock:
            # Cancel any pending timer
            if self._pending_timer is not None:
                self.logger.debug("🔄 Cancelling previous pending processing timer")
                self._pending_timer.cancel()

            # Schedule new processing timer
            self._pending_timer = threading.Timer(
                self.delay_seconds, self._execute_processing
            )
            self._pending_timer.start()
            self.logger.debug(
                f"⏰ Scheduled processing in {self.delay_seconds} seconds"
            )

    def cleanup(self) -> None:
        """
        Clean up any pending timers and reset state.

        This is called during test teardown to prevent background threads
        from interfering with subsequent tests.
        """
        with self._lock:
            if self._pending_timer is not None:
                self.logger.debug("🧹 Cleaning up pending processing timer")
                self._pending_timer.cancel()
                self._pending_timer = None
            self._orchestrator = None

    def _determine_pipeline_type(self) -> str:
        """
        Determine which pipeline to execute based on registered decorators.

        Returns:
            "mcp": Only MCP agents/tools found
            "api": Only API routes found
            "mixed": Both MCP and API decorators found (throws exception)
            "none": No decorators found
        """
        from ...engine.decorator_registry import DecoratorRegistry

        agents = DecoratorRegistry.get_mesh_agents()
        tools = DecoratorRegistry.get_mesh_tools()
        routes = DecoratorRegistry.get_all_by_type("mesh_route")

        has_mcp = len(agents) > 0 or len(tools) > 0
        has_api = len(routes) > 0

        self.logger.debug(
            f"🔍 Pipeline type detection: MCP={has_mcp} ({len(agents)} agents, {len(tools)} tools), API={has_api} ({len(routes)} routes)"
        )

        if has_api and has_mcp:
            return "mixed"
        elif has_api:
            return "api"
        elif has_mcp:
            return "mcp"
        else:
            return "none"

    def _execute_processing(self) -> None:
        """Execute the processing (called by timer)."""
        try:

            if self._orchestrator is None:
                self.logger.error("❌ No orchestrator set for processing")
                return

            self.logger.info(
                f"🚀 Debounce delay ({self.delay_seconds}s) complete, processing all decorators"
            )

            # Determine which pipeline to execute
            pipeline_type = self._determine_pipeline_type()

            if pipeline_type == "mixed":
                error_msg = (
                    "❌ Mixed mode not supported: Cannot use @mesh.route decorators "
                    "together with @mesh.tool/@mesh.agent decorators in the same process. "
                    "Please use either MCP agent decorators OR API route decorators, not both."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            elif pipeline_type == "none":
                self.logger.warning("⚠️ No decorators found - nothing to process")
                return

            # Execute the pipeline using asyncio.run
            import asyncio

            # Check if auto-run is enabled (defaults to true for persistent service behavior)
            auto_run_enabled = self._check_auto_run_enabled()

            self.logger.debug(f"🔍 Auto-run enabled: {auto_run_enabled}")
            self.logger.info(f"🎯 Pipeline type: {pipeline_type}")

            if auto_run_enabled:
                self.logger.info("🔄 Auto-run enabled - using FastAPI natural blocking")

                # Execute appropriate pipeline based on type
                if pipeline_type == "mcp":
                    # Phase 1: Run async MCP pipeline setup
                    result = asyncio.run(self._orchestrator.process_once())
                elif pipeline_type == "api":
                    # Phase 1: Run async API pipeline setup
                    result = asyncio.run(self._orchestrator.process_api_once())
                else:
                    raise RuntimeError(f"Unsupported pipeline type: {pipeline_type}")

                # Phase 2: Extract FastAPI app and start synchronous server
                pipeline_context = result.get("context", {}).get("pipeline_context", {})
                fastapi_app = pipeline_context.get("fastapi_app")
                binding_config = pipeline_context.get("fastapi_binding_config", {})
                heartbeat_config = pipeline_context.get("heartbeat_config", {})

                if pipeline_type == "api":
                    # For API services, ONLY do dependency injection - user controls their FastAPI server
                    # Dependency injection is already complete from pipeline execution
                    # Optionally start heartbeat in background (non-blocking)
                    self._setup_api_heartbeat_background(
                        heartbeat_config, pipeline_context
                    )
                    self.logger.info(
                        "✅ API dependency injection complete - user's FastAPI server can now start"
                    )
                    return  # Don't block - let user's uvicorn run
                elif fastapi_app and binding_config:
                    # For MCP agents - use same daemon thread pattern as API apps
                    self._setup_mcp_heartbeat_background(
                        heartbeat_config, pipeline_context
                    )

                    # Check if server was already reused from immediate uvicorn start
                    server_reused = pipeline_context.get("server_reused", False)
                    existing_server = pipeline_context.get("existing_server", {})

                    if server_reused:
                        # Check server status to determine action
                        server_status = existing_server.get("status", "unknown")

                        if server_status == "configured":
                            self.logger.info(
                                "🔄 CONFIGURED SERVER: Starting configured uvicorn server within pipeline event loop"
                            )
                            # Start the configured server within this event loop
                            server_obj = existing_server.get("server")
                            if server_obj:
                                self.logger.info(
                                    "🚀 CONFIGURED SERVER: Starting server.serve() within pipeline context"
                                )
                                # This runs in the same event loop as the pipeline - no conflict!
                                import asyncio

                                # Define async function to run the server
                                async def run_configured_server():
                                    await server_obj.serve()

                                # Run the server within the existing event loop context
                                asyncio.run(run_configured_server())
                                self.logger.info(
                                    "✅ CONFIGURED SERVER: Server started successfully"
                                )
                            else:
                                self.logger.error(
                                    "❌ CONFIGURED SERVER: No server object found, falling back to uvicorn.run()"
                                )
                                self._start_blocking_fastapi_server(
                                    fastapi_app, binding_config
                                )
                        elif server_status == "running":
                            self.logger.debug(
                                "🔄 RUNNING SERVER: Server already running with proper lifecycle, pipeline skipping uvicorn.run()"
                            )
                            self.logger.info(
                                "✅ FastMCP mounted on running server - agent in normal operating state"
                            )
                            # Server is already running in normal state - no further action needed
                            return
                        else:
                            self.logger.info(
                                "🔄 SERVER REUSE: Existing server detected, skipping uvicorn.run()"
                            )
                            self.logger.info(
                                "✅ FastMCP mounted on existing server - agent ready"
                            )
                            # Keep the process alive but don't start new uvicorn
                            # Use a robust keep-alive pattern that doesn't overflow
                            import time

                            try:
                                while True:
                                    time.sleep(
                                        3600
                                    )  # Sleep 1 hour at a time instead of infinity
                            except KeyboardInterrupt:
                                self.logger.info(
                                    "🛑 Server reuse mode interrupted - shutting down"
                                )
                                return
                    else:
                        self._start_blocking_fastapi_server(fastapi_app, binding_config)
                else:
                    self.logger.warning(
                        "⚠️ Auto-run enabled but no FastAPI app prepared - exiting"
                    )
            else:
                # Single execution mode (for testing/debugging)
                self.logger.info("🏁 Auto-run disabled - single execution mode")

                if pipeline_type == "mcp":
                    result = asyncio.run(self._orchestrator.process_once())
                elif pipeline_type == "api":
                    result = asyncio.run(self._orchestrator.process_api_once())
                else:
                    raise RuntimeError(f"Unsupported pipeline type: {pipeline_type}")

                self.logger.info("✅ Pipeline execution completed, exiting")

        except Exception as e:
            self.logger.error(f"❌ Error in debounced processing: {e}")
            # Re-raise to ensure the system exits on mixed mode or other critical errors
            raise

    def _start_blocking_fastapi_server(
        self, app: Any, binding_config: dict[str, Any]
    ) -> None:
        """Start FastAPI server with uvicorn (signal handlers already registered)."""
        try:
            import uvicorn

            bind_host = binding_config.get("bind_host", "0.0.0.0")
            bind_port = binding_config.get("bind_port", 8080)

            self.logger.info(f"🚀 Starting FastAPI server on {bind_host}:{bind_port}")
            self.logger.info("🛑 Press Ctrl+C to stop the service")

            # Use uvicorn.run() - signal handlers should already be registered
            uvicorn.run(
                app,
                host=bind_host,
                port=bind_port,
                log_level="info",
                access_log=False,  # Reduce noise
            )

        except KeyboardInterrupt:
            self.logger.info(
                "🔴 Received KeyboardInterrupt, shutdown will be handled by FastAPI lifespan"
            )
        except Exception as e:
            self.logger.error(f"❌ FastAPI server error: {e}")
            raise

    def _setup_api_heartbeat_background(
        self, heartbeat_config: dict[str, Any], pipeline_context: dict[str, Any]
    ) -> None:
        """Setup API heartbeat to run in background - non-blocking."""
        try:
            # Populate heartbeat context with current pipeline context
            heartbeat_config["context"] = pipeline_context
            service_id = heartbeat_config.get("service_id", "unknown")
            standalone_mode = heartbeat_config.get("standalone_mode", False)

            if standalone_mode:
                self.logger.info(
                    f"📝 API service '{service_id}' configured in standalone mode - no heartbeat"
                )
                return

            self.logger.info(
                f"🔗 Setting up background API heartbeat for service '{service_id}'"
            )

            # Import heartbeat functionality
            import asyncio
            import threading

            from ..api_heartbeat.api_lifespan_integration import (
                api_heartbeat_lifespan_task,
            )

            def run_heartbeat():
                """Run heartbeat in separate thread with its own event loop."""
                self.logger.debug(
                    f"Starting background heartbeat thread for {service_id}"
                )
                try:
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Run heartbeat task
                    loop.run_until_complete(
                        api_heartbeat_lifespan_task(heartbeat_config)
                    )
                except Exception as e:
                    self.logger.error(f"❌ Background heartbeat error: {e}")
                finally:
                    loop.close()

            # Start heartbeat in daemon thread (won't prevent process exit)
            heartbeat_thread = threading.Thread(target=run_heartbeat, daemon=True)
            heartbeat_thread.start()

            self.logger.info(
                f"💓 Background API heartbeat thread started for service '{service_id}'"
            )

        except Exception as e:
            self.logger.warning(f"⚠️ Could not setup API heartbeat: {e}")
            # Don't fail - heartbeat is optional for API services

    def _setup_mcp_heartbeat_background(
        self, heartbeat_config: dict[str, Any], pipeline_context: dict[str, Any]
    ) -> None:
        """Setup MCP heartbeat to run in background - same pattern as API apps."""
        try:
            # Populate heartbeat context with current pipeline context
            heartbeat_config["context"] = pipeline_context
            agent_id = heartbeat_config.get("agent_id", "unknown")
            standalone_mode = heartbeat_config.get("standalone_mode", False)

            if standalone_mode:
                self.logger.info(
                    f"📝 MCP agent '{agent_id}' configured in standalone mode - no heartbeat"
                )
                return

            self.logger.info(
                f"🔗 Setting up background MCP heartbeat for agent '{agent_id}'"
            )

            # Import heartbeat functionality
            import asyncio
            import threading

            from ..mcp_heartbeat.lifespan_integration import heartbeat_lifespan_task

            def run_heartbeat():
                """Run heartbeat in separate thread with its own event loop."""
                self.logger.debug(
                    f"Starting background heartbeat thread for {agent_id}"
                )
                try:
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    # Run heartbeat task
                    loop.run_until_complete(heartbeat_lifespan_task(heartbeat_config))
                except Exception as e:
                    self.logger.error(f"❌ Background heartbeat error: {e}")
                finally:
                    loop.close()

            # Start heartbeat in daemon thread (won't prevent process exit)
            heartbeat_thread = threading.Thread(target=run_heartbeat, daemon=True)
            heartbeat_thread.start()

            self.logger.info(
                f"💓 Background MCP heartbeat thread started for agent '{agent_id}'"
            )

        except Exception as e:
            self.logger.warning(f"⚠️ Could not setup MCP heartbeat: {e}")
            # Don't fail - heartbeat is optional for MCP agents

    # Graceful shutdown is now handled by FastAPI lifespan in simple_shutdown.py

    def _check_auto_run_enabled(self) -> bool:
        """Check if auto-run is enabled (defaults to True for persistent service behavior)."""
        # Check environment variable - defaults to "true" for persistent service behavior
        env_auto_run = os.getenv("MCP_MESH_AUTO_RUN", "true").lower()
        self.logger.debug(f"🔍 MCP_MESH_AUTO_RUN='{env_auto_run}' (default: 'true')")

        if env_auto_run in ("false", "0", "no"):
            self.logger.debug(
                "🔍 Auto-run explicitly disabled via environment variable"
            )
            return False
        else:
            # Default to True - agents should run persistently by default
            self.logger.debug("🔍 Auto-run enabled (default behavior)")
            return True


# Global debounce coordinator instance
_debounce_coordinator: Optional[DebounceCoordinator] = None


def get_debounce_coordinator() -> DebounceCoordinator:
    """Get or create the global debounce coordinator."""
    global _debounce_coordinator

    if _debounce_coordinator is None:
        # Get delay from environment variable, default to 1.0 seconds
        delay = float(os.getenv("MCP_MESH_DEBOUNCE_DELAY", "1.0"))
        _debounce_coordinator = DebounceCoordinator(delay_seconds=delay)

    return _debounce_coordinator


def clear_debounce_coordinator() -> None:
    """
    Clear the global debounce coordinator and clean up any pending timers.

    This function is intended for test cleanup to prevent background threads
    from interfering with subsequent tests.
    """
    global _debounce_coordinator

    if _debounce_coordinator is not None:
        _debounce_coordinator.cleanup()
        _debounce_coordinator = None


class MeshOrchestrator:
    """
    Pipeline orchestrator that manages the complete MCP Mesh lifecycle.

    Replaces the scattered background processing, auto-initialization,
    and complex async workflows with a single, explicit pipeline.
    """

    def __init__(self, name: str = "mcp-mesh"):
        self.name = name
        self.pipeline = StartupPipeline(name=name)
        self.logger = logging.getLogger(f"{__name__}.{name}")

    async def process_once(self) -> dict:
        """
        Execute the pipeline once.

        This replaces the background polling with explicit execution.
        """
        self.logger.debug(f"🚀 Starting single pipeline execution: {self.name}")

        result = await self.pipeline.execute()

        # Convert result to dict for return type
        return {
            "status": result.status.value,
            "message": result.message,
            "errors": result.errors,
            "context": result.context,
            "timestamp": result.timestamp.isoformat(),
        }

    async def process_api_once(self) -> dict:
        """
        Execute the API pipeline once for @mesh.route decorators.

        This handles FastAPI route integration and dependency injection setup.
        """
        self.logger.info(f"🚀 Starting API pipeline execution: {self.name}")

        try:
            # Import API pipeline here to avoid circular imports
            from ..api_startup import APIPipeline

            # Create and execute API pipeline
            api_pipeline = APIPipeline(name=f"{self.name}-api")
            result = await api_pipeline.execute()

            # Convert result to dict for return type (same format as MCP pipeline)
            return {
                "status": result.status.value,
                "message": result.message,
                "errors": result.errors,
                "context": result.context,
                "timestamp": result.timestamp.isoformat(),
            }

        except Exception as e:
            error_msg = f"API pipeline execution failed: {e}"
            self.logger.error(f"❌ {error_msg}")

            return {
                "status": "failed",
                "message": error_msg,
                "errors": [str(e)],
                "context": {},
                "timestamp": "unknown",
            }

    async def start_service(self, auto_run_config: Optional[dict] = None) -> None:
        """
        Start the service with optional auto-run behavior.

        This replaces the complex atexit handlers and background tasks.
        """
        self.logger.info(f"🎯 Starting mesh service: {self.name}")

        # Execute pipeline once to initialize
        initial_result = await self.process_once()

        if not initial_result.get("status") == "success":
            self.logger.error(
                f"💥 Initial pipeline execution failed: {initial_result.get('message')}"
            )
            return

        # Handle auto-run if configured
        if auto_run_config and auto_run_config.get("enabled"):
            await self._run_auto_service(auto_run_config)
        else:
            self.logger.info("✅ Single execution completed, no auto-run configured")

    async def _run_auto_service(self, auto_run_config: dict) -> None:
        """Run the auto-service with periodic pipeline execution."""
        interval = auto_run_config.get("interval", 30)
        service_name = auto_run_config.get("name", self.name)

        self.logger.info(
            f"🔄 Starting auto-service '{service_name}' with {interval}s interval"
        )

        heartbeat_count = 0

        try:
            while True:
                await asyncio.sleep(interval)
                heartbeat_count += 1

                # Execute pipeline periodically
                try:
                    result = await self.process_once()

                    if heartbeat_count % 6 == 0:  # Every 3 minutes with 30s interval
                        self.logger.info(
                            f"💓 Auto-service heartbeat #{heartbeat_count} for '{service_name}'"
                        )
                    else:
                        self.logger.debug(f"💓 Pipeline execution #{heartbeat_count}")

                except Exception as e:
                    self.logger.error(
                        f"❌ Pipeline execution #{heartbeat_count} failed: {e}"
                    )

        except KeyboardInterrupt:
            self.logger.info(f"🛑 Auto-service '{service_name}' interrupted by user")
        except Exception as e:
            self.logger.error(f"💥 Auto-service '{service_name}' failed: {e}")


# Global orchestrator instance
_global_orchestrator: Optional[MeshOrchestrator] = None


def get_global_orchestrator() -> MeshOrchestrator:
    """Get or create the global orchestrator instance."""
    global _global_orchestrator

    if _global_orchestrator is None:
        _global_orchestrator = MeshOrchestrator()

    return _global_orchestrator


async def process_decorators_once() -> dict:
    """
    Process all decorators once using the pipeline.

    This is the main entry point that replaces the complex
    DecoratorProcessor.process_all_decorators() method.
    """
    orchestrator = get_global_orchestrator()
    return await orchestrator.process_once()


def start_runtime() -> None:
    """
    Start the MCP Mesh runtime with debounced pipeline architecture.

    This initializes the debounce coordinator and sets up the orchestrator.
    Actual pipeline execution will be triggered by decorator registration
    with a configurable delay to ensure all decorators are captured.
    """
    # Configure logging FIRST before any log messages
    from ...shared.logging_config import configure_logging

    configure_logging()

    logger.info("🔧 Starting MCP Mesh runtime with debouncing")

    # Signal handlers removed - cleanup now handled by FastAPI lifespan

    # Create orchestrator and set up debouncing
    orchestrator = get_global_orchestrator()
    debounce_coordinator = get_debounce_coordinator()

    # Connect coordinator to orchestrator
    debounce_coordinator.set_orchestrator(orchestrator)

    delay = debounce_coordinator.delay_seconds
    logger.info(f"🎯 Runtime initialized with {delay}s debounce delay")
    logger.debug(f"Pipeline configured with {len(orchestrator.pipeline.steps)} steps")

    # The actual pipeline execution will be triggered by decorator registration
    # through the debounce coordinator


# Signal handlers removed - cleanup now handled by FastAPI lifespan in simple_shutdown.py


# Minimal signal handlers restored to provide graceful shutdown with DELETE /heartbeats
# Avoids complex operations that could conflict with DNS resolution in containers
