"""
FastAPI lifespan integration for API heartbeat pipeline.

Handles the execution of API heartbeat pipeline as a background task
during FastAPI application lifespan for @mesh.route decorator services.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def api_heartbeat_lifespan_task(heartbeat_config: dict[str, Any]) -> None:
    """
    API heartbeat task that runs in FastAPI lifespan using pipeline architecture.

    Args:
        heartbeat_config: Configuration containing service_id, interval, 
                         and context for API heartbeat execution
    """
    service_id = heartbeat_config["service_id"]
    interval = heartbeat_config["interval"]  # Already validated by get_config_value in setup
    context = heartbeat_config["context"]
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    # Check if running in standalone mode
    if standalone_mode:
        logger.info(
            f"💓 Starting API heartbeat pipeline in standalone mode for service '{service_id}' "
            f"(no registry communication)"
        )
        return  # For now, skip heartbeat in standalone mode

    # Create API heartbeat orchestrator for pipeline execution
    from .api_heartbeat_orchestrator import APIHeartbeatOrchestrator

    api_heartbeat_orchestrator = APIHeartbeatOrchestrator()

    logger.info(f"💓 Starting API heartbeat pipeline task for service '{service_id}'")

    try:
        while True:
            try:
                # Execute API heartbeat pipeline
                success = await api_heartbeat_orchestrator.execute_api_heartbeat(
                    service_id, context
                )

                if not success:
                    # Log failure but continue to next cycle (pipeline handles detailed logging)
                    logger.debug(
                        f"💔 API heartbeat pipeline failed for service '{service_id}' - "
                        f"continuing to next cycle"
                    )

            except Exception as e:
                # Log pipeline execution error but continue to next cycle for resilience
                logger.error(
                    f"❌ API heartbeat pipeline execution error for service '{service_id}': {e}"
                )
                # Continue to next cycle - heartbeat should be resilient

            # Wait for next heartbeat interval
            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info(f"🛑 API heartbeat pipeline task cancelled for service '{service_id}'")
        raise


def create_api_lifespan_handler(heartbeat_config: dict[str, Any]) -> Any:
    """
    Create a FastAPI lifespan context manager that runs API heartbeat pipeline.

    Args:
        heartbeat_config: Configuration for API heartbeat execution

    Returns:
        Async context manager for FastAPI lifespan
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def api_lifespan(app):
        """FastAPI lifespan context manager with API heartbeat integration."""
        service_id = heartbeat_config.get("service_id", "unknown")
        logger.info(f"🚀 Starting FastAPI lifespan for service '{service_id}'")

        # Start API heartbeat task
        heartbeat_task = asyncio.create_task(
            api_heartbeat_lifespan_task(heartbeat_config)
        )

        try:
            # Yield control to FastAPI
            yield
        finally:
            # Cleanup: cancel heartbeat task
            logger.info(f"🛑 Shutting down FastAPI lifespan for service '{service_id}'")
            heartbeat_task.cancel()
            
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                logger.info(f"✅ API heartbeat task cancelled for service '{service_id}'")

    return api_lifespan


def integrate_api_heartbeat_with_fastapi(
    fastapi_app: Any, heartbeat_config: dict[str, Any]
) -> None:
    """
    Integrate API heartbeat pipeline with FastAPI lifespan events.

    Args:
        fastapi_app: FastAPI application instance
        heartbeat_config: Configuration for heartbeat execution
    """
    service_id = heartbeat_config.get("service_id", "unknown")
    
    try:
        # Check if FastAPI app already has a lifespan handler
        existing_lifespan = getattr(fastapi_app, "router.lifespan_context", None)
        
        if existing_lifespan is not None:
            logger.warning(
                f"⚠️ FastAPI app already has lifespan handler - "
                f"API heartbeat integration may conflict for service '{service_id}'"
            )

        # Create and set the lifespan handler
        api_lifespan = create_api_lifespan_handler(heartbeat_config)
        fastapi_app.router.lifespan_context = api_lifespan

        logger.info(
            f"🔗 API heartbeat integrated with FastAPI lifespan for service '{service_id}'"
        )

    except Exception as e:
        logger.error(
            f"❌ Failed to integrate API heartbeat with FastAPI lifespan "
            f"for service '{service_id}': {e}"
        )
        raise