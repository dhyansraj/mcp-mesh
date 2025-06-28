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
    registry_wrapper = heartbeat_config["registry_wrapper"]
    agent_id = heartbeat_config["agent_id"]
    interval = heartbeat_config["interval"]
    context = heartbeat_config["context"]

    # Create heartbeat orchestrator for pipeline execution
    from .heartbeat_orchestrator import HeartbeatOrchestrator

    heartbeat_orchestrator = HeartbeatOrchestrator()

    logger.info(f"💓 Starting heartbeat pipeline task for agent '{agent_id}'")

    try:
        while True:
            try:
                # Execute heartbeat pipeline
                success = await heartbeat_orchestrator.execute_heartbeat(
                    registry_wrapper, agent_id, context
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
        logger.info(
            f"🛑 Heartbeat pipeline task cancelled for agent '{agent_id}'"
        )
        raise