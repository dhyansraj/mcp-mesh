"""Register the inbound cancel HTTP route on the agent's FastAPI app
(Phase 1 — MeshJob substrate).

Per ``MESHJOB_DESIGN.org`` "Wire Protocol / New endpoints" /
"Cancellation": when the registry receives a cancel request for a job
whose owner is alive, it forwards the call to the owner replica's
``POST /jobs/{job_id}/cancel`` HTTP route. That route fires the
in-process cancel token registered by the inbound tool wrapper (or the
claim worker) so any outbound HTTP calls under the active
:func:`mcp_mesh_core.with_job_async` scope abort.

The route is registered on the FastAPI app prepared by
:class:`FastAPIServerSetupStep`, AFTER that step has stored the app in
the pipeline context. Returning ``{"cancelled": True/False}`` tells the
registry whether a token was found in this process — useful for
diagnostics when a forwarded cancel races with the owning job
finishing.

Route ordering note (#bug 4)
----------------------------

:class:`FastAPIServerSetupStep` mounts the FastMCP HTTP app at the
root path (``app.mount("", fastmcp_app)``). Starlette resolves routes
in registration order and ``Mount("")`` matches *every* path — so an
explicit route added AFTER the mount via ``app.add_api_route`` is
shadowed and yields 404. To work around that, this step inserts the
cancel route at the FRONT of ``app.router.routes`` so it's matched
before the catch-all FastMCP mount.
"""

from __future__ import annotations

import logging
from typing import Any

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


class JobsCancelRouteStep(PipelineStep):
    """Add ``POST /jobs/{job_id}/cancel`` to the agent's FastAPI app.

    Runs AFTER :class:`FastAPIServerSetupStep` (which prepares /
    discovers the FastAPI app) and BEFORE the orchestrator hands the
    app to uvicorn (so the route is part of the served app).
    """

    def __init__(self) -> None:
        super().__init__(
            name="jobs-cancel-route",
            required=False,  # Best-effort: failing must not block startup.
            description=(
                "Register POST /jobs/{job_id}/cancel on the agent's "
                "FastAPI app (forwards to mcp_mesh_core.cancel_active_job)"
            ),
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="MeshJob cancel route registration")

        app = context.get("fastapi_app")
        if app is None:
            result.status = PipelineStatus.SKIPPED
            result.message = (
                "MeshJob cancel route skipped: no FastAPI app in context "
                "(HTTP transport disabled?)"
            )
            self.logger.info("⚠️ %s", result.message)
            return result

        # Late import: keep the SDK importable in test environments
        # where the native extension isn't built. The route still gets
        # registered (so HTTP 404 doesn't surface to the registry); it
        # just always returns ``cancelled=False``.
        try:
            from mcp_mesh_core import cancel_active_job
        except Exception as e:
            self.logger.warning(
                "MeshJob cancel route: mcp_mesh_core.cancel_active_job "
                "unavailable (%s); registering a stub route that always "
                "reports cancelled=false",
                e,
            )
            cancel_active_job = lambda _job_id: False  # noqa: E731

        async def cancel_job_route(job_id: str) -> dict[str, Any]:
            """Fire the local cancel token for ``job_id`` if present."""
            cancelled = bool(cancel_active_job(job_id))
            self.logger.info(
                "📨 cancel route: job_id=%s cancelled=%s", job_id, cancelled
            )
            return {"cancelled": cancelled, "job_id": job_id}

        try:
            # Build the FastAPI route, then INSERT it at the front of the
            # router's routes list so the explicit path is matched before
            # FastAPIServerSetupStep's ``app.mount("", fastmcp_app)``
            # catch-all (#bug 4).
            from fastapi.routing import APIRoute

            route = APIRoute(
                path="/jobs/{job_id}/cancel",
                endpoint=cancel_job_route,
                methods=["POST"],
                tags=["mesh-jobs"],
                summary="Fire the in-process cancel token for the given job",
            )

            # Defensive: skip duplicate registration on hot-reload.
            existing_paths = {
                getattr(r, "path", None) for r in app.router.routes
            }
            if route.path not in existing_paths:
                app.router.routes.insert(0, route)
                self.logger.debug(
                    "Inserted MeshJob cancel route at routes[0] (front of "
                    "FastMCP catch-all mount)"
                )
            else:
                self.logger.debug(
                    "MeshJob cancel route already registered at %s; skipping",
                    route.path,
                )
        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"MeshJob cancel route registration failed: {e}"
            result.add_error(str(e))
            self.logger.error("❌ %s", result.message)
            return result

        result.message = "Registered POST /jobs/{job_id}/cancel"
        self.logger.info("📨 %s", result.message)
        return result
