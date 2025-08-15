"""
Tracing Middleware Integration for FastAPI Applications.

This module provides automatic injection of tracing middleware into discovered
FastAPI applications, ensuring unified telemetry collection across both MCP 
agents and FastAPI apps without requiring user intervention.
"""

import logging
from typing import Any, Dict

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


class TracingMiddlewareIntegrationStep(PipelineStep):
    """
    Programmatically adds tracing middleware to discovered FastAPI applications.
    
    This ensures consistent telemetry collection across both MCP agents 
    (via HTTP wrapper middleware) and FastAPI apps (via injected middleware).
    
    The middleware handles:
    - Extracting trace headers (X-Trace-ID, X-Parent-Span) from requests
    - Setting up trace context for the request lifecycle
    - Propagating distributed tracing information
    """

    def __init__(self):
        super().__init__(
            name="tracing-middleware-integration",
            required=True,
            description="Add tracing middleware to FastAPI apps for distributed tracing",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Add tracing middleware to discovered FastAPI applications."""
        self.logger.debug("🔍 TRACING: Starting middleware integration for FastAPI apps...")

        result = PipelineResult(message="Tracing middleware integration completed")

        try:
            fastapi_apps = context.get("fastapi_apps", {})
            
            if not fastapi_apps:
                result.status = PipelineStatus.SKIPPED
                result.message = "No FastAPI applications found for middleware injection"
                self.logger.debug("🔍 TRACING: No FastAPI apps to add middleware to")
                return result

            # Add middleware to each discovered FastAPI app
            middleware_added = 0
            skipped_count = 0
            
            for app_id, app_info in fastapi_apps.items():
                fastapi_app = app_info["instance"]
                app_title = app_info.get("title", "Unknown App")
                
                self.logger.debug(
                    f"🔍 TRACING: Checking app '{app_title}' ({app_id}) for middleware injection"
                )
                
                # Check if middleware already exists to avoid duplicates
                if not self._has_tracing_middleware(fastapi_app):
                    self._add_tracing_middleware(fastapi_app, app_title)
                    middleware_added += 1
                    
                    self.logger.info(
                        f"🔍 TRACING: Added tracing middleware to FastAPI app '{app_title}'"
                    )
                else:
                    skipped_count += 1
                    self.logger.debug(
                        f"🔍 TRACING: Skipped '{app_title}' - tracing middleware already exists"
                    )

            # Store results in context
            result.add_context("middleware_added_count", middleware_added)
            result.add_context("middleware_skipped_count", skipped_count)
            result.message = (
                f"Added tracing middleware to {middleware_added} FastAPI apps "
                f"({skipped_count} already had middleware)"
            )

            self.logger.info(
                f"🔍 TRACING: Middleware integration complete - "
                f"added: {middleware_added}, skipped: {skipped_count}"
            )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Middleware integration failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"🔍 TRACING: Middleware integration failed: {e}")

        return result

    def _has_tracing_middleware(self, app) -> bool:
        """
        Check if FastAPI app already has MCP Mesh tracing middleware.
        
        Args:
            app: FastAPI application instance
            
        Returns:
            True if tracing middleware already exists, False otherwise
        """
        try:
            # Check user_middleware stack for our specific middleware classes
            if hasattr(app, 'user_middleware'):
                for middleware in app.user_middleware:
                    if hasattr(middleware, 'cls'):
                        middleware_name = middleware.cls.__name__
                        # Check for both old and new middleware names
                        if middleware_name in ('MCPMeshTracingMiddleware', 'FastAPITracingMiddleware'):
                            self.logger.debug(
                                f"🔍 TRACING: Found existing {middleware_name} in app"
                            )
                            return True
                            
            self.logger.debug("🔍 TRACING: No existing tracing middleware found")
            return False
            
        except Exception as e:
            # If we can't check middleware stack, assume it doesn't exist
            self.logger.debug(f"🔍 TRACING: Error checking middleware stack: {e}")
            return False

    def _add_tracing_middleware(self, app, app_title: str) -> None:
        """
        Add dedicated FastAPI tracing middleware to FastAPI app.
        
        Args:
            app: FastAPI application instance
            app_title: Human-readable app title for logging
        """
        try:
            from ....tracing.fastapi_tracing_middleware import FastAPITracingMiddleware
            
            # Add the dedicated FastAPI tracing middleware
            app.add_middleware(FastAPITracingMiddleware, logger_instance=self.logger)
            
            self.logger.debug(
                f"🔍 TRACING: Successfully added FastAPITracingMiddleware to '{app_title}'"
            )
            
        except Exception as e:
            # Log error but don't fail the entire pipeline
            self.logger.error(
                f"🔍 TRACING: Failed to add middleware to '{app_title}': {e}"
            )
            raise  # Re-raise so pipeline can handle the error appropriately