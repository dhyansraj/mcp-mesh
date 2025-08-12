"""
API heartbeat orchestrator for managing periodic pipeline execution.

Provides a high-level interface for executing API heartbeat pipelines 
with proper context management and error handling for FastAPI services.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from .api_heartbeat_pipeline import APIHeartbeatPipeline

logger = logging.getLogger(__name__)


class APIHeartbeatOrchestrator:
    """
    Orchestrates API heartbeat pipeline execution for periodic registry communication.

    Manages the context preparation, pipeline execution, and result processing
    for the periodic heartbeat cycle of FastAPI services using @mesh.route decorators.
    """

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.APIHeartbeatOrchestrator")
        self.pipeline = APIHeartbeatPipeline()
        self._heartbeat_count = 0

    async def execute_api_heartbeat(
        self, service_id: str, context: dict[str, Any]
    ) -> bool:
        """
        Execute a complete API heartbeat cycle with comprehensive error handling.

        Args:
            service_id: Service identifier for the FastAPI application
            context: Full pipeline context from API startup

        Returns:
            bool: True if heartbeat succeeded, False if failed
        """
        self._heartbeat_count += 1

        try:
            # Prepare heartbeat context with validation
            heartbeat_context = self._prepare_api_heartbeat_context(service_id, context)

            # Validate required context before proceeding
            if not self._validate_api_heartbeat_context(heartbeat_context):
                self.logger.error(
                    f"❌ API heartbeat #{self._heartbeat_count} failed: invalid context"
                )
                return False

            # Log heartbeat request details for debugging
            self._log_api_heartbeat_request(heartbeat_context, self._heartbeat_count)

            # Execute API heartbeat pipeline with timeout protection
            self.logger.info(f"💓 Executing API heartbeat #{self._heartbeat_count} for service '{service_id}'")

            # Add timeout to prevent hanging heartbeats (30 seconds max)
            import asyncio

            try:
                self.logger.debug("Starting API heartbeat pipeline execution")
                result = await asyncio.wait_for(
                    self.pipeline.execute_api_heartbeat_cycle(heartbeat_context),
                    timeout=30.0,
                )
                if result.is_success():
                    self.logger.debug("✅ API heartbeat pipeline completed successfully")
                else:
                    self.logger.error(f"❌ API heartbeat pipeline failed: {result.message}")
            except TimeoutError:
                self.logger.error(
                    f"❌ API heartbeat #{self._heartbeat_count} timed out after 30 seconds"
                )
                return False
            except Exception as e:
                self.logger.error(f"❌ [DEBUG] Pipeline execution exception: {e}")
                import traceback
                self.logger.error(f"❌ [DEBUG] Traceback: {traceback.format_exc()}")
                return False

            # Process results
            success = self._process_api_heartbeat_result(
                result, service_id, self._heartbeat_count
            )

            # Log periodic status updates
            if self._heartbeat_count % 10 == 0:
                elapsed_time = self._heartbeat_count * 5  # Using 5s interval (MeshDefaults.HEALTH_INTERVAL)
                self.logger.info(
                    f"💓 API heartbeat #{self._heartbeat_count} for service '{service_id}' - "
                    f"running for {elapsed_time} seconds"
                )

            return success

        except Exception as e:
            # Log detailed error information for debugging
            import traceback

            self.logger.error(
                f"❌ API heartbeat #{self._heartbeat_count} failed for service '{service_id}': {e}\n"
                f"Traceback: {traceback.format_exc()}"
            )
            return False

    def _prepare_api_heartbeat_context(
        self, service_id: str, startup_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Prepare context for API heartbeat pipeline execution."""

        # Get FastAPI app and other essential components from startup context
        fastapi_app = startup_context.get("fastapi_app")
        display_config = startup_context.get("display_config", {})
        
        # Get API service metadata from startup context
        api_service_metadata = startup_context.get("api_service_metadata", {})
        self.logger.debug(f"🔍 Startup context has api_service_metadata: {len(api_service_metadata) > 0}")
        if api_service_metadata:
            capabilities = api_service_metadata.get("capabilities", [])
            self.logger.debug(f"🔍 API service has {len(capabilities)} route capabilities")
        
        # Build heartbeat-specific context
        heartbeat_context = {
            "service_id": service_id,
            "agent_id": service_id,  # For compatibility with registry calls
            "fastapi_app": fastapi_app,
            "display_config": display_config,
            # Include registry and configuration from startup
            "agent_config": startup_context.get("agent_config", {}),
            "registration_data": startup_context.get("registration_data", {}),
            "registry_wrapper": startup_context.get("registry_wrapper"),
            # CRITICAL: Include API service metadata with route dependencies
            "api_service_metadata": api_service_metadata,
        }

        return heartbeat_context

    def _validate_api_heartbeat_context(self, heartbeat_context: dict[str, Any]) -> bool:
        """Validate that API heartbeat context has all required components."""

        required_fields = ["service_id", "fastapi_app"]

        for field in required_fields:
            if field not in heartbeat_context or heartbeat_context[field] is None:
                self.logger.error(
                    f"❌ API heartbeat context validation failed: missing '{field}'"
                )
                return False

        # Additional validation for FastAPI app
        fastapi_app = heartbeat_context.get("fastapi_app")
        if not hasattr(fastapi_app, "routes"):
            self.logger.error(
                "❌ API heartbeat context validation failed: invalid FastAPI app object"
            )
            return False

        return True

    def _log_api_heartbeat_request(
        self, heartbeat_context: dict[str, Any], heartbeat_count: int
    ) -> None:
        """Log API heartbeat request details for debugging."""

        service_id = heartbeat_context.get("service_id", "unknown")
        fastapi_app = heartbeat_context.get("fastapi_app")
        display_config = heartbeat_context.get("display_config", {})

        # Extract app information for logging
        app_info = {}
        if fastapi_app:
            app_info = {
                "title": getattr(fastapi_app, "title", "Unknown API"),
                "version": getattr(fastapi_app, "version", "1.0.0"),
                "routes_count": len(getattr(fastapi_app, "routes", [])),
            }

        # Log heartbeat details
        self.logger.debug(
            f"🔍 API Heartbeat #{heartbeat_count} for '{service_id}': "
            f"app={app_info}, display={display_config}"
        )

    def _process_api_heartbeat_result(
        self, result: Any, service_id: str, heartbeat_count: int
    ) -> bool:
        """Process API heartbeat pipeline result and log appropriately."""

        if result.is_success():
            # Check for heartbeat response in result context
            heartbeat_response = result.context.get("heartbeat_response")
            heartbeat_success = result.context.get("heartbeat_success", False)
            
            self.logger.debug(f"API heartbeat result - success: {heartbeat_success}")

            # Check if heartbeat was skipped due to optimization
            heartbeat_skipped = result.context.get("heartbeat_skipped", False)
            skip_reason = result.context.get("skip_reason")
            
            if heartbeat_success and heartbeat_response:
                # Log response details for debugging
                try:
                    response_json = json.dumps(
                        heartbeat_response, indent=2, default=str
                    )
                    self.logger.debug(
                        f"🔍 API heartbeat response #{heartbeat_count}:\n{response_json}"
                    )
                except Exception as e:
                    self.logger.debug(
                        f"🔍 API heartbeat response #{heartbeat_count}: {heartbeat_response} "
                        f"(json serialization failed: {e})"
                    )

                self.logger.info(
                    f"💚 API heartbeat #{heartbeat_count} sent successfully for service '{service_id}'"
                )
                return True
            elif heartbeat_success and heartbeat_skipped:
                # Heartbeat was skipped for optimization - this is success
                self.logger.debug(
                    f"🚀 API heartbeat #{heartbeat_count} skipped for service '{service_id}' - {skip_reason}"
                )
                return True
            else:
                self.logger.warning(
                    f"💔 [UPDATED] API heartbeat #{heartbeat_count} failed for service '{service_id}' - "
                    f"no response or unsuccessful (heartbeat_success={heartbeat_success}, heartbeat_response={heartbeat_response})"
                )
                return False
        else:
            self.logger.warning(
                f"💔 [UPDATED-PIPELINE] API heartbeat #{heartbeat_count} pipeline failed for service '{service_id}': {result.message}"
            )
            
            # Log detailed errors
            if hasattr(result, 'errors') and result.errors:
                for error in result.errors:
                    self.logger.warning(f"  - API heartbeat error: {error}")
                    
            return False