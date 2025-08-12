"""
Heartbeat orchestrator for managing periodic pipeline execution.

Provides a high-level interface for executing heartbeat pipelines with proper
context management and error handling.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from ...shared.support_types import HealthStatus, HealthStatusType
from .heartbeat_pipeline import HeartbeatPipeline

logger = logging.getLogger(__name__)


class HeartbeatOrchestrator:
    """
    Orchestrates heartbeat pipeline execution for periodic registry communication.

    Manages the context preparation, pipeline execution, and result processing
    for the 30-second heartbeat cycle.
    """

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.HeartbeatOrchestrator")
        self.pipeline = HeartbeatPipeline()
        self._heartbeat_count = 0

    async def execute_heartbeat(self, agent_id: str, context: dict[str, Any]) -> bool:
        """
        Execute a complete heartbeat cycle with comprehensive error handling.

        Args:
            agent_id: Agent identifier
            context: Full pipeline context from startup

        Returns:
            bool: True if heartbeat succeeded, False if failed
        """
        self._heartbeat_count += 1

        try:
            # Prepare heartbeat context with validation
            heartbeat_context = self._prepare_heartbeat_context(agent_id, context)

            # Validate required context before proceeding
            if not self._validate_heartbeat_context(heartbeat_context):
                self.logger.error(
                    f"❌ Heartbeat #{self._heartbeat_count} failed: invalid context"
                )
                return False

            # Log heartbeat request details for debugging
            self._log_heartbeat_request(heartbeat_context, self._heartbeat_count)

            # Execute heartbeat pipeline with timeout protection
            self.logger.info(
                f"💓 Executing heartbeat #{self._heartbeat_count} for agent '{agent_id}'"
            )

            # Add timeout to prevent hanging heartbeats (30 seconds max)
            import asyncio

            try:
                result = await asyncio.wait_for(
                    self.pipeline.execute_heartbeat_cycle(heartbeat_context),
                    timeout=30.0,
                )
            except TimeoutError:
                self.logger.error(
                    f"❌ Heartbeat #{self._heartbeat_count} timed out after 30 seconds"
                )
                return False

            # Process results
            success = self._process_heartbeat_result(
                result, agent_id, self._heartbeat_count
            )

            # Log periodic status updates
            if self._heartbeat_count % 10 == 0:
                elapsed_time = self._heartbeat_count * 30  # Assuming 30s interval
                self.logger.info(
                    f"💓 Heartbeat #{self._heartbeat_count} for agent '{agent_id}' - "
                    f"running for {elapsed_time} seconds"
                )

            return success

        except Exception as e:
            # Log detailed error information for debugging
            import traceback

            self.logger.error(
                f"❌ Heartbeat #{self._heartbeat_count} failed for agent '{agent_id}': {e}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            return False

    def _prepare_heartbeat_context(
        self, agent_id: str, startup_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Prepare context for heartbeat pipeline execution."""

        # Build health status from startup context
        health_status = self._build_health_status_from_context(
            startup_context, agent_id
        )

        # Prepare heartbeat-specific context - registry_wrapper will be created in pipeline
        heartbeat_context = {
            "agent_id": agent_id,
            "health_status": health_status,
            "agent_config": startup_context.get("agent_config", {}),
            "registration_data": startup_context.get("registration_data", {}),
            # Include other relevant context from startup
            "fastmcp_servers": startup_context.get("fastmcp_servers", {}),
            "capabilities": startup_context.get("capabilities", []),
        }

        return heartbeat_context

    def _validate_heartbeat_context(self, heartbeat_context: dict[str, Any]) -> bool:
        """Validate that heartbeat context has all required components."""

        required_fields = ["agent_id", "health_status"]

        for field in required_fields:
            if field not in heartbeat_context or heartbeat_context[field] is None:
                self.logger.error(
                    f"❌ Heartbeat context validation failed: missing '{field}'"
                )
                return False

        # Additional validation for health_status
        health_status = heartbeat_context.get("health_status")
        if not hasattr(health_status, "agent_name") or not hasattr(
            health_status, "status"
        ):
            self.logger.error(
                "❌ Heartbeat context validation failed: invalid health_status object"
            )
            return False

        return True

    def _build_health_status_from_context(
        self, startup_context: dict[str, Any], agent_id: str
    ) -> HealthStatus:
        """Build health status object from startup context."""

        # Get existing health status from context or build from current state
        existing_health_status = startup_context.get("health_status")

        if existing_health_status:
            # Update timestamp to current time for fresh heartbeat
            if hasattr(existing_health_status, "timestamp"):
                existing_health_status.timestamp = datetime.now(UTC)
            return existing_health_status

        # Build minimal health status from context if none exists
        agent_config = startup_context.get("agent_config", {})

        return HealthStatus(
            agent_name=agent_id,
            status=HealthStatusType.HEALTHY,
            capabilities=agent_config.get("capabilities", []),
            timestamp=datetime.now(UTC),
            version=agent_config.get("version", "1.0.0"),
            metadata=agent_config,
        )

    def _log_heartbeat_request(
        self, heartbeat_context: dict[str, Any], heartbeat_count: int
    ) -> None:
        """Log heartbeat request details for debugging."""

        health_status = heartbeat_context.get("health_status")
        if not health_status:
            return

        # Convert health status to dict for logging
        if hasattr(health_status, "__dict__"):
            health_dict = {
                "agent_name": getattr(health_status, "agent_name", "unknown"),
                "status": (
                    getattr(health_status, "status", "healthy").value
                    if hasattr(getattr(health_status, "status", "healthy"), "value")
                    else str(getattr(health_status, "status", "healthy"))
                ),
                "capabilities": getattr(health_status, "capabilities", []),
                "timestamp": (
                    getattr(health_status, "timestamp", "").isoformat()
                    if hasattr(getattr(health_status, "timestamp", ""), "isoformat")
                    else str(getattr(health_status, "timestamp", ""))
                ),
                "version": getattr(health_status, "version", "1.0.0"),
                "metadata": getattr(health_status, "metadata", {}),
            }
        else:
            health_dict = health_status

        request_json = json.dumps(health_dict, indent=2, default=str)

    def _process_heartbeat_result(
        self, result: Any, agent_id: str, heartbeat_count: int
    ) -> bool:
        """Process heartbeat pipeline result and log appropriately."""

        if result.is_success():
            # Check fast heartbeat status to understand what happened
            fast_heartbeat_status = result.context.get("fast_heartbeat_status")
            heartbeat_response = result.context.get("heartbeat_response")

            # Import FastHeartbeatStatus for comparison
            from ...shared.fast_heartbeat_status import (
                FastHeartbeatStatus,
                FastHeartbeatStatusUtil,
            )

            if not fast_heartbeat_status:
                self.logger.error(
                    f"💔 Heartbeat #{heartbeat_count} failed for agent '{agent_id}' - missing fast_heartbeat_status"
                )
                return False

            if FastHeartbeatStatusUtil.should_skip_for_optimization(
                fast_heartbeat_status
            ):
                # Fast heartbeat optimization - no changes detected
                self.logger.info(
                    f"🚀 Heartbeat #{heartbeat_count} optimized for agent '{agent_id}' - no changes detected"
                )
                return True
            elif FastHeartbeatStatusUtil.should_skip_for_resilience(
                fast_heartbeat_status
            ):
                # Fast heartbeat resilience - registry/network error
                self.logger.info(
                    f"⚠️ Heartbeat #{heartbeat_count} skipped for agent '{agent_id}' - resilience mode ({fast_heartbeat_status.value})"
                )
                return True
            elif FastHeartbeatStatusUtil.requires_full_heartbeat(fast_heartbeat_status):
                # Full heartbeat was executed - check for response
                if heartbeat_response:
                    # Log response details for debugging
                    response_json = json.dumps(
                        heartbeat_response, indent=2, default=str
                    )
                    self.logger.debug(
                        f"🔍 Heartbeat response #{heartbeat_count}:\n{response_json}"
                    )

                    # Log dependency resolution info if available
                    deps_resolved = heartbeat_response.get("dependencies_resolved", {})
                    if deps_resolved:
                        self.logger.info(
                            f"🔗 Dependencies resolved: {len(deps_resolved)} items"
                        )

                    self.logger.info(
                        f"💚 Heartbeat #{heartbeat_count} sent successfully for agent '{agent_id}' (full refresh: {fast_heartbeat_status.value})"
                    )
                    return True
                else:
                    self.logger.warning(
                        f"💔 Heartbeat #{heartbeat_count} failed for agent '{agent_id}' - full heartbeat expected but no response"
                    )
                    return False
            else:
                self.logger.warning(
                    f"💔 Heartbeat #{heartbeat_count} unknown status for agent '{agent_id}': {fast_heartbeat_status}"
                )
                return False
        else:
            self.logger.warning(
                f"💔 Heartbeat #{heartbeat_count} pipeline failed for agent '{agent_id}': {result.message}"
            )
            return False
