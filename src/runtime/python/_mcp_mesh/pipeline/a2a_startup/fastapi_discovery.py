"""
FastAPI app discovery for the A2A pipeline.

Mirrors ``api_startup/fastapi_discovery.py`` but gates on
``mesh_a2a_decorators`` instead of ``mesh_routes`` — the A2A pipeline
runs when the user has declared ``@mesh.a2a`` / ``mesh.a2a.mount`` but
no ``@mesh.route`` decorators.

The ``mesh.a2a.mount(...)`` helper has already attached the agent-card
+ JSON-RPC routes to the user's FastAPI app and applied DI to the
underlying handler at module import time. This step only locates the
app instance so the heartbeat config can ship the correct binding info
to the registry.
"""

import logging
from typing import Any

from ...shared.server_discovery import ServerDiscoveryUtil
from ..shared import PipelineResult, PipelineStatus, PipelineStep


class A2AFastAPIDiscoveryStep(PipelineStep):
    """
    Discovers existing FastAPI application instances for the A2A pipeline.

    Same discovery mechanism as ``FastAPIAppDiscoveryStep`` (via
    ``ServerDiscoveryUtil``), but gates on the presence of
    ``@mesh.a2a`` surfaces instead of ``@mesh.route`` handlers.
    """

    def __init__(self):
        super().__init__(
            name="a2a-fastapi-discovery",
            required=True,
            description="Discover existing FastAPI application instances for A2A surfaces",
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """Discover FastAPI applications hosting A2A surfaces."""
        self.logger.debug("Discovering FastAPI applications for A2A surfaces...")

        result = PipelineResult(message="A2A FastAPI discovery completed")

        try:
            mesh_a2a_decorators = context.get("mesh_a2a_decorators", {})

            if not mesh_a2a_decorators:
                result.status = PipelineStatus.SKIPPED
                result.message = "No @mesh.a2a surfaces found"
                self.logger.info("⚠️ No @mesh.a2a surfaces found to process")
                return result

            fastapi_apps = ServerDiscoveryUtil.discover_fastapi_instances()

            if not fastapi_apps:
                result.status = PipelineStatus.FAILED
                result.message = "No FastAPI applications found"
                result.add_error("No FastAPI applications discovered in runtime")
                self.logger.error(
                    "❌ No FastAPI applications found. @mesh.a2a / mesh.a2a.mount "
                    "requires an existing FastAPI app instance — please create a "
                    "FastAPI app before declaring A2A surfaces."
                )
                return result

            # Filter discovered apps to those that actually host an A2A
            # surface. Without this, multi-app runtimes (e.g. an unrelated
            # FastAPI app for admin / metrics in the same process) would
            # cause us to pick an arbitrary app — possibly one without any
            # of the routes ``mesh.a2a.mount(...)`` registered, leading
            # to "no surfaces visible" mysteries downstream.
            #
            # An app "hosts" a surface when one of its routes' paths
            # matches a configured ``@mesh.a2a`` ``path`` — either the
            # raw RPC path or the agent-card discovery suffix.
            wanted_paths: set = set()
            for decorated in mesh_a2a_decorators.values():
                meta = getattr(decorated, "metadata", None) or {}
                p = meta.get("path")
                if not p:
                    continue
                rpc_path = p.rstrip("/") or "/"
                card_path = p.rstrip("/") + "/.well-known/agent.json"
                wanted_paths.add(rpc_path)
                wanted_paths.add(card_path)

            filtered_apps: dict = {}
            for app_id, app_info in fastapi_apps.items():
                app = app_info.get("instance")
                if app is None:
                    continue
                app_route_paths = {
                    getattr(r, "path", None) for r in app.router.routes
                }
                if app_route_paths & wanted_paths:
                    filtered_apps[app_id] = app_info

            if not filtered_apps:
                result.status = PipelineStatus.FAILED
                result.message = (
                    "No FastAPI app hosts any @mesh.a2a surface route"
                )
                result.add_error(
                    "Discovered FastAPI app(s) but none had a route matching "
                    "the @mesh.a2a / mesh.a2a.mount path(s) — did mount() run "
                    "before pipeline execution?"
                )
                self.logger.error(
                    f"❌ A2A FastAPI discovery: found {len(fastapi_apps)} app(s) "
                    f"but none host any of the {len(wanted_paths)} expected "
                    "A2A route path(s)."
                )
                return result

            result.add_context("fastapi_apps", filtered_apps)
            result.add_context("discovered_app_count", len(filtered_apps))

            result.message = (
                f"Discovered {len(filtered_apps)} FastAPI app(s) hosting "
                f"{len(mesh_a2a_decorators)} @mesh.a2a surface(s)"
            )

            self.logger.info(
                f"📦 A2A FastAPI Discovery: {len(filtered_apps)} app(s) hosting "
                f"A2A surfaces (of {len(fastapi_apps)} total app(s) in runtime), "
                f"{len(mesh_a2a_decorators)} A2A surface(s)"
            )

            for app_id, app_info in filtered_apps.items():
                self.logger.debug(
                    f"  App '{app_info.get('title', 'Unknown')}' ({app_id}): "
                    f"{len(app_info.get('routes', []))} total route(s)"
                )

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"A2A FastAPI discovery failed: {e}"
            result.add_error(str(e))
            self.logger.error(f"❌ A2A FastAPI discovery failed: {e}")

        return result
