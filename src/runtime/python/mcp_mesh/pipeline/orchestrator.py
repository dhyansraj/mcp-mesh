"""
Simplified orchestrator for MCP Mesh using pipeline architecture.

This replaces the complex scattered initialization with a clean,
explicit pipeline execution that can be easily tested and debugged.
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from .pipeline import MeshPipeline
from .registry_steps import (
    DependencyResolutionStep,
    HeartbeatSendStep,
    RegistryConnectionStep,
)
from .steps import (
    ConfigurationStep,
    DecoratorCollectionStep,
    FastAPIServerSetupStep,
    FastMCPServerDiscoveryStep,
    HeartbeatPreparationStep,
)

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

    def _execute_processing(self) -> None:
        """Execute the processing (called by timer)."""
        try:
            if self._orchestrator is None:
                self.logger.error("❌ No orchestrator set for processing")
                return

            self.logger.info(
                f"🚀 Debounce delay ({self.delay_seconds}s) complete, processing all decorators"
            )

            # Execute the pipeline using asyncio.run
            import asyncio

            result = asyncio.run(self._orchestrator.process_once())

            # Check if we should exit after processing
            if os.getenv("MCP_MESH_DEBUG_EXIT", "true").lower() == "true":
                self.logger.info("🏁 Debug mode: exiting after processing")
                sys.exit(0)

        except Exception as e:
            self.logger.error(f"❌ Error in debounced processing: {e}")


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
        self.pipeline = MeshPipeline(name=name)
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self._setup_basic_pipeline()

    def _setup_basic_pipeline(self) -> None:
        """Set up the processing pipeline."""
        # Essential steps (complex features commented out with TODO: SIMPLIFICATION)
        steps = [
            DecoratorCollectionStep(),
            ConfigurationStep(),
            HeartbeatPreparationStep(),
            FastMCPServerDiscoveryStep(),  # New: Discover user's FastMCP instances
            FastAPIServerSetupStep(),  # New: Setup FastAPI server with mounted FastMCP + K8s endpoints
            RegistryConnectionStep(),
            HeartbeatSendStep(required=False),  # Optional for now
            DependencyResolutionStep(),
        ]

        self.pipeline.add_steps(steps)
        self.logger.debug(f"Pipeline configured with {len(steps)} steps")

    async def process_once(self) -> dict:
        """
        Execute the pipeline once.

        This replaces the background polling with explicit execution.
        """
        self.logger.info(f"🚀 Starting single pipeline execution: {self.name}")

        result = await self.pipeline.execute()

        # Convert result to dict for compatibility
        return {
            "status": result.status.value,
            "message": result.message,
            "errors": result.errors,
            "context": result.context,
            "timestamp": result.timestamp.isoformat(),
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


# Global orchestrator instance for compatibility
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
    logger.info("🔧 Starting MCP Mesh runtime with debouncing")

    # TODO: SIMPLIFICATION - Comment out complex features
    # - FastMCP patching
    # - HTTP wrapper setup
    # - Background async processing
    # - Complex dependency injection

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


# TODO: SIMPLIFICATION - Replace complex auto-initialization
# This will be enabled after the basic pipeline is tested
def enable_auto_initialization() -> None:
    """Enable auto-initialization (disabled during simplification)."""
    import os

    if os.getenv("MCP_MESH_ENABLED", "true").lower() == "true":
        start_simplified_runtime()
