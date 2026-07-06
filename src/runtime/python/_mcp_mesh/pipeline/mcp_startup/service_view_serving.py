"""Attach ``@mesh.service`` producer-sugar tools to the SERVED FastMCP server(s)
(RFC #1280).

An ordinary mesh tool is served because the user stacks ``@app.tool()`` (which
registers the callable on their FastMCP instance) alongside ``@mesh.tool()``
(which registers it in the DecoratorRegistry for the heartbeat/wire). Producer
sugar (``@mesh.service("prefix")``) applies ``@mesh.tool`` programmatically and
the user never touches the FastMCP server, so without this step the published
tools land in the DecoratorRegistry (→ heartbeat advertises ``prefix.method``)
but NOT on the served FastMCP instance — ``tools/list`` omits them and
``tools/call prefix.method`` returns "Unknown tool" (registration/serving
split-brain).

This step runs AFTER :class:`FastMCPServerDiscoveryStep` (so the servers exist)
and BEFORE :class:`FastAPIServerSetupStep` (so the mounted app advertises them),
exactly like :class:`JobsHelperToolsStep`. It registers every DI wrapper flagged
``_mesh_service_served_name`` (set by ``mesh._service._mark_for_serving`` for
both the sugar and tool-wins paths) on each discovered server, keyed by the
dotted capability — idempotent, no registry required.
"""

from __future__ import annotations

import logging
from typing import Any

from ..shared import PipelineResult, PipelineStatus, PipelineStep

logger = logging.getLogger(__name__)


async def _existing_tool_names(server: Any) -> set:
    """Names of tools already registered on ``server``.

    Prefers FastMCP's public async ``list_tools()`` surface (the installed
    version exposes no *sync* tool-listing API — ``list_tools`` / ``get_tool``
    are all coroutines). Falls back to the private ``local_provider._components``
    map only if the public call is unavailable / raises, so a FastMCP internals
    change can't break the idempotency guard.
    """
    try:
        tools = await server.list_tools()
        return {getattr(t, "name", None) for t in tools}
    except Exception:
        local_provider = getattr(server, "local_provider", None)
        components = getattr(local_provider, "_components", None)
        if not isinstance(components, dict):
            return set()
        return {
            getattr(comp, "name", None)
            for key, comp in components.items()
            if str(key).startswith("tool:")
        }


def _collect_served_tools() -> dict[str, tuple[Any, str]]:
    """Map ``served_name -> (callable, description)`` for every producer-sugar /
    tool-wins wrapper flagged for serving in the DecoratorRegistry."""
    from ...engine.decorator_registry import DecoratorRegistry

    out: dict[str, tuple[Any, str]] = {}
    for _name, decorated in DecoratorRegistry.get_mesh_tools().items():
        fn = decorated.function
        served_name = getattr(fn, "_mesh_service_served_name", None)
        if served_name is None:
            continue
        description = (decorated.metadata or {}).get("description") or ""
        out[served_name] = (fn, description)
    return out


class ServiceViewProducerServingStep(PipelineStep):
    """Register ``@mesh.service`` producer-sugar tools on each discovered FastMCP
    server so they appear in ``tools/list`` and answer ``tools/call``."""

    def __init__(self) -> None:
        super().__init__(
            name="service-view-producer-serving",
            required=False,  # Best-effort: must not block startup.
            description=(
                "Attach @mesh.service producer-sugar tools to the served "
                "FastMCP server(s)"
            ),
        )

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="Service-view producer serving")

        served = _collect_served_tools()
        if not served:
            result.status = PipelineStatus.SKIPPED
            result.message = "No @mesh.service producer-sugar tools to serve"
            return result

        servers = context.get("fastmcp_servers", {}) or {}
        if not servers:
            result.status = PipelineStatus.SKIPPED
            result.message = (
                "@mesh.service producer tools not served: no FastMCP servers "
                "discovered (a producer class needs a FastMCP server to serve "
                "its published tools)"
            )
            self.logger.warning("⚠️ %s", result.message)
            return result

        total = 0
        for server_key, server in servers.items():
            existing = await _existing_tool_names(server)
            for name, (fn, description) in served.items():
                if name in existing:
                    continue
                try:
                    server.tool(name=name, description=description)(fn)
                    total += 1
                    self.logger.debug(
                        "service-view serving: registered %s on FastMCP server %r",
                        name,
                        server_key,
                    )
                except Exception as e:
                    self.logger.warning(
                        "service-view serving: failed to register %s on %r: %s",
                        name,
                        server_key,
                        e,
                    )

        result.message = (
            f"Registered {total} @mesh.service producer tool(s) across "
            f"{len(servers)} FastMCP server(s)"
        )
        self.logger.info("🧩 %s", result.message)
        return result
