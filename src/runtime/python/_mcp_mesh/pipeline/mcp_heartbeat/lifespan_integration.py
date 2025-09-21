"""
FastAPI lifespan integration for heartbeat pipeline.

Handles the execution of heartbeat pipeline as a background task
during FastAPI application lifespan.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def heartbeat_lifespan_task(heartbeat_config: dict[str, Any]) -> None:
    """
    Heartbeat task that runs in FastAPI lifespan using pipeline architecture.

    Args:
        heartbeat_config: Configuration containing registry_wrapper, agent_id,
                         interval, and context for heartbeat execution
    """
    registry_wrapper = heartbeat_config[
        "registry_wrapper"
    ]  # May be None in standalone mode
    agent_id = heartbeat_config["agent_id"]
    interval = heartbeat_config["interval"]
    context = heartbeat_config["context"]
    standalone_mode = heartbeat_config.get("standalone_mode", False)

    # Check if running in standalone mode
    if standalone_mode:
        logger.info(
            f"💓 Starting heartbeat pipeline in standalone mode for agent '{agent_id}' (no registry communication)"
        )
        return  # For now, skip heartbeat in standalone mode

    # Create heartbeat orchestrator for pipeline execution
    from .heartbeat_orchestrator import HeartbeatOrchestrator

    heartbeat_orchestrator = HeartbeatOrchestrator()

    logger.info(f"💓 Starting heartbeat pipeline task for agent '{agent_id}'")

    try:
        while True:
            # Check if shutdown is complete before executing heartbeat
            try:
                from ...shared.simple_shutdown import should_stop_heartbeat

                if should_stop_heartbeat():
                    logger.info(
                        f"🛑 Heartbeat stopped for agent '{agent_id}' due to shutdown"
                    )
                    break
            except ImportError:
                # If simple_shutdown is not available, continue normally
                pass

            try:
                # Execute heartbeat pipeline
                success = await heartbeat_orchestrator.execute_heartbeat(
                    agent_id, context
                )

                if not success:
                    # Log failure but continue to next cycle (pipeline handles detailed logging)
                    logger.debug(
                        f"💔 Heartbeat pipeline failed for agent '{agent_id}' - continuing to next cycle"
                    )

            except Exception as e:
                # Log pipeline execution error but continue to next cycle for resilience
                logger.error(
                    f"❌ Heartbeat pipeline execution error for agent '{agent_id}': {e}"
                )
                # Continue to next cycle - heartbeat should be resilient

            # Wait for next heartbeat interval
            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info(f"🛑 Heartbeat pipeline task cancelled for agent '{agent_id}'")
        raise
