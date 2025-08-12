"""
API health check step for API heartbeat pipeline.

Validates FastAPI application health status and endpoint availability
for heartbeat reporting to the registry.
"""

import logging
from typing import Any

from ..shared.base_step import PipelineStep
from ..shared.pipeline_types import PipelineResult

logger = logging.getLogger(__name__)


class APIHealthCheckStep(PipelineStep):
    """
    Check FastAPI application health status.
    
    Validates that the FastAPI application is running properly
    and endpoints are accessible for dependency injection.
    """

    def __init__(self, required: bool = True):
        super().__init__(
            name="api-health-check",
            required=required,
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Check FastAPI application health status.

        Args:
            context: Pipeline context containing fastapi_app and service info

        Returns:
            PipelineResult with health_status in context
        """
        self.logger.info("🏥 [DEBUG] Checking FastAPI application health status")

        try:
            # Get FastAPI app from context
            fastapi_app = context.get("fastapi_app")
            service_id = context.get("service_id") or context.get("agent_id", "unknown")
            
            if not fastapi_app:
                error_msg = "No FastAPI application found in context for health check"
                self.logger.error(f"❌ {error_msg}")
                
                from ..shared.pipeline_types import PipelineStatus
                result = PipelineResult(
                    status=PipelineStatus.FAILED,
                    message=error_msg,
                    context=context
                )
                result.add_error(error_msg)
                return result

            # Check FastAPI app basic properties
            app_title = getattr(fastapi_app, "title", "Unknown API")
            app_version = getattr(fastapi_app, "version", "1.0.0")
            
            # Count available routes with dependency injection
            routes_with_mesh = self._count_mesh_routes(fastapi_app)
            total_routes = len(getattr(fastapi_app, "routes", []))

            self.logger.debug(
                f"🔍 FastAPI app health: {app_title} v{app_version}, "
                f"{routes_with_mesh}/{total_routes} routes with mesh injection"
            )

            # Build health status for API service
            # For API services, we create a simplified health status dict instead of using
            # the strict HealthStatus model which requires capabilities (designed for MCP agents)
            from datetime import UTC, datetime
            
            health_status_dict = {
                "agent_name": service_id,
                "status": "healthy",
                "timestamp": datetime.now(UTC).isoformat(),
                "version": app_version,
                "metadata": {
                    "service_type": "api",
                    "app_title": app_title,
                    "app_version": app_version,
                    "routes_total": total_routes,
                    "routes_with_mesh": routes_with_mesh,
                    "health_check_timestamp": datetime.now(UTC).isoformat(),
                }
            }

            self.logger.info(
                f"🏥 API health check passed: {app_title} v{app_version} "
                f"({routes_with_mesh} mesh routes)"
            )

            return PipelineResult(
                message=f"API health check passed for {app_title}",
                context={
                    "health_status": health_status_dict,
                    "app_title": app_title,
                    "app_version": app_version,
                    "routes_total": total_routes,
                    "routes_with_mesh": routes_with_mesh,
                }
            )

        except Exception as e:
            error_msg = f"API health check failed: {e}"
            self.logger.error(f"❌ {error_msg}")

            from ..shared.pipeline_types import PipelineStatus
            result = PipelineResult(
                status=PipelineStatus.FAILED,
                message=error_msg,
                context=context
            )
            result.add_error(str(e))
            return result

    def _count_mesh_routes(self, fastapi_app: Any) -> int:
        """Count routes that have mesh dependency injection applied."""
        try:
            mesh_routes = 0
            routes = getattr(fastapi_app, "routes", [])
            
            for route in routes:
                # Check if route has dependency injection wrapper
                endpoint = getattr(route, "endpoint", None)
                if endpoint and hasattr(endpoint, "__wrapped__"):
                    # This indicates our dependency injection wrapper
                    mesh_routes += 1
                    
            return mesh_routes
            
        except Exception as e:
            self.logger.warning(f"⚠️ Could not count mesh routes: {e}")
            return 0