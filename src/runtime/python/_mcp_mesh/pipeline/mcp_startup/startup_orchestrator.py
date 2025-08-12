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
        
        self.logger.debug(f"🔍 Pipeline type detection: MCP={has_mcp} ({len(agents)} agents, {len(tools)} tools), API={has_api} ({len(routes)} routes)")
        
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
                    self._setup_api_heartbeat_background(heartbeat_config, pipeline_context)
                    self.logger.info("✅ API dependency injection complete - user's FastAPI server can now start")
                    return  # Don't block - let user's uvicorn run
                elif fastapi_app and binding_config:
                    # For MCP agents with FastAPI server
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
                "🔴 Received KeyboardInterrupt, performing graceful shutdown..."
            )
            # Perform graceful shutdown before exiting
            self._perform_graceful_shutdown()
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
            from ..api_heartbeat.api_lifespan_integration import api_heartbeat_lifespan_task
            import threading
            import asyncio
            
            def run_heartbeat():
                """Run heartbeat in separate thread with its own event loop."""
                self.logger.debug(f"Starting background heartbeat thread for {service_id}")
                try:
                    # Create new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # Run heartbeat task
                    loop.run_until_complete(api_heartbeat_lifespan_task(heartbeat_config))
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

    def _perform_graceful_shutdown(self) -> None:
        """Perform graceful shutdown by unregistering from registry."""
        try:
            # Run graceful shutdown asynchronously
            import asyncio

            asyncio.run(self._graceful_shutdown_async())
        except Exception as e:
            self.logger.error(f"❌ Graceful shutdown failed: {e}")

    async def _graceful_shutdown_async(self) -> None:
        """Async graceful shutdown implementation."""
        try:
            # Get the latest pipeline context from the orchestrator
            if self._orchestrator is None:
                self.logger.warning(
                    "🚨 No orchestrator available for graceful shutdown"
                )
                return

            # Access the pipeline context through the orchestrator
            pipeline_context = getattr(self._orchestrator.pipeline, "_last_context", {})

            # Get registry configuration
            registry_url = pipeline_context.get("registry_url")
            agent_id = pipeline_context.get("agent_id")

            if not registry_url or not agent_id:
                self.logger.warning(
                    f"🚨 Cannot perform graceful shutdown: missing registry_url={registry_url} or agent_id={agent_id}"
                )
                return

            # Create registry client for shutdown
            from ...generated.mcp_mesh_registry_client.api_client import ApiClient
            from ...generated.mcp_mesh_registry_client.configuration import (
                Configuration,
            )
            from ...shared.registry_client_wrapper import RegistryClientWrapper

            config = Configuration(host=registry_url)
            api_client = ApiClient(configuration=config)
            registry_wrapper = RegistryClientWrapper(api_client)

            # Perform graceful unregistration
            success = await registry_wrapper.unregister_agent(agent_id)
            if success:
                self.logger.info(
                    f"🏁 Graceful shutdown completed for agent '{agent_id}'"
                )
            else:
                self.logger.warning(
                    f"⚠️ Graceful shutdown failed for agent '{agent_id}' - continuing shutdown"
                )

        except Exception as e:
            # Don't fail the shutdown process due to unregistration errors
            self.logger.error(f"❌ Graceful shutdown error: {e} - continuing shutdown")

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
        self.logger.info(f"🚀 Starting single pipeline execution: {self.name}")

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

    # Install signal handlers in main thread FIRST (before any threading)
    _install_signal_handlers()

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


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown in main thread."""
    try:
        import signal
        import threading

        # Only install if we're in the main thread
        if threading.current_thread() is not threading.main_thread():
            logger.debug("🚨 Not in main thread, skipping signal handler installation")
            return

        def signal_handler(signum, frame):
            logger.info(f"🔴 Received signal {signum}, performing graceful shutdown...")

            # Get the global orchestrator and perform shutdown
            orchestrator = get_global_orchestrator()

            # Create a simple sync shutdown using the stored context
            import asyncio

            try:
                # Try to get pipeline context for graceful shutdown
                pipeline_context = getattr(orchestrator.pipeline, "_last_context", {})
                registry_url = pipeline_context.get("registry_url")
                agent_id = pipeline_context.get("agent_id")

                if registry_url and agent_id:
                    # Perform synchronous graceful shutdown
                    logger.info(
                        f"🏁 Gracefully unregistering agent '{agent_id}' from {registry_url}"
                    )

                    # Import here to avoid circular imports
                    from ...generated.mcp_mesh_registry_client.api_client import (
                        ApiClient,
                    )
                    from ...generated.mcp_mesh_registry_client.configuration import (
                        Configuration,
                    )
                    from ...shared.registry_client_wrapper import RegistryClientWrapper

                    config = Configuration(host=registry_url)
                    api_client = ApiClient(configuration=config)
                    registry_wrapper = RegistryClientWrapper(api_client)

                    # Run the async unregister in a new event loop
                    success = asyncio.run(registry_wrapper.unregister_agent(agent_id))
                    if success:
                        logger.info(f"✅ Agent '{agent_id}' unregistered successfully")
                    else:
                        logger.warning(
                            f"⚠️ Agent '{agent_id}' unregister failed - continuing shutdown"
                        )
                else:
                    logger.warning(
                        f"🚨 Cannot perform graceful shutdown: missing registry_url={registry_url} or agent_id={agent_id}"
                    )

            except Exception as e:
                logger.error(f"❌ Graceful shutdown error: {e} - continuing shutdown")

            # Exit gracefully
            import sys

            sys.exit(0)

        # Register signal handlers for SIGINT (Ctrl+C) and SIGTERM
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info(
            "📡 Signal handlers registered in main thread for graceful shutdown"
        )

    except Exception as e:
        logger.warning(f"⚠️ Failed to install signal handlers: {e}")
        # Continue without signal handlers - graceful shutdown will rely on FastAPI lifespan
